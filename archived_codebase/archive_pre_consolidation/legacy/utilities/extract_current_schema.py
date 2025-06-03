#!/usr/bin/env python3
"""
Extract current Supabase schema to fix monitoring script
"""
import json
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager

def extract_schema():
    """Extract schema by querying actual tables"""
    db = SupabaseManager()
    schema = {
        "extraction_timestamp": datetime.now().isoformat(),
        "tables": {}
    }
    
    # List of tables to check
    tables_to_check = [
        'document_processing_queue',
        'source_documents', 
        'neo4j_documents',
        'neo4j_chunks',
        'neo4j_entity_mentions',
        'neo4j_canonical_entities',
        'neo4j_relationships_staging',
        'textract_jobs',
        'projects'
    ]
    
    print("Extracting Supabase schema...")
    
    for table_name in tables_to_check:
        try:
            # Get a sample row to see columns
            result = db.client.table(table_name).select('*').limit(1).execute()
            
            if result.data and len(result.data) > 0:
                # Extract column names from the first row
                columns = list(result.data[0].keys())
                schema['tables'][table_name] = {
                    'columns': columns,
                    'sample_row': result.data[0]
                }
                print(f"✅ {table_name}: {len(columns)} columns found")
            else:
                # Table exists but is empty, try to get structure from an error
                print(f"⚠️  {table_name}: Table is empty, checking structure...")
                # Try a query that will fail but give us info
                try:
                    db.client.table(table_name).select('*').eq('id', -999999).execute()
                    schema['tables'][table_name] = {'columns': [], 'note': 'empty table'}
                except Exception as e:
                    schema['tables'][table_name] = {'columns': [], 'error': str(e)}
                
        except Exception as e:
            print(f"❌ {table_name}: {str(e)}")
            schema['tables'][table_name] = {'error': str(e)}
    
    # Save schema
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"monitoring/current_schema_{timestamp}.json"
    
    os.makedirs('monitoring', exist_ok=True)
    
    with open(filename, 'w') as f:
        json.dump(schema, f, indent=2, default=str)
    
    print(f"\n📄 Schema saved to: {filename}")
    
    # Print summary of key columns
    print("\n🔍 Key columns found:")
    if 'document_processing_queue' in schema['tables'] and 'columns' in schema['tables']['document_processing_queue']:
        cols = schema['tables']['document_processing_queue']['columns']
        print(f"\ndocument_processing_queue columns: {', '.join(cols)}")
        
        # Check for document ID column
        doc_id_cols = [col for col in cols if 'document' in col.lower() or 'doc' in col.lower()]
        if doc_id_cols:
            print(f"  Document ID columns found: {doc_id_cols}")
    
    return schema

if __name__ == "__main__":
    extract_schema()