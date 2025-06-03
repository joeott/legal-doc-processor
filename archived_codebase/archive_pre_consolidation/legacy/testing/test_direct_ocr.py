#!/usr/bin/env python3
"""Test OCR processing directly without Celery"""
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ocr_extraction import extract_text_from_pdf_textract
from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3StorageManager

def test_direct_ocr():
    """Test OCR processing directly"""
    db = SupabaseManager()
    s3_manager = S3StorageManager()
    
    # File to test
    file_path = Path("/Users/josephott/Documents/phase_1_2_3_process_v5/input_docs/Pre-Trial Order -  Ory v. Roeslein.pdf")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return
        
    print(f"📄 Testing direct OCR on: {file_path.name}")
    
    try:
        # First, upload to S3 since Textract needs S3 URIs
        print("\n📤 Uploading to S3...")
        upload_result = s3_manager.upload_document_with_uuid_naming(
            local_file_path=str(file_path),
            document_uuid="test-ocr-doc",
            original_filename=file_path.name
        )
        s3_uri = f"s3://{upload_result['s3_bucket']}/{upload_result['s3_key']}"
        print(f"✅ Uploaded to S3: {s3_uri}")
        
        # Create a test document entry
        project_id_sql, project_uuid = db.get_or_create_project(
            "test-direct-ocr",
            "Direct OCR Test"
        )
        
        # Check if document already exists, delete if so
        existing = db.client.table('source_documents')\
            .select('id')\
            .eq('original_file_name', file_path.name)\
            .eq('project_fk_id', project_id_sql)\
            .execute()
            
        if existing.data:
            print(f"🗑️  Removing existing test document...")
            db.client.table('source_documents').delete().eq('id', existing.data[0]['id']).execute()
        
        # Create new document entry
        doc_id, doc_uuid = db.create_source_document_entry(
            project_fk_id=project_id_sql,
            project_uuid=project_uuid,
            original_file_path=s3_uri,
            original_file_name=file_path.name,
            detected_file_type="pdf"
        )
        print(f"✅ Document created: ID={doc_id}, UUID={doc_uuid[:8]}...")
        
        # Run OCR directly
        print("\n🔍 Running OCR with Textract...")
        raw_text, ocr_meta = extract_text_from_pdf_textract(
            db_manager=db,
            source_doc_sql_id=doc_id,
            pdf_path_or_s3_uri=s3_uri,
            document_uuid_from_db=doc_uuid
        )
        
        if raw_text:
            print(f"✅ OCR successful! Extracted {len(raw_text)} characters")
            print(f"\n📝 First 500 characters:")
            print("-" * 50)
            print(raw_text[:500])
            print("-" * 50)
            
            # Check database update
            result = db.client.table('source_documents')\
                .select('raw_extracted_text, initial_processing_status')\
                .eq('id', doc_id)\
                .single()\
                .execute()
                
            if result.data.get('raw_extracted_text'):
                print(f"\n✅ Database updated successfully")
                print(f"   Status: {result.data.get('initial_processing_status')}")
            else:
                print(f"\n⚠️  Database not updated with OCR text")
        else:
            print(f"❌ OCR failed - no text extracted")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_direct_ocr()