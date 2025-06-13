#!/usr/bin/env python3
"""Test script to verify idempotent chunking operations"""
import os
import sys
import logging
import uuid
from datetime import datetime
from scripts.supabase_utils import SupabaseManager
from scripts.celery_tasks.idempotent_ops import IdempotentDatabaseOps

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_idempotent_chunking():
    """Test that chunk upsert operations work correctly"""
    db_manager = SupabaseManager()
    idempotent_ops = IdempotentDatabaseOps(db_manager)
    
    # Test data
    test_doc_uuid = "test-idempotent-chunk-" + datetime.now().strftime("%Y%m%d%H%M%S")
    test_doc_name = "Test Idempotent Chunking Document"
    test_project_uuid = str(uuid.uuid4())
    
    try:
        # Step 0: Create a test project
        logger.info("Creating test project...")
        project_result = db_manager.client.table('projects').insert({
            'projectId': test_project_uuid,
            'name': 'Test Idempotent Chunking Project'
        }).execute()
        test_project_id = project_result.data[0]['id']
        logger.info(f"Created test project: ID={test_project_id}")
        
        # Step 1: Create a test document
        logger.info("Creating test document...")
        source_doc_id, source_doc_uuid = db_manager.create_source_document_entry(
            project_fk_id=test_project_id,
            project_uuid=test_project_uuid,
            original_file_path=f"test/{test_doc_name}",
            original_file_name=test_doc_name,
            detected_file_type="pdf"
        )
        logger.info(f"Created source document: ID={source_doc_id}, UUID={source_doc_uuid}")
        
        # Step 2: Create neo4j document
        neo4j_doc_id, neo4j_doc_uuid = idempotent_ops.upsert_neo4j_document(
            source_doc_uuid=source_doc_uuid,
            source_doc_id=source_doc_id,
            project_id=test_project_id,
            project_uuid=test_project_uuid,
            file_name=test_doc_name
        )
        logger.info(f"Created neo4j document: ID={neo4j_doc_id}, UUID={neo4j_doc_uuid}")
        
        # Step 3: First chunk insertion
        logger.info("\nTest 1: Initial chunk insertion")
        chunk1_id, chunk1_uuid = idempotent_ops.upsert_chunk(
            document_id=neo4j_doc_id,
            document_uuid=neo4j_doc_uuid,
            chunk_index=0,
            chunk_text="This is the first chunk of text.",
            chunk_metadata={"test": "initial", "version": 1}
        )
        logger.info(f"✓ First insertion: Chunk ID={chunk1_id}, UUID={chunk1_uuid}")
        
        # Step 4: Second insertion (should update)
        logger.info("\nTest 2: Updating existing chunk")
        chunk2_id, chunk2_uuid = idempotent_ops.upsert_chunk(
            document_id=neo4j_doc_id,
            document_uuid=neo4j_doc_uuid,
            chunk_index=0,
            chunk_text="This is the UPDATED first chunk of text.",
            chunk_metadata={"test": "updated", "version": 2}
        )
        logger.info(f"✓ Second insertion: Chunk ID={chunk2_id}, UUID={chunk2_uuid}")
        
        # Verify same IDs
        if chunk1_id == chunk2_id and chunk1_uuid == chunk2_uuid:
            logger.info("✓ SUCCESS: Chunk was updated (same ID and UUID)")
        else:
            logger.error("✗ FAILED: Different IDs returned")
            return False
        
        # Step 5: Verify chunk content was updated
        chunk_data = db_manager.client.table('neo4j_chunks').select('*').eq('id', chunk1_id).single().execute()
        if chunk_data.data['text'] == "This is the UPDATED first chunk of text.":
            logger.info("✓ SUCCESS: Chunk text was properly updated")
        else:
            logger.error("✗ FAILED: Chunk text was not updated")
            return False
        
        # Step 6: Test multiple chunks
        logger.info("\nTest 3: Multiple chunks with same document")
        chunk3_id, chunk3_uuid = idempotent_ops.upsert_chunk(
            document_id=neo4j_doc_id,
            document_uuid=neo4j_doc_uuid,
            chunk_index=1,
            chunk_text="This is the second chunk.",
            chunk_metadata={"test": "second_chunk"}
        )
        logger.info(f"✓ Created second chunk: ID={chunk3_id}, UUID={chunk3_uuid}")
        
        # Step 7: Test clear chunks function
        logger.info("\nTest 4: Clear chunks for document")
        cleared_count = idempotent_ops.clear_chunks_for_document(neo4j_doc_id)
        logger.info(f"✓ Cleared {cleared_count} chunks")
        
        # Verify chunks were deleted
        remaining_chunks = db_manager.client.table('neo4j_chunks').select('id').eq('document_id', neo4j_doc_id).execute()
        if len(remaining_chunks.data) == 0:
            logger.info("✓ SUCCESS: All chunks were cleared")
        else:
            logger.error(f"✗ FAILED: {len(remaining_chunks.data)} chunks remain")
            return False
        
        logger.info("\n✓ ALL TESTS PASSED!")
        return True
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        return False
    finally:
        # Cleanup test data
        logger.info("\nCleaning up test data...")
        try:
            # Delete test documents
            if 'source_doc_id' in locals():
                db_manager.client.table('source_documents').delete().eq('id', source_doc_id).execute()
            if 'neo4j_doc_id' in locals():
                db_manager.client.table('neo4j_documents').delete().eq('id', neo4j_doc_id).execute()
            if 'test_project_id' in locals():
                db_manager.client.table('projects').delete().eq('id', test_project_id).execute()
            logger.info("✓ Test data cleaned up")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

if __name__ == "__main__":
    success = test_idempotent_chunking()
    sys.exit(0 if success else 1)