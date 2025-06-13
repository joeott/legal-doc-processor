#!/usr/bin/env python3
"""Diagnose why a specific document failed processing."""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from scripts.supabase_utils import SupabaseManager
from scripts.config import *
import boto3
import logging

logging.basicConfig(level=logging.DEBUG)

def diagnose_document(doc_id: int = None, doc_uuid: str = None):
    """Run comprehensive diagnostics on a failed document."""
    db = SupabaseManager()
    
    # Get document
    if doc_id:
        doc_result = db.client.table('source_documents').select('*').eq('id', doc_id).execute()
    elif doc_uuid:
        doc_result = db.client.table('source_documents').select('*').eq('document_uuid', doc_uuid).execute()
    else:
        # Get first failed document
        doc_result = db.client.table('source_documents').select('*').eq('celery_status', 'ocr_failed').limit(1).execute()
    
    if not doc_result.data:
        print("No document found")
        return
    
    doc = doc_result.data[0]
    print(f"\nDocument: {doc['original_file_name']}")
    print(f"Status: {doc['celery_status']}")
    print(f"S3 Key: {doc['s3_key']}")
    
    # Test S3 access
    print("\n1. Testing S3 Access...")
    try:
        s3 = boto3.client('s3')
        response = s3.head_object(Bucket=S3_PRIMARY_DOCUMENT_BUCKET, Key=doc['s3_key'])
        print(f"✅ S3 object exists, size: {response['ContentLength']} bytes")
    except Exception as e:
        print(f"❌ S3 access failed: {e}")
        return
    
    # Test Textract access
    print("\n2. Testing AWS Textract...")
    try:
        textract = boto3.client('textract')
        # Just test that we can call the service
        print("✅ Textract client created successfully")
    except Exception as e:
        print(f"❌ Textract access failed: {e}")
    
    # Test OpenAI access
    print("\n3. Testing OpenAI API...")
    try:
        import openai
        openai.api_key = OPENAI_API_KEY
        # Test with a simple completion
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo-preview",
            messages=[{"role": "user", "content": "Say 'API working'"}],
            max_tokens=10
        )
        print("✅ OpenAI API working")
    except Exception as e:
        print(f"❌ OpenAI API failed: {e}")
    
    # Test direct OCR
    print("\n4. Testing direct OCR extraction...")
    try:
        from scripts.ocr_extraction import extract_text_from_pdf_textract
        result = extract_text_from_pdf_textract(
            db_manager=db,
            source_doc_sql_id=doc['id'],
            pdf_path_or_s3_uri=doc['s3_key'],
            document_uuid_from_db=doc['document_uuid']
        )
        print(f"✅ OCR extraction returned: {type(result)}")
    except Exception as e:
        print(f"❌ OCR extraction failed: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    doc_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    diagnose_document(doc_id)