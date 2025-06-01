#!/usr/bin/env python3
"""
Database Cleanup Script - DANGEROUS!
This script will permanently delete all data from the database.
Use with extreme caution!
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from supabase_utils import SupabaseManager
import argparse
from datetime import datetime
import json

def get_confirmation(message: str) -> bool:
    """Get user confirmation for dangerous operations"""
    print(f"\n⚠️  WARNING: {message}")
    response = input("Type 'YES' (all caps) to confirm: ")
    return response == "YES"

def print_current_stats(db: SupabaseManager):
    """Print current database statistics"""
    print("\n📊 Current Database Statistics:")
    print("-" * 50)
    
    tables = [
        'projects',
        'source_documents', 
        'neo4j_documents',
        'neo4j_chunks',
        'neo4j_entity_mentions',
        'neo4j_canonical_entities',
        'neo4j_relationships_staging',
        'document_processing_queue',
        'textract_jobs'
    ]
    
    total_rows = 0
    for table in tables:
        try:
            # Use service client for RLS-protected tables
            client = db.service_client if table in ['neo4j_relationships_staging'] else db.client
            result = client.table(table).select('*', count='exact').limit(1).execute()
            count = result.count if hasattr(result, 'count') else 0
            print(f"{table:30} {count:>10} rows")
            total_rows += count
        except Exception as e:
            print(f"{table:30} {'ERROR':>10} ({str(e)[:30]}...)")
    
    print("-" * 50)
    print(f"{'TOTAL':30} {total_rows:>10} rows")
    print("-" * 50)

def cleanup_all_data(db: SupabaseManager, skip_confirm: bool = False):
    """Clean up all data from the database"""
    
    # Show current stats
    print_current_stats(db)
    
    if not skip_confirm:
        # First confirmation
        if not get_confirmation("This will DELETE ALL DATA from ALL TABLES!"):
            print("\n❌ Operation cancelled.")
            return
        
        # Second confirmation
        print("\n🔴 FINAL WARNING: This action CANNOT be undone!")
        print("All documents, projects, entities, and relationships will be PERMANENTLY DELETED!")
        
        if not get_confirmation("Are you ABSOLUTELY SURE you want to delete EVERYTHING?"):
            print("\n❌ Operation cancelled.")
            return
    
    # Create backup info
    backup_info = {
        'timestamp': datetime.now().isoformat(),
        'action': 'complete_database_cleanup',
        'warning': 'All data was deleted'
    }
    
    # Save backup info
    backup_file = f"cleanup_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(backup_file, 'w') as f:
        json.dump(backup_info, f, indent=2)
    
    print(f"\n📝 Backup info saved to: {backup_file}")
    print("\n🗑️  Starting database cleanup...")
    
    try:
        # Perform the cleanup
        deletion_counts = db.cleanup_all_data(confirm=True)
        
        # Print results
        print("\n✅ Cleanup Complete!")
        print("-" * 50)
        print("Deleted rows by table:")
        for table, count in deletion_counts.items():
            if count >= 0:
                print(f"{table:30} {count:>10} rows deleted")
            else:
                print(f"{table:30} {'ERROR':>10}")
        
        total_deleted = sum(c for c in deletion_counts.values() if c > 0)
        print("-" * 50)
        print(f"{'TOTAL DELETED':30} {total_deleted:>10} rows")
        
        # Show final stats (should be all zeros)
        print("\n📊 Final Database Statistics (should be empty):")
        print_current_stats(db)
        
    except Exception as e:
        print(f"\n❌ Error during cleanup: {e}")
        raise

def cleanup_project(db: SupabaseManager, project_id: str, skip_confirm: bool = False):
    """Clean up data for a specific project"""
    
    print(f"\n🔍 Looking up project: {project_id}")
    
    # Verify project exists
    project_result = db.client.table('projects').select('*').eq('projectId', project_id).execute()
    
    if not project_result.data:
        print(f"❌ Project not found: {project_id}")
        return
    
    project = project_result.data[0]
    print(f"✓ Found project: {project.get('name', 'Unnamed')} (ID: {project['id']})")
    
    # Get document count
    doc_count = db.client.table('source_documents').select('*', count='exact').eq('project_uuid', project_id).limit(1).execute()
    doc_count = doc_count.count if hasattr(doc_count, 'count') else 0
    
    print(f"📄 This project has {doc_count} documents")
    
    if not skip_confirm:
        if not get_confirmation(f"Delete all data for project '{project.get('name', project_id)}'?"):
            print("\n❌ Operation cancelled.")
            return
    
    print(f"\n🗑️  Cleaning up project: {project_id}")
    
    try:
        deletion_counts = db.cleanup_project_data(project_id)
        
        # Print results
        print("\n✅ Project Cleanup Complete!")
        print("-" * 50)
        print("Deleted rows by table:")
        for table, count in deletion_counts.items():
            if count > 0:
                print(f"{table:30} {count:>10} rows deleted")
        
        total_deleted = sum(deletion_counts.values())
        print("-" * 50)
        print(f"{'TOTAL DELETED':30} {total_deleted:>10} rows")
        
    except Exception as e:
        print(f"\n❌ Error during cleanup: {e}")
        raise

def main():
    parser = argparse.ArgumentParser(
        description='Database Cleanup Tool - DANGEROUS! Permanently deletes data.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show current database statistics
  python cleanup_database.py --stats
  
  # Clean up all data (with confirmations)
  python cleanup_database.py --all
  
  # Clean up specific project
  python cleanup_database.py --project "project-uuid-here"
  
  # Force cleanup without confirmations (VERY DANGEROUS!)
  python cleanup_database.py --all --force
        """
    )
    
    parser.add_argument('--stats', action='store_true', 
                       help='Show current database statistics only')
    parser.add_argument('--all', action='store_true',
                       help='Delete ALL data from ALL tables')
    parser.add_argument('--project', type=str,
                       help='Delete data for specific project UUID')
    parser.add_argument('--force', action='store_true',
                       help='Skip confirmation prompts (DANGEROUS!)')
    
    args = parser.parse_args()
    
    # Initialize database
    print("🔌 Connecting to database...")
    db = SupabaseManager()
    
    if args.stats:
        print_current_stats(db)
    elif args.all:
        cleanup_all_data(db, skip_confirm=args.force)
    elif args.project:
        cleanup_project(db, args.project, skip_confirm=args.force)
    else:
        parser.print_help()
        print("\n⚠️  No action specified. Use --help for usage information.")

if __name__ == "__main__":
    main()