#!/usr/bin/env python3
"""
Production Readiness Verification Script
Purpose: Execute comprehensive tests to verify system is production-ready
"""

import os
import sys
import time
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import concurrent.futures
from pathlib import Path

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class TestResult:
    """Store test results"""
    test_name: str
    phase: str
    status: str  # PASS, FAIL, SKIP
    duration: float
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: str = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

class ProductionVerifier:
    """Main verification orchestrator"""
    
    def __init__(self):
        self.results = []
        self.start_time = time.time()
        self.test_data_dir = Path("test_data")
        self.results_dir = Path("test_results")
        self.create_directories()
        
    def create_directories(self):
        """Create test directories"""
        for size in ["small", "medium", "large", "edge_cases"]:
            (self.test_data_dir / size).mkdir(parents=True, exist_ok=True)
        
        for phase in range(1, 7):
            (self.results_dir / f"phase{phase}").mkdir(parents=True, exist_ok=True)
    
    def record_result(self, result: TestResult):
        """Record a test result"""
        self.results.append(result)
        logger.info(f"{result.status}: {result.test_name} ({result.duration:.2f}s)")
        
        if result.error:
            logger.error(f"Error: {result.error}")
    
    def save_results(self, phase: int):
        """Save results for a phase"""
        filename = self.results_dir / f"phase{phase}" / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w') as f:
            json.dump([asdict(r) for r in self.results if r.phase == f"phase{phase}"], f, indent=2)
        
        logger.info(f"Results saved to {filename}")
    
    # Phase 1: Environment & Dependency Verification
    def verify_environment(self) -> bool:
        """Phase 1.1: Environment Configuration Check"""
        logger.info("=" * 60)
        logger.info("PHASE 1: Environment & Dependency Verification")
        logger.info("=" * 60)
        
        start = time.time()
        all_passed = True
        
        # Check environment variables
        required_vars = [
            "DATABASE_URL",
            "REDIS_HOST",
            "REDIS_PORT",
            "REDIS_PASSWORD",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_DEFAULT_REGION",
            "S3_PRIMARY_DOCUMENT_BUCKET",
            "OPENAI_API_KEY",
            "DEPLOYMENT_STAGE"
        ]
        
        logger.info("\n1.1 Checking environment variables...")
        missing_vars = []
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            self.record_result(TestResult(
                test_name="environment_variables",
                phase="phase1",
                status="FAIL",
                duration=time.time() - start,
                error=f"Missing variables: {missing_vars}"
            ))
            all_passed = False
        else:
            self.record_result(TestResult(
                test_name="environment_variables",
                phase="phase1",
                status="PASS",
                duration=time.time() - start
            ))
        
        return all_passed
    
    def verify_connectivity(self) -> bool:
        """Phase 1.1: Test service connectivity"""
        logger.info("\n1.1 Testing service connectivity...")
        all_passed = True
        
        # Test database
        start = time.time()
        try:
            from scripts.db import DatabaseManager
            db = DatabaseManager()
            logger.info("✅ Database connection successful")
            self.record_result(TestResult(
                test_name="database_connectivity",
                phase="phase1",
                status="PASS",
                duration=time.time() - start
            ))
        except Exception as e:
            self.record_result(TestResult(
                test_name="database_connectivity",
                phase="phase1",
                status="FAIL",
                duration=time.time() - start,
                error=str(e)
            ))
            all_passed = False
        
        # Test Redis
        start = time.time()
        try:
            from scripts.cache import get_redis_manager
            redis = get_redis_manager()
            redis.get_client().ping()
            logger.info("✅ Redis connection successful")
            self.record_result(TestResult(
                test_name="redis_connectivity",
                phase="phase1",
                status="PASS",
                duration=time.time() - start
            ))
        except Exception as e:
            self.record_result(TestResult(
                test_name="redis_connectivity",
                phase="phase1",
                status="FAIL",
                duration=time.time() - start,
                error=str(e)
            ))
            all_passed = False
        
        # Test S3
        start = time.time()
        try:
            from scripts.s3_storage import S3StorageManager
            s3 = S3StorageManager()
            # Just initialize, don't actually access S3
            logger.info("✅ S3 client initialized")
            self.record_result(TestResult(
                test_name="s3_initialization",
                phase="phase1",
                status="PASS",
                duration=time.time() - start
            ))
        except Exception as e:
            self.record_result(TestResult(
                test_name="s3_initialization",
                phase="phase1",
                status="FAIL",
                duration=time.time() - start,
                error=str(e)
            ))
            all_passed = False
        
        return all_passed
    
    def verify_imports(self) -> bool:
        """Phase 1.2: Test core module imports"""
        logger.info("\n1.2 Testing core module imports...")
        
        modules = [
            "scripts.celery_app",
            "scripts.pdf_tasks",
            "scripts.db",
            "scripts.cache",
            "scripts.config",
            "scripts.models",
            "scripts.graph_service",
            "scripts.entity_service",
            "scripts.chunking_utils",
            "scripts.ocr_extraction",
            "scripts.textract_utils",
            "scripts.s3_storage",
            "scripts.logging_config"
        ]
        
        all_passed = True
        for module in modules:
            start = time.time()
            try:
                __import__(module)
                self.record_result(TestResult(
                    test_name=f"import_{module}",
                    phase="phase1",
                    status="PASS",
                    duration=time.time() - start
                ))
            except Exception as e:
                self.record_result(TestResult(
                    test_name=f"import_{module}",
                    phase="phase1",
                    status="FAIL",
                    duration=time.time() - start,
                    error=str(e)
                ))
                all_passed = False
        
        return all_passed
    
    # Phase 2: Core Functionality Testing
    def test_single_document(self, test_file: str = None) -> bool:
        """Phase 2.1: Single document end-to-end test"""
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 2: Core Functionality Testing")
        logger.info("=" * 60)
        
        logger.info("\n2.1 Single document end-to-end test...")
        
        # For now, simulate the test
        start = time.time()
        
        # In real implementation, would:
        # 1. Upload document to S3
        # 2. Trigger processing
        # 3. Monitor pipeline stages
        # 4. Verify completion
        
        self.record_result(TestResult(
            test_name="single_document_e2e",
            phase="phase2",
            status="SKIP",
            duration=time.time() - start,
            details={"reason": "Requires actual document and running system"}
        ))
        
        return True
    
    def test_pipeline_stages(self) -> bool:
        """Phase 2.2: Test individual pipeline stages"""
        logger.info("\n2.2 Testing pipeline stages independently...")
        
        stages = [
            "ocr_processing",
            "text_chunking",
            "entity_extraction",
            "entity_resolution",
            "relationship_building",
            "pipeline_finalization"
        ]
        
        all_passed = True
        for stage in stages:
            start = time.time()
            
            # In real implementation, would test each stage
            self.record_result(TestResult(
                test_name=f"stage_{stage}",
                phase="phase2",
                status="SKIP",
                duration=time.time() - start,
                details={"reason": "Requires mock data and stage isolation"}
            ))
        
        return all_passed
    
    # Phase 3: Batch Processing Verification
    def test_batch_processing(self) -> bool:
        """Phase 3.1: Sequential batch processing"""
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 3: Batch Processing Verification")
        logger.info("=" * 60)
        
        batch_sizes = [5, 10, 25]
        
        for size in batch_sizes:
            start = time.time()
            logger.info(f"\n3.1 Testing sequential batch of {size} documents...")
            
            # Simulate batch processing
            self.record_result(TestResult(
                test_name=f"sequential_batch_{size}",
                phase="phase3",
                status="SKIP",
                duration=time.time() - start,
                details={"batch_size": size, "reason": "Requires test documents"}
            ))
        
        return True
    
    def test_concurrent_processing(self) -> bool:
        """Phase 3.2: Concurrent processing test"""
        logger.info("\n3.2 Testing concurrent processing...")
        
        concurrent_counts = [3, 5, 10]
        
        for count in concurrent_counts:
            start = time.time()
            logger.info(f"Testing {count} concurrent documents...")
            
            # Simulate concurrent processing
            self.record_result(TestResult(
                test_name=f"concurrent_{count}",
                phase="phase3",
                status="SKIP",
                duration=time.time() - start,
                details={"concurrent_count": count, "reason": "Requires test documents"}
            ))
        
        return True
    
    # Phase 4: Performance Testing
    def test_performance_baseline(self) -> bool:
        """Phase 4.1: Establish performance baseline"""
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 4: Performance & Scalability Testing")
        logger.info("=" * 60)
        
        logger.info("\n4.1 Measuring performance baseline...")
        
        # Test basic operations
        metrics = {}
        
        # Database query performance
        start = time.time()
        try:
            from scripts.db import DatabaseManager
            db = DatabaseManager()
            # Would run test queries
            query_time = time.time() - start
            metrics["db_connection"] = query_time
            logger.info(f"Database connection: {query_time:.3f}s")
        except:
            metrics["db_connection"] = None
        
        # Redis performance
        start = time.time()
        try:
            from scripts.cache import get_redis_manager
            redis = get_redis_manager()
            test_key = f"perf_test_{int(time.time())}"
            # Use RedisManager methods properly
            client = redis.get_client()
            client.setex(test_key, 60, json.dumps({"test": "data"}))
            client.get(test_key)
            client.delete(test_key)
            cache_time = time.time() - start
            metrics["cache_operations"] = cache_time
            logger.info(f"Cache operations: {cache_time:.3f}s")
        except Exception as e:
            logger.debug(f"Cache test error: {e}")
            metrics["cache_operations"] = None
        
        self.record_result(TestResult(
            test_name="performance_baseline",
            phase="phase4",
            status="PASS" if all(v is not None for v in metrics.values()) else "PARTIAL",
            duration=sum(v for v in metrics.values() if v),
            details=metrics
        ))
        
        return True
    
    # Phase 5: Data Integrity Testing
    def test_data_integrity(self) -> bool:
        """Phase 5.1: Data validation tests"""
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 5: Data Integrity & Quality Testing")
        logger.info("=" * 60)
        
        logger.info("\n5.1 Testing data validation...")
        
        # Test Pydantic model validation
        start = time.time()
        try:
            from scripts.models import SourceDocumentMinimal
            from uuid import uuid4
            
            # Valid document
            doc = SourceDocumentMinimal(
                document_uuid=uuid4(),
                project_uuid=uuid4(),
                file_name="test.pdf",
                file_size=1000
            )
            
            # Test invalid data
            try:
                invalid_doc = SourceDocumentMinimal(
                    document_uuid="not-a-uuid",
                    project_uuid=uuid4(),
                    file_name="test.pdf"
                )
                validation_works = False
            except:
                validation_works = True
            
            self.record_result(TestResult(
                test_name="pydantic_validation",
                phase="phase5",
                status="PASS" if validation_works else "FAIL",
                duration=time.time() - start
            ))
        except Exception as e:
            self.record_result(TestResult(
                test_name="pydantic_validation",
                phase="phase5",
                status="FAIL",
                duration=time.time() - start,
                error=str(e)
            ))
        
        return True
    
    # Phase 6: Operational Readiness
    def test_operational_readiness(self) -> bool:
        """Phase 6.1: Monitoring & observability"""
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 6: Operational Readiness")
        logger.info("=" * 60)
        
        logger.info("\n6.1 Testing monitoring & observability...")
        
        # Check if monitoring tools exist
        start = time.time()
        monitoring_files = [
            "scripts/cli/monitor.py",
            "scripts/logging_config.py"
        ]
        
        all_exist = all(os.path.exists(f) for f in monitoring_files)
        
        self.record_result(TestResult(
            test_name="monitoring_tools",
            phase="phase6",
            status="PASS" if all_exist else "FAIL",
            duration=time.time() - start,
            details={"files_checked": monitoring_files}
        ))
        
        return all_exist
    
    def generate_report(self):
        """Generate final verification report"""
        logger.info("\n" + "=" * 60)
        logger.info("PRODUCTION READINESS VERIFICATION REPORT")
        logger.info("=" * 60)
        
        # Calculate statistics
        total_tests = len(self.results)
        passed = len([r for r in self.results if r.status == "PASS"])
        failed = len([r for r in self.results if r.status == "FAIL"])
        skipped = len([r for r in self.results if r.status == "SKIP"])
        
        pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0
        
        logger.info(f"\nTotal Tests: {total_tests}")
        logger.info(f"Passed: {passed} ({pass_rate:.1f}%)")
        logger.info(f"Failed: {failed}")
        logger.info(f"Skipped: {skipped}")
        
        # Phase breakdown
        logger.info("\nPhase Breakdown:")
        for phase in range(1, 7):
            phase_results = [r for r in self.results if r.phase == f"phase{phase}"]
            if phase_results:
                phase_passed = len([r for r in phase_results if r.status == "PASS"])
                logger.info(f"  Phase {phase}: {phase_passed}/{len(phase_results)} passed")
        
        # Critical failures
        critical_failures = [r for r in self.results if r.status == "FAIL" and r.phase in ["phase1", "phase2"]]
        if critical_failures:
            logger.warning("\nCRITICAL FAILURES:")
            for failure in critical_failures:
                logger.warning(f"  - {failure.test_name}: {failure.error}")
        
        # Save final report
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_duration": time.time() - self.start_time,
            "summary": {
                "total_tests": total_tests,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pass_rate": pass_rate
            },
            "results": [asdict(r) for r in self.results]
        }
        
        report_file = self.results_dir / f"final_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"\nFinal report saved to: {report_file}")
        
        # Overall assessment
        if pass_rate >= 90 and not critical_failures:
            logger.info("\n✅ PRODUCTION READINESS: PASS")
        elif pass_rate >= 70:
            logger.warning("\n⚠️ PRODUCTION READINESS: CONDITIONAL PASS (address failures)")
        else:
            logger.error("\n❌ PRODUCTION READINESS: FAIL")
        
        return report

def main():
    """Run production readiness verification"""
    verifier = ProductionVerifier()
    
    try:
        # Phase 1: Environment & Dependencies
        verifier.verify_environment()
        verifier.verify_connectivity()
        verifier.verify_imports()
        verifier.save_results(1)
        
        # Phase 2: Core Functionality
        verifier.test_single_document()
        verifier.test_pipeline_stages()
        verifier.save_results(2)
        
        # Phase 3: Batch Processing
        verifier.test_batch_processing()
        verifier.test_concurrent_processing()
        verifier.save_results(3)
        
        # Phase 4: Performance
        verifier.test_performance_baseline()
        verifier.save_results(4)
        
        # Phase 5: Data Integrity
        verifier.test_data_integrity()
        verifier.save_results(5)
        
        # Phase 6: Operational Readiness
        verifier.test_operational_readiness()
        verifier.save_results(6)
        
    except KeyboardInterrupt:
        logger.info("\nVerification interrupted by user")
    except Exception as e:
        logger.error(f"Verification error: {e}")
    finally:
        # Generate final report
        verifier.generate_report()

if __name__ == "__main__":
    main()