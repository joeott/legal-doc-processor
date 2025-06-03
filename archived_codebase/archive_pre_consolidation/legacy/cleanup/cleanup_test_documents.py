#!/usr/bin/env python3
"""Cleanup test documents from database"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager

def cleanup_test_documents():
    db = SupabaseManager()
    
    print("🧹 Cleaning up test documents...")
    
    # Find all test projects
    test_project_names = [
        "test-celery-e2e", "test-single-doc", "test-direct-ocr", 
        "test-full-pipeline", "Single Document Test", "Direct OCR Test",
        "Full Pipeline Test"
    ]
    
    for project_name in test_project_names:
        result = db.client.table('projects').select('id, name').eq('name', project_name).execute()
        if result.data:
            project_id = result.data[0]['id']
            print(f"\n📦 Found test project: {project_name} (ID: {project_id})")
            
            # Delete source documents
            docs = db.client.table('source_documents').select('id').eq('project_fk_id', project_id).execute()
            if docs.data:
                print(f"   Deleting {len(docs.data)} source documents...")
                db.client.table('source_documents').delete().eq('project_fk_id', project_id).execute()
            
            # Delete neo4j documents
            neo4j_docs = db.client.table('neo4j_documents').select('id').eq('project_id', project_id).execute()
            if neo4j_docs.data:
                print(f"   Deleting {len(neo4j_docs.data)} neo4j documents...")
                db.client.table('neo4j_documents').delete().eq('project_id', project_id).execute()
            
            # Delete project
            db.client.table('projects').delete().eq('id', project_id).execute()
            print(f"   ✅ Deleted project {project_name}")
    
    # Also clean up any documents with test paths
    test_paths = [
        's3://samu-docs-private-upload/documents/test-pipeline-doc.pdf',
        's3://samu-docs-private-upload/documents/test-ocr-doc.pdf'
    ]
    
    for path in test_paths:
        result = db.client.table('source_documents').select('id').eq('original_file_path', path).execute()
        if result.data:
            print(f"\n🗑️  Found {len(result.data)} documents with path: {path}")
            db.client.table('source_documents').delete().eq('original_file_path', path).execute()
            print(f"   ✅ Deleted")
    
    print("\n✅ Cleanup complete!")

if __name__ == "__main__":
    cleanup_test_documents()