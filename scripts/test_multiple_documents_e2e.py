#!/usr/bin/env python3
"""
Test multiple documents end-to-end through the entire pipeline
Track and verify each stage of processing
"""
import os
import sys
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import after path setup
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from sqlalchemy import text as sql_text

class DocumentPipelineVerifier:
    """Verify documents through each pipeline stage"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.redis_manager = get_redis_manager()
        self.verification_results = []
    
    def get_test_documents(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get documents for testing"""
        session = next(self.db_manager.get_session())
        
        try:
            # Find documents in various states
            query = sql_text("""
                SELECT document_uuid, file_name, status, 
                       ocr_completed_at, processing_completed_at,
                       created_at
                FROM source_documents
                WHERE file_name LIKE '%.pdf'
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            
            results = session.execute(query, {'limit': limit}).fetchall()
            
            documents = []
            for row in results:
                documents.append({
                    'document_uuid': str(row.document_uuid),
                    'file_name': row.file_name,
                    'status': row.status,
                    'ocr_completed': row.ocr_completed_at is not None,
                    'processing_completed': row.processing_completed_at is not None,
                    'created_at': row.created_at
                })
            
            return documents
            
        finally:
            session.close()
    
    def verify_ocr_stage(self, document_uuid: str) -> Dict[str, Any]:
        """Verify OCR extraction stage"""
        session = next(self.db_manager.get_session())
        
        try:
            # Check OCR status
            query = sql_text("""
                SELECT raw_extracted_text, ocr_completed_at, ocr_provider,
                       textract_job_id, textract_job_status
                FROM source_documents
                WHERE document_uuid = :doc_uuid
            """)
            
            result = session.execute(query, {'doc_uuid': document_uuid}).fetchone()
            
            verification = {
                'stage': 'OCR Extraction',
                'completed': result.ocr_completed_at is not None,
                'has_text': bool(result.raw_extracted_text),
                'text_length': len(result.raw_extracted_text) if result.raw_extracted_text else 0,
                'provider': result.ocr_provider,
                'textract_job_id': result.textract_job_id,
                'textract_status': result.textract_job_status
            }
            
            # Check Redis cache
            ocr_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)
            cached_ocr = self.redis_manager.get_dict(ocr_key)
            verification['cached'] = cached_ocr is not None
            
            return verification
            
        finally:
            session.close()
    
    def verify_chunking_stage(self, document_uuid: str) -> Dict[str, Any]:
        """Verify text chunking stage"""
        session = next(self.db_manager.get_session())
        
        try:
            # Check chunks
            query = sql_text("""
                SELECT COUNT(*) as chunk_count,
                       SUM(char_end_index - char_start_index) as total_chars,
                       MIN(chunk_index) as min_index,
                       MAX(chunk_index) as max_index,
                       COUNT(DISTINCT chunk_uuid) as unique_chunks
                FROM document_chunks
                WHERE document_uuid = :doc_uuid
            """)
            
            result = session.execute(query, {'doc_uuid': document_uuid}).fetchone()
            
            # Get sample chunk
            sample_query = sql_text("""
                SELECT text, char_start_index, char_end_index
                FROM document_chunks
                WHERE document_uuid = :doc_uuid
                ORDER BY chunk_index
                LIMIT 1
            """)
            
            sample = session.execute(sample_query, {'doc_uuid': document_uuid}).fetchone()
            
            verification = {
                'stage': 'Text Chunking',
                'completed': result.chunk_count > 0,
                'chunk_count': result.chunk_count or 0,
                'total_characters': result.total_chars or 0,
                'chunk_indices': f"{result.min_index or 0}-{result.max_index or 0}",
                'unique_chunks': result.unique_chunks or 0,
                'sample_chunk_length': len(sample.text) if sample else 0
            }
            
            # Check Redis cache
            chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
            cached_chunks = self.redis_manager.get_dict(chunks_key)
            verification['cached'] = cached_chunks is not None
            
            return verification
            
        finally:
            session.close()
    
    def verify_entity_extraction_stage(self, document_uuid: str) -> Dict[str, Any]:
        """Verify entity extraction stage"""
        session = next(self.db_manager.get_session())
        
        try:
            # Check entity mentions
            query = sql_text("""
                SELECT entity_type, COUNT(*) as count
                FROM entity_mentions
                WHERE document_uuid = :doc_uuid
                GROUP BY entity_type
                ORDER BY count DESC
            """)
            
            results = session.execute(query, {'doc_uuid': document_uuid}).fetchall()
            
            entity_counts = {}
            total_entities = 0
            for row in results:
                entity_counts[row.entity_type] = row.count
                total_entities += row.count
            
            # Check unique entities
            unique_query = sql_text("""
                SELECT COUNT(DISTINCT entity_text) as unique_count
                FROM entity_mentions
                WHERE document_uuid = :doc_uuid
            """)
            
            unique_result = session.execute(unique_query, {'doc_uuid': document_uuid}).scalar()
            
            verification = {
                'stage': 'Entity Extraction',
                'completed': total_entities > 0,
                'total_mentions': total_entities,
                'unique_texts': unique_result or 0,
                'entity_types': entity_counts,
                'types_found': list(entity_counts.keys())
            }
            
            # Check Redis cache
            mentions_key = CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=document_uuid)
            cached_mentions = self.redis_manager.get_dict(mentions_key)
            verification['cached'] = cached_mentions is not None
            
            return verification
            
        finally:
            session.close()
    
    def verify_entity_resolution_stage(self, document_uuid: str) -> Dict[str, Any]:
        """Verify entity resolution stage"""
        session = next(self.db_manager.get_session())
        
        try:
            # Check canonical entities
            query = sql_text("""
                SELECT ce.entity_type, COUNT(DISTINCT ce.canonical_entity_uuid) as canonical_count,
                       COUNT(DISTINCT em.id) as mention_count
                FROM entity_mentions em
                LEFT JOIN canonical_entities ce ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                WHERE em.document_uuid = :doc_uuid
                GROUP BY ce.entity_type
            """)
            
            results = session.execute(query, {'doc_uuid': document_uuid}).fetchall()
            
            resolution_stats = {}
            total_canonical = 0
            total_mentions = 0
            
            for row in results:
                entity_type = row.entity_type or 'unresolved'
                resolution_stats[entity_type] = {
                    'canonical': row.canonical_count,
                    'mentions': row.mention_count
                }
                if row.entity_type:  # Only count resolved
                    total_canonical += row.canonical_count
                    total_mentions += row.mention_count
            
            # Check resolution rate
            resolved_query = sql_text("""
                SELECT 
                    COUNT(*) FILTER (WHERE canonical_entity_uuid IS NOT NULL) as resolved,
                    COUNT(*) as total
                FROM entity_mentions
                WHERE document_uuid = :doc_uuid
            """)
            
            resolved_result = session.execute(resolved_query, {'doc_uuid': document_uuid}).fetchone()
            
            verification = {
                'stage': 'Entity Resolution',
                'completed': resolved_result.resolved > 0,
                'mentions_resolved': resolved_result.resolved,
                'total_mentions': resolved_result.total,
                'resolution_rate': f"{(resolved_result.resolved / resolved_result.total * 100):.1f}%" if resolved_result.total > 0 else "0%",
                'canonical_entities': total_canonical,
                'deduplication_rate': f"{(1 - (total_canonical / total_mentions)) * 100:.1f}%" if total_mentions > 0 else "0%",
                'by_type': resolution_stats
            }
            
            return verification
            
        finally:
            session.close()
    
    def verify_relationship_stage(self, document_uuid: str) -> Dict[str, Any]:
        """Verify relationship building stage"""
        # Check Redis state for relationship building
        state_key = CacheKeys.DOC_STATE.format(document_uuid=document_uuid)
        doc_state = self.redis_manager.get_dict(state_key) or {}
        
        relationships_state = doc_state.get('relationships', {})
        
        verification = {
            'stage': 'Relationship Building',
            'completed': relationships_state.get('status') == 'completed',
            'status': relationships_state.get('status', 'not_started'),
            'relationship_count': relationships_state.get('metadata', {}).get('relationship_count', 0),
            'relationship_types': relationships_state.get('metadata', {}).get('relationship_types', 'unknown')
        }
        
        return verification
    
    def verify_pipeline_completion(self, document_uuid: str) -> Dict[str, Any]:
        """Verify overall pipeline completion"""
        session = next(self.db_manager.get_session())
        
        try:
            query = sql_text("""
                SELECT status, processing_completed_at
                FROM source_documents
                WHERE document_uuid = :doc_uuid
            """)
            
            result = session.execute(query, {'doc_uuid': document_uuid}).fetchone()
            
            # Check Redis state
            state_key = CacheKeys.DOC_STATE.format(document_uuid=document_uuid)
            doc_state = self.redis_manager.get_dict(state_key) or {}
            pipeline_state = doc_state.get('pipeline', {})
            
            verification = {
                'stage': 'Pipeline Completion',
                'completed': result.processing_completed_at is not None,
                'database_status': result.status,
                'redis_status': pipeline_state.get('status', 'unknown'),
                'completion_time': result.processing_completed_at.isoformat() if result.processing_completed_at else None
            }
            
            return verification
            
        finally:
            session.close()
    
    def verify_document_pipeline(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Verify all stages for a document"""
        doc_uuid = document['document_uuid']
        
        print(f"\n{'='*80}")
        print(f"Document: {document['file_name']}")
        print(f"UUID: {doc_uuid}")
        print(f"Initial Status: {document['status']}")
        print(f"{'='*80}")
        
        stages = []
        
        # Verify each stage
        ocr = self.verify_ocr_stage(doc_uuid)
        stages.append(ocr)
        self.print_stage_verification(ocr)
        
        chunking = self.verify_chunking_stage(doc_uuid)
        stages.append(chunking)
        self.print_stage_verification(chunking)
        
        extraction = self.verify_entity_extraction_stage(doc_uuid)
        stages.append(extraction)
        self.print_stage_verification(extraction)
        
        resolution = self.verify_entity_resolution_stage(doc_uuid)
        stages.append(resolution)
        self.print_stage_verification(resolution)
        
        relationships = self.verify_relationship_stage(doc_uuid)
        stages.append(relationships)
        self.print_stage_verification(relationships)
        
        completion = self.verify_pipeline_completion(doc_uuid)
        stages.append(completion)
        self.print_stage_verification(completion)
        
        # Calculate overall completion
        completed_stages = sum(1 for s in stages if s['completed'])
        
        result = {
            'document_uuid': doc_uuid,
            'file_name': document['file_name'],
            'stages_completed': f"{completed_stages}/{len(stages)}",
            'fully_processed': completed_stages == len(stages),
            'stages': stages
        }
        
        print(f"\n📊 Overall: {completed_stages}/{len(stages)} stages completed")
        print(f"✅ Fully Processed: {'Yes' if result['fully_processed'] else 'No'}")
        
        return result
    
    def print_stage_verification(self, verification: Dict[str, Any]):
        """Print formatted stage verification"""
        stage_name = verification['stage']
        completed = verification['completed']
        
        print(f"\n{stage_name}:")
        print(f"  Status: {'✅ Completed' if completed else '❌ Not Completed'}")
        
        # Print stage-specific details
        for key, value in verification.items():
            if key not in ['stage', 'completed']:
                if isinstance(value, dict):
                    print(f"  {key}:")
                    for k, v in value.items():
                        print(f"    - {k}: {v}")
                else:
                    print(f"  {key}: {value}")

def main():
    """Test multiple documents through the pipeline"""
    print("\n" + "="*80)
    print("Multi-Document End-to-End Pipeline Verification")
    print("="*80)
    
    verifier = DocumentPipelineVerifier()
    
    # Get test documents
    print("\nFinding test documents...")
    documents = verifier.get_test_documents(limit=5)
    
    if not documents:
        print("❌ No documents found for testing")
        return
    
    print(f"✅ Found {len(documents)} documents to verify")
    
    # Verify each document
    all_results = []
    for i, doc in enumerate(documents, 1):
        print(f"\n\n{'#'*80}")
        print(f"DOCUMENT {i}/{len(documents)}")
        print(f"{'#'*80}")
        
        result = verifier.verify_document_pipeline(doc)
        all_results.append(result)
        
        # Brief pause between documents
        if i < len(documents):
            time.sleep(1)
    
    # Summary report
    print("\n\n" + "="*80)
    print("SUMMARY REPORT")
    print("="*80)
    
    fully_processed = sum(1 for r in all_results if r['fully_processed'])
    print(f"\nDocuments fully processed: {fully_processed}/{len(all_results)}")
    
    # Stage completion summary
    stage_names = ['OCR Extraction', 'Text Chunking', 'Entity Extraction', 
                   'Entity Resolution', 'Relationship Building', 'Pipeline Completion']
    
    stage_completions = {name: 0 for name in stage_names}
    
    for result in all_results:
        for stage in result['stages']:
            if stage['completed']:
                stage_completions[stage['stage']] += 1
    
    print("\nStage Completion Rates:")
    for stage_name in stage_names:
        completed = stage_completions[stage_name]
        rate = (completed / len(all_results)) * 100
        print(f"  {stage_name}: {completed}/{len(all_results)} ({rate:.0f}%)")
    
    # Save detailed results
    results_file = '/opt/legal-doc-processor/ai_docs/context_318_multi_document_verification.json'
    with open(results_file, 'w') as f:
        json.dump({
            'verification_timestamp': datetime.utcnow().isoformat(),
            'documents_tested': len(all_results),
            'fully_processed': fully_processed,
            'stage_completions': stage_completions,
            'detailed_results': all_results
        }, f, indent=2)
    
    print(f"\n📄 Detailed results saved to: {results_file}")

if __name__ == "__main__":
    main()