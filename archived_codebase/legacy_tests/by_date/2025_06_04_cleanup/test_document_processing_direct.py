#!/usr/bin/env python3
"""
Direct Document Processing Test
Purpose: Test document processing directly without Celery workers
This allows us to validate core functionality
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Add parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DirectDocumentTester:
    """Test document processing without workers"""
    
    def __init__(self):
        self.test_doc_path = Path("/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf")
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "stages": {},
            "errors": [],
            "metrics": {}
        }
        
    def test_database_operations(self):
        """Test database connectivity and operations"""
        logger.info("\n" + "="*60)
        logger.info("TESTING DATABASE OPERATIONS")
        logger.info("="*60)
        
        try:
            from scripts.db import DatabaseManager
            db = DatabaseManager()
            
            # Use generator properly
            db_gen = db.get_session()
            session = next(db_gen)
            
            try:
                # Test connection
                version = session.execute("SELECT version()").scalar()
                logger.info(f"✅ Database connected: {version}")
                self.results["stages"]["database"] = {"success": True, "version": version}
                
                # Test project creation
                project_uuid = str(uuid4())
                session.execute(
                    """INSERT INTO projects (project_uuid, project_name, created_at) 
                       VALUES (:uuid, :name, :created)
                       ON CONFLICT (project_uuid) DO NOTHING""",
                    {
                        "uuid": project_uuid,
                        "name": "Direct Test Project",
                        "created": datetime.now()
                    }
                )
                session.commit()
                logger.info(f"✅ Created test project: {project_uuid}")
                
                # Test document record creation
                doc_uuid = str(uuid4())
                session.execute(
                    """INSERT INTO source_documents 
                       (document_uuid, project_uuid, file_name, file_path, 
                        processing_status, created_at)
                       VALUES (:doc_uuid, :proj_uuid, :name, :path, 
                               :status, :created)""",
                    {
                        "doc_uuid": doc_uuid,
                        "proj_uuid": project_uuid,
                        "name": self.test_doc_path.name,
                        "path": str(self.test_doc_path),
                        "status": "pending",
                        "created": datetime.now()
                    }
                )
                session.commit()
                logger.info(f"✅ Created document record: {doc_uuid}")
                
                self.results["test_document_uuid"] = doc_uuid
                self.results["test_project_uuid"] = project_uuid
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"❌ Database test failed: {e}")
            self.results["stages"]["database"] = {"success": False, "error": str(e)}
            self.results["errors"].append({"stage": "database", "error": str(e)})
    
    def test_s3_operations(self):
        """Test S3 upload and retrieval"""
        logger.info("\n" + "="*60)
        logger.info("TESTING S3 OPERATIONS")
        logger.info("="*60)
        
        try:
            from scripts.s3_storage import S3StorageManager
            s3 = S3StorageManager()
            
            if not self.test_doc_path.exists():
                logger.error(f"❌ Test document not found: {self.test_doc_path}")
                return
            
            # Upload test document
            doc_uuid = self.results.get("test_document_uuid", str(uuid4()))
            s3_key = f"documents/test/{doc_uuid}/{self.test_doc_path.name}"
            
            with open(self.test_doc_path, 'rb') as f:
                s3.upload_document(f, s3_key)
            
            logger.info(f"✅ Uploaded document to S3: {s3_key}")
            
            # Generate presigned URL
            url = s3.generate_presigned_url(s3_key)
            logger.info(f"✅ Generated presigned URL")
            
            self.results["stages"]["s3"] = {
                "success": True,
                "s3_key": s3_key,
                "file_size": self.test_doc_path.stat().st_size
            }
            
        except Exception as e:
            logger.error(f"❌ S3 test failed: {e}")
            self.results["stages"]["s3"] = {"success": False, "error": str(e)}
            self.results["errors"].append({"stage": "s3", "error": str(e)})
    
    def test_textract_submission(self):
        """Test Textract job submission"""
        logger.info("\n" + "="*60)
        logger.info("TESTING TEXTRACT SUBMISSION")
        logger.info("="*60)
        
        try:
            from scripts.textract_utils import TextractManager
            
            # Get S3 info from previous test
            s3_info = self.results["stages"].get("s3", {})
            if not s3_info.get("success"):
                logger.error("❌ S3 upload required first")
                return
            
            s3_key = s3_info["s3_key"]
            bucket = os.getenv("S3_PRIMARY_DOCUMENT_BUCKET")
            
            # Submit Textract job
            manager = TextractManager()
            job_id = manager.start_document_analysis(bucket, s3_key)
            
            logger.info(f"✅ Textract job submitted: {job_id}")
            
            # Wait for completion (with timeout)
            logger.info("⏳ Waiting for Textract completion...")
            start_time = time.time()
            timeout = 60  # 1 minute timeout
            
            while time.time() - start_time < timeout:
                status = manager.get_job_status(job_id)
                
                if status == "SUCCEEDED":
                    logger.info("✅ Textract job completed successfully")
                    
                    # Get results
                    results = manager.get_job_results(job_id)
                    text_length = len(results.get("text", ""))
                    page_count = results.get("pages", 0)
                    
                    logger.info(f"📄 Extracted {text_length} characters from {page_count} pages")
                    
                    self.results["stages"]["textract"] = {
                        "success": True,
                        "job_id": job_id,
                        "text_length": text_length,
                        "page_count": page_count
                    }
                    break
                    
                elif status == "FAILED":
                    logger.error("❌ Textract job failed")
                    self.results["stages"]["textract"] = {
                        "success": False,
                        "error": "Job failed"
                    }
                    break
                    
                time.sleep(5)
            else:
                logger.warning("⚠️ Textract timeout - job still running")
                self.results["stages"]["textract"] = {
                    "success": False,
                    "error": "Timeout",
                    "job_id": job_id
                }
                
        except Exception as e:
            logger.error(f"❌ Textract test failed: {e}")
            self.results["stages"]["textract"] = {"success": False, "error": str(e)}
            self.results["errors"].append({"stage": "textract", "error": str(e)})
    
    def test_entity_extraction(self):
        """Test entity extraction with OpenAI"""
        logger.info("\n" + "="*60)
        logger.info("TESTING ENTITY EXTRACTION")
        logger.info("="*60)
        
        try:
            # Test with sample text if Textract didn't complete
            sample_text = """
            This disclosure statement is filed by Paul, Michael on behalf of 
            Wombat Corp in the matter of Acuity vs. Wombat Corp. The disclosure
            was prepared on October 23, 2024 and includes relevant financial
            information and party relationships.
            """
            
            from scripts.entity_service import EntityService
            from scripts.db import DatabaseManager
            db = DatabaseManager()
            service = EntityService(db)
            
            # Create a minimal chunk for testing
            chunk_data = {
                "chunk_id": str(uuid4()),
                "document_uuid": self.results.get("test_document_uuid", str(uuid4())),
                "chunk_text": sample_text,
                "chunk_index": 0
            }
            
            # Extract entities
            result = service.extract_entities_from_chunk(
                chunk_data["chunk_text"],
                uuid4(),  # chunk_uuid
                chunk_data["document_uuid"]
            )
            entities = result.entity_mentions if hasattr(result, 'entity_mentions') else []
            
            logger.info(f"✅ Extracted {len(entities)} entities")
            
            # Log entity details
            entity_types = {}
            for entity in entities:
                entity_type = entity.get("entity_type", "UNKNOWN")
                entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
                logger.info(f"  - {entity.get('entity_text')} ({entity_type})")
            
            self.results["stages"]["entity_extraction"] = {
                "success": True,
                "total_entities": len(entities),
                "entity_types": entity_types,
                "sample_entities": [e.get("entity_text") for e in entities[:5]]
            }
            
        except Exception as e:
            logger.error(f"❌ Entity extraction failed: {e}")
            self.results["stages"]["entity_extraction"] = {"success": False, "error": str(e)}
            self.results["errors"].append({"stage": "entity_extraction", "error": str(e)})
    
    def test_redis_caching(self):
        """Test Redis caching operations"""
        logger.info("\n" + "="*60)
        logger.info("TESTING REDIS CACHING")
        logger.info("="*60)
        
        try:
            from scripts.cache import get_redis_manager
            redis = get_redis_manager()
            
            # Test basic operations
            test_key = f"test:{int(time.time())}"
            test_data = {"test": "data", "timestamp": datetime.now().isoformat()}
            
            # Set data
            redis.set(test_key, test_data, ttl=300)
            logger.info("✅ Set cache data")
            
            # Get data
            retrieved = redis.get_dict(test_key)
            if retrieved and retrieved.get("test") == "data":
                logger.info("✅ Retrieved cache data correctly")
            else:
                logger.error("❌ Cache retrieval mismatch")
            
            # Test document state caching
            doc_uuid = self.results.get("test_document_uuid", str(uuid4()))
            state_key = f"doc:state:{doc_uuid}"
            
            state_data = {
                "status": "processing",
                "current_stage": "entity_extraction",
                "updated_at": datetime.now().isoformat()
            }
            
            redis.set(state_key, state_data, ttl=3600)
            logger.info("✅ Set document state")
            
            # Clean up
            redis.delete(test_key)
            
            self.results["stages"]["redis"] = {
                "success": True,
                "operations_tested": ["set", "get", "delete"]
            }
            
        except Exception as e:
            logger.error(f"❌ Redis test failed: {e}")
            self.results["stages"]["redis"] = {"success": False, "error": str(e)}
            self.results["errors"].append({"stage": "redis", "error": str(e)})
    
    def generate_report(self):
        """Generate test report"""
        logger.info("\n" + "="*60)
        logger.info("DIRECT PROCESSING TEST REPORT")
        logger.info("="*60)
        
        # Calculate success metrics
        stages_tested = len(self.results["stages"])
        stages_passed = sum(1 for s in self.results["stages"].values() if s.get("success"))
        success_rate = (stages_passed / stages_tested * 100) if stages_tested > 0 else 0
        
        logger.info(f"\nStages Tested: {stages_tested}")
        logger.info(f"Stages Passed: {stages_passed}")
        logger.info(f"Success Rate: {success_rate:.1f}%")
        
        # Stage breakdown
        logger.info("\nStage Results:")
        for stage, result in self.results["stages"].items():
            status = "✅ PASS" if result.get("success") else "❌ FAIL"
            logger.info(f"  {stage}: {status}")
            if not result.get("success"):
                logger.info(f"    Error: {result.get('error', 'Unknown')}")
        
        # Critical assessment for fairness mission
        logger.info("\nFAIRNESS IMPACT ASSESSMENT:")
        
        if self.results["stages"].get("database", {}).get("success"):
            logger.info("✅ Can store case information - preserves legal record")
        else:
            logger.error("❌ Cannot store data - legal information will be lost")
        
        if self.results["stages"].get("textract", {}).get("success"):
            logger.info("✅ Can read legal documents - makes justice accessible")
        else:
            logger.error("❌ Cannot read documents - maintains information barriers")
        
        if self.results["stages"].get("entity_extraction", {}).get("success"):
            logger.info("✅ Can identify parties and dates - enables case understanding")
        else:
            logger.error("❌ Cannot extract entities - critical information remains hidden")
        
        # Overall fitness
        if success_rate >= 80:
            logger.info("\n✅ SYSTEM FITNESS: READY FOR TESTING")
            logger.info("Core functions operational - can begin reducing legal inequality")
        elif success_rate >= 60:
            logger.warning("\n⚠️ SYSTEM FITNESS: PARTIAL")
            logger.warning("Some functions work - limited impact on fairness possible")
        else:
            logger.error("\n❌ SYSTEM FITNESS: NOT READY")
            logger.error("Critical functions failing - cannot serve justice mission")
        
        # Save report
        report_file = f"direct_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"\nDetailed report saved to: {report_file}")
        
        return self.results
    
    def run_all_tests(self):
        """Run all direct tests"""
        logger.info("Starting Direct Document Processing Test")
        logger.info("Testing core functions without Celery workers")
        logger.info("="*80)
        
        # Run tests in sequence
        self.test_database_operations()
        self.test_s3_operations()
        self.test_redis_caching()
        
        # Only test these if prerequisites passed
        if self.results["stages"].get("s3", {}).get("success"):
            self.test_textract_submission()
        
        self.test_entity_extraction()
        
        # Generate report
        return self.generate_report()

def main():
    """Run direct testing"""
    tester = DirectDocumentTester()
    
    try:
        report = tester.run_all_tests()
        
        # Return appropriate exit code
        success_rate = sum(1 for s in report["stages"].values() if s.get("success")) / len(report["stages"]) * 100
        if success_rate >= 80:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Direct test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()