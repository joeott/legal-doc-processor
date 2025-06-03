#!/usr/bin/env python3
"""
End-to-End Testing Script for Celery Document Processing Pipeline
Tests documents from input directory through complete processing
"""
import os
import sys
import time
import json
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_submission import submit_document_to_celery
from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager, CacheKeys
from scripts.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, OPENAI_API_KEY

class ErrorLogger:
    """Structured error logging for debugging"""
    def __init__(self, log_file="celery_e2e_errors.log"):
        self.log_file = log_file
        self.errors = []
        
    def log_error(self, doc_id: str, doc_uuid: str, stage: str, error_type: str, details: str):
        """Log an error with full context"""
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "document_id": doc_id,
            "document_uuid": doc_uuid,
            "stage": stage,
            "error_type": error_type,
            "details": details,
            "stack_trace": traceback.format_exc() if sys.exc_info()[0] else None
        }
        self.errors.append(error_entry)
        
        # Write to file immediately
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(error_entry) + '\n')
        
        print(f"  ❌ ERROR logged: {error_type} at {stage}")

class CeleryE2ETester:
    """End-to-end testing for Celery document processing"""
    
    # Expected stage progression
    EXPECTED_STAGES = [
        'pending',
        'processing',
        'ocr_processing',
        'ocr_complete',
        'text_processing',
        'entity_extraction', 
        'entity_resolution',
        'graph_building',
        'completed'
    ]
    
    # Error states
    ERROR_STATES = [
        'ocr_failed',
        'text_failed',
        'entity_failed',
        'resolution_failed',
        'graph_failed'
    ]
    
    def __init__(self):
        self.db = SupabaseManager()
        self.redis_mgr = get_redis_manager()
        self.redis_client = self.redis_mgr.get_client() if self.redis_mgr else None
        self.error_logger = ErrorLogger()
        self.test_results = []
        self.input_dir = Path("/Users/josephott/Documents/phase_1_2_3_process_v5/input/Zwicky, Jessica/Investigations")
        
    def verify_prerequisites(self) -> bool:
        """Verify system is ready for testing"""
        print("\n🔍 Verifying Prerequisites...")
        checks_passed = True
        
        # Check Redis
        try:
            if self.redis_client and self.redis_client.ping():
                print("  ✅ Redis connected")
            else:
                print("  ❌ Redis not available")
                checks_passed = False
        except Exception as e:
            print(f"  ❌ Redis error: {e}")
            checks_passed = False
        
        # Check database
        try:
            result = self.db.client.table('source_documents').select('id').limit(1).execute()
            print("  ✅ Database connected")
        except Exception as e:
            print(f"  ❌ Database error: {e}")
            checks_passed = False
        
        # Check AWS credentials
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            print("  ✅ AWS credentials configured")
        else:
            print("  ❌ AWS credentials missing (required for Textract)")
            checks_passed = False
        
        # Check OpenAI
        if OPENAI_API_KEY:
            print("  ✅ OpenAI API key configured")
        else:
            print("  ❌ OpenAI API key missing (required for entity extraction)")
            checks_passed = False
        
        # Check input directory
        if self.input_dir.exists():
            doc_count = len(list(self.input_dir.glob('*.*')))
            print(f"  ✅ Input directory found with {doc_count} files")
        else:
            print(f"  ❌ Input directory not found: {self.input_dir}")
            checks_passed = False
            
        return checks_passed
    
    def test_document(self, file_path: Path) -> Dict:
        """Test a single document through the pipeline"""
        result = {
            'file': file_path.name,
            'file_type': file_path.suffix.lower(),
            'start_time': datetime.now(),
            'stages_completed': [],
            'errors': [],
            'success': False,
            'final_status': None,
            'processing_time': None
        }
        
        try:
            # Step 1: Create document entry
            print(f"\n  📄 Submitting {file_path.name}...")
            
            # Get or create project
            project_id_sql, project_uuid = self.db.get_or_create_project(
                "test-celery-e2e", 
                "Celery E2E Test Project"
            )
            
            # Create source document entry
            doc_id, doc_uuid = self.db.create_source_document_entry(
                project_fk_id=project_id_sql,
                project_uuid=project_uuid,
                original_file_path=str(file_path),
                original_file_name=file_path.name,
                detected_file_type=file_path.suffix[1:]  # Remove dot
            )
            
            result['doc_id'] = doc_id
            result['doc_uuid'] = doc_uuid
            
            print(f"    Created document: ID={doc_id}, UUID={doc_uuid[:8]}...")
            
            # Step 2: Submit to Celery
            task_id, success = submit_document_to_celery(
                document_id=doc_id,
                document_uuid=doc_uuid,
                file_path=str(file_path),
                file_type=file_path.suffix[1:],  # Remove dot
                file_name=file_path.name,
                project_sql_id=project_id_sql
            )
            
            if not success:
                raise Exception("Failed to submit to Celery")
            
            result['celery_task_id'] = task_id
            print(f"    Submitted to Celery: Task ID={task_id[:8]}...")
            
            # Step 3: Monitor processing
            final_status = self.monitor_document_processing(doc_id, doc_uuid, result)
            result['final_status'] = final_status
            
            # Calculate processing time
            result['end_time'] = datetime.now()
            result['processing_time'] = (result['end_time'] - result['start_time']).total_seconds()
            
            # Determine success
            if final_status == 'completed':
                result['success'] = True
                print(f"    ✅ SUCCESS: Completed in {result['processing_time']:.1f}s")
            else:
                print(f"    ❌ FAILED: Final status = {final_status}")
                
        except Exception as e:
            result['errors'].append({
                'stage': 'submission',
                'error': str(e),
                'traceback': traceback.format_exc()
            })
            self.error_logger.log_error(
                str(result.get('doc_id', 'unknown')),
                result.get('doc_uuid', 'unknown'),
                'submission',
                type(e).__name__,
                str(e)
            )
            print(f"    ❌ EXCEPTION: {e}")
        
        return result
    
    def monitor_document_processing(self, doc_id: int, doc_uuid: str, result: Dict, 
                                   timeout: int = 600) -> str:
        """Monitor document through all processing stages"""
        start_time = time.time()
        last_status = None
        stage_times = {}
        
        print(f"    ⏳ Monitoring processing...")
        
        while time.time() - start_time < timeout:
            try:
                # Get current status from database
                doc_result = self.db.client.table('source_documents')\
                    .select('celery_status, celery_task_id, error_message')\
                    .eq('id', doc_id)\
                    .single()\
                    .execute()
                
                if not doc_result.data:
                    raise Exception("Document not found in database")
                
                current_status = doc_result.data.get('celery_status', 'unknown')
                
                # Log status change
                if current_status != last_status:
                    elapsed = time.time() - start_time
                    stage_times[current_status] = elapsed
                    result['stages_completed'].append({
                        'stage': current_status,
                        'timestamp': datetime.now().isoformat(),
                        'elapsed_seconds': elapsed
                    })
                    print(f"      → {current_status} ({elapsed:.1f}s)")
                    last_status = current_status
                
                # Check for completion or error
                if current_status == 'completed':
                    self.verify_complete_processing(doc_id, doc_uuid, result)
                    return current_status
                    
                if current_status in self.ERROR_STATES:
                    error_msg = doc_result.data.get('error_message', 'Unknown error')
                    result['errors'].append({
                        'stage': current_status,
                        'error': error_msg
                    })
                    self.error_logger.log_error(
                        str(doc_id), doc_uuid, current_status,
                        'Processing Failed', error_msg
                    )
                    return current_status
                
                # Check Redis state for more details
                if elapsed % 10 < 1:  # Every 10 seconds
                    self.check_redis_state(doc_uuid)
                
                time.sleep(2)  # Poll every 2 seconds
                
            except Exception as e:
                result['errors'].append({
                    'stage': 'monitoring',
                    'error': str(e)
                })
                self.error_logger.log_error(
                    str(doc_id), doc_uuid, 'monitoring',
                    type(e).__name__, str(e)
                )
                return 'error_monitoring'
        
        # Timeout reached
        print(f"      ⏱️ TIMEOUT after {timeout}s at status: {last_status}")
        self.debug_stuck_document(doc_uuid, last_status)
        return 'timeout'
    
    def verify_complete_processing(self, doc_id: int, doc_uuid: str, result: Dict):
        """Verify all expected outputs exist"""
        verifications = []
        
        # Check neo4j_documents
        neo4j_doc = self.db.client.table('neo4j_documents')\
            .select('id, processingStatus')\
            .eq('sourceDocumentUuid', doc_uuid)\
            .maybe_single()\
            .execute()
        
        if neo4j_doc.data:
            verifications.append('neo4j_document')
            
            # Check chunks
            chunks = self.db.client.table('neo4j_chunks')\
                .select('id', count='exact')\
                .eq('document_id', neo4j_doc.data['id'])\
                .execute()
            
            if chunks.count > 0:
                verifications.append(f'chunks({chunks.count})')
                
                # Check entity mentions
                mentions = self.db.client.table('neo4j_entity_mentions')\
                    .select('id', count='exact')\
                    .in_('chunk_id', [c['id'] for c in chunks.data[:10]])\
                    .execute()
                
                if mentions.count > 0:
                    verifications.append(f'entities({mentions.count})')
        
        result['verifications'] = verifications
        print(f"      ✓ Verified: {', '.join(verifications)}")
    
    def check_redis_state(self, doc_uuid: str):
        """Check Redis for processing state details"""
        if not self.redis_client:
            return
            
        try:
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=doc_uuid)
            state_data = self.redis_client.hgetall(state_key)
            
            if state_data:
                # Decode bytes to strings if needed
                decoded_state = {}
                for k, v in state_data.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    val = v.decode() if isinstance(v, bytes) else v
                    decoded_state[key] = val
                
                # Log any errors found in state
                for key, value in decoded_state.items():
                    if 'error' in key.lower() or 'failed' in value.lower():
                        print(f"        ⚠️ Redis state - {key}: {value[:100]}")
                        
        except Exception as e:
            print(f"        ⚠️ Redis check error: {e}")
    
    def debug_stuck_document(self, doc_uuid: str, last_status: str):
        """Debug why a document is stuck"""
        print(f"\n    🔍 Debugging stuck document at {last_status}...")
        
        # Check all related tables
        tables_to_check = [
            ('source_documents', 'document_uuid'),
            ('neo4j_documents', 'sourceDocumentUuid'),
            ('textract_jobs', 'source_document_uuid')
        ]
        
        for table, uuid_field in tables_to_check:
            try:
                result = self.db.client.table(table)\
                    .select('*')\
                    .eq(uuid_field, doc_uuid)\
                    .maybe_single()\
                    .execute()
                
                if result.data:
                    print(f"      {table}: Found record")
                    # Log relevant fields
                    for key in ['status', 'processingStatus', 'job_status', 'error_message']:
                        if key in result.data:
                            print(f"        - {key}: {result.data[key]}")
                else:
                    print(f"      {table}: No record found")
                    
            except Exception as e:
                print(f"      {table}: Error checking - {e}")
    
    def run_all_tests(self) -> Dict:
        """Run tests on all documents in input directory"""
        if not self.verify_prerequisites():
            print("\n❌ Prerequisites not met. Please fix issues above.")
            return {'success': False, 'reason': 'Prerequisites failed'}
        
        # Find all test documents
        test_files = []
        for pattern in ['*.pdf', '*.docx', '*.txt', '*.eml']:
            test_files.extend(self.input_dir.glob(pattern))
        
        if not test_files:
            print(f"\n❌ No test documents found in {self.input_dir}")
            return {'success': False, 'reason': 'No test documents'}
        
        print(f"\n📁 Found {len(test_files)} test documents")
        print("=" * 80)
        
        # Test each document
        for i, file_path in enumerate(test_files):
            print(f"\n[{i+1}/{len(test_files)}] Testing: {file_path.name}")
            print("-" * 60)
            
            result = self.test_document(file_path)
            self.test_results.append(result)
            
            # Brief pause between submissions
            if i < len(test_files) - 1:
                print("\n  ⏸️  Pausing 5 seconds before next document...")
                time.sleep(5)
        
        # Generate summary
        return self.generate_summary()
    
    def generate_summary(self) -> Dict:
        """Generate test summary and report"""
        print("\n" + "=" * 80)
        print("📊 TEST SUMMARY")
        print("=" * 80)
        
        # Calculate statistics
        total = len(self.test_results)
        successful = sum(1 for r in self.test_results if r['success'])
        failed = total - successful
        
        # Group by file type
        by_type = defaultdict(lambda: {'total': 0, 'success': 0})
        for result in self.test_results:
            file_type = result['file_type']
            by_type[file_type]['total'] += 1
            if result['success']:
                by_type[file_type]['success'] += 1
        
        # Print summary
        print(f"\n📈 Overall Results:")
        print(f"  Total Documents: {total}")
        print(f"  ✅ Successful: {successful} ({successful/total*100:.1f}%)")
        print(f"  ❌ Failed: {failed} ({failed/total*100:.1f}%)")
        
        print(f"\n📊 Results by File Type:")
        for file_type, stats in by_type.items():
            success_rate = stats['success'] / stats['total'] * 100
            print(f"  {file_type}: {stats['success']}/{stats['total']} ({success_rate:.1f}%)")
        
        # Processing time statistics
        successful_times = [r['processing_time'] for r in self.test_results 
                          if r['success'] and r['processing_time']]
        if successful_times:
            avg_time = sum(successful_times) / len(successful_times)
            min_time = min(successful_times)
            max_time = max(successful_times)
            print(f"\n⏱️  Processing Times (successful documents):")
            print(f"  Average: {avg_time:.1f}s")
            print(f"  Min: {min_time:.1f}s")
            print(f"  Max: {max_time:.1f}s")
        
        # Error analysis
        if failed > 0:
            print(f"\n❌ Error Analysis:")
            error_counts = defaultdict(int)
            for result in self.test_results:
                if not result['success']:
                    final_status = result.get('final_status', 'unknown')
                    error_counts[final_status] += 1
            
            for status, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  {status}: {count}")
        
        # Save detailed report
        report_file = f"celery_e2e_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump({
                'summary': {
                    'total': total,
                    'successful': successful,
                    'failed': failed,
                    'success_rate': successful / total * 100 if total > 0 else 0
                },
                'by_type': dict(by_type),
                'detailed_results': self.test_results
            }, f, indent=2, default=str)
        
        print(f"\n📄 Detailed report saved to: {report_file}")
        
        if self.error_logger.errors:
            print(f"📄 Error log saved to: {self.error_logger.log_file}")
        
        return {
            'success': failed == 0,
            'total': total,
            'successful': successful,
            'failed': failed
        }


def main():
    """Main entry point"""
    print("🚀 Celery End-to-End Testing")
    print("=" * 80)
    
    tester = CeleryE2ETester()
    results = tester.run_all_tests()
    
    if results.get('success'):
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print(f"\n❌ Tests failed: {results.get('failed', 0)} documents failed")
        sys.exit(1)


if __name__ == "__main__":
    main()