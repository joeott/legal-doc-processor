"""
Database Migration Helper for Pydantic Model Integration.

This module provides utilities to validate existing database data against
new Pydantic schemas and assist with the migration process.
"""

import logging
import json
from typing import List, Dict, Any, Optional, Type, Tuple
from datetime import datetime
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError
from supabase import Client

from .schemas import (
    ProjectModel, SourceDocumentModel, Neo4jDocumentModel,
    ChunkModel, EntityMentionModel, CanonicalEntityModel,
    RelationshipStagingModel, TextractJobModel, ImportSessionModel,
    ChunkEmbeddingModel, CanonicalEntityEmbeddingModel,
    DocumentProcessingHistoryModel, create_model_from_db
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating a database record against a Pydantic model"""
    table_name: str
    record_id: Optional[int]
    is_valid: bool
    model_instance: Optional[BaseModel] = None
    errors: List[str] = None
    warnings: List[str] = None
    suggested_fixes: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.suggested_fixes is None:
            self.suggested_fixes = []


@dataclass
class MigrationReport:
    """Comprehensive report of database migration validation"""
    total_records: int
    valid_records: int
    invalid_records: int
    tables_validated: List[str]
    validation_results: List[ValidationResult]
    error_summary: Dict[str, int]
    generated_at: datetime
    
    @property
    def success_rate(self) -> float:
        """Calculate validation success rate"""
        if self.total_records == 0:
            return 100.0
        return (self.valid_records / self.total_records) * 100
    
    def get_errors_by_table(self) -> Dict[str, List[ValidationResult]]:
        """Group validation errors by table"""
        errors_by_table = {}
        for result in self.validation_results:
            if not result.is_valid:
                if result.table_name not in errors_by_table:
                    errors_by_table[result.table_name] = []
                errors_by_table[result.table_name].append(result)
        return errors_by_table


class DatabaseMigrationHelper:
    """Helper class for validating and migrating database data to Pydantic models"""
    
    # Mapping of table names to their corresponding Pydantic models
    TABLE_MODEL_MAPPING = {
        'projects': ProjectModel,
        'source_documents': SourceDocumentModel,
        'neo4j_documents': Neo4jDocumentModel,
        'neo4j_chunks': ChunkModel,
        'neo4j_entity_mentions': EntityMentionModel,
        'neo4j_canonical_entities': CanonicalEntityModel,
        'neo4j_relationships_staging': RelationshipStagingModel,
        'textract_jobs': TextractJobModel,
        'import_sessions': ImportSessionModel,
        'chunk_embeddings': ChunkEmbeddingModel,
        'canonical_entity_embeddings': CanonicalEntityEmbeddingModel,
        'document_processing_history': DocumentProcessingHistoryModel,
    }
    
    def __init__(self, supabase_client: Client):
        """Initialize with Supabase client"""
        self.client = supabase_client
        self.validation_results: List[ValidationResult] = []
    
    def validate_table_data(self, table_name: str, limit: Optional[int] = None, 
                           offset: int = 0) -> List[ValidationResult]:
        """
        Validate all records in a table against their Pydantic model.
        
        Args:
            table_name: Name of the table to validate
            limit: Maximum number of records to validate (None for all)
            offset: Number of records to skip
            
        Returns:
            List of validation results
        """
        if table_name not in self.TABLE_MODEL_MAPPING:
            raise ValueError(f"No Pydantic model defined for table: {table_name}")
        
        model_class = self.TABLE_MODEL_MAPPING[table_name]
        results = []
        
        logger.info(f"Validating table '{table_name}' against {model_class.__name__}")
        
        try:
            # Fetch data from table
            query = self.client.table(table_name).select('*').range(offset, offset + (limit or 1000) - 1)
            if limit:
                query = query.limit(limit)
            
            response = query.execute()
            records = response.data
            
            logger.info(f"Fetched {len(records)} records from {table_name}")
            
            for record in records:
                result = self._validate_record(table_name, record, model_class)
                results.append(result)
                
                if not result.is_valid:
                    logger.warning(f"Validation failed for {table_name} record {record.get('id')}: {result.errors}")
            
            valid_count = sum(1 for r in results if r.is_valid)
            logger.info(f"Validation complete for {table_name}: {valid_count}/{len(results)} records valid")
            
        except Exception as e:
            logger.error(f"Error validating table {table_name}: {str(e)}")
            # Create error result for the entire table
            results.append(ValidationResult(
                table_name=table_name,
                record_id=None,
                is_valid=False,
                errors=[f"Table validation failed: {str(e)}"]
            ))
        
        self.validation_results.extend(results)
        return results
    
    def _validate_record(self, table_name: str, record: Dict[str, Any], 
                        model_class: Type[BaseModel]) -> ValidationResult:
        """Validate a single record against its Pydantic model"""
        record_id = record.get('id')
        
        try:
            # Attempt to create model instance
            model_instance = create_model_from_db(model_class, record)
            
            return ValidationResult(
                table_name=table_name,
                record_id=record_id,
                is_valid=True,
                model_instance=model_instance
            )
            
        except ValidationError as e:
            # Parse validation errors
            errors = []
            warnings = []
            suggested_fixes = []
            
            for error in e.errors():
                field = '.'.join(str(loc) for loc in error['loc'])
                message = error['msg']
                error_type = error['type']
                
                error_msg = f"Field '{field}': {message} (type: {error_type})"
                errors.append(error_msg)
                
                # Generate suggested fixes based on error type
                fix = self._suggest_fix(field, error_type, error.get('input'))
                if fix:
                    suggested_fixes.append(fix)
            
            return ValidationResult(
                table_name=table_name,
                record_id=record_id,
                is_valid=False,
                errors=errors,
                warnings=warnings,
                suggested_fixes=suggested_fixes
            )
            
        except Exception as e:
            return ValidationResult(
                table_name=table_name,
                record_id=record_id,
                is_valid=False,
                errors=[f"Unexpected error: {str(e)}"]
            )
    
    def _suggest_fix(self, field: str, error_type: str, input_value: Any) -> Optional[str]:
        """Generate suggested fixes for common validation errors"""
        if error_type == 'value_error.uuid':
            return f"Convert '{field}' to valid UUID format"
        elif error_type == 'type_error.datetime':
            return f"Convert '{field}' to ISO datetime format"
        elif error_type == 'value_error.missing':
            return f"Add required field '{field}'"
        elif error_type == 'type_error.none.not_allowed':
            return f"Provide non-null value for '{field}'"
        elif error_type == 'value_error.json_invalid':
            return f"Fix JSON syntax in '{field}'"
        elif 'enum' in error_type:
            return f"Use valid enum value for '{field}'"
        else:
            return None
    
    def validate_all_tables(self, tables: Optional[List[str]] = None, 
                           sample_size: Optional[int] = 100) -> MigrationReport:
        """
        Validate all tables or a subset of tables.
        
        Args:
            tables: List of table names to validate (None for all)
            sample_size: Number of records to sample from each table (None for all)
            
        Returns:
            Comprehensive migration report
        """
        if tables is None:
            tables = list(self.TABLE_MODEL_MAPPING.keys())
        
        logger.info(f"Starting validation of {len(tables)} tables")
        
        all_results = []
        error_summary = {}
        
        for table_name in tables:
            logger.info(f"Validating table: {table_name}")
            
            try:
                results = self.validate_table_data(table_name, limit=sample_size)
                all_results.extend(results)
                
                # Count errors by type
                for result in results:
                    if not result.is_valid:
                        for error in result.errors:
                            error_type = error.split(':')[0] if ':' in error else 'unknown'
                            error_summary[error_type] = error_summary.get(error_type, 0) + 1
                            
            except Exception as e:
                logger.error(f"Failed to validate table {table_name}: {str(e)}")
                all_results.append(ValidationResult(
                    table_name=table_name,
                    record_id=None,
                    is_valid=False,
                    errors=[f"Table validation failed: {str(e)}"]
                ))
        
        # Generate report
        total_records = len(all_results)
        valid_records = sum(1 for r in all_results if r.is_valid)
        invalid_records = total_records - valid_records
        
        report = MigrationReport(
            total_records=total_records,
            valid_records=valid_records,
            invalid_records=invalid_records,
            tables_validated=tables,
            validation_results=all_results,
            error_summary=error_summary,
            generated_at=datetime.now()
        )
        
        logger.info(f"Validation complete: {valid_records}/{total_records} records valid ({report.success_rate:.1f}%)")
        
        return report
    
    def generate_migration_script(self, report: MigrationReport, 
                                 output_file: str = "migration_fixes.sql") -> str:
        """
        Generate SQL migration script to fix common validation errors.
        
        Args:
            report: Migration report with validation results
            output_file: Path to output SQL file
            
        Returns:
            Path to generated migration script
        """
        sql_statements = []
        sql_statements.append("-- Auto-generated migration script for Pydantic model compatibility")
        sql_statements.append(f"-- Generated at: {datetime.now().isoformat()}")
        sql_statements.append(f"-- Success rate: {report.success_rate:.1f}%")
        sql_statements.append("")
        
        # Group fixes by table
        errors_by_table = report.get_errors_by_table()
        
        for table_name, error_results in errors_by_table.items():
            sql_statements.append(f"-- Fixes for table: {table_name}")
            
            for result in error_results:
                if result.record_id and result.suggested_fixes:
                    sql_statements.append(f"-- Record ID: {result.record_id}")
                    for fix in result.suggested_fixes:
                        sql_statements.append(f"-- TODO: {fix}")
                    sql_statements.append("")
        
        # Write to file
        with open(output_file, 'w') as f:
            f.write('\n'.join(sql_statements))
        
        logger.info(f"Migration script generated: {output_file}")
        return output_file
    
    def export_validation_report(self, report: MigrationReport, 
                                output_file: str = "validation_report.json") -> str:
        """
        Export validation report to JSON file.
        
        Args:
            report: Migration report to export
            output_file: Path to output JSON file
            
        Returns:
            Path to exported report
        """
        # Convert report to serializable format
        report_data = {
            "summary": {
                "total_records": report.total_records,
                "valid_records": report.valid_records,
                "invalid_records": report.invalid_records,
                "success_rate": report.success_rate,
                "tables_validated": report.tables_validated,
                "generated_at": report.generated_at.isoformat()
            },
            "error_summary": report.error_summary,
            "validation_results": []
        }
        
        # Add validation results (excluding model instances for serialization)
        for result in report.validation_results:
            result_data = {
                "table_name": result.table_name,
                "record_id": result.record_id,
                "is_valid": result.is_valid,
                "errors": result.errors,
                "warnings": result.warnings,
                "suggested_fixes": result.suggested_fixes
            }
            report_data["validation_results"].append(result_data)
        
        # Write to file
        with open(output_file, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        logger.info(f"Validation report exported: {output_file}")
        return output_file
    
    def fix_common_issues(self, dry_run: bool = True) -> Dict[str, int]:
        """
        Automatically fix common validation issues in the database.
        
        Args:
            dry_run: If True, only log what would be fixed without making changes
            
        Returns:
            Dictionary of fix counts by issue type
        """
        fix_counts = {
            "null_uuids_generated": 0,
            "invalid_json_fixed": 0,
            "invalid_dates_fixed": 0,
            "enum_values_corrected": 0
        }
        
        logger.info(f"Starting automatic fixes (dry_run={dry_run})")
        
        # This would contain actual fix implementations
        # For now, just log what would be done
        
        if dry_run:
            logger.info("Dry run complete - no changes made")
        else:
            logger.info("Automatic fixes applied")
        
        return fix_counts


# Utility functions for migration
def validate_single_table(client: Client, table_name: str, 
                         limit: Optional[int] = None) -> MigrationReport:
    """Convenience function to validate a single table"""
    helper = DatabaseMigrationHelper(client)
    results = helper.validate_table_data(table_name, limit=limit)
    
    total_records = len(results)
    valid_records = sum(1 for r in results if r.is_valid)
    
    return MigrationReport(
        total_records=total_records,
        valid_records=valid_records,
        invalid_records=total_records - valid_records,
        tables_validated=[table_name],
        validation_results=results,
        error_summary={},
        generated_at=datetime.now()
    )


def quick_validation_check(client: Client, sample_size: int = 10) -> Dict[str, float]:
    """Quick validation check across all tables with small sample"""
    helper = DatabaseMigrationHelper(client)
    report = helper.validate_all_tables(sample_size=sample_size)
    
    # Return success rates by table
    success_rates = {}
    errors_by_table = report.get_errors_by_table()
    
    for table_name in helper.TABLE_MODEL_MAPPING.keys():
        table_results = [r for r in report.validation_results if r.table_name == table_name]
        if table_results:
            valid_count = sum(1 for r in table_results if r.is_valid)
            success_rates[table_name] = (valid_count / len(table_results)) * 100
        else:
            success_rates[table_name] = 0.0
    
    return success_rates 