#!/usr/bin/env python3
"""
Production Testing in Simulation Mode
Purpose: Test the system without requiring Celery workers
This will help us validate the core functionality and identify issues
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
from uuid import uuid4

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging with detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('production_test_simulation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ProductionTestSimulator:
    """Simulate production testing to identify issues"""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "errors": [],
            "warnings": [],
            "successes": [],
            "recommendations": []
        }
        
    def log_error(self, context: str, error: str, recommendation: str = None):
        """Log an error with context and recommendation"""
        logger.error(f"[{context}] {error}")
        self.results["errors"].append({
            "context": context,
            "error": error,
            "recommendation": recommendation,
            "timestamp": datetime.now().isoformat()
        })
        
    def log_success(self, context: str, message: str):
        """Log a success"""
        logger.info(f"✅ [{context}] {message}")
        self.results["successes"].append({
            "context": context,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
    
    def test_environment(self):
        """Test environment setup"""
        logger.info("\n" + "="*60)
        logger.info("TESTING ENVIRONMENT SETUP")
        logger.info("="*60)
        
        # Check critical environment variables
        critical_vars = {
            "DATABASE_URL": "Database connection string",
            "AWS_ACCESS_KEY_ID": "AWS credentials for S3/Textract",
            "AWS_SECRET_ACCESS_KEY": "AWS credentials",
            "S3_PRIMARY_DOCUMENT_BUCKET": "S3 bucket for documents",
            "OPENAI_API_KEY": "OpenAI API for entity extraction",
            "DEPLOYMENT_STAGE": "Deployment configuration"
        }
        
        for var, description in critical_vars.items():
            value = os.getenv(var)
            if value:
                # Don't log sensitive values
                self.log_success("Environment", f"{var} is set ({description})")
            else:
                self.log_error(
                    "Environment", 
                    f"{var} is not set - {description}",
                    f"Set {var} in .env file or environment"
                )
        
        # Check Redis configuration
        redis_config = os.getenv("REDIS_CONFIG")
        if redis_config:
            self.log_success("Environment", "Redis configuration found")
        else:
            # Check individual Redis vars
            redis_vars = ["REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD"]
            missing = [v for v in redis_vars if not os.getenv(v)]
            if missing:
                self.log_error(
                    "Environment",
                    f"Redis variables missing: {missing}",
                    "Redis is configured via REDIS_CONFIG, individual vars not needed"
                )
    
    def test_database_connection(self):
        """Test database connectivity"""
        logger.info("\n" + "="*60)
        logger.info("TESTING DATABASE CONNECTION")
        logger.info("="*60)
        
        try:
            from scripts.db import DatabaseManager
            db = DatabaseManager()
            
            with db.get_session() as session:
                # Test basic query
                result = session.execute("SELECT version()").scalar()
                self.log_success("Database", f"Connected to PostgreSQL: {result}")
                
                # Check schema
                tables = session.execute(
                    """SELECT table_name FROM information_schema.tables 
                       WHERE table_schema = 'public'"""
                ).fetchall()
                
                required_tables = [
                    "projects", "source_documents", "document_chunks",
                    "entity_mentions", "canonical_entities", "relationship_staging",
                    "processing_tasks"
                ]
                
                existing_tables = [t[0] for t in tables]
                for table in required_tables:
                    if table in existing_tables:
                        self.log_success("Database", f"Table '{table}' exists")
                    else:
                        self.log_error(
                            "Database",
                            f"Required table '{table}' not found",
                            "Run database migration scripts"
                        )
                        
        except Exception as e:
            self.log_error(
                "Database",
                f"Connection failed: {str(e)}",
                "Check DATABASE_URL and database accessibility"
            )
    
    def test_redis_connection(self):
        """Test Redis connectivity"""
        logger.info("\n" + "="*60)
        logger.info("TESTING REDIS CONNECTION")
        logger.info("="*60)
        
        try:
            from scripts.cache import get_redis_manager
            redis = get_redis_manager()
            
            # Test connection
            client = redis.get_client()
            client.ping()
            self.log_success("Redis", "Connected to Redis successfully")
            
            # Test operations
            test_key = f"test_key_{int(time.time())}"
            client.setex(test_key, 60, "test_value")
            value = client.get(test_key)
            client.delete(test_key)
            
            if value == b"test_value":
                self.log_success("Redis", "Read/write operations working")
            else:
                self.log_error(
                    "Redis",
                    "Read/write test failed",
                    "Check Redis permissions"
                )
                
        except Exception as e:
            self.log_error(
                "Redis",
                f"Connection failed: {str(e)}",
                "Check Redis configuration and connectivity"
            )
    
    def test_s3_access(self):
        """Test S3 bucket access"""
        logger.info("\n" + "="*60)
        logger.info("TESTING S3 ACCESS")
        logger.info("="*60)
        
        try:
            from scripts.s3_storage import S3StorageManager
            s3 = S3StorageManager()
            bucket = os.getenv("S3_PRIMARY_DOCUMENT_BUCKET")
            
            if not bucket:
                self.log_error(
                    "S3",
                    "S3_PRIMARY_DOCUMENT_BUCKET not set",
                    "Set the S3 bucket name in environment"
                )
                return
            
            # Test bucket access
            s3.s3_client.head_bucket(Bucket=bucket)
            self.log_success("S3", f"Bucket '{bucket}' is accessible")
            
            # Test write permissions
            test_key = f"test/permissions_test_{int(time.time())}.txt"
            try:
                s3.s3_client.put_object(
                    Bucket=bucket,
                    Key=test_key,
                    Body=b"test content",
                    ContentType="text/plain"
                )
                self.log_success("S3", "Write permissions confirmed")
                
                # Clean up
                s3.s3_client.delete_object(Bucket=bucket, Key=test_key)
                
            except Exception as e:
                self.log_error(
                    "S3",
                    f"Write test failed: {str(e)}",
                    "Check IAM permissions for S3 bucket"
                )
                
        except Exception as e:
            self.log_error(
                "S3",
                f"S3 access failed: {str(e)}",
                "Check AWS credentials and S3 configuration"
            )
    
    def test_textract_access(self):
        """Test AWS Textract access"""
        logger.info("\n" + "="*60)
        logger.info("TESTING TEXTRACT ACCESS")
        logger.info("="*60)
        
        try:
            import boto3
            
            # Test Textract client creation
            textract = boto3.client(
                'textract',
                region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
            )
            
            # We can't test actual OCR without a document, but we can check access
            try:
                # This will fail with specific error if no access
                response = textract.describe_document_text_detection_job(
                    JobId="test-job-id"
                )
            except textract.exceptions.InvalidJobIdException:
                # This error is expected - it means we have access
                self.log_success("Textract", "API access confirmed")
            except Exception as e:
                if "InvalidJobIdException" in str(e):
                    self.log_success("Textract", "API access confirmed")
                else:
                    self.log_error(
                        "Textract",
                        f"Access test failed: {str(e)}",
                        "Check IAM permissions for Textract"
                    )
                    
        except Exception as e:
            self.log_error(
                "Textract",
                f"Client creation failed: {str(e)}",
                "Check AWS credentials and region configuration"
            )
    
    def test_openai_access(self):
        """Test OpenAI API access"""
        logger.info("\n" + "="*60)
        logger.info("TESTING OPENAI ACCESS")
        logger.info("="*60)
        
        try:
            import openai
            
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                self.log_error(
                    "OpenAI",
                    "OPENAI_API_KEY not set",
                    "Set OpenAI API key in environment"
                )
                return
            
            # Test with a simple completion
            openai.api_key = api_key
            
            try:
                # Test the API with minimal tokens
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": "test"}],
                    max_tokens=1
                )
                self.log_success("OpenAI", "API access confirmed")
                
            except Exception as e:
                self.log_error(
                    "OpenAI",
                    f"API test failed: {str(e)}",
                    "Check API key validity and credits"
                )
                
        except ImportError:
            self.log_error(
                "OpenAI",
                "openai package not installed",
                "Run: pip install openai"
            )
    
    def test_document_samples(self):
        """Test if sample documents exist"""
        logger.info("\n" + "="*60)
        logger.info("TESTING DOCUMENT SAMPLES")
        logger.info("="*60)
        
        doc_path = Path("/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)")
        
        if not doc_path.exists():
            self.log_error(
                "Documents",
                f"Sample document directory not found: {doc_path}",
                "Ensure sample documents are available"
            )
            return
        
        # List PDF files
        pdf_files = list(doc_path.glob("*.pdf"))
        if pdf_files:
            self.log_success("Documents", f"Found {len(pdf_files)} PDF files")
            
            # Check specific test document
            test_doc = doc_path / "Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf"
            if test_doc.exists():
                size_kb = test_doc.stat().st_size / 1024
                self.log_success(
                    "Documents", 
                    f"Primary test document found: {test_doc.name} ({size_kb:.1f}KB)"
                )
            else:
                self.log_error(
                    "Documents",
                    "Primary test document not found",
                    "Check document path and filename"
                )
        else:
            self.log_error(
                "Documents",
                "No PDF files found in sample directory",
                "Add sample legal documents for testing"
            )
    
    def test_celery_setup(self):
        """Test Celery configuration"""
        logger.info("\n" + "="*60)
        logger.info("TESTING CELERY SETUP")
        logger.info("="*60)
        
        try:
            from scripts.celery_app import app
            
            # Check registered tasks
            tasks = list(app.tasks.keys())
            important_tasks = [
                "scripts.pdf_tasks.process_pdf_document",
                "scripts.pdf_tasks.process_ocr_task",
                "scripts.pdf_tasks.chunk_document_task",
                "scripts.pdf_tasks.extract_entities_task",
                "scripts.pdf_tasks.resolve_entities_task",
                "scripts.pdf_tasks.build_relationships_task"
            ]
            
            for task in important_tasks:
                if task in tasks:
                    self.log_success("Celery", f"Task registered: {task}")
                else:
                    self.log_error(
                        "Celery",
                        f"Task not found: {task}",
                        "Check task registration in celery_app.py"
                    )
            
            # Check broker URL
            broker = app.conf.broker_url
            if broker:
                self.log_success("Celery", f"Broker configured: {broker[:20]}...")
            else:
                self.log_error(
                    "Celery",
                    "No broker URL configured",
                    "Set CELERY_BROKER_URL or use Redis"
                )
                
        except Exception as e:
            self.log_error(
                "Celery",
                f"Setup test failed: {str(e)}",
                "Check Celery configuration"
            )
    
    def generate_report(self):
        """Generate comprehensive report"""
        logger.info("\n" + "="*60)
        logger.info("PRODUCTION TEST REPORT")
        logger.info("="*60)
        
        # Count results
        error_count = len(self.results["errors"])
        success_count = len(self.results["successes"])
        
        # Overall assessment
        if error_count == 0:
            assessment = "READY FOR PRODUCTION"
            logger.info("✅ ALL TESTS PASSED - System ready for production")
        elif error_count <= 2:
            assessment = "CONDITIONAL - Minor issues to fix"
            logger.warning(f"⚠️ CONDITIONAL PASS - {error_count} issues found")
        else:
            assessment = "NOT READY - Critical issues found"
            logger.error(f"❌ NOT READY - {error_count} critical issues")
        
        self.results["summary"] = {
            "assessment": assessment,
            "total_tests": error_count + success_count,
            "passed": success_count,
            "failed": error_count,
            "success_rate": (success_count / (error_count + success_count) * 100) if (error_count + success_count) > 0 else 0
        }
        
        # Critical issues that could impact fairness
        critical_issues = []
        for error in self.results["errors"]:
            if any(keyword in error["context"].lower() for keyword in ["database", "openai", "textract"]):
                critical_issues.append(error)
        
        if critical_issues:
            logger.error("\nCRITICAL ISSUES IMPACTING FAIRNESS:")
            for issue in critical_issues:
                logger.error(f"  - {issue['context']}: {issue['error']}")
                if issue.get("recommendation"):
                    logger.info(f"    → {issue['recommendation']}")
        
        # Save detailed report
        report_file = f"production_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"\nDetailed report saved to: {report_file}")
        
        # Recommendations for production
        logger.info("\nRECOMMENDATIONS FOR PRODUCTION:")
        if error_count == 0:
            logger.info("1. System is ready for production deployment")
            logger.info("2. Start with small batch of documents")
            logger.info("3. Monitor performance closely")
            logger.info("4. Have rollback plan ready")
        else:
            logger.info("1. Fix critical issues before deployment")
            logger.info("2. Re-run tests after fixes")
            logger.info("3. Consider staged rollout")
            logger.info("4. Implement comprehensive monitoring")
        
        return self.results
    
    def run_all_tests(self):
        """Run all production tests"""
        logger.info("Starting Production Testing Simulation")
        logger.info("This will help identify issues preventing production deployment")
        logger.info("="*80)
        
        # Run test suite
        self.test_environment()
        self.test_database_connection()
        self.test_redis_connection()
        self.test_s3_access()
        self.test_textract_access()
        self.test_openai_access()
        self.test_document_samples()
        self.test_celery_setup()
        
        # Generate report
        return self.generate_report()

def main():
    """Run production testing"""
    tester = ProductionTestSimulator()
    
    try:
        report = tester.run_all_tests()
        
        # Exit code based on assessment
        if report["summary"]["assessment"] == "READY FOR PRODUCTION":
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Production test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()