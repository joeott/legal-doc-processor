#!/usr/bin/env python3
"""
Verify conformance between pipeline expectations and actual RDS schema
Shows exactly what needs to be mapped or fixed
"""

import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, inspect, text
from scripts.core.schemas import (
    SourceDocumentModel, ChunkModel, EntityMentionModel,
    CanonicalEntityModel, RelationshipModel
)
from scripts.rds_utils import TABLE_MAPPINGS, COLUMN_MAPPINGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConformanceChecker:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.inspector = inspect(self.engine)
        
    def check_conformance(self):
        """Check conformance between models and database"""
        print("=" * 70)
        print("Pipeline-RDS Conformance Check")
        print("=" * 70)
        
        # Get actual tables in database
        actual_tables = self.inspector.get_table_names()
        print(f"\nActual tables in RDS: {actual_tables}")
        
        # Define expected models and their table names
        models = {
            'source_documents': SourceDocumentModel,
            'document_chunks': ChunkModel,
            'entity_mentions': EntityMentionModel,
            'canonical_entities': CanonicalEntityModel,
            'relationship_staging': RelationshipModel
        }
        
        print("\n" + "-" * 70)
        print("TABLE MAPPING VERIFICATION")
        print("-" * 70)
        
        all_good = True
        
        for expected_table, model in models.items():
            mapped_table = TABLE_MAPPINGS.get(expected_table, expected_table)
            exists = mapped_table in actual_tables
            
            status = "✅" if exists else "❌"
            print(f"{status} {expected_table} → {mapped_table} {'(exists)' if exists else '(MISSING)'}")
            
            if exists:
                # Check columns
                self._check_columns(expected_table, mapped_table, model)
            else:
                all_good = False
                
        return all_good
    
    def _check_columns(self, expected_table: str, actual_table: str, model):
        """Check column conformance for a table"""
        print(f"\n  Checking columns for {actual_table}:")
        
        # Get actual columns
        actual_columns = {col['name'] for col in self.inspector.get_columns(actual_table)}
        
        # Get expected columns from model
        expected_columns = set()
        for field_name, field in model.__fields__.items():
            # Handle field aliases
            if hasattr(field, 'alias') and field.alias:
                expected_columns.add(field.alias)
            else:
                expected_columns.add(field_name)
        
        # Get column mappings for this table
        mappings = COLUMN_MAPPINGS.get(actual_table, {})
        
        # Check each expected column
        missing_mappings = []
        for expected_col in sorted(expected_columns):
            mapped_col = mappings.get(expected_col, expected_col)
            exists = mapped_col in actual_columns
            
            if exists:
                if expected_col != mapped_col:
                    print(f"  ✅ {expected_col} → {mapped_col} (mapped)")
                else:
                    print(f"  ✅ {expected_col} (direct match)")
            else:
                print(f"  ❌ {expected_col} → {mapped_col} (MISSING in DB)")
                missing_mappings.append((expected_col, mapped_col))
        
        # Check for extra columns in DB not in model
        model_columns = set(mappings.values()) | expected_columns
        extra_columns = actual_columns - model_columns - {'id', 'created_at', 'updated_at'}
        if extra_columns:
            print(f"  ℹ️  Extra columns in DB: {extra_columns}")
            
        return missing_mappings

    def suggest_fixes(self):
        """Suggest SQL to fix missing columns"""
        print("\n" + "=" * 70)
        print("SUGGESTED FIXES")
        print("=" * 70)
        
        # Check each table
        for expected_table in ['source_documents', 'document_chunks', 'entity_mentions']:
            mapped_table = TABLE_MAPPINGS.get(expected_table, expected_table)
            
            if mapped_table not in self.inspector.get_table_names():
                print(f"\n-- Create table {mapped_table}")
                print(f"-- (See create_schema.sql for structure)")
                continue
                
            # Get missing columns
            model = {
                'source_documents': SourceDocumentModel,
                'document_chunks': ChunkModel,
                'entity_mentions': EntityMentionModel
            }.get(expected_table)
            
            if not model:
                continue
                
            missing = self._check_missing_columns(expected_table, mapped_table, model)
            
            if missing:
                print(f"\n-- Add missing columns to {mapped_table}:")
                for col_name, col_type in missing:
                    print(f"ALTER TABLE {mapped_table} ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
    
    def _check_missing_columns(self, expected_table: str, actual_table: str, model) -> List[Tuple[str, str]]:
        """Get list of missing columns with their types"""
        actual_columns = {col['name'] for col in self.inspector.get_columns(actual_table)}
        mappings = COLUMN_MAPPINGS.get(actual_table, {})
        
        missing = []
        
        # Common column types based on field types
        type_map = {
            'str': 'TEXT',
            'int': 'INTEGER',
            'float': 'DOUBLE PRECISION',
            'bool': 'BOOLEAN',
            'datetime': 'TIMESTAMP WITH TIME ZONE',
            'UUID': 'UUID',
            'Dict': 'JSONB',
            'List': 'JSONB'
        }
        
        for field_name, field in model.__fields__.items():
            expected_col = field.alias if hasattr(field, 'alias') and field.alias else field_name
            mapped_col = mappings.get(expected_col, expected_col)
            
            if mapped_col not in actual_columns:
                # Determine SQL type
                field_type = field.annotation
                sql_type = 'TEXT'  # default
                
                if hasattr(field_type, '__name__'):
                    type_name = field_type.__name__
                    sql_type = type_map.get(type_name, 'TEXT')
                
                # Special cases
                if 'uuid' in mapped_col.lower():
                    sql_type = 'UUID'
                elif 'json' in mapped_col.lower() or 'metadata' in mapped_col.lower():
                    sql_type = 'JSONB'
                elif 'count' in mapped_col.lower() or 'size' in mapped_col.lower():
                    sql_type = 'INTEGER'
                elif 'score' in mapped_col.lower():
                    sql_type = 'DOUBLE PRECISION'
                    
                missing.append((mapped_col, sql_type))
                
        return missing

    def test_operations(self):
        """Test actual database operations through the mapping layer"""
        print("\n" + "=" * 70)
        print("TESTING ACTUAL OPERATIONS")
        print("=" * 70)
        
        from scripts.rds_utils import insert_record, select_records, table_exists
        import uuid
        
        # Test 1: Check if we can insert into 'source_documents' (mapped to 'documents')
        print("\nTest 1: Insert document through mapping layer")
        test_id = str(uuid.uuid4())
        
        try:
            result = insert_record('source_documents', {
                'document_uuid': test_id,
                'original_file_name': 'conformance_test.pdf',
                'processing_status': 'pending'
            })
            print("✅ Insert successful through mapping layer")
            
            # Try to read it back
            docs = select_records('source_documents', {'document_uuid': test_id})
            if docs:
                print("✅ Read back successful")
                print(f"   Document status: {docs[0].get('status', 'N/A')}")
        except Exception as e:
            print(f"❌ Operation failed: {e}")

def main():
    # Get database URL
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        return 1
    
    # Run conformance check
    checker = ConformanceChecker(db_url)
    
    # Check conformance
    conformant = checker.check_conformance()
    
    # Suggest fixes
    checker.suggest_fixes()
    
    # Test operations
    checker.test_operations()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if conformant:
        print("✅ Pipeline can work with current RDS schema using mapping layer!")
    else:
        print("⚠️  Some tables are missing, but mapping layer handles most cases")
        print("   Run the suggested SQL fixes to complete the setup")
    
    return 0 if conformant else 1

if __name__ == "__main__":
    sys.exit(main())