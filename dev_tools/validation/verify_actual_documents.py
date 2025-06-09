#!/usr/bin/env python3
"""
Actual Document Verification Script
Purpose: Validate document processing pipeline with real legal documents
"""

import os
import sys
import time
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import boto3
from uuid import uuid4

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.s3_storage import S3StorageManager
from scripts.pdf_tasks import process_pdf_document
from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DocumentVerifier:
    """Verify actual document processing"""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.redis = get_redis_manager()
        self.s3 = S3StorageManager()
        self.results = {
            "phases": {},
            "documents": {},
            "metrics": {},
            "errors": []
        }
        self.start_time = time.time()
        
    def get_test_documents(self) -> List[Dict[str, Any]]:
        """Get list of test documents"""
        test_docs = [
            {
                "name": "Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf",
                "path": "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf",
                "size": 102 * 1024,
                "type": "disclosure_statement",
                "expected_entities": ["Paul, Michael", "Wombat Corp", "Acuity"]
            },
            {
                "name": "Paul, Michael - Plaintiff Acuity Disclosure Stmt 9-20-24.pdf",
                "path": "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Disclosure Stmt 9-20-24.pdf",
                "size": 125 * 1024,
                "type": "disclosure_statement"
            },
            {
                "name": "Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf",
                "path": "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf",
                "size": 149 * 1024,
                "type": "disclosure_statement"
            }
        ]
        
        # Verify files exist
        valid_docs = []
        for doc in test_docs:
            if os.path.exists(doc["path"]):
                valid_docs.append(doc)
                logger.info(f"✅ Found test document: {doc['name']}")
            else:
                logger.warning(f"❌ Test document not found: {doc['path']}")
                
        return valid_docs
    
    def check_prerequisites(self) -> Dict[str, bool]:
        """Check system prerequisites"""
        logger.info("\n" + "="*60)
        logger.info("CHECKING PREREQUISITES")
        logger.info("="*60)
        
        checks = {
            "database": False,
            "redis": False,
            "s3": False,
            "workers": False,
            "project": False
        }
        
        # Check database
        try:
            with self.db.get_session() as session:
                session.execute("SELECT 1")
            checks["database"] = True
            logger.info("✅ Database connection OK")
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
        
        # Check Redis
        try:
            self.redis.get_client().ping()
            checks["redis"] = True
            logger.info("✅ Redis connection OK")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
        
        # Check S3
        try:
            self.s3.s3_client.head_bucket(Bucket=S3_PRIMARY_DOCUMENT_BUCKET)
            checks["s3"] = True
            logger.info("✅ S3 bucket accessible")
        except Exception as e:
            logger.error(f"❌ S3 access failed: {e}")
        
        # Check for test project
        try:
            project_uuid = self.get_or_create_test_project()
            if project_uuid:
                checks["project"] = True
                logger.info(f"✅ Test project ready: {project_uuid}")
        except Exception as e:
            logger.error(f"❌ Project setup failed: {e}")
        
        # Check Celery workers (basic check)
        try:
            from scripts.celery_app import app
            stats = app.control.inspect().stats()
            if stats:
                checks["workers"] = True
                logger.info(f"✅ Celery workers active: {len(stats)} workers")
            else:
                logger.warning("⚠️ No active Celery workers detected")
        except Exception as e:
            logger.warning(f"⚠️ Could not check Celery workers: {e}")
        
        return checks
    
    def get_or_create_test_project(self) -> Optional[str]:
        """Get or create test project"""
        with self.db.get_session() as session:
            # Check for existing test project
            result = session.execute(
                "SELECT project_uuid FROM projects WHERE project_name = 'Verification Test Project' LIMIT 1"
            ).fetchone()
            
            if result:
                return str(result[0])
            
            # Create new test project
            project_uuid = str(uuid4())
            session.execute(
                """INSERT INTO projects (project_uuid, project_name, created_at) 
                   VALUES (:uuid, :name, :created)""",
                {
                    "uuid": project_uuid,
                    "name": "Verification Test Project",
                    "created": datetime.now()
                }
            )
            session.commit()
            return project_uuid
    
    def process_single_document(self, doc_info: Dict[str, Any], project_uuid: str) -> Dict[str, Any]:
        """Process a single document through the pipeline"""
        logger.info(f"\nProcessing: {doc_info['name']}")
        start_time = time.time()
        doc_uuid = str(uuid4())
        
        result = {
            "document_uuid": doc_uuid,
            "name": doc_info["name"],
            "start_time": start_time,
            "phases": {},
            "errors": [],
            "success": False
        }
        
        try:
            # Phase 1: Upload to S3
            logger.info("📤 Uploading to S3...")
            s3_key = f"documents/{project_uuid}/{doc_uuid}/{doc_info['name']}"
            with open(doc_info["path"], 'rb') as f:
                self.s3.s3_client.upload_fileobj(f, S3_PRIMARY_DOCUMENT_BUCKET, s3_key)
            s3_path = f"s3://{S3_PRIMARY_DOCUMENT_BUCKET}/{s3_key}"
            result["phases"]["upload"] = {"success": True, "s3_path": s3_path}
            logger.info(f"✅ Uploaded to: {s3_path}")
            
            # Phase 2: Create database record
            logger.info("💾 Creating database record...")
            with self.db.get_session() as session:
                session.execute(
                    """INSERT INTO source_documents 
                       (document_uuid, project_uuid, file_name, file_path, file_size, 
                        processing_status, created_at)
                       VALUES (:doc_uuid, :proj_uuid, :name, :path, :size, 
                               'pending', :created)""",
                    {
                        "doc_uuid": doc_uuid,
                        "proj_uuid": project_uuid,
                        "name": doc_info["name"],
                        "path": s3_path,
                        "size": doc_info["size"],
                        "created": datetime.now()
                    }
                )
                session.commit()
            result["phases"]["database"] = {"success": True}
            logger.info("✅ Database record created")
            
            # Phase 3: Trigger processing
            logger.info("🚀 Triggering document processing...")
            task = process_pdf_document.delay(
                document_uuid=doc_uuid,
                file_path=s3_path,
                project_uuid=project_uuid
            )
            result["phases"]["trigger"] = {
                "success": True, 
                "task_id": task.id
            }
            logger.info(f"✅ Processing triggered: {task.id}")
            
            # Phase 4: Monitor processing
            logger.info("📊 Monitoring pipeline progress...")
            completion_result = self.monitor_document_processing(
                doc_uuid, 
                doc_info.get("expected_entities", [])
            )
            result["phases"]["processing"] = completion_result
            
            # Calculate total time
            result["total_time"] = time.time() - start_time
            result["success"] = completion_result.get("success", False)
            
            if result["success"]:
                logger.info(f"✅ Document processed successfully in {result['total_time']:.2f}s")
            else:
                logger.error(f"❌ Document processing failed: {completion_result.get('error', 'Unknown error')}")
                
        except Exception as e:
            logger.error(f"❌ Error processing document: {e}")
            result["errors"].append(str(e))
            result["success"] = False
            
        return result
    
    def monitor_document_processing(self, doc_uuid: str, expected_entities: List[str], 
                                   timeout: int = 300) -> Dict[str, Any]:
        """Monitor document processing progress"""
        start_time = time.time()
        result = {
            "stages": {},
            "metrics": {},
            "success": False
        }
        
        while time.time() - start_time < timeout:
            try:
                # Check document status
                with self.db.get_session() as session:
                    doc_status = session.execute(
                        """SELECT processing_status, current_stage 
                           FROM source_documents 
                           WHERE document_uuid = :uuid""",
                        {"uuid": doc_uuid}
                    ).fetchone()
                    
                    if not doc_status:
                        result["error"] = "Document not found"
                        return result
                    
                    status, stage = doc_status
                    
                    # Log stage progress
                    if stage and stage not in result["stages"]:
                        result["stages"][stage] = {
                            "start_time": time.time() - start_time,
                            "status": "in_progress"
                        }
                        logger.info(f"📍 Stage: {stage}")
                    
                    # Check if completed
                    if status == "completed":
                        result["success"] = True
                        result["total_time"] = time.time() - start_time
                        
                        # Validate results
                        validation = self.validate_processing_results(doc_uuid, expected_entities)
                        result["validation"] = validation
                        
                        logger.info(f"✅ Processing completed in {result['total_time']:.2f}s")
                        return result
                    
                    elif status == "failed":
                        result["error"] = "Processing failed"
                        # Get error details
                        error_info = session.execute(
                            """SELECT error_message FROM processing_tasks 
                               WHERE document_uuid = :uuid 
                               ORDER BY created_at DESC LIMIT 1""",
                            {"uuid": doc_uuid}
                        ).fetchone()
                        if error_info:
                            result["error"] = error_info[0]
                        return result
                
                # Check cache metrics
                cache_stats = self.check_cache_status(doc_uuid)
                result["metrics"]["cache"] = cache_stats
                
                # Wait before next check
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                result["error"] = str(e)
                return result
        
        result["error"] = "Processing timeout"
        return result
    
    def validate_processing_results(self, doc_uuid: str, expected_entities: List[str]) -> Dict[str, Any]:
        """Validate processing results"""
        validation = {
            "ocr": {"success": False},
            "chunks": {"success": False, "count": 0},
            "entities": {"success": False, "found": [], "expected": expected_entities},
            "resolution": {"success": False, "canonical_count": 0}
        }
        
        try:
            with self.db.get_session() as session:
                # Check OCR results
                ocr_result = self.redis.get_cached(f"doc:ocr:{doc_uuid}")
                if ocr_result and len(ocr_result.get("text", "")) > 100:
                    validation["ocr"]["success"] = True
                    validation["ocr"]["text_length"] = len(ocr_result.get("text", ""))
                
                # Check chunks
                chunk_count = session.execute(
                    "SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid",
                    {"uuid": doc_uuid}
                ).scalar()
                if chunk_count > 0:
                    validation["chunks"]["success"] = True
                    validation["chunks"]["count"] = chunk_count
                
                # Check entities
                entities = session.execute(
                    """SELECT DISTINCT entity_text, entity_type 
                       FROM entity_mentions 
                       WHERE document_uuid = :uuid""",
                    {"uuid": doc_uuid}
                ).fetchall()
                
                if entities:
                    validation["entities"]["success"] = True
                    validation["entities"]["found"] = [
                        {"text": e[0], "type": e[1]} for e in entities
                    ]
                    
                    # Check for expected entities
                    found_texts = [e[0].lower() for e in entities]
                    for expected in expected_entities:
                        if any(expected.lower() in text for text in found_texts):
                            validation["entities"]["matches"] = validation["entities"].get("matches", 0) + 1
                
                # Check canonical entities
                canonical_count = session.execute(
                    """SELECT COUNT(DISTINCT ce.canonical_entity_uuid)
                       FROM canonical_entities ce
                       JOIN entity_mentions em ON ce.canonical_entity_uuid = em.canonical_entity_uuid
                       WHERE em.document_uuid = :uuid""",
                    {"uuid": doc_uuid}
                ).scalar()
                
                if canonical_count > 0:
                    validation["resolution"]["success"] = True
                    validation["resolution"]["canonical_count"] = canonical_count
                    
        except Exception as e:
            logger.error(f"Validation error: {e}")
            
        return validation
    
    def check_cache_status(self, doc_uuid: str) -> Dict[str, int]:
        """Check cache population status"""
        cache_keys = {
            "state": f"doc:state:{doc_uuid}",
            "ocr": f"doc:ocr:{doc_uuid}",
            "chunks": f"doc:chunks:{doc_uuid}",
            "chunks_list": f"doc:chunks_list:{doc_uuid}"
        }
        
        stats = {}
        client = self.redis.get_client()
        
        for key_type, key in cache_keys.items():
            stats[key_type] = 1 if client.exists(key) else 0
            
        return stats
    
    def run_batch_test(self, documents: List[Dict[str, Any]], 
                      concurrent: bool = False) -> Dict[str, Any]:
        """Run batch processing test"""
        logger.info("\n" + "="*60)
        logger.info(f"BATCH TEST: {len(documents)} documents ({'concurrent' if concurrent else 'sequential'})")
        logger.info("="*60)
        
        project_uuid = self.get_or_create_test_project()
        batch_start = time.time()
        results = []
        
        if concurrent:
            # Process documents concurrently
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(self.process_single_document, doc, project_uuid)
                    for doc in documents
                ]
                
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Concurrent processing error: {e}")
        else:
            # Process documents sequentially
            for doc in documents:
                result = self.process_single_document(doc, project_uuid)
                results.append(result)
        
        batch_time = time.time() - batch_start
        successful = len([r for r in results if r["success"]])
        
        return {
            "total_documents": len(documents),
            "successful": successful,
            "failed": len(documents) - successful,
            "success_rate": (successful / len(documents) * 100) if documents else 0,
            "total_time": batch_time,
            "avg_time_per_doc": batch_time / len(documents) if documents else 0,
            "type": "concurrent" if concurrent else "sequential",
            "results": results
        }
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive verification report"""
        logger.info("\n" + "="*60)
        logger.info("VERIFICATION REPORT")
        logger.info("="*60)
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_duration": time.time() - self.start_time,
            "results": self.results,
            "summary": {
                "prerequisites": {},
                "documents_processed": 0,
                "success_rate": 0,
                "avg_processing_time": 0,
                "validation_results": {}
            }
        }
        
        # Calculate summary metrics
        if "single_document" in self.results:
            single = self.results["single_document"]
            if single["success"]:
                report["summary"]["single_document_time"] = single["total_time"]
                report["summary"]["validation_results"] = single["phases"]["processing"]["validation"]
        
        if "batch_sequential" in self.results:
            seq = self.results["batch_sequential"]
            report["summary"]["sequential_performance"] = {
                "success_rate": seq["success_rate"],
                "avg_time": seq["avg_time_per_doc"]
            }
        
        if "batch_concurrent" in self.results:
            conc = self.results["batch_concurrent"]
            report["summary"]["concurrent_performance"] = {
                "success_rate": conc["success_rate"],
                "avg_time": conc["avg_time_per_doc"]
            }
            
            # Calculate speedup
            if "batch_sequential" in self.results:
                speedup = seq["avg_time_per_doc"] / conc["avg_time_per_doc"]
                report["summary"]["concurrent_speedup"] = f"{speedup:.2f}x"
        
        # Overall assessment
        all_tests_passed = all([
            self.results.get("prerequisites", {}).get("database"),
            self.results.get("prerequisites", {}).get("redis"),
            self.results.get("prerequisites", {}).get("s3"),
            self.results.get("single_document", {}).get("success", False)
        ])
        
        report["summary"]["fitness_for_production"] = "READY" if all_tests_passed else "NOT READY"
        
        # Save report
        report_file = f"document_verification_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"\nReport saved to: {report_file}")
        
        # Print summary
        logger.info("\nSUMMARY:")
        logger.info(f"  Prerequisites: {sum(self.results.get('prerequisites', {}).values())}/{len(self.results.get('prerequisites', {}))}")
        logger.info(f"  Documents Processed: {report['summary'].get('documents_processed', 0)}")
        logger.info(f"  Success Rate: {report['summary'].get('success_rate', 0):.1f}%")
        logger.info(f"  Fitness: {report['summary']['fitness_for_production']}")
        
        return report
    
    def run_full_verification(self):
        """Run complete verification suite"""
        logger.info("Starting Actual Document Verification")
        logger.info("="*80)
        
        # Check prerequisites
        prereq_results = self.check_prerequisites()
        self.results["prerequisites"] = prereq_results
        
        if not all([prereq_results["database"], prereq_results["redis"], prereq_results["s3"]]):
            logger.error("❌ Prerequisites not met. Aborting verification.")
            return self.generate_report()
        
        # Get test documents
        test_docs = self.get_test_documents()
        if not test_docs:
            logger.error("❌ No test documents found. Aborting verification.")
            return self.generate_report()
        
        # Phase 1: Single document test
        logger.info("\n" + "="*60)
        logger.info("PHASE 1: Single Document Processing")
        logger.info("="*60)
        
        project_uuid = self.get_or_create_test_project()
        single_result = self.process_single_document(test_docs[0], project_uuid)
        self.results["single_document"] = single_result
        
        if not single_result["success"]:
            logger.warning("⚠️ Single document test failed. Skipping batch tests.")
            return self.generate_report()
        
        # Phase 2: Batch processing (if enough documents)
        if len(test_docs) >= 3:
            # Sequential batch
            batch_result = self.run_batch_test(test_docs[:3], concurrent=False)
            self.results["batch_sequential"] = batch_result
            
            # Concurrent batch
            batch_result = self.run_batch_test(test_docs[:3], concurrent=True)
            self.results["batch_concurrent"] = batch_result
        
        return self.generate_report()

def main():
    """Run document verification"""
    verifier = DocumentVerifier()
    
    try:
        report = verifier.run_full_verification()
        
        # Determine exit code based on fitness
        if report["summary"]["fitness_for_production"] == "READY":
            logger.info("\n✅ VERIFICATION PASSED - System is ready for production")
            sys.exit(0)
        else:
            logger.error("\n❌ VERIFICATION FAILED - System needs fixes")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("\nVerification interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Verification error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()