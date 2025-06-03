#!/usr/bin/env python3
"""
Automated verification script for import fixes.
Tests the import process progressively from single document to full batch.
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager


class ImportVerificationTester:
    """Test and verify import fixes"""
    
    def __init__(self):
        self.db_manager = SupabaseManager()
        self.test_results = []
    
    def run_verification_tests(self):
        """Run comprehensive verification tests"""
        print("🔍 Starting Import Verification Tests")
        print("="*60)
        
        # Phase 1: Database Schema Verification
        self._test_database_schema()
        
        # Phase 2: Project Association Test
        self._test_project_association()
        
        # Phase 3: Single Document Test (if manifest exists)
        manifest_path = "input_manifest.json"
        if os.path.exists(manifest_path):
            self._test_single_document_import(manifest_path)
        
        # Print results
        self._print_test_results()
    
    def _test_database_schema(self):
        """Test database schema compatibility"""
        print("\n📋 Testing Database Schema...")
        
        try:
            # Test projects table
            result = self.db_manager.client.table('projects')\
                .select('id, name, projectId')\
                .limit(1)\
                .execute()
            
            print("  ✓ Projects table accessible")
            
            # Test source_documents table
            result = self.db_manager.client.table('source_documents')\
                .select('id, project_fk_id, project_uuid, document_uuid')\
                .limit(1)\
                .execute()
            
            print("  ✓ Source documents table accessible")
            
            # Test import_sessions table
            result = self.db_manager.client.table('import_sessions')\
                .select('id, project_id, case_name')\
                .limit(1)\
                .execute()
            
            print("  ✓ Import sessions table accessible")
            
            # Test processing_costs table
            result = self.db_manager.client.table('processing_costs')\
                .select('id, import_session_id, document_id')\
                .limit(1)\
                .execute()
            
            print("  ✓ Processing costs table accessible")
            
            self.test_results.append({
                'test': 'Database Schema',
                'status': 'PASS',
                'details': 'All required tables accessible'
            })
            
        except Exception as e:
            print(f"  ❌ Database schema test failed: {e}")
            self.test_results.append({
                'test': 'Database Schema',
                'status': 'FAIL',
                'details': str(e)
            })
    
    def _test_project_association(self):
        """Test project creation and association logic"""
        print("\n🔗 Testing Project Association...")
        
        try:
            # Test finding existing projects
            result = self.db_manager.client.table('projects')\
                .select('id, name, projectId')\
                .ilike('name', '%Input%')\
                .execute()
            
            if result.data:
                project = result.data[0]
                print(f"  ✓ Found existing Input project: {project['name']} (ID: {project['id']})")
                
                if project['projectId']:
                    print(f"  ✓ Project has UUID: {project['projectId']}")
                else:
                    print("  ⚠️  Project missing UUID (will be generated)")
                
                self.test_results.append({
                    'test': 'Project Association',
                    'status': 'PASS',
                    'details': f"Project exists with ID {project['id']}"
                })
            else:
                print("  ℹ️  No existing Input project found (will be created)")
                self.test_results.append({
                    'test': 'Project Association',
                    'status': 'PASS',
                    'details': 'Ready to create new project'
                })
                
        except Exception as e:
            print(f"  ❌ Project association test failed: {e}")
            self.test_results.append({
                'test': 'Project Association',
                'status': 'FAIL',
                'details': str(e)
            })
    
    def _test_single_document_import(self, manifest_path: str):
        """Test import process with single document"""
        print("\n📄 Testing Single Document Import...")
        
        try:
            # Load manifest
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            total_files = len(manifest['files'])
            print(f"  📊 Manifest loaded: {total_files} files")
            
            # Create test manifest with just first file
            test_manifest = manifest.copy()
            test_manifest['files'] = [manifest['files'][0]]
            test_manifest['metadata']['case_name'] = 'Test Single Document Import'
            
            test_manifest_path = 'test_single_manifest.json'
            with open(test_manifest_path, 'w') as f:
                json.dump(test_manifest, f, indent=2)
            
            print(f"  ✓ Created test manifest: {test_manifest['files'][0]['filename']}")
            
            # Test dry run
            import subprocess
            result = subprocess.run([
                'python', 'scripts/import_from_manifest_fixed.py',
                test_manifest_path, '--dry-run', '--workers', '1', '--batch-size', '1'
            ], capture_output=True, text=True, cwd=os.getcwd())
            
            if result.returncode == 0:
                print("  ✓ Dry run successful")
                
                # Check for key success indicators
                if "Using existing project" in result.stdout or "Created new project" in result.stdout:
                    print("  ✓ Project association working")
                
                if "Created import session" in result.stdout:
                    print("  ✓ Import session creation working")
                
                if "DRY RUN" in result.stdout:
                    print("  ✓ Dry run mode working")
                
                self.test_results.append({
                    'test': 'Single Document Import (Dry Run)',
                    'status': 'PASS',
                    'details': 'All components working correctly'
                })
            else:
                print(f"  ❌ Dry run failed: {result.stderr}")
                self.test_results.append({
                    'test': 'Single Document Import (Dry Run)',
                    'status': 'FAIL',
                    'details': result.stderr
                })
            
            # Clean up test file
            if os.path.exists(test_manifest_path):
                os.remove(test_manifest_path)
                
        except Exception as e:
            print(f"  ❌ Single document import test failed: {e}")
            self.test_results.append({
                'test': 'Single Document Import',
                'status': 'FAIL',
                'details': str(e)
            })
    
    def _print_test_results(self):
        """Print comprehensive test results"""
        print("\n" + "="*60)
        print("🧪 VERIFICATION TEST RESULTS")
        print("="*60)
        
        passed = 0
        failed = 0
        
        for result in self.test_results:
            status_emoji = "✅" if result['status'] == 'PASS' else "❌"
            print(f"{status_emoji} {result['test']}: {result['status']}")
            print(f"   {result['details']}")
            
            if result['status'] == 'PASS':
                passed += 1
            else:
                failed += 1
        
        print(f"\n📈 Summary: {passed} passed, {failed} failed")
        
        if failed == 0:
            print("\n🎉 All tests passed! Import system is ready.")
            print("\n📋 Next Steps:")
            print("1. Run single document test:")
            print("   python scripts/import_from_manifest_fixed.py input_manifest.json --workers 1 --batch-size 1")
            print("2. Monitor with:")
            print("   python scripts/standalone_pipeline_monitor.py")
            print("3. Check results with:")
            print("   python scripts/check_import_completion.py --recent 1")
        else:
            print(f"\n⚠️  {failed} tests failed. Please fix issues before proceeding.")
        
        return failed == 0


def verify_celery_workers():
    """Check if Celery workers are running"""
    print("\n⚙️  Checking Celery Workers...")
    
    try:
        import subprocess
        result = subprocess.run([
            'celery', '-A', 'scripts.celery_app', 'inspect', 'active'
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            if "ERROR" not in result.stdout and "FAILED" not in result.stdout:
                print("  ✅ Celery workers are running")
                return True
            else:
                print("  ⚠️  Celery workers may have issues")
                return False
        else:
            print("  ❌ Celery workers not responding")
            return False
            
    except subprocess.TimeoutExpired:
        print("  ⏱️  Celery check timed out (workers may be slow)")
        return False
    except Exception as e:
        print(f"  ❌ Error checking Celery: {e}")
        return False


def main():
    """Main verification entry point"""
    print("🚀 Import System Verification Tool")
    print("This tool verifies the import fixes before processing documents.")
    print()
    
    # Check Celery workers
    celery_ok = verify_celery_workers()
    
    if not celery_ok:
        print("\n⚠️  Warning: Celery workers not detected.")
        print("Start workers with:")
        print("celery -A scripts.celery_app worker --loglevel=info --concurrency=2 --queues=default,ocr,text,entity,graph,embeddings")
        print()
    
    # Run verification tests
    tester = ImportVerificationTester()
    success = tester.run_verification_tests()
    
    if success and celery_ok:
        print("\n🟢 System ready for import!")
    elif success:
        print("\n🟡 System ready, but start Celery workers first!")
    else:
        print("\n🔴 System not ready - fix errors before importing!")
    
    return 0 if success else 1


if __name__ == '__main__':
    exit(main())