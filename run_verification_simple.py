#!/usr/bin/env python3
"""
Simple verification runner that shows results without pytest dependency.
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    print("=" * 60)
    print("PRODUCTION VERIFICATION REPORT")
    print("=" * 60)
    print(f"Date: {datetime.now().isoformat()}")
    print(f"Deployment Stage: {os.getenv('DEPLOYMENT_STAGE', '1')} - Cloud-only (OpenAI/Textract)")
    
    # Track results
    results = {
        "timestamp": datetime.now().isoformat(),
        "checks": {},
        "summary": {
            "total": 0,
            "passed": 0,
            "failed": 0
        }
    }
    
    print("\n### Phase 1: Environment Verification")
    
    # ENV-001: Check environment variables
    print("\n[ENV-001] Environment Variables:")
    env_vars = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "S3_PRIMARY_DOCUMENT_BUCKET": os.getenv("S3_PRIMARY_DOCUMENT_BUCKET"),
        "DATABASE_URL": os.getenv("DATABASE_URL")
    }
    
    missing = []
    for var, value in env_vars.items():
        if value:
            print(f"  ✅ {var} is set")
        else:
            print(f"  ❌ {var} is NOT set")
            missing.append(var)
    
    results["checks"]["ENV-001"] = {
        "name": "Environment Variables",
        "passed": len(missing) == 0,
        "details": f"{len(env_vars) - len(missing)}/{len(env_vars)} variables set"
    }
    results["summary"]["total"] += 1
    if len(missing) == 0:
        results["summary"]["passed"] += 1
    else:
        results["summary"]["failed"] += 1
    
    # ENV-002: Redis connection
    print("\n[ENV-002] Redis Connection:")
    try:
        from scripts.cache import get_redis_manager
        redis = get_redis_manager()
        if redis.is_available():
            print("  ✅ Redis connection successful")
            # Test operations
            test_key = "verify_test"
            redis.set_cached(test_key, "test_value", ttl=10)
            value = redis.get_cached(test_key)
            if value == "test_value":
                print("  ✅ Redis operations working")
                results["checks"]["ENV-002"] = {"name": "Redis Connection", "passed": True}
                results["summary"]["passed"] += 1
            else:
                print("  ❌ Redis operations failed")
                results["checks"]["ENV-002"] = {"name": "Redis Connection", "passed": False, "error": "Operations failed"}
                results["summary"]["failed"] += 1
        else:
            print("  ❌ Redis not available")
            results["checks"]["ENV-002"] = {"name": "Redis Connection", "passed": False, "error": "Not available"}
            results["summary"]["failed"] += 1
    except Exception as e:
        print(f"  ❌ Redis error: {e}")
        results["checks"]["ENV-002"] = {"name": "Redis Connection", "passed": False, "error": str(e)}
        results["summary"]["failed"] += 1
    results["summary"]["total"] += 1
    
    # ENV-003: Database connection
    print("\n[ENV-003] Database Connection:")
    try:
        from scripts.db import DatabaseManager
        from sqlalchemy import text
        db = DatabaseManager(validate_conformance=False)
        for session in db.get_session():
            result = session.execute(text("SELECT 1")).fetchone()
            if result and result[0] == 1:
                print("  ✅ Database connection successful")
                results["checks"]["ENV-003"] = {"name": "Database Connection", "passed": True}
                results["summary"]["passed"] += 1
            else:
                print("  ❌ Database query failed")
                results["checks"]["ENV-003"] = {"name": "Database Connection", "passed": False}
                results["summary"]["failed"] += 1
            break
    except Exception as e:
        print(f"  ❌ Database error: {e}")
        results["checks"]["ENV-003"] = {"name": "Database Connection", "passed": False, "error": str(e)}
        results["summary"]["failed"] += 1
    results["summary"]["total"] += 1
    
    # ENV-004: S3 access
    print("\n[ENV-004] S3 Access:")
    bucket = os.getenv("S3_PRIMARY_DOCUMENT_BUCKET")
    if bucket:
        try:
            import subprocess
            # Use head-bucket command
            cmd = f"aws s3api head-bucket --bucket {bucket} 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True)
            if result.returncode == 0:
                print(f"  ✅ S3 bucket '{bucket}' accessible")
                results["checks"]["ENV-004"] = {"name": "S3 Access", "passed": True, "bucket": bucket}
                results["summary"]["passed"] += 1
            else:
                print(f"  ❌ S3 bucket '{bucket}' not accessible")
                results["checks"]["ENV-004"] = {"name": "S3 Access", "passed": False, "bucket": bucket}
                results["summary"]["failed"] += 1
        except Exception as e:
            print(f"  ❌ S3 check error: {e}")
            results["checks"]["ENV-004"] = {"name": "S3 Access", "passed": False, "error": str(e)}
            results["summary"]["failed"] += 1
    else:
        print("  ❌ S3_PRIMARY_DOCUMENT_BUCKET not set")
        results["checks"]["ENV-004"] = {"name": "S3 Access", "passed": False, "error": "Bucket not configured"}
        results["summary"]["failed"] += 1
    results["summary"]["total"] += 1
    
    # ENV-005: Input documents
    print("\n[ENV-005] Input Documents:")
    input_dir = "/opt/legal-doc-processor/input_docs"
    if os.path.exists(input_dir):
        file_count = sum(1 for _ in Path(input_dir).rglob("*") if _.is_file())
        print(f"  ✅ Found {file_count} input documents")
        results["checks"]["ENV-005"] = {"name": "Input Documents", "passed": True, "count": file_count}
        results["summary"]["passed"] += 1
    else:
        print(f"  ❌ Input directory not found: {input_dir}")
        results["checks"]["ENV-005"] = {"name": "Input Documents", "passed": False, "error": "Directory not found"}
        results["summary"]["failed"] += 1
    results["summary"]["total"] += 1
    
    print("\n### Phase 2: Core System Components")
    
    # Test document discovery
    print("\n[DISC-001] Document Discovery:")
    try:
        from scripts.intake_service import DocumentIntakeService
        service = DocumentIntakeService()
        docs = service.discover_documents(input_dir, recursive=True)
        print(f"  ✅ Discovered {len(docs)} documents")
        if docs:
            print(f"  Sample: {docs[0].filename} ({docs[0].file_size_mb:.1f}MB)")
        results["checks"]["DISC-001"] = {"name": "Document Discovery", "passed": True, "count": len(docs)}
        results["summary"]["passed"] += 1
    except Exception as e:
        print(f"  ❌ Discovery error: {e}")
        results["checks"]["DISC-001"] = {"name": "Document Discovery", "passed": False, "error": str(e)}
        results["summary"]["failed"] += 1
    results["summary"]["total"] += 1
    
    # Test status tracking
    print("\n[STATUS-001] Status Tracking:")
    try:
        from scripts.status_manager import StatusManager
        manager = StatusManager()
        test_doc = f"verify-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        manager.track_document_status(test_doc, "ocr", "testing", {"test": True})
        status = manager.get_document_status(test_doc)
        if status:
            print(f"  ✅ Status tracking working")
            results["checks"]["STATUS-001"] = {"name": "Status Tracking", "passed": True}
            results["summary"]["passed"] += 1
        else:
            print("  ❌ Status tracking failed")
            results["checks"]["STATUS-001"] = {"name": "Status Tracking", "passed": False}
            results["summary"]["failed"] += 1
    except Exception as e:
        print(f"  ❌ Status tracking error: {e}")
        results["checks"]["STATUS-001"] = {"name": "Status Tracking", "passed": False, "error": str(e)}
        results["summary"]["failed"] += 1
    results["summary"]["total"] += 1
    
    # Check workers
    print("\n[SYS-001] Worker Status:")
    try:
        workers = manager.get_worker_health_status()
        if workers:
            print(f"  ✅ Found {len(workers)} active workers")
            results["checks"]["SYS-001"] = {"name": "Worker Status", "passed": True, "count": len(workers)}
            results["summary"]["passed"] += 1
        else:
            print("  ⚠️  No active workers (start with: celery -A scripts.celery_app worker)")
            results["checks"]["SYS-001"] = {"name": "Worker Status", "passed": False, "warning": "No workers"}
            results["summary"]["failed"] += 1
    except Exception as e:
        print(f"  ❌ Worker check error: {e}")
        results["checks"]["SYS-001"] = {"name": "Worker Status", "passed": False, "error": str(e)}
        results["summary"]["failed"] += 1
    results["summary"]["total"] += 1
    
    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total Checks: {results['summary']['total']}")
    print(f"Passed: {results['summary']['passed']}")
    print(f"Failed: {results['summary']['failed']}")
    success_rate = (results['summary']['passed'] / results['summary']['total'] * 100) if results['summary']['total'] > 0 else 0
    print(f"Success Rate: {success_rate:.1f}%")
    
    # System status
    critical_checks = ["ENV-001", "ENV-002", "ENV-003", "ENV-004", "ENV-005"]
    critical_passed = all(results["checks"].get(check, {}).get("passed", False) for check in critical_checks)
    
    if critical_passed and success_rate >= 80:
        print("\n🎯 System Status: PRODUCTION READY")
    elif critical_passed:
        print("\n⚠️  System Status: PARTIALLY READY (non-critical issues)")
    else:
        print("\n❌ System Status: NOT READY (critical issues)")
    
    # Save report
    report_dir = Path("/opt/legal-doc-processor/monitoring/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"simple_verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n📄 Report saved to: {report_file}")
    
    print("=" * 60)
    
    return 0 if critical_passed else 1

if __name__ == "__main__":
    sys.exit(main())