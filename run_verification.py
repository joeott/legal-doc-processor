#!/usr/bin/env python3
"""
Production Verification Runner

Simple script to run the verification protocol from context_399
without requiring pytest. This script executes all verification
tests and provides a comprehensive report.

Usage:
    python run_verification.py              # Run all tests
    python run_verification.py --phase 1    # Run specific phase
    python run_verification.py --quick      # Run essential tests only
"""

import os
import sys
import argparse
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import test classes
from tests.verification.test_production_verification import (
    TestPreFlight,
    TestDocumentDiscovery,
    TestBatchProcessing,
    TestStatusTracking,
    TestValidationFramework,
    TestAuditLogging,
    TestProductionProcessing,
    TestPerformanceVerification,
    TestQualityVerification,
    TestSystemIntegration,
    TestFinalVerification,
    VerificationResult
)


class VerificationRunner:
    """Runs verification tests and collects results."""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.results = []
        self.phase_results = {}
        
    def log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(message)
    
    def run_test_method(self, test_instance, method_name: str) -> Tuple[bool, str, Dict]:
        """Run a single test method and capture results."""
        try:
            # Run the test
            method = getattr(test_instance, method_name)
            method()
            
            # Extract test ID from method name (e.g., test_ENV_001_... -> ENV-001)
            parts = method_name.split('_')
            if len(parts) >= 3 and parts[1].isupper():
                test_id = f"{parts[1]}-{parts[2]}"
            else:
                test_id = method_name
            
            return True, f"✅ {test_id}: Passed", {"test_id": test_id, "method": method_name}
            
        except AssertionError as e:
            # Test failed with assertion
            error_msg = str(e)
            return False, f"❌ {method_name}: {error_msg}", {"error": error_msg}
            
        except Exception as e:
            # Test failed with exception
            return False, f"❌ {method_name}: Exception - {str(e)}", {"exception": str(e)}
    
    def run_phase(self, phase_name: str, test_class, test_methods: List[str]) -> Dict[str, Any]:
        """Run all tests in a phase."""
        self.log(f"\n{'='*60}")
        self.log(f"Phase: {phase_name}")
        self.log(f"{'='*60}")
        
        phase_start = time.time()
        passed = 0
        failed = 0
        results = []
        
        # Create test instance
        test_instance = test_class()
        
        # Handle special case for TestProductionProcessing that needs fixtures
        if test_class == TestProductionProcessing:
            import tempfile
            import shutil
            temp_dir = tempfile.mkdtemp(prefix="verification_test_")
            
        for method_name in test_methods:
            if test_class == TestProductionProcessing and method_name == "test_PROD_001_small_batch_processing":
                # Special handling for test that needs temp directory
                try:
                    success, message, details = self.run_test_method(test_instance, method_name)
                    # Pass temp_dir as argument
                    method = getattr(test_instance, method_name)
                    method(temp_dir)
                    success = True
                    message = f"✅ PROD-001: Passed"
                    details = {"test_id": "PROD-001", "method": method_name}
                except Exception as e:
                    success = False
                    message = f"❌ PROD-001: {str(e)}"
                    details = {"error": str(e)}
            else:
                success, message, details = self.run_test_method(test_instance, method_name)
            
            self.log(f"  {message}")
            
            if success:
                passed += 1
            else:
                failed += 1
            
            results.append({
                "method": method_name,
                "success": success,
                "message": message,
                "details": details
            })
        
        # Cleanup temp directory if created
        if test_class == TestProductionProcessing:
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        phase_time = time.time() - phase_start
        
        phase_summary = {
            "phase": phase_name,
            "passed": passed,
            "failed": failed,
            "total": passed + failed,
            "duration_seconds": round(phase_time, 2),
            "results": results
        }
        
        self.log(f"\nPhase Summary: {passed}/{passed + failed} passed ({phase_time:.1f}s)")
        
        return phase_summary
    
    def run_all_phases(self) -> Dict[str, Any]:
        """Run all verification phases."""
        start_time = time.time()
        
        # Define all phases and their tests
        phases = [
            ("Pre-Flight Environment Checks", TestPreFlight, [
                "test_ENV_001_environment_variables",
                "test_ENV_002_redis_connection",
                "test_ENV_003_database_connection",
                "test_ENV_004_s3_access",
                "test_ENV_005_input_documents_exist"
            ]),
            ("Document Discovery and Intake", TestDocumentDiscovery, [
                "test_DISC_001_document_discovery",
                "test_DISC_002_document_deduplication",
                "test_VAL_001_document_integrity"
            ]),
            ("Batch Processing", TestBatchProcessing, [
                "test_BATCH_001_batch_creation",
                "test_BATCH_002_batch_manifest"
            ]),
            ("Status Tracking", TestStatusTracking, [
                "test_STATUS_001_document_status",
                "test_STATUS_002_batch_progress",
                "test_DASH_001_dashboard_data"
            ]),
            ("Validation Framework", TestValidationFramework, [
                "test_OCR_001_validation",
                "test_ENTITY_001_type_distribution"
            ]),
            ("Audit Logging", TestAuditLogging, [
                "test_LOG_001_audit_functionality",
                "test_LOG_002_directory_structure"
            ]),
            ("Production Processing", TestProductionProcessing, [
                "test_PROD_001_small_batch_processing",
                "test_PROD_002_campaign_monitoring"
            ]),
            ("Performance Verification", TestPerformanceVerification, [
                "test_PERF_001_throughput_measurement",
                "test_PERF_002_error_rates"
            ]),
            ("Quality Verification", TestQualityVerification, [
                "test_QUAL_001_ocr_quality",
                "test_QUAL_002_data_consistency"
            ]),
            ("System Integration", TestSystemIntegration, [
                "test_E2E_001_pipeline_flow",
                "test_SYS_001_worker_health"
            ])
        ]
        
        # Run each phase
        all_results = []
        total_passed = 0
        total_failed = 0
        
        for phase_name, test_class, test_methods in phases:
            phase_result = self.run_phase(phase_name, test_class, test_methods)
            all_results.append(phase_result)
            total_passed += phase_result["passed"]
            total_failed += phase_result["failed"]
        
        # Run final verification
        self.log(f"\n{'='*60}")
        self.log("Final Verification")
        self.log(f"{'='*60}")
        
        final_test = TestFinalVerification()
        try:
            final_test.test_FINAL_verification_summary()
            self.log("  ✅ Final verification summary generated")
        except Exception as e:
            self.log(f"  ❌ Final verification failed: {e}")
        
        total_time = time.time() - start_time
        
        # Create comprehensive report
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_duration_seconds": round(total_time, 2),
            "total_duration_minutes": round(total_time / 60, 1),
            "total_tests": total_passed + total_failed,
            "passed": total_passed,
            "failed": total_failed,
            "success_rate": round((total_passed / (total_passed + total_failed) * 100), 1) if (total_passed + total_failed) > 0 else 0,
            "phases": all_results,
            "system_ready": total_failed == 0
        }
        
        return report
    
    def run_quick_verification(self) -> Dict[str, Any]:
        """Run only essential verification tests."""
        self.log("\n🚀 Running Quick Verification (Essential Tests Only)")
        
        # Define essential tests
        essential_phases = [
            ("Environment Check", TestPreFlight, [
                "test_ENV_001_environment_variables",
                "test_ENV_002_redis_connection",
                "test_ENV_003_database_connection"
            ]),
            ("Document Discovery", TestDocumentDiscovery, [
                "test_DISC_001_document_discovery"
            ]),
            ("Core Systems", TestStatusTracking, [
                "test_STATUS_001_document_status"
            ])
        ]
        
        results = []
        for phase_name, test_class, test_methods in essential_phases:
            phase_result = self.run_phase(phase_name, test_class, test_methods)
            results.append(phase_result)
        
        return {
            "type": "quick_verification",
            "timestamp": datetime.now().isoformat(),
            "phases": results
        }
    
    def save_report(self, report: Dict[str, Any]):
        """Save verification report to file."""
        reports_dir = Path("/opt/legal-doc-processor/monitoring/reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = reports_dir / f"verification_report_{timestamp}.json"
        
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.log(f"\n📄 Report saved to: {report_file}")
        return report_file


def print_summary(report: Dict[str, Any]):
    """Print a summary of the verification results."""
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    print(f"Timestamp: {report['timestamp']}")
    print(f"Duration: {report.get('total_duration_minutes', 0):.1f} minutes")
    print(f"\nTest Results:")
    print(f"  Total Tests: {report.get('total_tests', 0)}")
    print(f"  Passed: {report.get('passed', 0)}")
    print(f"  Failed: {report.get('failed', 0)}")
    print(f"  Success Rate: {report.get('success_rate', 0):.1f}%")
    
    if report.get('failed', 0) > 0:
        print(f"\n⚠️  Failed Tests:")
        for phase in report.get('phases', []):
            if phase['failed'] > 0:
                print(f"\n  {phase['phase']}:")
                for result in phase['results']:
                    if not result['success']:
                        print(f"    - {result['message']}")
    
    print(f"\n🎯 System Status: {'PRODUCTION READY' if report.get('system_ready', False) else 'NOT READY'}")
    print("="*60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run production verification tests")
    parser.add_argument('--phase', type=int, help='Run specific phase (1-10)')
    parser.add_argument('--quick', action='store_true', help='Run essential tests only')
    parser.add_argument('--quiet', action='store_true', help='Minimize output')
    parser.add_argument('--no-save', action='store_true', help='Do not save report to file')
    
    args = parser.parse_args()
    
    # Create runner
    runner = VerificationRunner(verbose=not args.quiet)
    
    try:
        if args.quick:
            # Run quick verification
            report = runner.run_quick_verification()
        elif args.phase:
            # Run specific phase (not implemented for simplicity)
            print(f"Running phase {args.phase} not yet implemented. Running all phases instead.")
            report = runner.run_all_phases()
        else:
            # Run all phases
            report = runner.run_all_phases()
        
        # Save report
        if not args.no_save:
            runner.save_report(report)
        
        # Print summary
        print_summary(report)
        
        # Exit with appropriate code
        sys.exit(0 if report.get('system_ready', False) else 1)
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Verification interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Verification failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()