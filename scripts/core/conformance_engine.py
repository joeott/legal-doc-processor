"""
SQLAlchemy-Pydantic Conformance Engine
Ensures database schema and Pydantic models remain synchronized.
"""
import logging
import os
from typing import Dict, List, Type, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import inspect, MetaData, Table
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from scripts.db import engine
from scripts.core.schemas import (
    SourceDocumentModel, ChunkModel, EntityMentionModel,
    CanonicalEntityModel, RelationshipStagingModel
)

logger = logging.getLogger(__name__)


class ConformanceStatus(Enum):
    """Status of conformance check."""
    CONFORMANT = "conformant"
    MISSING_COLUMN = "missing_column"
    TYPE_MISMATCH = "type_mismatch"
    CONSTRAINT_MISMATCH = "constraint_mismatch"
    MISSING_TABLE = "missing_table"


@dataclass
class ConformanceIssue:
    """Represents a single conformance issue."""
    table_name: str
    field_name: str
    issue_type: ConformanceStatus
    database_type: Optional[str]
    model_type: Optional[str]
    severity: str  # "error", "warning", "info"
    fix_sql: Optional[str] = None
    

@dataclass
class ConformanceReport:
    """Complete conformance validation report."""
    timestamp: datetime
    total_tables: int
    conformant_tables: int
    issues: List[ConformanceIssue]
    can_auto_fix: bool
    
    @property
    def is_conformant(self) -> bool:
        """Check if system is fully conformant."""
        return len([i for i in self.issues if i.severity == "error"]) == 0
    
    def get_fix_script(self) -> str:
        """Generate SQL script to fix issues."""
        fixes = [issue.fix_sql for issue in self.issues if issue.fix_sql]
        return "\n".join(fixes) if fixes else ""


class ConformanceEngine:
    """Engine for validating and fixing schema conformance."""
    
    # Mapping of Pydantic models to database tables
    MODEL_TABLE_MAP = {
        SourceDocumentModel: "source_documents",
        ChunkModel: "document_chunks",
        EntityMentionModel: "entity_mentions",
        CanonicalEntityModel: "canonical_entities",
        RelationshipStagingModel: "relationship_staging",
    }
    
    # Comprehensive type mapping from Pydantic to PostgreSQL
    TYPE_MAP = {
        "str": ["varchar", "text", "character varying", "char"],
        "int": ["integer", "bigint", "smallint", "serial", "bigserial"],
        "float": ["numeric", "real", "double precision", "decimal"],
        "bool": ["boolean"],
        "datetime": ["timestamp", "timestamp with time zone", "timestamp without time zone"],
        "date": ["date"],
        "time": ["time", "time with time zone", "time without time zone"],
        "UUID": ["uuid"],
        "Dict": ["json", "jsonb"],
        "List": ["json", "jsonb", "array"],
        "Optional": ["nullable"],  # Handle Optional types
        "Union": ["multiple"],  # Handle Union types
        "Enum": ["varchar", "text", "enum"],  # Handle Enum types
        "bytes": ["bytea"],
        "Decimal": ["numeric", "decimal"],
    }
    
    # PostgreSQL to Python type reverse mapping
    POSTGRES_TO_PYTHON = {
        "varchar": "str", "text": "str", "character varying": "str", "char": "str",
        "integer": "int", "bigint": "int", "smallint": "int", "serial": "int", "bigserial": "int",
        "numeric": "float", "real": "float", "double precision": "float", "decimal": "Decimal",
        "boolean": "bool",
        "timestamp": "datetime", "timestamp with time zone": "datetime", "timestamp without time zone": "datetime",
        "date": "date", "time": "time",
        "uuid": "UUID",
        "json": "Dict", "jsonb": "Dict",
        "array": "List",
        "bytea": "bytes"
    }
    
    def __init__(self):
        """Initialize conformance engine."""
        self.inspector = inspect(engine)
        self.metadata = MetaData()
        self.metadata.reflect(bind=engine)
        
    def check_conformance(self) -> ConformanceReport:
        """Check conformance between Pydantic models and database schema."""
        issues = []
        total_tables = len(self.MODEL_TABLE_MAP)
        conformant_tables = 0
        
        for model_class, table_name in self.MODEL_TABLE_MAP.items():
            table_issues = self._check_table_conformance(model_class, table_name)
            if not table_issues:
                conformant_tables += 1
            issues.extend(table_issues)
            
        return ConformanceReport(
            timestamp=datetime.utcnow(),
            total_tables=total_tables,
            conformant_tables=conformant_tables,
            issues=issues,
            can_auto_fix=self._can_auto_fix(issues)
        )
    
    def _check_table_conformance(
        self, 
        model_class: Type[BaseModel], 
        table_name: str
    ) -> List[ConformanceIssue]:
        """Check conformance for a single table."""
        issues = []
        
        # Check if table exists
        if table_name not in self.metadata.tables:
            issues.append(ConformanceIssue(
                table_name=table_name,
                field_name="",
                issue_type=ConformanceStatus.MISSING_TABLE,
                database_type=None,
                model_type=model_class.__name__,
                severity="error",
                fix_sql=self._generate_create_table_sql(model_class, table_name)
            ))
            return issues
        
        # Get table columns
        table = self.metadata.tables[table_name]
        db_columns = {col.name: col for col in table.columns}
        
        # Get model fields
        model_fields = model_class.model_fields
        
        # Check each model field exists in database
        for field_name, field_info in model_fields.items():
            if field_name not in db_columns:
                issues.append(ConformanceIssue(
                    table_name=table_name,
                    field_name=field_name,
                    issue_type=ConformanceStatus.MISSING_COLUMN,
                    database_type=None,
                    model_type=self._get_field_type(field_info),
                    severity="error",
                    fix_sql=self._generate_add_column_sql(
                        table_name, field_name, field_info
                    )
                ))
            else:
                # Check type compatibility
                type_issue = self._check_type_compatibility(
                    table_name, field_name, field_info, db_columns[field_name]
                )
                if type_issue:
                    issues.append(type_issue)
        
        # Check for extra database columns not in model
        for col_name in db_columns:
            if col_name not in model_fields:
                issues.append(ConformanceIssue(
                    table_name=table_name,
                    field_name=col_name,
                    issue_type=ConformanceStatus.MISSING_COLUMN,
                    database_type=str(db_columns[col_name].type),
                    model_type=None,
                    severity="warning",  # Extra columns are warnings, not errors
                    fix_sql=None  # Don't auto-drop columns
                ))
        
        return issues
    
    def _check_type_compatibility(
        self, 
        table_name: str,
        field_name: str,
        field_info: Any,
        db_column: Any
    ) -> Optional[ConformanceIssue]:
        """Check if database column type matches model field type."""
        model_type = self._get_field_type(field_info)
        db_type = str(db_column.type).lower()
        
        # Get compatible types for this model type
        compatible_types = []
        for pydantic_type, db_types in self.TYPE_MAP.items():
            if pydantic_type.lower() in model_type.lower():
                compatible_types.extend(db_types)
                break
        
        # Check if database type is compatible
        is_compatible = any(
            compat_type in db_type 
            for compat_type in compatible_types
        )
        
        if not is_compatible:
            return ConformanceIssue(
                table_name=table_name,
                field_name=field_name,
                issue_type=ConformanceStatus.TYPE_MISMATCH,
                database_type=db_type,
                model_type=model_type,
                severity="error",
                fix_sql=self._generate_alter_column_sql(
                    table_name, field_name, field_info
                )
            )
        
        return None
    
    def _get_field_type(self, field_info: Any) -> str:
        """Extract type string from field info."""
        if hasattr(field_info, 'annotation'):
            return str(field_info.annotation).replace('typing.', '')
        return "Unknown"
    
    def _can_auto_fix(self, issues: List[ConformanceIssue]) -> bool:
        """Determine if issues can be automatically fixed."""
        # Only auto-fix if all issues have fix SQL
        error_issues = [i for i in issues if i.severity == "error"]
        return all(issue.fix_sql is not None for issue in error_issues)
    
    def _generate_create_table_sql(
        self, 
        model_class: Type[BaseModel], 
        table_name: str
    ) -> str:
        """Generate CREATE TABLE SQL from Pydantic model."""
        columns = []
        constraints = []
        
        model_fields = model_class.model_fields
        
        for field_name, field_info in model_fields.items():
            column_def = self._generate_column_definition(field_name, field_info)
            columns.append(column_def)
            
            # Add constraints
            if field_name.endswith('_uuid') or field_name == 'id':
                if field_name == 'id':
                    constraints.append(f"PRIMARY KEY ({field_name})")
                elif field_name.endswith('_uuid') and not field_name.startswith('document_'):
                    # Foreign key constraint (simplified)
                    ref_table = field_name.replace('_uuid', 's')  # Basic pluralization
                    constraints.append(f"FOREIGN KEY ({field_name}) REFERENCES {ref_table}(id)")
        
        # Add created_at and updated_at if not present
        if 'created_at' not in model_fields:
            columns.append("created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP")
        if 'updated_at' not in model_fields:
            columns.append("updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP")
        
        all_definitions = columns + constraints
        
        definitions_str = ',\\n    '.join(all_definitions)
        sql = f"""CREATE TABLE IF NOT EXISTS {table_name} (
    {definitions_str}
);"""
        
        return sql
    
    def _generate_add_column_sql(
        self, 
        table_name: str, 
        field_name: str, 
        field_info: Any
    ) -> str:
        """Generate ALTER TABLE ADD COLUMN SQL."""
        column_def = self._generate_column_definition(field_name, field_info)
        return f"ALTER TABLE {table_name} ADD COLUMN {column_def};"
    
    def _generate_alter_column_sql(
        self, 
        table_name: str, 
        field_name: str, 
        field_info: Any
    ) -> str:
        """Generate ALTER TABLE ALTER COLUMN SQL."""
        postgres_type = self._get_postgres_type(field_info)
        return f"ALTER TABLE {table_name} ALTER COLUMN {field_name} TYPE {postgres_type};"
    
    def _generate_column_definition(self, field_name: str, field_info: Any) -> str:
        """Generate column definition for CREATE/ALTER statements."""
        postgres_type = self._get_postgres_type(field_info)
        
        column_def = f"{field_name} {postgres_type}"
        
        # Add NOT NULL constraint
        if self._is_required_field(field_info):
            column_def += " NOT NULL"
        
        # Add DEFAULT values
        default_value = self._get_default_value(field_info)
        if default_value:
            column_def += f" DEFAULT {default_value}"
        
        return column_def
    
    def _get_postgres_type(self, field_info: Any) -> str:
        """Map Pydantic field to PostgreSQL type."""
        field_type = self._get_field_type(field_info)
        
        # Handle Optional types
        if "Optional" in field_type or "Union" in field_type:
            # Extract the actual type from Optional[Type] or Union[Type, None]
            field_type = field_type.replace("Optional[", "").replace("]", "")
            field_type = field_type.replace("Union[", "").split(",")[0].strip()
        
        # Map to PostgreSQL type
        for pydantic_type, postgres_types in self.TYPE_MAP.items():
            if pydantic_type.lower() in field_type.lower():
                return postgres_types[0]  # Use the first (preferred) type
        
        # Handle specific cases
        if "UUID" in field_type:
            return "UUID"
        elif "datetime" in field_type.lower():
            return "TIMESTAMP WITH TIME ZONE"
        elif "int" in field_type.lower():
            return "INTEGER"
        elif "str" in field_type.lower():
            return "TEXT"
        elif "bool" in field_type.lower():
            return "BOOLEAN"
        elif "float" in field_type.lower():
            return "NUMERIC"
        elif "dict" in field_type.lower() or "Dict" in field_type:
            return "JSONB"
        elif "list" in field_type.lower() or "List" in field_type:
            return "JSONB"
        
        # Default fallback
        return "TEXT"
    
    def _is_required_field(self, field_info: Any) -> bool:
        """Check if field is required (not Optional)."""
        field_type = self._get_field_type(field_info)
        return "Optional" not in field_type and "Union" not in field_type
    
    def _get_default_value(self, field_info: Any) -> Optional[str]:
        """Get default value for field if any."""
        if hasattr(field_info, 'default') and field_info.default is not None:
            default = field_info.default
            if isinstance(default, str):
                return f"'{default}'"
            elif isinstance(default, bool):
                return str(default).upper()
            elif hasattr(default, '__call__'):
                # Handle callable defaults like datetime.utcnow
                if 'datetime' in str(default):
                    return "CURRENT_TIMESTAMP"
            return str(default)
        return None
    
    def enforce_conformance(self, dry_run: bool = True, backup: bool = True) -> Tuple[bool, str]:
        """
        Enforce conformance by applying fixes with backup and rollback support.
        
        Args:
            dry_run: If True, only return SQL without executing
            backup: If True, create backup before applying changes
            
        Returns:
            Tuple of (success, message/sql)
        """
        report = self.check_conformance()
        
        if report.is_conformant:
            return True, "System is already conformant"
        
        if not report.can_auto_fix:
            manual_issues = [i for i in report.issues if i.severity == "error" and not i.fix_sql]
            return False, f"Manual intervention required for {len(manual_issues)} issues"
        
        fix_script = report.get_fix_script()
        
        if dry_run:
            return True, fix_script
        
        # Create backup if requested
        backup_info = None
        if backup:
            backup_info = self._create_schema_backup()
            if not backup_info:
                return False, "Failed to create backup before applying fixes"
        
        # Execute fixes with transaction rollback support
        try:
            with engine.begin() as conn:  # Use transaction
                for statement in fix_script.split(';'):
                    if statement.strip() and not statement.strip().startswith('--'):
                        logger.info(f"Executing: {statement.strip()}")
                        conn.execute(text(statement))
                
                # Verify conformance after changes
                post_fix_report = self.check_conformance()
                if not post_fix_report.is_conformant:
                    raise Exception(f"Conformance not achieved after fixes: {len(post_fix_report.issues)} issues remain")
                
                logger.info("Conformance fixes applied successfully")
                return True, f"Conformance fixes applied successfully. Backup: {backup_info}"
                
        except Exception as e:
            logger.error(f"Failed to apply conformance fixes: {e}")
            if backup_info:
                logger.info(f"Backup available for rollback: {backup_info}")
            return False, f"Fix failed: {str(e)}. Backup: {backup_info}"
    
    def _create_schema_backup(self) -> Optional[str]:
        """Create a backup of current schema before making changes."""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_file = f"schema_backup_{timestamp}.sql"
            
            with engine.connect() as conn:
                # Get schema dump (simplified - in production use pg_dump)
                tables = self.metadata.tables.keys()
                backup_sql = []
                
                for table_name in tables:
                    # Get CREATE TABLE statement
                    result = conn.execute(text(f"""
                        SELECT 'CREATE TABLE ' || schemaname||'.'||tablename||' (' || 
                               array_to_string(array_agg(column_name||' '||data_type), ', ') || ');'
                        FROM information_schema.columns 
                        WHERE table_name = '{table_name}'
                        GROUP BY schemaname, tablename
                    """))
                    
                    for row in result:
                        backup_sql.append(row[0])
                
                # Write backup file
                backup_path = f"backups/{backup_file}"
                os.makedirs("backups", exist_ok=True)
                
                with open(backup_path, 'w') as f:
                    f.write("\n".join(backup_sql))
                
                return backup_path
                
        except Exception as e:
            logger.error(f"Failed to create schema backup: {e}")
            return None


def check_and_report_conformance():
    """Check conformance and print detailed report."""
    engine = ConformanceEngine()
    report = engine.check_conformance()
    
    print(f"\n{'='*60}")
    print(f"CONFORMANCE REPORT - {report.timestamp}")
    print(f"{'='*60}")
    print(f"Total Tables: {report.total_tables}")
    print(f"Conformant Tables: {report.conformant_tables}")
    print(f"Issues Found: {len(report.issues)}")
    print(f"System Conformant: {'✓ YES' if report.is_conformant else '✗ NO'}")
    
    if report.issues:
        print(f"\n{'='*60}")
        print("ISSUES DETECTED:")
        print(f"{'='*60}")
        
        # Group by severity
        errors = [i for i in report.issues if i.severity == "error"]
        warnings = [i for i in report.issues if i.severity == "warning"]
        
        if errors:
            print(f"\nERRORS ({len(errors)}):")
            for issue in errors:
                print(f"  - {issue.table_name}.{issue.field_name}: {issue.issue_type.value}")
                print(f"    Model Type: {issue.model_type}, DB Type: {issue.database_type}")
                if issue.fix_sql:
                    print(f"    Fix Available: YES")
        
        if warnings:
            print(f"\nWARNINGS ({len(warnings)}):")
            for issue in warnings:
                print(f"  - {issue.table_name}.{issue.field_name}: {issue.issue_type.value}")
    
    if report.can_auto_fix and not report.is_conformant:
        print(f"\n{'='*60}")
        print("AUTO-FIX AVAILABLE")
        print(f"{'='*60}")
        print("Run with --fix flag to apply corrections")
    
    return report


if __name__ == "__main__":
    import sys
    
    if "--fix" in sys.argv:
        engine = ConformanceEngine()
        success, message = engine.enforce_conformance(dry_run=False)
        print(f"\nFix Result: {message}")
    else:
        check_and_report_conformance()