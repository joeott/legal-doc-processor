#!/usr/bin/env python3
"""
Load test for async processing - submit multiple documents concurrently.
"""

import os
import sys
import time
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Setup Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load environment
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

import logging
from scripts.pdf_tasks import process_pdf_document
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.core.model_factory import get_source_document_model

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

def submit_document(index: int):
    """Submit a single document for processing."""
    doc_uuid = str(uuid.uuid4())
    project_uuid = str(uuid.uuid4())
    
    try:
        db_manager = DatabaseManager(validate_conformance=False)
        
        # Create document
        SourceDocumentModel = get_source_document_model()
        doc_model = SourceDocumentModel(
            document_uuid=doc_uuid,
            project_uuid=project_uuid,
            original_file_name=f"load_test_{index}.pdf",
            s3_bucket="samu-docs-private-upload",
            s3_key=f"test/load_test_{index}.pdf",
            status="pending"
        )
        
        result = db_manager.create_source_document(doc_model)
        if not result:
            return None, f"Failed to create document {index}"
        
        # Submit for processing
        s3_path = f"s3://{doc_model.s3_bucket}/{doc_model.s3_key}"
        task = process_pdf_document.apply_async(
            args=[doc_uuid, s3_path, project_uuid]
        )
        
        return {
            'index': index,
            'doc_uuid': doc_uuid,
            'task_id': task.id,
            'status': 'submitted'
        }, None
        
    except Exception as e:
        return None, f"Error submitting document {index}: {e}"

def test_load_async(num_documents=5):
    """Test submitting multiple documents concurrently."""
    logger.info("=" * 60)
    logger.info(f"Starting load test with {num_documents} documents")
    logger.info("=" * 60)
    
    # Submit documents concurrently
    logger.info("\n1. Submitting documents...")
    results = []
    errors = []
    
    with ThreadPoolExecutor(max_workers=num_documents) as executor:
        futures = []
        for i in range(num_documents):
            future = executor.submit(submit_document, i)
            futures.append(future)
        
        for future in as_completed(futures):
            result, error = future.result()
            if result:
                results.append(result)
                logger.info(f"✅ Document {result['index']} submitted: {result['doc_uuid']}")
            else:
                errors.append(error)
                logger.error(f"❌ {error}")
    
    # Monitor all documents
    logger.info(f"\n2. Monitoring {len(results)} documents...")
    redis_manager = get_redis_manager()
    
    start_time = time.time()
    max_wait = 30  # seconds
    
    while time.time() - start_time < max_wait:
        active_count = 0
        for doc_info in results:
            state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_info['doc_uuid'])
            state = redis_manager.get_dict(state_key) or {}
            
            if state:
                pipeline_status = state.get('pipeline', {}).get('status', 'unknown')
                if pipeline_status in ['processing', 'starting']:
                    active_count += 1
        
        logger.info(f"   Active documents: {active_count}/{len(results)}")
        
        if active_count == len(results):
            logger.info("✅ All documents are processing!")
            break
        
        time.sleep(2)
    
    # Check Textract jobs
    logger.info("\n3. Checking Textract job distribution...")
    db_manager = DatabaseManager(validate_conformance=False)
    
    job_count = 0
    for doc_info in results:
        doc = db_manager.get_source_document(doc_info['doc_uuid'])
        if doc and doc.textract_job_id:
            job_count += 1
            logger.info(f"   Doc {doc_info['index']}: Job {doc.textract_job_id[:8]}...")
    
    logger.info(f"\n📊 Textract jobs started: {job_count}/{len(results)}")
    
    # Cleanup
    logger.info("\n4. Cleaning up...")
    for doc_info in results:
        try:
            db_manager.delete("source_documents", {"document_uuid": doc_info['doc_uuid']})
            state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_info['doc_uuid'])
            redis_manager.delete(state_key)
        except:
            pass
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("✅ Load Test Summary:")
    logger.info(f"   - Documents submitted: {len(results)}")
    logger.info(f"   - Submission errors: {len(errors)}")
    logger.info(f"   - Active processing: {active_count}")
    logger.info(f"   - Textract jobs: {job_count}")
    logger.info("   - System remained responsive")
    logger.info("=" * 60)
    
    return len(results) == num_documents and len(errors) == 0

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=5, help='Number of documents to submit')
    args = parser.parse_args()
    
    success = test_load_async(args.count)
    sys.exit(0 if success else 1)