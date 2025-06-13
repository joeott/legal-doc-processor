#!/usr/bin/env python3
"""
Real Document Processing Test Suite
NO MOCKS, NO SIMULATIONS - Real processing only.
Tests actual document flow through all pipeline stages.
"""

import os
import sys
import time
import uuid
import json
from pathlib import Path
from datetime import datetime

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document
from scripts.db import get_db
from scripts.cache import get_redis_manager
from sqlalchemy import text
from scripts.logging_config import get_logger

logger = get_logger(__name__)

class RealDocumentTester:
    """Test actual document processing through the complete pipeline"""
    
    def __init__(self):
        # Use real available documents
        self.test_docs = [
            "input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf"
        ]
        self.results = {}
        self.redis = get_redis_manager()
        
    def test_single_document_e2e(self, file_path):
        """Test complete pipeline for one real document"""
        doc_uuid = str(uuid.uuid4())
        project_uuid = str(uuid.uuid4())
        
        print(f"\n{'='*60}")
        print(f"Testing: {file_path}")
        print(f"Document UUID: {doc_uuid}")
        print(f"Project UUID: {project_uuid}")
        print(f"{'='*60}")
        
        # Check file exists
        if not os.path.exists(file_path):
            print(f"ERROR: Test file not found: {file_path}")
            return False
            
        # Submit to actual pipeline
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Submitting to pipeline...")
        try:
            task = process_pdf_document.delay(doc_uuid, file_path, project_uuid)
            print(f"Task ID: {task.id}")
        except Exception as e:
            print(f"ERROR submitting task: {e}")
            return False
        
        # Monitor real progress
        start_time = time.time()
        timeout = 300  # 5 minutes for real processing
        last_status = None
        
        while time.time() - start_time < timeout:
            try:
                if task.ready():
                    if task.successful():
                        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Task completed successfully!")
                        result = task.result
                        print(f"Result: {json.dumps(result, indent=2)}")
                    else:
                        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Task failed!")
                        print(f"Error: {task.info}")
                    break
                    
                # Check intermediate stages
                current_status = self.check_pipeline_status(doc_uuid)
                if current_status != last_status:
                    self.display_status_change(current_status)
                    last_status = current_status
                    
            except Exception as e:
                print(f"ERROR checking status: {e}")
                
            time.sleep(5)
        
        # Verify completion
        elapsed = time.time() - start_time
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Processing time: {elapsed:.1f} seconds")
        
        if not task.ready():
            print("ERROR: Task timed out!")
            return False
            
        # Verify all stages completed
        final_verification = self.verify_all_stages(doc_uuid)
        return final_verification
    
    def check_pipeline_status(self, doc_uuid):
        """Check current pipeline status from database"""
        status = {
            "document": False,
            "ocr": False,
            "chunks": 0,
            "entities": 0,
            "canonical": 0,
            "relationships": 0
        }
        
        try:
            session = next(get_db())
            try:
                # Check document
                result = session.execute(text(
                    "SELECT document_uuid, textract_job_status FROM source_documents WHERE document_uuid = :uuid"
                ), {"uuid": doc_uuid}).fetchone()
                if result:
                    status["document"] = True
                    status["ocr"] = result.textract_job_status == 'SUCCEEDED'
                    
                # Check chunks
                result = session.execute(text(
                    "SELECT COUNT(*) as count FROM document_chunks WHERE source_document_uuid = :uuid"
                ), {"uuid": doc_uuid}).fetchone()
                status["chunks"] = result.count if result else 0
                
                # Check entities
                result = session.execute(text(
                    "SELECT COUNT(*) as count FROM entity_mentions WHERE source_document_uuid = :uuid"
                ), {"uuid": doc_uuid}).fetchone()
                status["entities"] = result.count if result else 0
                
                # Check canonical entities
                result = session.execute(text(
                    "SELECT COUNT(*) as count FROM canonical_entities WHERE created_from_document_uuid = :uuid"
                ), {"uuid": doc_uuid}).fetchone()
                status["canonical"] = result.count if result else 0
                
                # Check relationships
                result = session.execute(text(
                    "SELECT COUNT(*) as count FROM relationship_staging WHERE source_document_uuid = :uuid"
                ), {"uuid": doc_uuid}).fetchone()
                status["relationships"] = result.count if result else 0
                
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Error checking status: {e}")
            
        return status
    
    def display_status_change(self, status):
        """Display status changes as they occur"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        if status["document"] and not status["ocr"]:
            print(f"[{timestamp}] ✓ Document created, OCR in progress...")
        elif status["ocr"] and status["chunks"] == 0:
            print(f"[{timestamp}] ✓ OCR completed, chunking in progress...")
        elif status["chunks"] > 0 and status["entities"] == 0:
            print(f"[{timestamp}] ✓ {status['chunks']} chunks created, extracting entities...")
        elif status["entities"] > 0 and status["canonical"] == 0:
            print(f"[{timestamp}] ✓ {status['entities']} entities extracted, resolving...")
        elif status["canonical"] > 0 and status["relationships"] == 0:
            print(f"[{timestamp}] ✓ {status['canonical']} canonical entities, building relationships...")
        elif status["relationships"] > 0:
            print(f"[{timestamp}] ✓ {status['relationships']} relationships built!")
    
    def verify_all_stages(self, doc_uuid):
        """Comprehensive verification of all pipeline stages"""
        print(f"\n{'='*60}")
        print("PIPELINE VERIFICATION")
        print(f"{'='*60}")
        
        verifications = {
            "1_document_created": False,
            "2_ocr_completed": False,
            "3_chunks_created": False,
            "4_entities_extracted": False,
            "5_entities_resolved": False,
            "6_relationships_built": False
        }
        
        details = {}
        
        try:
            session = next(get_db())
            try:
                # Stage 1: Document record
                result = session.execute(text(
                    "SELECT file_name, textract_job_status, created_at FROM source_documents WHERE document_uuid = :uuid"
                ), {"uuid": doc_uuid}).fetchone()
                if result:
                    verifications["1_document_created"] = True
                    details["document"] = {
                        "filename": result.file_name,
                        "ocr_status": result.textract_job_status,
                        "created_at": str(result.created_at)
                    }
                    if result.textract_job_status == 'SUCCEEDED':
                        verifications["2_ocr_completed"] = True
                    
                # Stage 2: Chunks
                result = session.execute(text(
                    """SELECT COUNT(*) as count, SUM(LENGTH(content)) as total_chars 
                       FROM document_chunks WHERE source_document_uuid = :uuid"""
                ), {"uuid": doc_uuid}).fetchone()
                if result and result.count > 0:
                    verifications["3_chunks_created"] = True
                    details["chunks"] = {
                        "count": result.count,
                        "total_chars": result.total_chars or 0
                    }
                    
                # Stage 3: Entity mentions
                result = session.execute(text(
                    """SELECT COUNT(*) as count, COUNT(DISTINCT entity_type) as types 
                       FROM entity_mentions WHERE source_document_uuid = :uuid"""
                ), {"uuid": doc_uuid}).fetchone()
                if result and result.count > 0:
                    verifications["4_entities_extracted"] = True
                    details["entities"] = {
                        "count": result.count,
                        "unique_types": result.types
                    }
                    
                # Stage 4: Canonical entities
                result = session.execute(text(
                    """SELECT COUNT(*) as count, COUNT(DISTINCT entity_type) as types 
                       FROM canonical_entities WHERE created_from_document_uuid = :uuid"""
                ), {"uuid": doc_uuid}).fetchone()
                if result and result.count > 0:
                    verifications["5_entities_resolved"] = True
                    details["canonical"] = {
                        "count": result.count,
                        "unique_types": result.types
                    }
                    
                # Stage 5: Relationships
                result = session.execute(text(
                    """SELECT COUNT(*) as count, COUNT(DISTINCT relationship_type) as types 
                       FROM relationship_staging WHERE source_document_uuid = :uuid"""
                ), {"uuid": doc_uuid}).fetchone()
                if result and result.count > 0:
                    verifications["6_relationships_built"] = True
                    details["relationships"] = {
                        "count": result.count,
                        "unique_types": result.types
                    }
                    
            finally:
                session.close()
        except Exception as e:
            print(f"ERROR during verification: {e}")
            logger.error(f"Verification error: {e}", exc_info=True)
        
        # Display results
        print("\nStage Verification:")
        print("-" * 40)
        all_passed = True
        for stage, passed in sorted(verifications.items()):
            status = "✓ PASS" if passed else "✗ FAIL"
            stage_name = stage[2:].replace('_', ' ').title()
            print(f"{stage_name:.<30} {status}")
            if not passed:
                all_passed = False
        
        # Display details
        if details:
            print("\nProcessing Details:")
            print("-" * 40)
            print(json.dumps(details, indent=2))
        
        # Overall result
        print(f"\nOVERALL RESULT: {'SUCCESS' if all_passed else 'FAILED'}")
        print(f"Stages Completed: {sum(1 for v in verifications.values() if v)}/6")
        
        return all_passed
    
    def run_comprehensive_test(self):
        """Test all documents and generate report"""
        print("\n" + "="*60)
        print("REAL DOCUMENT PROCESSING TEST SUITE")
        print("="*60)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Check if we have test documents
        available_docs = []
        for doc_path in self.test_docs:
            if os.path.exists(doc_path):
                available_docs.append(doc_path)
            else:
                print(f"WARNING: Test document not found: {doc_path}")
                
        if not available_docs:
            print("\nERROR: No test documents found!")
            print("Please ensure test documents are in:")
            for path in self.test_docs:
                print(f"  - {path}")
            return
        
        print(f"\nTesting {len(available_docs)} documents...")
        
        # Test each document
        for doc_path in available_docs:
            success = self.test_single_document_e2e(doc_path)
            self.results[doc_path] = success
        
        # Generate report
        self.generate_report()
    
    def generate_report(self):
        """Generate comprehensive test report"""
        print("\n" + "="*60)
        print("TEST REPORT SUMMARY")
        print("="*60)
        
        if not self.results:
            print("No test results to report.")
            return
            
        total = len(self.results)
        passed = sum(1 for v in self.results.values() if v)
        
        print(f"\nDocuments Tested: {total}")
        print(f"Successful: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        print("\nDetailed Results:")
        print("-" * 60)
        for doc, success in self.results.items():
            status = "✓ SUCCESS" if success else "✗ FAILED"
            doc_name = os.path.basename(doc)
            print(f"  {doc_name:.<50} {status}")
        
        # Save report to file
        report_file = f"test_results/real_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs("test_results", exist_ok=True)
        
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "total_documents": total,
            "passed": passed,
            "failed": total - passed,
            "success_rate": (passed/total)*100 if total > 0 else 0,
            "results": self.results
        }
        
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2)
            
        print(f"\nReport saved to: {report_file}")


def main():
    """Run the real document test suite"""
    # Ensure we're in the right environment
    print("Real Document Processing Test Suite")
    print("-" * 40)
    
    # Check Celery connection
    try:
        i = app.control.inspect()
        stats = i.stats()
        if stats:
            print(f"✓ Celery workers available: {len(stats)}")
        else:
            print("✗ No Celery workers found! Please start workers first.")
            return
    except Exception as e:
        print(f"✗ Cannot connect to Celery: {e}")
        return
    
    # Run tests
    tester = RealDocumentTester()
    tester.run_comprehensive_test()


if __name__ == "__main__":
    main()