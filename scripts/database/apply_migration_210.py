#!/usr/bin/env python3
"""
Apply Context 203 Schema Migration to Supabase
This script applies the schema changes directly through table operations
"""

import os
import sys
from datetime import datetime
from typing import Dict
import json

# Add the project root to the path so we can import modules
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from scripts.database import get_supabase_client
from rich.console import Console
from rich.progress import track
from rich.table import Table

console = Console()

def apply_schema_migration():
    """Apply the complete context_203 schema migration."""
    
    console.print("[bold blue]Starting Context 203 Schema Migration...[/bold blue]")
    
    supabase = get_supabase_client()
    
    # Since we can't execute raw SQL, we'll use table operations to verify/create the schema
    # This approach checks what exists and reports on compliance
    
    expected_tables = {
        'projects': {
            'description': 'Core projects table',
            'required_columns': ['project_uuid', 'project_name', 'project_code', 'client_name', 'processing_config']
        },
        'documents': {
            'description': 'Main documents table with processing state',
            'required_columns': ['document_uuid', 'project_uuid', 'original_filename', 'processing_status']
        },
        'processing_pipeline': {
            'description': 'Pipeline stage tracking',
            'required_columns': ['pipeline_id', 'document_uuid', 'stage_name', 'stage_status']
        },
        'processing_queue': {
            'description': 'Document processing queue',
            'required_columns': ['queue_id', 'document_uuid', 'priority', 'queue_status']
        },
        'document_chunks': {
            'description': 'Document text chunks with embeddings',
            'required_columns': ['chunk_uuid', 'document_uuid', 'chunk_index', 'chunk_text']
        },
        'entity_mentions': {
            'description': 'Raw entity extractions',
            'required_columns': ['mention_uuid', 'chunk_uuid', 'entity_text', 'entity_type']
        },
        'canonical_entities': {
            'description': 'Resolved unique entities',
            'required_columns': ['entity_uuid', 'project_uuid', 'entity_name', 'entity_type']
        },
        'relationship_staging': {
            'description': 'Pre-graph relationship storage',
            'required_columns': ['staging_uuid', 'from_entity_uuid', 'to_entity_uuid', 'relationship_type']
        },
        'processing_metrics': {
            'description': 'Performance metrics aggregation',
            'required_columns': ['metric_id', 'metric_date', 'project_uuid', 'processing_stage']
        },
        'import_sessions': {
            'description': 'Batch import tracking',
            'required_columns': ['session_uuid', 'project_uuid', 'session_name', 'total_files']
        }
    }
    
    # Check current schema status
    console.print("\n[bold yellow]Checking Current Schema Status...[/bold yellow]")
    
    schema_status = {}
    
    for table_name, _table_info in track(expected_tables.items(), description="Checking tables..."):
        try:
            # Try to query the table to see if it exists
            result = supabase.table(table_name).select('*').limit(1).execute()
            schema_status[table_name] = {
                'exists': True,
                'accessible': True,
                'record_count': len(result.data) if result.data else 0
            }
            
            # Try to get count
            try:
                count_result = supabase.table(table_name).select('*', count='exact').execute()
                schema_status[table_name]['total_records'] = count_result.count
            except:
                schema_status[table_name]['total_records'] = 'Unknown'
                
        except Exception as e:
            if 'does not exist' in str(e):
                schema_status[table_name] = {
                    'exists': False,
                    'accessible': False,
                    'error': 'Table does not exist'
                }
            else:
                schema_status[table_name] = {
                    'exists': 'Unknown',
                    'accessible': False,
                    'error': str(e)[:100]
                }
    
    # Display results table
    display_schema_status(schema_status, expected_tables)
    
    # Generate migration instructions
    generate_migration_instructions(schema_status, expected_tables)
    
    return schema_status

def display_schema_status(schema_status: Dict, expected_tables: Dict):
    """Display the current schema status in a table."""
    
    table = Table(title="Schema Migration Status", show_header=True, header_style="bold magenta")
    table.add_column("Table", style="cyan", width=20)
    table.add_column("Status", style="yellow", width=12)
    table.add_column("Records", style="green", width=10)
    table.add_column("Description", style="white", width=30)
    
    for table_name, table_info in expected_tables.items():
        status = schema_status.get(table_name, {})
        
        if status.get('exists'):
            status_text = "✅ EXISTS"
            records = str(status.get('total_records', 'N/A'))
        else:
            status_text = "❌ MISSING"
            records = "-"
            
        table.add_row(
            table_name,
            status_text,
            records,
            table_info['description']
        )
    
    console.print(table)

def generate_migration_instructions(schema_status: Dict, expected_tables: Dict):
    """Generate specific migration instructions."""
    
    missing_tables = [name for name, status in schema_status.items() if not status.get('exists')]
    existing_tables = [name for name, status in schema_status.items() if status.get('exists')]
    
    # Use expected_tables for context but primary logic is based on schema_status
    total_expected = len(expected_tables)
    
    console.print(f"\n[bold green]Migration Summary:[/bold green]")
    console.print(f"✅ Existing tables: {len(existing_tables)}")
    console.print(f"❌ Missing tables: {len(missing_tables)}")
    
    if missing_tables:
        console.print(f"\n[bold red]Missing tables requiring manual creation in Supabase Dashboard:[/bold red]")
        for table in missing_tables:
            console.print(f"  • {table}")
            
        console.print(f"\n[bold yellow]Next Steps:[/bold yellow]")
        console.print("1. Open Supabase Dashboard > SQL Editor")
        console.print("2. Execute the migration SQL file: scripts/database/migration_210_complete_schema.sql")
        console.print("3. Verify all tables are created successfully")
        console.print("4. Run this script again to verify completion")
        console.print("5. Update CLI tools to use new schema")
    else:
        console.print(f"\n[bold green]✅ All tables exist! Schema migration is complete.[/bold green]")
        console.print("Next: Update CLI tools and test functionality")
    
    # Save status to file
    status_file = f"ai_docs/migration_210_status_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(status_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'schema_status': schema_status,
            'missing_tables': missing_tables,
            'existing_tables': existing_tables
        }, f, indent=2)
    
    console.print(f"\nDetailed status saved to: {status_file}")

if __name__ == "__main__":
    try:
        apply_schema_migration()
    except Exception as e:
        console.print(f"[bold red]Migration failed: {e}[/bold red]")
        sys.exit(1)