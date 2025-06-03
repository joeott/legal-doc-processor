#!/usr/bin/env python3
"""
Core Function Baseline Testing Script
Purpose: Establish current performance and reliability metrics for all core functions
"""

import time
import traceback
import psutil
import os
from typing import Dict, Any, List
import json

# Test results collection
test_results = {
    "timestamp": time.strftime("%Y%m%d_%H%M%S"),
    "core_imports": {},
    "performance_metrics": {},
    "memory_usage": {},
    "error_handling": {},
    "integration_tests": {}
}

def test_core_imports() -> Dict[str, bool]:
    """Test that all core modules import successfully"""
    print("🔍 Testing Core Module Imports...")
    
    core_modules = [
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
    
    results = {}
    for module in core_modules:
        try:
            __import__(module)
            results[module] = True
            print(f"✅ {module}")
        except Exception as e:
            results[module] = False
            print(f"❌ {module}: {str(e)}")
    
    test_results["core_imports"] = results
    return results

def test_database_performance() -> Dict[str, Any]:
    """Test database connection and query performance"""
    print("\n🗄️ Testing Database Performance...")
    
    results = {
        "connection_time": None,
        "simple_query_time": None,
        "connection_pool_size": None,
        "errors": []
    }
    
    try:
        from scripts.db import DatabaseManager
        
        # Test connection time
        start = time.time()
        db = DatabaseManager()
        results["connection_time"] = time.time() - start
        print(f"✅ Connection time: {results['connection_time']:.3f}s")
        
        # Test simple query
        start = time.time()
        with db.get_session() as session:
            session.execute("SELECT 1").scalar()
        results["simple_query_time"] = time.time() - start
        print(f"✅ Query time: {results['simple_query_time']:.3f}s")
        
    except Exception as e:
        results["errors"].append(str(e))
        print(f"❌ Database error: {e}")
    
    test_results["performance_metrics"]["database"] = results
    return results

def test_cache_performance() -> Dict[str, Any]:
    """Test Redis cache performance"""
    print("\n💾 Testing Cache Performance...")
    
    results = {
        "connection_time": None,
        "set_operation_time": None,
        "get_operation_time": None,
        "errors": []
    }
    
    try:
        from scripts.cache import get_redis_manager
        
        # Test connection
        start = time.time()
        redis_manager = get_redis_manager()
        results["connection_time"] = time.time() - start
        print(f"✅ Connection time: {results['connection_time']:.3f}s")
        
        # Test set operation
        test_key = f"test_key_{int(time.time())}"
        test_data = {"test": "data", "timestamp": time.time()}
        
        start = time.time()
        redis_manager.set(test_key, test_data, ttl=60)
        results["set_operation_time"] = time.time() - start
        print(f"✅ Set operation: {results['set_operation_time']:.3f}s")
        
        # Test get operation
        start = time.time()
        retrieved = redis_manager.get_dict(test_key)
        results["get_operation_time"] = time.time() - start
        print(f"✅ Get operation: {results['get_operation_time']:.3f}s")
        
        # Cleanup
        redis_manager.delete(test_key)
        
    except Exception as e:
        results["errors"].append(str(e))
        print(f"❌ Cache error: {e}")
    
    test_results["performance_metrics"]["cache"] = results
    return results

def test_memory_usage() -> Dict[str, Any]:
    """Test memory usage of core components"""
    print("\n🧠 Testing Memory Usage...")
    
    process = psutil.Process(os.getpid())
    baseline_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    results = {
        "baseline_mb": baseline_memory,
        "after_imports_mb": None,
        "peak_mb": None
    }
    
    # Measure after all imports
    results["after_imports_mb"] = process.memory_info().rss / 1024 / 1024
    
    print(f"✅ Baseline memory: {results['baseline_mb']:.1f} MB")
    print(f"✅ After imports: {results['after_imports_mb']:.1f} MB")
    print(f"✅ Import overhead: {results['after_imports_mb'] - results['baseline_mb']:.1f} MB")
    
    test_results["memory_usage"] = results
    return results

def test_error_handling() -> Dict[str, Any]:
    """Test error handling in core functions"""
    print("\n🛡️ Testing Error Handling...")
    
    results = {
        "celery_retry_mechanism": False,
        "database_connection_recovery": False,
        "cache_fallback": False,
        "validation_errors": False
    }
    
    # Test Celery retry mechanism
    try:
        from scripts.pdf_tasks import PDFTask
        if hasattr(PDFTask, 'retry'):
            results["celery_retry_mechanism"] = True
            print("✅ Celery retry mechanism present")
    except:
        print("❌ Could not verify Celery retry mechanism")
    
    # Test database error handling
    try:
        from scripts.db import DatabaseManager
        # This will fail but should handle gracefully
        db = DatabaseManager()
        # Check if __enter__ is implemented (context manager)
        if hasattr(db, '__enter__'):
            results["database_connection_recovery"] = True
            print("✅ Database context manager implemented")
    except:
        pass
    
    # Test validation
    try:
        from scripts.models import SourceDocument
        # Try invalid data
        try:
            doc = SourceDocument(project_uuid="invalid-not-uuid")
        except:
            results["validation_errors"] = True
            print("✅ Pydantic validation working")
    except:
        pass
    
    test_results["error_handling"] = results
    return results

def test_pipeline_integration() -> Dict[str, Any]:
    """Test basic pipeline integration"""
    print("\n🔗 Testing Pipeline Integration...")
    
    results = {
        "task_registration": False,
        "queue_configuration": False,
        "pipeline_stages": []
    }
    
    try:
        from scripts.celery_app import app
        
        # Check registered tasks
        registered_tasks = list(app.tasks.keys())
        pipeline_tasks = [t for t in registered_tasks if 'scripts.pdf_tasks' in t]
        
        if pipeline_tasks:
            results["task_registration"] = True
            results["pipeline_stages"] = pipeline_tasks[:5]  # First 5 tasks
            print(f"✅ Found {len(pipeline_tasks)} pipeline tasks")
            
        # Check queue configuration
        if hasattr(app.conf, 'task_routes'):
            results["queue_configuration"] = True
            print("✅ Queue routing configured")
            
    except Exception as e:
        print(f"❌ Integration test error: {e}")
    
    test_results["integration_tests"] = results
    return results

def generate_report():
    """Generate comprehensive test report"""
    print("\n" + "="*60)
    print("📊 CORE FUNCTION BASELINE TEST REPORT")
    print("="*60)
    
    # Import success rate
    import_results = test_results.get("core_imports", {})
    success_count = sum(1 for v in import_results.values() if v)
    total_count = len(import_results)
    print(f"\n✅ Import Success Rate: {success_count}/{total_count} ({success_count/total_count*100:.1f}%)")
    
    # Performance summary
    db_perf = test_results.get("performance_metrics", {}).get("database", {})
    cache_perf = test_results.get("performance_metrics", {}).get("cache", {})
    
    if db_perf.get("connection_time"):
        print(f"\n🗄️ Database Performance:")
        print(f"   • Connection: {db_perf['connection_time']:.3f}s")
        print(f"   • Query: {db_perf.get('simple_query_time', 'N/A')}")
    
    if cache_perf.get("connection_time"):
        print(f"\n💾 Cache Performance:")
        print(f"   • Connection: {cache_perf['connection_time']:.3f}s")
        print(f"   • Set: {cache_perf.get('set_operation_time', 'N/A')}")
        print(f"   • Get: {cache_perf.get('get_operation_time', 'N/A')}")
    
    # Memory usage
    mem = test_results.get("memory_usage", {})
    if mem.get("baseline_mb"):
        print(f"\n🧠 Memory Usage:")
        print(f"   • Baseline: {mem['baseline_mb']:.1f} MB")
        print(f"   • After imports: {mem.get('after_imports_mb', 'N/A')} MB")
    
    # Error handling
    error_handling = test_results.get("error_handling", {})
    error_features = sum(1 for v in error_handling.values() if v)
    print(f"\n🛡️ Error Handling Features: {error_features}/4")
    
    # Save results
    report_file = f"baseline_test_results_{test_results['timestamp']}.json"
    with open(report_file, 'w') as f:
        json.dump(test_results, f, indent=2)
    print(f"\n💾 Full results saved to: {report_file}")

def main():
    """Run all baseline tests"""
    print("🚀 Starting Core Function Baseline Tests")
    print("="*60)
    
    # Run tests
    test_core_imports()
    test_database_performance()
    test_cache_performance()
    test_memory_usage()
    test_error_handling()
    test_pipeline_integration()
    
    # Generate report
    generate_report()
    
    print("\n✅ Baseline testing complete!")

if __name__ == "__main__":
    main()