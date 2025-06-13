#!/usr/bin/env python3
"""
Test script to verify pipeline fix for stages 5-6
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.db import DatabaseManager
from scripts.batch_tasks import submit_batch
from scripts.pdf_tasks import process_pdf_document
from sqlalchemy import text

def check_pipeline_stages(document_uuid):
    """Check which pipeline stages completed for a document"""
    db_manager = DatabaseManager(validate_conformance=False)
    
    with next(db_manager.get_session()) as session:
        # Get all tasks for this document
        result = session.execute(text("""
            SELECT task_type, status, created_at, error_message
            FROM processing_tasks 
            WHERE document_id = :doc_id
            ORDER BY created_at
        """), {'doc_id': document_uuid})
        
        tasks = []
        for row in result:
            tasks.append({
                'task_type': row.task_type,
                'status': row.status,
                'created_at': row.created_at.isoformat(),
                'error_message': row.error_message
            })
            
    return tasks

def test_single_document():
    """Test pipeline with a single document"""
    
    # Use a test document
    test_dir = Path("/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)")
    test_files = list(test_dir.glob("*.pdf"))[:1]  # Just one file
    
    if not test_files:
        print("No test files found!")
        return
        
    test_file = test_files[0]
    print(f"Testing with: {test_file.name}")
    
    # Create document record
    from scripts.batch_tasks import create_document_records
    
    documents = [{
        'filename': test_file.name,
        's3_bucket': 'samu-docs-private-upload',
        's3_key': f'test/{test_file.name}',
        'file_size_mb': test_file.stat().st_size / (1024 * 1024),
        'mime_type': 'application/pdf'
    }]
    
    # Create records and get UUIDs
    doc_records = create_document_records(documents, project_uuid='test-project-123')
    
    if not doc_records:
        print("Failed to create document records")
        return
        
    document_uuid = doc_records[0]['document_uuid']
    print(f"Document UUID: {document_uuid}")
    
    # Start processing directly
    print("\nStarting pipeline processing...")
    result = process_pdf_document(
        document_uuid,
        f"s3://samu-docs-private-upload/test/{test_file.name}",
        'test-project-123',
        {'test': True}
    )
    
    print(f"Pipeline started: {result}")
    
    # Wait and check stages
    print("\nWaiting for pipeline to progress...")
    for i in range(30):  # Check for 5 minutes
        time.sleep(10)
        stages = check_pipeline_stages(document_uuid)
        
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Pipeline stages:")
        stage_summary = {}
        for stage in stages:
            stage_type = stage['task_type']
            stage_status = stage['status']
            stage_summary[stage_type] = stage_status
            
            print(f"  - {stage_type}: {stage_status}")
            if stage['error_message']:
                print(f"    ERROR: {stage['error_message'][:100]}...")
        
        # Check if we have all 6 stages
        expected_stages = [
            'ocr', 'chunking', 'entity_extraction', 
            'entity_resolution', 'relationship_building', 'finalization'
        ]
        
        missing_stages = [s for s in expected_stages if s not in stage_summary]
        if missing_stages:
            print(f"  Missing stages: {missing_stages}")
        
        # Check if pipeline completed or failed
        if all(stage_summary.get(s) in ['completed', 'failed'] 
               for s in stage_summary.keys()):
            print("\nPipeline finished!")
            break
    
    # Final summary
    print("\n" + "="*50)
    print("FINAL PIPELINE STATUS")
    print("="*50)
    
    final_stages = check_pipeline_stages(document_uuid)
    for stage in final_stages:
        status_icon = "✅" if stage['status'] == 'completed' else "❌"
        print(f"{status_icon} {stage['task_type']}: {stage['status']}")
        if stage['error_message']:
            print(f"   Error: {stage['error_message']}")

if __name__ == "__main__":
    test_single_document()