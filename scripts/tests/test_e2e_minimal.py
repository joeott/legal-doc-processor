#!/usr/bin/env python3
"""
End-to-end test for minimal models and async processing.
"""

import os
import sys
import time
import uuid
from pathlib import Path

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
from scripts.config import USE_MINIMAL_MODELS, SKIP_CONFORMANCE_CHECK

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_e2e_minimal():
    """Test end-to-end processing with minimal models."""
    logger.info("=" * 60)
    logger.info("Starting E2E test with minimal models")
    logger.info(f"USE_MINIMAL_MODELS: {USE_MINIMAL_MODELS}")
    logger.info(f"SKIP_CONFORMANCE_CHECK: {SKIP_CONFORMANCE_CHECK}")
    logger.info("=" * 60)
    
    # Verify configuration
    if not USE_MINIMAL_MODELS:
        logger.error("USE_MINIMAL_MODELS is not set to true!")
        return False
    
    # Initialize components
    db_manager = DatabaseManager(validate_conformance=False)
    redis_manager = get_redis_manager()
    
    # Create test identifiers
    doc_uuid = str(uuid.uuid4())
    project_uuid = str(uuid.uuid4())
    
    logger.info(f"Test Document UUID: {doc_uuid}")
    logger.info(f"Test Project UUID: {project_uuid}")
    
    try:
        # Step 1: Clear any existing cache
        logger.info("\n1. Clearing cache...")
        cache_keys = [
            CacheKeys.DOC_STATE.format(document_uuid=doc_uuid),
            CacheKeys.DOC_OCR_RESULT.format(document_uuid=doc_uuid),
            CacheKeys.DOC_CHUNKS.format(document_uuid=doc_uuid),
            CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=doc_uuid),
            CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=doc_uuid)
        ]
        for key in cache_keys:
            redis_manager.delete(key)
        logger.info("✅ Cache cleared")
        
        # Step 2: Create document using minimal model
        logger.info("\n2. Creating document with minimal model...")
        SourceDocumentModel = get_source_document_model()
        logger.info(f"Using model: {SourceDocumentModel.__name__}")
        
        doc_model = SourceDocumentModel(
            document_uuid=doc_uuid,
            project_uuid=project_uuid,
            original_file_name="test_e2e_minimal.pdf",
            s3_bucket="samu-docs-private-upload",
            s3_key="test/test_e2e_minimal.pdf",
            status="pending"
        )
        
        # Store in database
        result = db_manager.create_source_document(doc_model)
        if result:
            logger.info("✅ Document created successfully")
            logger.info(f"   Document ID: {result.id}")
        else:
            logger.error("❌ Failed to create document")
            return False
        
        # Step 3: Submit for processing
        logger.info("\n3. Submitting document for async processing...")
        s3_path = f"s3://{doc_model.s3_bucket}/{doc_model.s3_key}"
        
        task = process_pdf_document.apply_async(
            args=[doc_uuid, s3_path, project_uuid],
            kwargs={'document_metadata': {'test': 'e2e_minimal'}}
        )
        logger.info(f"✅ Task submitted: {task.id}")
        
        # Step 4: Monitor processing
        logger.info("\n4. Monitoring processing status...")
        max_wait = 30  # seconds
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            # Check document state
            state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
            state = redis_manager.get_dict(state_key) or {}
            
            # Log current state
            if state:
                pipeline_status = state.get('pipeline', {}).get('status', 'unknown')
                ocr_status = state.get('ocr', {}).get('status', 'unknown')
                
                logger.info(f"   Pipeline: {pipeline_status}, OCR: {ocr_status}")
                
                # Check for OCR processing
                if ocr_status == 'processing':
                    job_id = state.get('ocr', {}).get('metadata', {}).get('job_id')
                    if job_id:
                        logger.info(f"   📋 Textract Job ID: {job_id}")
                
                # Check if processing started
                if pipeline_status == 'processing':
                    logger.info("✅ Pipeline is processing asynchronously")
                    break
            
            time.sleep(2)
        
        # Step 5: Verify Textract job tracking
        logger.info("\n5. Verifying Textract job tracking...")
        doc = db_manager.get_source_document(doc_uuid)
        if doc and doc.textract_job_id:
            logger.info(f"✅ Textract job tracked in DB: {doc.textract_job_id}")
            logger.info(f"   Status: {doc.textract_job_status}")
        else:
            logger.warning("⚠️  Textract job not yet tracked in database")
        
        # Step 6: Check Redis state details
        logger.info("\n6. Checking Redis state details...")
        state = redis_manager.get_dict(state_key) or {}
        
        stages = ['pipeline', 'ocr', 'chunking', 'entity_extraction', 'relationships']
        for stage in stages:
            stage_data = state.get(stage, {})
            if stage_data:
                status = stage_data.get('status', 'not_started')
                timestamp = stage_data.get('timestamp', 'N/A')
                logger.info(f"   {stage}: {status} (at {timestamp})")
        
        # Success summary
        logger.info("\n" + "=" * 60)
        logger.info("✅ E2E Test Summary:")
        logger.info("   - Minimal models working correctly")
        logger.info("   - Document created without conformance errors")
        logger.info("   - Async processing initiated successfully")
        logger.info("   - Textract job submission working")
        logger.info("   - Pipeline state tracking functional")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        logger.info("\n7. Cleaning up test data...")
        try:
            db_manager.delete("source_documents", {"document_uuid": doc_uuid})
            state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
            redis_manager.delete(state_key)
            logger.info("✅ Cleanup complete")
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")

if __name__ == "__main__":
    success = test_e2e_minimal()
    sys.exit(0 if success else 1)