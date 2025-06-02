#!/usr/bin/env python3
"""
Unit tests for minimal models and model factory.
"""

import os
import sys
import uuid
from pathlib import Path

# Setup Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load environment
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

import logging
from scripts.core.models_minimal import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal
)
from scripts.core.model_factory import (
    get_source_document_model,
    get_chunk_model,
    get_entity_mention_model,
    get_canonical_entity_model
)
from scripts.config import USE_MINIMAL_MODELS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_minimal_models():
    """Test creation and validation of minimal models."""
    logger.info("Testing minimal model creation...")
    
    tests_passed = 0
    tests_failed = 0
    
    # Test 1: SourceDocumentMinimal
    try:
        doc_uuid = uuid.uuid4()
        doc = SourceDocumentMinimal(
            document_uuid=doc_uuid,
            original_file_name="test.pdf",
            s3_bucket="test-bucket",
            s3_key="test/key.pdf"
        )
        assert doc.document_uuid == doc_uuid
        assert doc.status == "pending"  # default value
        logger.info("✅ SourceDocumentMinimal: PASS")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ SourceDocumentMinimal: FAIL - {e}")
        tests_failed += 1
    
    # Test 2: DocumentChunkMinimal
    try:
        chunk_uuid = uuid.uuid4()
        chunk = DocumentChunkMinimal(
            chunk_uuid=chunk_uuid,
            document_uuid=doc_uuid,
            chunk_index=0,
            text_content="Test content",
            start_char=0,
            end_char=100
        )
        assert chunk.chunk_uuid == chunk_uuid
        assert chunk.chunk_index == 0
        logger.info("✅ DocumentChunkMinimal: PASS")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ DocumentChunkMinimal: FAIL - {e}")
        tests_failed += 1
    
    # Test 3: EntityMentionMinimal
    try:
        mention = EntityMentionMinimal(
            mention_uuid=uuid.uuid4(),
            document_uuid=doc_uuid,
            chunk_uuid=chunk_uuid,
            entity_text="John Doe",
            entity_type="PERSON",
            start_char=10,
            end_char=18
        )
        assert mention.entity_text == "John Doe"
        assert mention.entity_type == "PERSON"
        logger.info("✅ EntityMentionMinimal: PASS")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ EntityMentionMinimal: FAIL - {e}")
        tests_failed += 1
    
    # Test 4: CanonicalEntityMinimal
    try:
        entity = CanonicalEntityMinimal(
            canonical_entity_uuid=uuid.uuid4(),
            entity_type="PERSON",
            canonical_name="John Doe",
            mention_count=5
        )
        assert entity.canonical_name == "John Doe"
        assert entity.mention_count == 5
        logger.info("✅ CanonicalEntityMinimal: PASS")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ CanonicalEntityMinimal: FAIL - {e}")
        tests_failed += 1
    
    logger.info(f"\nModel Creation Tests: {tests_passed} passed, {tests_failed} failed")
    return tests_failed == 0

def test_model_factory():
    """Test model factory returns correct models based on configuration."""
    logger.info(f"\nTesting model factory (USE_MINIMAL_MODELS={USE_MINIMAL_MODELS})...")
    
    tests_passed = 0
    tests_failed = 0
    
    # Test source document model
    try:
        model_class = get_source_document_model()
        if USE_MINIMAL_MODELS:
            assert model_class.__name__ == "SourceDocumentMinimal"
        else:
            assert model_class.__name__ == "SourceDocumentModel"
        logger.info(f"✅ get_source_document_model: {model_class.__name__}")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ get_source_document_model: FAIL - {e}")
        tests_failed += 1
    
    # Test chunk model
    try:
        model_class = get_chunk_model()
        if USE_MINIMAL_MODELS:
            assert model_class.__name__ == "DocumentChunkMinimal"
        else:
            assert model_class.__name__ == "ChunkModel"
        logger.info(f"✅ get_chunk_model: {model_class.__name__}")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ get_chunk_model: FAIL - {e}")
        tests_failed += 1
    
    # Test entity mention model
    try:
        model_class = get_entity_mention_model()
        if USE_MINIMAL_MODELS:
            assert model_class.__name__ == "EntityMentionMinimal"
        else:
            assert model_class.__name__ == "EntityMentionModel"
        logger.info(f"✅ get_entity_mention_model: {model_class.__name__}")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ get_entity_mention_model: FAIL - {e}")
        tests_failed += 1
    
    # Test canonical entity model
    try:
        model_class = get_canonical_entity_model()
        if USE_MINIMAL_MODELS:
            assert model_class.__name__ == "CanonicalEntityMinimal"
        else:
            assert model_class.__name__ == "CanonicalEntityModel"
        logger.info(f"✅ get_canonical_entity_model: {model_class.__name__}")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ get_canonical_entity_model: FAIL - {e}")
        tests_failed += 1
    
    logger.info(f"\nModel Factory Tests: {tests_passed} passed, {tests_failed} failed")
    return tests_failed == 0

def test_field_compatibility():
    """Test that minimal models have compatible fields with database."""
    logger.info("\nTesting field compatibility...")
    
    # Essential fields that must exist
    essential_fields = {
        'SourceDocumentMinimal': [
            'document_uuid', 'original_file_name', 's3_key', 's3_bucket',
            'status', 'textract_job_id', 'textract_job_status'
        ],
        'DocumentChunkMinimal': [
            'chunk_uuid', 'document_uuid', 'chunk_index', 'text_content'
        ],
        'EntityMentionMinimal': [
            'mention_uuid', 'document_uuid', 'chunk_uuid', 'entity_text', 'entity_type'
        ],
        'CanonicalEntityMinimal': [
            'canonical_entity_uuid', 'entity_type', 'canonical_name'
        ]
    }
    
    tests_passed = 0
    tests_failed = 0
    
    for model_name, fields in essential_fields.items():
        try:
            if model_name == 'SourceDocumentMinimal':
                model = SourceDocumentMinimal
            elif model_name == 'DocumentChunkMinimal':
                model = DocumentChunkMinimal
            elif model_name == 'EntityMentionMinimal':
                model = EntityMentionMinimal
            else:
                model = CanonicalEntityMinimal
            
            model_fields = model.model_fields.keys()
            missing_fields = set(fields) - set(model_fields)
            
            if missing_fields:
                logger.error(f"❌ {model_name}: Missing fields: {missing_fields}")
                tests_failed += 1
            else:
                logger.info(f"✅ {model_name}: All essential fields present")
                tests_passed += 1
                
        except Exception as e:
            logger.error(f"❌ {model_name}: Error - {e}")
            tests_failed += 1
    
    logger.info(f"\nField Compatibility Tests: {tests_passed} passed, {tests_failed} failed")
    return tests_failed == 0

def main():
    """Run all minimal model tests."""
    logger.info("=" * 60)
    logger.info("MINIMAL MODELS UNIT TESTS")
    logger.info("=" * 60)
    
    all_passed = True
    
    # Run tests
    all_passed &= test_minimal_models()
    all_passed &= test_model_factory()
    all_passed &= test_field_compatibility()
    
    # Summary
    logger.info("\n" + "=" * 60)
    if all_passed:
        logger.info("✅ ALL TESTS PASSED")
    else:
        logger.error("❌ SOME TESTS FAILED")
    logger.info("=" * 60)
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)