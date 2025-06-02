#!/usr/bin/env python3
"""
Process documents through the pipeline and monitor their progress
"""
import os
import sys
import time
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import after path setup
from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document
from scripts.test_multiple_documents_e2e import DocumentPipelineVerifier

def process_documents(documents):
    """Submit documents for processing"""
    tasks = []
    
    for doc in documents:
        logger.info(f"Submitting {doc['file_name']} for processing...")
        
        # Submit to Celery
        task = process_pdf_document.delay(
            document_uuid=doc['document_uuid'],
            file_path=doc['s3_key'],  # S3 key is used as file path
            project_uuid=doc['project_uuid'],
            document_metadata={'file_name': doc['file_name']}
        )
        
        tasks.append({
            'document_uuid': doc['document_uuid'],
            'file_name': doc['file_name'],
            'task_id': task.id,
            'task': task
        })
        
        logger.info(f"  Task ID: {task.id}")
    
    return tasks

def monitor_progress(tasks, max_wait=300, check_interval=10):
    """Monitor document processing progress"""
    verifier = DocumentPipelineVerifier()
    start_time = time.time()
    
    print(f"\nMonitoring {len(tasks)} documents...")
    print("="*80)
    
    completed = set()
    
    while len(completed) < len(tasks) and (time.time() - start_time) < max_wait:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking status...")
        
        for task_info in tasks:
            if task_info['document_uuid'] in completed:
                continue
            
            doc_uuid = task_info['document_uuid']
            file_name = task_info['file_name']
            
            print(f"\n{file_name}:")
            
            # Quick verification of key stages
            stages = []
            
            # OCR
            ocr = verifier.verify_ocr_stage(doc_uuid)
            stages.append(('OCR', ocr['completed'], f"{ocr['text_length']} chars" if ocr['completed'] else "waiting"))
            
            # Chunking
            chunking = verifier.verify_chunking_stage(doc_uuid)
            stages.append(('Chunks', chunking['completed'], f"{chunking['chunk_count']} chunks" if chunking['completed'] else "waiting"))
            
            # Entities
            entities = verifier.verify_entity_extraction_stage(doc_uuid)
            stages.append(('Entities', entities['completed'], f"{entities['total_mentions']} mentions" if entities['completed'] else "waiting"))
            
            # Resolution
            resolution = verifier.verify_entity_resolution_stage(doc_uuid)
            stages.append(('Resolution', resolution['completed'], resolution['resolution_rate'] if resolution['completed'] else "waiting"))
            
            # Relationships
            relationships = verifier.verify_relationship_stage(doc_uuid)
            stages.append(('Relations', relationships['completed'], f"{relationships['relationship_count']} rels" if relationships['completed'] else "waiting"))
            
            # Completion
            completion = verifier.verify_pipeline_completion(doc_uuid)
            stages.append(('Complete', completion['completed'], completion['database_status']))
            
            # Print stage status
            for stage_name, is_complete, detail in stages:
                status = "✅" if is_complete else "⏳"
                print(f"  {status} {stage_name}: {detail}")
            
            # Check if fully processed
            if all(stage[1] for stage in stages):
                completed.add(doc_uuid)
                print(f"  🎉 FULLY PROCESSED!")
        
        if len(completed) < len(tasks):
            print(f"\nWaiting {check_interval} seconds before next check...")
            time.sleep(check_interval)
    
    # Final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    print(f"Completed: {len(completed)}/{len(tasks)}")
    print(f"Time elapsed: {time.time() - start_time:.1f} seconds")
    
    return completed

def main():
    """Process and monitor documents"""
    # Documents to process
    documents = [
        {
            'document_uuid': '519fd8c1-40fc-4671-b20b-12a3bb919634',
            'file_name': 'Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf',
            's3_key': 'documents/519fd8c1-40fc-4671-b20b-12a3bb919634.pdf',
            'project_uuid': 'e0c57112-c755-4798-bc1f-4ecc3f0eec78'
        },
        {
            'document_uuid': 'b1588104-009f-44b7-9931-79b866d5ed79',
            'file_name': 'Paul, Michael - Riverdale Disclosure Stmt 10-25-24.pdf',
            's3_key': 'documents/b1588104-009f-44b7-9931-79b866d5ed79.pdf',
            'project_uuid': 'e0c57112-c755-4798-bc1f-4ecc3f0eec78'
        },
        {
            'document_uuid': '849531b3-89e0-4187-9dd2-ea8779b4f069',
            'file_name': 'Paul, Michael - Plaintiff Acuity Disclosure Stmt 9-20-24.pdf',
            's3_key': 'documents/849531b3-89e0-4187-9dd2-ea8779b4f069.pdf',
            'project_uuid': 'e0c57112-c755-4798-bc1f-4ecc3f0eec78'
        }
    ]
    
    print("\n" + "="*80)
    print("DOCUMENT PROCESSING AND MONITORING")
    print("="*80)
    
    # Submit documents for processing
    print("\nSubmitting documents for processing...")
    tasks = process_documents(documents)
    
    # Monitor progress
    completed = monitor_progress(tasks, max_wait=600, check_interval=15)
    
    # Run detailed verification on completed documents
    if completed:
        print("\n\nRunning detailed verification on completed documents...")
        verifier = DocumentPipelineVerifier()
        
        for doc in documents:
            if doc['document_uuid'] in completed:
                print(f"\n{'#'*80}")
                print(f"DETAILED VERIFICATION: {doc['file_name']}")
                print(f"{'#'*80}")
                verifier.verify_document_pipeline({
                    'document_uuid': doc['document_uuid'],
                    'file_name': doc['file_name'],
                    'status': 'processing'
                })

if __name__ == "__main__":
    main()