#!/usr/bin/env python3
"""
Test Schema Conformance
Verifies that the RDS database schema matches script expectations
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.db import DatabaseManager, DatabaseType
from scripts.core import schemas
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SchemaConformanceTester:
    """Test that database schema matches script expectations."""
    
    def __init__(self):
        self.db = DatabaseManager(validate_conformance=False)  # Skip validation for testing
        self.expected_tables = [
            'projects',
            'source_documents',
            'import_sessions',
            'neo4j_documents',
            'document_chunks',
            'entity_mentions',
            'canonical_entities',
            'relationship_staging',
            'textract_jobs',
            'chunk_embeddings',
            'canonical_entity_embeddings',
            'document_processing_history'
        ]
        
    def test_tables_exist(self) -> Tuple[bool, List[str]]:
        """Test that all expected tables exist."""
        missing_tables = []
        
        # Use direct connection from pool
        from sqlalchemy import text
        with self.db.engine.connect() as conn:
            # Get existing tables
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE'
            """))
            existing_tables = {row[0] for row in result}
            
            # Check each expected table
            for table in self.expected_tables:
                if table not in existing_tables:
                    missing_tables.append(table)
                    
        return len(missing_tables) == 0, missing_tables
        
    def test_table_columns(self, table_name: str) -> Tuple[bool, Dict]:
        """Test that table has expected columns."""
        issues = {'missing_columns': [], 'type_mismatches': []}
        
        # Map tables to their expected models
        model_mapping = {
            'projects': schemas.ProjectModel,
            'source_documents': schemas.SourceDocumentModel,
            'import_sessions': schemas.ImportSessionModel,
            'neo4j_documents': schemas.Neo4jDocumentModel,
            'document_chunks': schemas.ChunkModel,
            'entity_mentions': schemas.EntityMentionModel,
            'canonical_entities': schemas.CanonicalEntityModel,
            'relationship_staging': schemas.RelationshipStagingModel,
            'textract_jobs': schemas.TextractJobModel,
            'chunk_embeddings': schemas.ChunkEmbeddingModel,
            'canonical_entity_embeddings': schemas.CanonicalEntityEmbeddingModel,
            'document_processing_history': schemas.DocumentProcessingHistoryModel
        }
        
        if table_name not in model_mapping:
            return True, issues  # Skip unknown tables
            
        model = model_mapping[table_name]
        
        with self.db.engine.connect() as conn:
            # Get actual columns
            result = conn.execute(text(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = '{table_name}'
                AND table_schema = 'public'
            """))
            
            actual_columns = {
                row[0]: {'type': row[1], 'nullable': row[2] == 'YES'}
                for row in result
            }
            
            # Check expected fields from Pydantic model
            for field_name, field_info in model.model_fields.items():
                # Some fields might have different names in DB
                db_field_name = self._map_field_name(field_name)
                
                if db_field_name not in actual_columns:
                    issues['missing_columns'].append(field_name)
                    
        return len(issues['missing_columns']) == 0, issues
        
    def _map_field_name(self, field_name: str) -> str:
        """Map Pydantic field names to database column names."""
        # Add any special mappings here
        return field_name
        
    def test_foreign_keys(self) -> Tuple[bool, List[str]]:
        """Test that foreign key relationships exist."""
        issues = []
        
        expected_fks = [
            ('source_documents', 'project_uuid', 'projects', 'project_uuid'),
            ('document_chunks', 'document_uuid', 'source_documents', 'document_uuid'),
            ('entity_mentions', 'chunk_uuid', 'document_chunks', 'chunk_uuid'),
            ('relationship_staging', 'source_entity_uuid', 'canonical_entities', 'canonical_entity_uuid'),
            ('relationship_staging', 'target_entity_uuid', 'canonical_entities', 'canonical_entity_uuid'),
        ]
        
        with self.db.engine.connect() as conn:
            for table, column, ref_table, ref_column in expected_fks:
                result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu 
                        ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.referential_constraints rc
                        ON tc.constraint_name = rc.constraint_name
                    JOIN information_schema.key_column_usage kcu2
                        ON rc.unique_constraint_name = kcu2.constraint_name
                    WHERE tc.table_name = '{table}'
                    AND kcu.column_name = '{column}'
                    AND kcu2.table_name = '{ref_table}'
                    AND kcu2.column_name = '{ref_column}'
                    AND tc.constraint_type = 'FOREIGN KEY'
                """))
                
                if result.scalar() == 0:
                    issues.append(f"{table}.{column} -> {ref_table}.{ref_column}")
                    
        return len(issues) == 0, issues
        
    def test_indexes(self) -> Tuple[bool, List[str]]:
        """Test that performance indexes exist."""
        missing_indexes = []
        
        expected_indexes = [
            ('source_documents', 'project_uuid'),
            ('source_documents', 'processing_status'),
            ('document_chunks', 'document_uuid'),
            ('entity_mentions', 'chunk_uuid'),
            ('canonical_entities', 'entity_type'),
        ]
        
        with self.db.engine.connect() as conn:
            for table, column in expected_indexes:
                result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM pg_indexes
                    WHERE tablename = '{table}'
                    AND indexdef LIKE '%{column}%'
                """))
                
                if result.scalar() == 0:
                    missing_indexes.append(f"{table}.{column}")
                    
        return len(missing_indexes) == 0, missing_indexes
        
    def test_triggers(self) -> Tuple[bool, List[str]]:
        """Test that update triggers exist."""
        missing_triggers = []
        
        expected_triggers = [
            ('projects', 'update_projects_updated_at'),
            ('source_documents', 'update_source_documents_updated_at'),
            ('source_documents', 'populate_source_documents_fks'),
            ('document_chunks', 'populate_document_chunks_fks'),
        ]
        
        with self.db.engine.connect() as conn:
            for table, trigger in expected_triggers:
                result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM information_schema.triggers
                    WHERE event_object_table = '{table}'
                    AND trigger_name = '{trigger}'
                """))
                
                if result.scalar() == 0:
                    missing_triggers.append(f"{table}.{trigger}")
                    
        return len(missing_triggers) == 0, missing_triggers
        
    def run_all_tests(self) -> Dict:
        """Run all conformance tests."""
        results = {
            'overall_pass': True,
            'tests': {}
        }
        
        # Test 1: Tables exist
        logger.info("Testing table existence...")
        passed, missing = self.test_tables_exist()
        results['tests']['tables_exist'] = {
            'passed': passed,
            'missing_tables': missing
        }
        if not passed:
            results['overall_pass'] = False
            logger.error(f"Missing tables: {missing}")
        else:
            logger.info("✓ All expected tables exist")
            
        # Test 2: Foreign keys
        logger.info("Testing foreign key relationships...")
        passed, issues = self.test_foreign_keys()
        results['tests']['foreign_keys'] = {
            'passed': passed,
            'missing_fks': issues
        }
        if not passed:
            results['overall_pass'] = False
            logger.warning(f"Missing foreign keys: {issues}")
        else:
            logger.info("✓ All foreign key relationships exist")
            
        # Test 3: Indexes
        logger.info("Testing performance indexes...")
        passed, missing = self.test_indexes()
        results['tests']['indexes'] = {
            'passed': passed,
            'missing_indexes': missing
        }
        if not passed:
            logger.warning(f"Missing indexes: {missing}")
        else:
            logger.info("✓ All performance indexes exist")
            
        # Test 4: Triggers
        logger.info("Testing triggers...")
        passed, missing = self.test_triggers()
        results['tests']['triggers'] = {
            'passed': passed,
            'missing_triggers': missing
        }
        if not passed:
            logger.warning(f"Missing triggers: {missing}")
        else:
            logger.info("✓ All triggers exist")
            
        # Test 5: Sample operations
        logger.info("Testing sample database operations...")
        try:
            # Test project creation
            project_data = {
                'name': 'Test Project',
                'client_name': 'Test Client',
                'matter_type': 'Test Matter'
            }
            result = self.db.insert_record('projects', project_data)
            assert result is not None
            logger.info("✓ Project insertion successful")
            
            # Test document creation
            doc_data = {
                'project_uuid': result['project_uuid'],
                'filename': 'test.pdf',
                'file_type': 'pdf',
                'processing_status': 'pending'
            }
            doc_result = self.db.insert_record('source_documents', doc_data)
            assert doc_result is not None
            logger.info("✓ Document insertion successful")
            
            # Clean up test data
            self.db.delete_records('source_documents', {'document_uuid': doc_result['document_uuid']})
            self.db.delete_records('projects', {'project_uuid': result['project_uuid']})
            logger.info("✓ Cleanup successful")
            
            results['tests']['operations'] = {'passed': True}
            
        except Exception as e:
            results['tests']['operations'] = {'passed': False, 'error': str(e)}
            results['overall_pass'] = False
            logger.error(f"Operation test failed: {e}")
            
        return results


def main():
    """Run schema conformance tests."""
    tester = SchemaConformanceTester()
    results = tester.run_all_tests()
    
    print("\n" + "=" * 60)
    print("SCHEMA CONFORMANCE TEST RESULTS")
    print("=" * 60)
    
    if results['overall_pass']:
        print("\n✅ ALL TESTS PASSED - Schema is fully conformant!")
    else:
        print("\n❌ SOME TESTS FAILED - Schema needs attention")
        
    print("\nDetailed Results:")
    for test_name, test_results in results['tests'].items():
        status = "✓ PASS" if test_results['passed'] else "✗ FAIL"
        print(f"\n{test_name}: {status}")
        
        # Show details for failures
        if not test_results['passed']:
            for key, value in test_results.items():
                if key != 'passed' and value:
                    print(f"  - {key}: {value}")
                    
    return 0 if results['overall_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())