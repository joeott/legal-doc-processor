#!/usr/bin/env python3
"""Test model consistency with database schema"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.models import *
from scripts.db import DatabaseManager
from sqlalchemy import text
from uuid import uuid4

def test_model_db_consistency():
    """Verify models match database schema"""
    db = DatabaseManager()
    session = next(db.get_session())
    
    # Test each model against its table
    tests = [
        ("source_documents", SourceDocumentMinimal),
        ("document_chunks", DocumentChunkMinimal),
        ("entity_mentions", EntityMentionMinimal),
        ("canonical_entities", CanonicalEntityMinimal),
        ("relationship_staging", RelationshipStagingMinimal)
    ]
    
    results = []
    
    for table_name, model_class in tests:
        print(f"\nTesting {model_class.__name__} against {table_name}")
        
        # Get DB columns
        result = session.execute(text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
        """)).fetchall()
        
        db_columns = {row.column_name for row in result}
        model_fields = set(model_class.model_fields.keys())
        
        # Check for mismatches
        only_in_db = db_columns - model_fields
        only_in_model = model_fields - db_columns
        
        # Remove columns we're intentionally not including
        optional_db_columns = {
            'import_session_id', 'file_type', 'detected_file_type', 
            'markdown_text', 'cleaned_text', 'ocr_metadata_json',
            'ocr_processing_seconds', 'ocr_confidence_score',
            'textract_job_status', 'textract_start_time', 'textract_end_time',
            'textract_page_count', 'textract_error_message',
            'transcription_metadata_json', 'retry_count', 'last_retry_at',
            'chunk_number', 'cleaned_text', 'start_page', 'end_page',
            'metadata_json', 'chunk_type', 'embedding_vector', 'embedding_model',
            'start_char_index', 'end_char_index', 'metadata',
            'chunk_fk_id', 'entity_subtype', 'extraction_method',
            'processing_metadata', 'chunk_id', 's3_key_public', 's3_bucket_public',
            'celery_status', 'initial_processing_status'
        }
        
        only_in_db = only_in_db - optional_db_columns
        
        if only_in_db:
            print(f"  ⚠️  In DB but not model: {only_in_db}")
        if only_in_model:
            print(f"  ⚠️  In model but not DB: {only_in_model}")
        if not (only_in_db or only_in_model):
            print(f"  ✅ Model matches database perfectly")
            
        results.append({
            'model': model_class.__name__,
            'table': table_name,
            'missing_from_model': list(only_in_db),
            'missing_from_db': list(only_in_model),
            'success': not (only_in_db or only_in_model)
        })
    
    session.close()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    all_success = all(r['success'] for r in results)
    if all_success:
        print("✅ All models match database schema!")
    else:
        print("❌ Some models need updating:")
        for r in results:
            if not r['success']:
                print(f"\n{r['model']}:")
                if r['missing_from_model']:
                    print(f"  - Add to model: {r['missing_from_model']}")
                if r['missing_from_db']:
                    print(f"  - Remove from model: {r['missing_from_db']}")
    
    return all_success

def test_model_instantiation():
    """Test that models can be instantiated with proper data"""
    print("\n" + "="*60)
    print("TESTING MODEL INSTANTIATION")
    print("="*60)
    
    # Test SourceDocumentMinimal
    doc = SourceDocumentMinimal(
        document_uuid=uuid4(),
        file_name="test.pdf",
        status="pending"
    )
    print(f"✅ SourceDocumentMinimal created: {doc.document_uuid}")
    
    # Test DocumentChunkMinimal
    chunk = DocumentChunkMinimal(
        chunk_uuid=uuid4(),
        document_uuid=doc.document_uuid,
        chunk_index=0,
        text="Test chunk",
        char_start_index=0,
        char_end_index=10
    )
    print(f"✅ DocumentChunkMinimal created: {chunk.chunk_uuid}")
    
    # Test EntityMentionMinimal
    mention = EntityMentionMinimal(
        mention_uuid=uuid4(),
        chunk_uuid=chunk.chunk_uuid,
        document_uuid=doc.document_uuid,
        entity_text="Test Entity",
        entity_type="PERSON",
        start_char=0,
        end_char=11
    )
    print(f"✅ EntityMentionMinimal created: {mention.mention_uuid}")
    
    # Test CanonicalEntityMinimal
    canonical = CanonicalEntityMinimal(
        canonical_entity_uuid=uuid4(),
        entity_type="PERSON",
        canonical_name="Test Entity"
    )
    print(f"✅ CanonicalEntityMinimal created: {canonical.canonical_entity_uuid}")
    
    # Test RelationshipStagingMinimal
    rel = RelationshipStagingMinimal(
        source_entity_uuid=uuid4(),
        target_entity_uuid=uuid4(),
        relationship_type="RELATED_TO"
    )
    print(f"✅ RelationshipStagingMinimal created")
    
    print("\n✅ All models instantiate correctly!")

if __name__ == "__main__":
    # Test model consistency
    consistent = test_model_db_consistency()
    
    # Test model instantiation
    test_model_instantiation()
    
    if consistent:
        print("\n🎉 All tests passed!")
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")