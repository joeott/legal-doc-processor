#!/usr/bin/env python3
"""
Simple pragmatic document processor for Paul, Michael (Acuity) case.
Processes documents one by one, fixing errors as they arise.
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, '/opt/legal-doc-processor/scripts')

# Import required modules
from s3_storage import S3StorageManager
from textract_utils import TextractProcessor
import uuid

def process_single_document(file_path):
    """Process a single document through Textract."""
    print(f"\n{'='*60}")
    print(f"Processing: {os.path.basename(file_path)}")
    print(f"Size: {os.path.getsize(file_path) / (1024*1024):.2f} MB")
    
    try:
        # Step 1: Upload to S3
        s3_manager = S3StorageManager()
        doc_uuid = str(uuid.uuid4())
        
        result = s3_manager.upload_document_with_uuid_naming(
            local_file_path=file_path,
            document_uuid=doc_uuid,
            original_filename=os.path.basename(file_path)
        )
        
        s3_url = f"s3://{s3_manager.private_bucket_name}/documents/{doc_uuid}.pdf"
        
        print(f"✅ Uploaded to S3: {s3_url}")
        
        # Step 2: Submit to Textract
        # Use boto3 directly for simplicity
        import boto3
        textract_client = boto3.client('textract', region_name='us-east-2')
        
        bucket = s3_manager.private_bucket_name
        file_ext = os.path.splitext(file_path)[1].lower()
        s3_key = f"documents/{doc_uuid}{file_ext}"
        
        response = textract_client.start_document_text_detection(
            DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': s3_key}}
        )
        job_id = response['JobId']
        
        print(f"✅ Textract job started: {job_id}")
        
        # Step 3: Wait for completion
        print("⏳ Waiting for Textract to complete...", end='', flush=True)
        while True:
            response = textract_client.get_document_text_detection(JobId=job_id)
            status = response['JobStatus']
            
            if status == 'SUCCEEDED':
                print(" ✅ SUCCEEDED")
                pages = response.get('DocumentMetadata', {}).get('Pages', 0)
                print(f"📄 Document has {pages} pages")
                return {
                    'file': os.path.basename(file_path),
                    'status': 'SUCCESS',
                    'job_id': job_id,
                    'pages': pages,
                    'uuid': doc_uuid
                }
            elif status == 'FAILED':
                print(" ❌ FAILED")
                return {
                    'file': os.path.basename(file_path),
                    'status': 'FAILED',
                    'error': response.get('StatusMessage', 'Unknown error')
                }
            else:
                print(".", end='', flush=True)
                time.sleep(5)
                
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        return {
            'file': os.path.basename(file_path),
            'status': 'ERROR',
            'error': str(e)
        }

def main():
    """Process all documents in Paul, Michael case."""
    # Load document discovery
    discovery_file = "/opt/legal-doc-processor/paul_michael_discovery_20250604_032359.json"
    
    with open(discovery_file, 'r') as f:
        discovery = json.load(f)
    
    documents = discovery['documents']
    total = len(documents)
    
    print(f"🚀 Starting processing of {total} documents")
    print(f"📁 Paul, Michael (Acuity) case")
    
    results = []
    succeeded = 0
    failed = 0
    
    start_time = time.time()
    
    # Process each document
    for i, doc in enumerate(documents, 1):
        print(f"\n[{i}/{total}] Document {i} of {total}")
        
        result = process_single_document(doc['absolute_path'])
        results.append(result)
        
        if result['status'] == 'SUCCESS':
            succeeded += 1
        else:
            failed += 1
        
        # Show running statistics
        elapsed = time.time() - start_time
        rate = i / (elapsed / 3600) if elapsed > 0 else 0
        eta = (total - i) / rate if rate > 0 else 0
        
        print(f"\n📊 Progress: {succeeded} succeeded, {failed} failed")
        print(f"⏱️  Rate: {rate:.1f} docs/hour, ETA: {eta:.1f} hours")
    
    # Final report
    print(f"\n{'='*60}")
    print(f"📊 FINAL REPORT")
    print(f"{'='*60}")
    print(f"Total documents: {total}")
    print(f"Succeeded: {succeeded} ({succeeded/total*100:.1f}%)")
    print(f"Failed: {failed} ({failed/total*100:.1f}%)")
    print(f"Total time: {(time.time() - start_time)/60:.1f} minutes")
    
    # Save results
    results_file = f"paul_michael_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump({
            'summary': {
                'total': total,
                'succeeded': succeeded,
                'failed': failed,
                'success_rate': succeeded/total*100 if total > 0 else 0
            },
            'documents': results
        }, f, indent=2)
    
    print(f"\n💾 Results saved to: {results_file}")

if __name__ == "__main__":
    main()