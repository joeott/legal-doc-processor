#!/usr/bin/env python3
"""Test single document through Celery pipeline"""
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.supabase_utils import SupabaseManager
from scripts.celery_tasks.ocr_tasks import process_ocr
from scripts.ocr_extraction import detect_file_category

def test_single_document(file_path_str=None):
    """Test single document processing"""
    db = SupabaseManager()
    
    # Get file path from argument or use default
    if file_path_str:
        file_path = Path(file_path_str)
    else:
        file_path = Path("/Users/josephott/Documents/phase_1_2_3_process_v5/input/Zwicky, Jessica/Medicals/Jessica Zwicky - SJCMO Med Rec and Bill.pdf")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return
        
    print(f"📄 Testing document: {file_path.name}")
    
    try:
        # Create project
        project_result = db.get_or_create_project(
            "test-single-doc",
            "Single Document Test"
        )
        
        # Handle the return from get_or_create_project
        # The function returns (project_model, sql_id, project_uuid)
        if hasattr(project_result[0], 'id'):
            # First element is the model
            project_model = project_result[0]
            project_id_sql = project_model.id
            project_uuid = str(project_model.project_id)
        else:
            # Fallback to tuple unpacking
            if len(project_result) == 3:
                _, project_id_sql, project_uuid = project_result
            else:
                project_id_sql, project_uuid = project_result
            
        print(f"✅ Project: ID={project_id_sql}, UUID={project_uuid}")
        
        # Detect file type with dot
        file_extension = file_path.suffix.lower()
        if not file_extension.startswith('.'):
            file_extension = '.' + file_extension
            
        # Create source document
        doc_result = db.create_source_document_entry(
            project_fk_id=project_id_sql,
            project_uuid=project_uuid,
            original_file_path=str(file_path),
            original_file_name=file_path.name,
            detected_file_type=file_extension  # Use extension with dot
        )
        
        # Handle the return from create_source_document_entry
        # The function returns (SourceDocumentModel, sql_id, document_uuid)
        if hasattr(doc_result[0], 'id'):
            # First element is the model
            doc_model = doc_result[0]
            doc_id = doc_result[1]
            doc_uuid = doc_result[2]
        else:
            # Fallback to tuple unpacking
            if len(doc_result) == 3:
                _, doc_id, doc_uuid = doc_result
            else:
                doc_id, doc_uuid = doc_result
            
        print(f"✅ Document created: ID={doc_id}, UUID={str(doc_uuid)[:8]}...")
        
        # Determine file category for proper task routing
        file_category = detect_file_category(str(file_path))
        print(f"📁 File category: {file_category}")
        
        # Submit to Celery based on file category
        try:
            # Submit OCR task
            task = process_ocr.delay(
                document_uuid=str(doc_uuid),
                source_doc_sql_id=doc_id,
                file_path=str(file_path),
                file_name=file_path.name,
                detected_file_type=file_extension,
                project_sql_id=project_id_sql
            )
            
            # Update document with task ID
            db.client.table('source_documents').update({
                'celery_task_id': task.id,
                'celery_status': 'submitted',
                'file_category': file_category
            }).eq('id', doc_id).execute()
            
            print(f"✅ Submitted to Celery with task ID: {task.id}")
            print(f"📊 Monitor with: python scripts/cli/monitor.py document {str(doc_uuid)}")
            
            # Return document info for monitoring
            return {
                'doc_id': doc_id,
                'doc_uuid': doc_uuid,
                'task_id': task.id,
                'file_path': str(file_path)
            }
            
        except Exception as e:
            print(f"⚠️  Could not submit to Celery: {e}")
            print("   Please ensure Celery workers are running")
            import traceback
            traceback.print_exc()
            
        # Monitor for a bit
        print("\n⏳ Monitoring status...")
        for i in range(30):  # Monitor for 60 seconds
            result = db.client.table('source_documents')\
                .select('celery_status, error_message')\
                .eq('id', doc_id)\
                .single()\
                .execute()
                
            status = result.data.get('celery_status', 'unknown')
            print(f"  [{i*2}s] Status: {status}")
            
            if status == 'completed':
                print("\n✅ Document processed successfully!")
                break
            elif status.endswith('_failed'):
                error = result.data.get('error_message', 'Unknown error')
                print(f"\n❌ Processing failed: {error}")
                break
                
            time.sleep(2)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Test single document processing')
    parser.add_argument('file_path', nargs='?', help='Path to file to process')
    args = parser.parse_args()
    
    test_single_document(args.file_path)