#!/usr/bin/env python3
"""
Document Results Validation Script
Purpose: Validate and report on processed document quality
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DocumentValidator:
    """Validate document processing results"""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.redis = get_redis_manager()
        
    def validate_document(self, doc_uuid: str) -> Dict[str, Any]:
        """Comprehensive validation of a processed document"""
        logger.info(f"\nValidating document: {doc_uuid}")
        logger.info("="*60)
        
        results = {
            "document_uuid": doc_uuid,
            "timestamp": datetime.now().isoformat(),
            "status": {},
            "quality_metrics": {},
            "data_completeness": {},
            "errors": []
        }
        
        with self.db.get_session() as session:
            # 1. Check document status
            doc_info = session.execute(
                """SELECT file_name, processing_status, current_stage, 
                          created_at, updated_at, processing_time_seconds
                   FROM source_documents 
                   WHERE document_uuid = :uuid""",
                {"uuid": doc_uuid}
            ).fetchone()
            
            if not doc_info:
                results["errors"].append("Document not found")
                return results
            
            results["status"] = {
                "file_name": doc_info[0],
                "processing_status": doc_info[1],
                "current_stage": doc_info[2],
                "processing_time": doc_info[5]
            }
            
            logger.info(f"📄 File: {doc_info[0]}")
            logger.info(f"📊 Status: {doc_info[1]} (Stage: {doc_info[2]})")
            logger.info(f"⏱️  Processing time: {doc_info[5]}s")
            
            # 2. Check OCR quality
            ocr_data = self.redis.get_cached(f"doc:ocr:{doc_uuid}")
            if ocr_data:
                text_length = len(ocr_data.get("text", ""))
                results["quality_metrics"]["ocr"] = {
                    "text_length": text_length,
                    "pages": ocr_data.get("pages", 0),
                    "avg_chars_per_page": text_length / ocr_data.get("pages", 1)
                }
                logger.info(f"📝 OCR: {text_length} characters from {ocr_data.get('pages', 0)} pages")
            
            # 3. Check chunking quality
            chunks = session.execute(
                """SELECT COUNT(*), AVG(LENGTH(chunk_text)), MIN(LENGTH(chunk_text)), MAX(LENGTH(chunk_text))
                   FROM document_chunks 
                   WHERE document_uuid = :uuid""",
                {"uuid": doc_uuid}
            ).fetchone()
            
            if chunks and chunks[0] > 0:
                results["quality_metrics"]["chunking"] = {
                    "total_chunks": chunks[0],
                    "avg_chunk_size": float(chunks[1]) if chunks[1] else 0,
                    "min_chunk_size": chunks[2],
                    "max_chunk_size": chunks[3]
                }
                logger.info(f"📦 Chunks: {chunks[0]} (avg size: {chunks[1]:.0f} chars)")
            
            # 4. Check entity extraction
            entities = session.execute(
                """SELECT entity_type, COUNT(*), COUNT(DISTINCT entity_text)
                   FROM entity_mentions 
                   WHERE document_uuid = :uuid
                   GROUP BY entity_type""",
                {"uuid": doc_uuid}
            ).fetchall()
            
            if entities:
                results["quality_metrics"]["entities"] = {}
                total_entities = 0
                for entity_type, count, unique_count in entities:
                    results["quality_metrics"]["entities"][entity_type] = {
                        "total_mentions": count,
                        "unique_entities": unique_count
                    }
                    total_entities += count
                    logger.info(f"👤 {entity_type}: {unique_count} unique ({count} mentions)")
                
                results["data_completeness"]["entity_extraction"] = total_entities > 0
            
            # 5. Check entity resolution
            canonical = session.execute(
                """SELECT COUNT(DISTINCT ce.canonical_entity_uuid), 
                          COUNT(DISTINCT ce.entity_type),
                          AVG(em.confidence_score)
                   FROM canonical_entities ce
                   JOIN entity_mentions em ON ce.canonical_entity_uuid = em.canonical_entity_uuid
                   WHERE em.document_uuid = :uuid""",
                {"uuid": doc_uuid}
            ).fetchone()
            
            if canonical and canonical[0] > 0:
                results["quality_metrics"]["resolution"] = {
                    "canonical_entities": canonical[0],
                    "entity_types": canonical[1],
                    "avg_confidence": float(canonical[2]) if canonical[2] else 0
                }
                logger.info(f"🔗 Canonical entities: {canonical[0]} (avg confidence: {canonical[2]:.2f})")
            
            # 6. Check relationships
            relationships = session.execute(
                """SELECT COUNT(*), COUNT(DISTINCT relationship_type)
                   FROM relationship_staging
                   WHERE source_entity_uuid IN (
                       SELECT DISTINCT canonical_entity_uuid 
                       FROM entity_mentions 
                       WHERE document_uuid = :uuid
                   )""",
                {"uuid": doc_uuid}
            ).fetchone()
            
            if relationships and relationships[0] > 0:
                results["quality_metrics"]["relationships"] = {
                    "total_relationships": relationships[0],
                    "relationship_types": relationships[1]
                }
                logger.info(f"🔀 Relationships: {relationships[0]}")
            
            # 7. Data completeness check
            results["data_completeness"] = {
                "document_record": True,
                "ocr_completed": bool(ocr_data),
                "chunks_created": chunks[0] > 0 if chunks else False,
                "entities_extracted": len(entities) > 0 if entities else False,
                "entities_resolved": canonical[0] > 0 if canonical else False,
                "relationships_built": relationships[0] > 0 if relationships else False
            }
            
            # 8. Calculate overall score
            completeness_score = sum(results["data_completeness"].values()) / len(results["data_completeness"]) * 100
            results["overall_score"] = completeness_score
            
            # 9. Fitness assessment
            if completeness_score >= 90 and results["status"]["processing_status"] == "completed":
                results["fitness"] = "EXCELLENT"
            elif completeness_score >= 70:
                results["fitness"] = "GOOD"
            elif completeness_score >= 50:
                results["fitness"] = "FAIR"
            else:
                results["fitness"] = "POOR"
            
            logger.info(f"\n📊 Overall Score: {completeness_score:.1f}%")
            logger.info(f"✅ Fitness: {results['fitness']}")
            
        return results
    
    def validate_batch(self, doc_uuids: List[str]) -> Dict[str, Any]:
        """Validate multiple documents"""
        batch_results = {
            "total_documents": len(doc_uuids),
            "timestamp": datetime.now().isoformat(),
            "documents": {},
            "summary": {
                "excellent": 0,
                "good": 0,
                "fair": 0,
                "poor": 0,
                "avg_score": 0
            }
        }
        
        total_score = 0
        for doc_uuid in doc_uuids:
            result = self.validate_document(doc_uuid)
            batch_results["documents"][doc_uuid] = result
            
            if result.get("fitness"):
                batch_results["summary"][result["fitness"].lower()] += 1
                total_score += result.get("overall_score", 0)
        
        batch_results["summary"]["avg_score"] = total_score / len(doc_uuids) if doc_uuids else 0
        
        return batch_results
    
    def find_recent_documents(self, limit: int = 10) -> List[str]:
        """Find recently processed documents"""
        with self.db.get_session() as session:
            docs = session.execute(
                """SELECT document_uuid, file_name, processing_status
                   FROM source_documents 
                   WHERE processing_status IN ('completed', 'failed')
                   ORDER BY updated_at DESC 
                   LIMIT :limit""",
                {"limit": limit}
            ).fetchall()
            
            logger.info(f"\nFound {len(docs)} recent documents:")
            doc_uuids = []
            for doc in docs:
                logger.info(f"  - {doc[1]} ({doc[2]})")
                if doc[2] == "completed":
                    doc_uuids.append(str(doc[0]))
                    
            return doc_uuids

def main():
    """Run validation"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate document processing results")
    parser.add_argument("--document", "-d", help="Document UUID to validate")
    parser.add_argument("--recent", "-r", type=int, help="Validate N recent documents")
    parser.add_argument("--batch", "-b", nargs="+", help="List of document UUIDs")
    
    args = parser.parse_args()
    
    validator = DocumentValidator()
    
    if args.document:
        # Validate single document
        result = validator.validate_document(args.document)
        
        # Save result
        filename = f"validation_{args.document[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(result, f, indent=2)
        logger.info(f"\nValidation saved to: {filename}")
        
    elif args.recent:
        # Validate recent documents
        doc_uuids = validator.find_recent_documents(args.recent)
        if doc_uuids:
            batch_result = validator.validate_batch(doc_uuids)
            
            filename = f"batch_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(batch_result, f, indent=2)
            logger.info(f"\nBatch validation saved to: {filename}")
            
            logger.info(f"\nBatch Summary:")
            logger.info(f"  Average Score: {batch_result['summary']['avg_score']:.1f}%")
            logger.info(f"  Excellent: {batch_result['summary']['excellent']}")
            logger.info(f"  Good: {batch_result['summary']['good']}")
            logger.info(f"  Fair: {batch_result['summary']['fair']}")
            logger.info(f"  Poor: {batch_result['summary']['poor']}")
            
    elif args.batch:
        # Validate specific batch
        batch_result = validator.validate_batch(args.batch)
        
        filename = f"batch_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(batch_result, f, indent=2)
        logger.info(f"\nBatch validation saved to: {filename}")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()