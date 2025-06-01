#!/usr/bin/env python3
"""Test full pipeline processing directly without Celery"""
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ocr_extraction import extract_text_from_pdf_textract
from scripts.text_processing import (
    clean_extracted_text, categorize_document_text,
    process_document_with_semantic_chunking
)
from scripts.entity_extraction import extract_entities_from_chunk
from scripts.entity_resolution import resolve_document_entities
from scripts.relationship_builder import stage_structural_relationships
from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3StorageManager

def test_full_pipeline():
    """Test full pipeline processing"""
    db = SupabaseManager()
    s3_manager = S3StorageManager()
    
    # File to test
    file_path = Path("/Users/josephott/Documents/phase_1_2_3_process_v5/input_docs/Pre-Trial Order -  Ory v. Roeslein.pdf")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return
        
    print(f"📄 Testing full pipeline on: {file_path.name}")
    print("=" * 80)
    
    try:
        # Phase 1: Document setup and S3 upload
        print("\n📋 Phase 1: Document Setup")
        
        # Create project
        project_id_sql, project_uuid = db.get_or_create_project(
            "test-full-pipeline",
            "Full Pipeline Test"
        )
        
        # Check for existing document
        existing = db.client.table('source_documents')\
            .select('id')\
            .eq('original_file_name', file_path.name)\
            .eq('project_fk_id', project_id_sql)\
            .execute()
            
        if existing.data:
            print(f"🗑️  Removing existing test document...")
            db.client.table('source_documents').delete().eq('id', existing.data[0]['id']).execute()
        
        # Upload to S3
        upload_result = s3_manager.upload_document_with_uuid_naming(
            local_file_path=str(file_path),
            document_uuid="test-pipeline-doc",
            original_filename=file_path.name
        )
        s3_uri = f"s3://{upload_result['s3_bucket']}/{upload_result['s3_key']}"
        print(f"✅ Uploaded to S3: {s3_uri}")
        
        # Create document entry
        doc_id, doc_uuid = db.create_source_document_entry(
            project_fk_id=project_id_sql,
            project_uuid=project_uuid,
            original_file_path=s3_uri,
            original_file_name=file_path.name,
            detected_file_type="pdf"
        )
        print(f"✅ Document created: ID={doc_id}, UUID={doc_uuid[:8]}...")
        
        # Phase 2: OCR
        print("\n📋 Phase 2: OCR Processing")
        raw_text, ocr_meta = extract_text_from_pdf_textract(
            db_manager=db,
            source_doc_sql_id=doc_id,
            pdf_path_or_s3_uri=s3_uri,
            document_uuid_from_db=doc_uuid
        )
        
        if not raw_text:
            print("❌ OCR failed - no text extracted")
            return
            
        print(f"✅ OCR successful! Extracted {len(raw_text)} characters")
        
        # Phase 3: Create Neo4j document
        print("\n📋 Phase 3: Neo4j Document Creation")
        neo4j_doc_id, neo4j_doc_uuid = db.create_neo4j_document_entry(
            source_doc_fk_id=doc_id,
            source_doc_uuid=doc_uuid,
            project_fk_id=project_id_sql,
            project_uuid=project_uuid,
            file_name=file_path.name
        )
        print(f"✅ Neo4j document created: ID={neo4j_doc_id}, UUID={neo4j_doc_uuid[:8]}...")
        
        # Phase 4: Text Processing
        print("\n📋 Phase 4: Text Processing")
        cleaned_text = clean_extracted_text(raw_text)
        category = categorize_document_text(cleaned_text)
        print(f"✅ Document categorized as: {category}")
        
        # Update neo4j document
        db.update_neo4j_document_details(
            neo4j_doc_sql_id=neo4j_doc_id,
            category=category,
            file_type="pdf",
            cleaned_text=cleaned_text,
            status="text_processed"
        )
        
        # Phase 5: Chunking
        print("\n📋 Phase 5: Semantic Chunking")
        chunks, structured_data = process_document_with_semantic_chunking(
            db_manager=db,
            document_sql_id=neo4j_doc_id,
            document_uuid=neo4j_doc_uuid,
            raw_text=raw_text,
            doc_category=category,
            use_structured_extraction=False  # Skip for now to test basic flow
        )
        print(f"✅ Created {len(chunks)} semantic chunks")
        
        # Extract chunk IDs from the already-created chunks
        chunk_ids = []
        for chunk in chunks:
            chunk_ids.append((chunk['sql_id'], chunk['chunk_uuid']))
            
        print(f"✅ Saved {len(chunk_ids)} chunks to database")
        
        # Phase 6: Entity Extraction
        print("\n📋 Phase 6: Entity Extraction")
        total_entities = 0
        for i, (chunk, (chunk_id, chunk_uuid)) in enumerate(zip(chunks, chunk_ids)):
            print(f"   Processing chunk {i+1}/{len(chunks)}...")
            entities = extract_entities_from_chunk(
                chunk_text=chunk['text'],
                chunk_id=chunk_id,
                db_manager=db,
                use_openai=True
            )
            
            if entities:
                total_entities += len(entities)
                
        print(f"✅ Extracted {total_entities} total entity mentions")
        
        # Phase 7: Entity Resolution
        print("\n📋 Phase 7: Entity Resolution")
        resolved_count = resolve_document_entities(
            document_uuid=neo4j_doc_uuid,
            neo4j_doc_sql_id=neo4j_doc_id
        )
        print(f"✅ Resolved entities into {resolved_count} canonical entities")
        
        # Phase 8: Relationship Building
        print("\n📋 Phase 8: Relationship Building")
        relationships = stage_structural_relationships(
            document_uuid=neo4j_doc_uuid,
            document_id=neo4j_doc_id
        )
        print(f"✅ Staged {len(relationships)} relationships")
        
        # Update final status
        db.update_neo4j_document_status(neo4j_doc_id, "fully_processed")
        db.client.table('source_documents').update({
            'celery_status': 'completed',
            'initial_processing_status': 'fully_processed'
        }).eq('id', doc_id).execute()
        
        print("\n✅ Pipeline completed successfully!")
        print("=" * 80)
        
        # Summary
        print("\n📊 Processing Summary:")
        print(f"  • Document: {file_path.name}")
        print(f"  • OCR Text: {len(raw_text)} characters")
        print(f"  • Category: {category}")
        print(f"  • Chunks: {len(chunks)}")
        print(f"  • Entity Mentions: {total_entities}")
        print(f"  • Canonical Entities: {resolved_count}")
        print(f"  • Relationships: {len(relationships)}")
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_full_pipeline()