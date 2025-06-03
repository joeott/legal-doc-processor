#!/usr/bin/env python3
"""
Verify document import completeness and processing status.

This script validates that all documents were imported successfully
and tracks their processing progress through the pipeline.
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import hashlib

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.import_tracker import ImportTracker
from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3DocumentStorage


class ImportVerifier:
    """Verify import completeness and processing status."""
    
    def __init__(self, session_id: int):
        self.session_id = session_id
        self.tracker = ImportTracker()
        self.db_manager = SupabaseManager()
        self.s3_storage = S3DocumentStorage()
        
        # Get session info
        self.session_info = self.tracker.get_session_status(session_id)
        
        # Verification results
        self.results = {
            'session_id': session_id,
            'timestamp': datetime.now().isoformat(),
            'checks': {},
            'issues': [],
            'statistics': {}
        }
    
    def verify_all(self, deep_check: bool = False) -> Dict:
        """Run all verification checks."""
        print(f"Verifying import session {self.session_id}")
        print(f"Case: {self.session_info['case_name']}")
        print("="*60)
        
        # Basic import checks
        self._verify_import_completeness()
        self._verify_no_duplicates()
        self._verify_file_integrity()
        
        # Database checks
        self._verify_database_entries()
        self._verify_s3_uploads()
        
        # Processing checks
        self._verify_processing_status()
        self._verify_error_patterns()
        
        # Deep checks (optional)
        if deep_check:
            self._verify_s3_accessibility()
            self._verify_processing_outputs()
        
        # Generate summary
        self._generate_summary()
        
        return self.results
    
    def _verify_import_completeness(self):
        """Verify all files were imported."""
        print("\n1. Checking import completeness...")
        
        with self.tracker.lock:
            cursor = self.tracker.conn.cursor()
            
            # Get import statistics
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status IN ('completed', 'uploaded', 'queued') THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped
                FROM document_imports
                WHERE session_id = ?
            """, (self.session_id,))
            
            stats = dict(cursor.fetchone())
            
            completeness_rate = stats['successful'] / stats['total'] if stats['total'] > 0 else 0
            
            self.results['checks']['import_completeness'] = {
                'status': 'PASS' if completeness_rate >= 0.95 else 'WARN' if completeness_rate >= 0.90 else 'FAIL',
                'completeness_rate': completeness_rate,
                'statistics': stats
            }
            
            print(f"  Total files: {stats['total']}")
            print(f"  Successful: {stats['successful']} ({completeness_rate*100:.1f}%)")
            print(f"  Failed: {stats['failed']}")
            print(f"  Pending: {stats['pending']}")
            
            if stats['failed'] > 0:
                self.results['issues'].append({
                    'type': 'import_failures',
                    'severity': 'high',
                    'count': stats['failed'],
                    'message': f"{stats['failed']} files failed to import"
                })
    
    def _verify_no_duplicates(self):
        """Verify no duplicate files were imported."""
        print("\n2. Checking for duplicates...")
        
        with self.tracker.lock:
            cursor = self.tracker.conn.cursor()
            
            # Find duplicate imports
            cursor.execute("""
                SELECT file_hash, COUNT(*) as count, GROUP_CONCAT(file_path, '||') as paths
                FROM document_imports
                WHERE session_id = ?
                GROUP BY file_hash
                HAVING COUNT(*) > 1
            """, (self.session_id,))
            
            duplicates = []
            for row in cursor.fetchall():
                duplicates.append({
                    'file_hash': row['file_hash'],
                    'count': row['count'],
                    'paths': row['paths'].split('||')
                })
            
            self.results['checks']['duplicates'] = {
                'status': 'PASS' if len(duplicates) == 0 else 'WARN',
                'duplicate_groups': len(duplicates),
                'total_duplicates': sum(d['count'] - 1 for d in duplicates)
            }
            
            print(f"  Duplicate groups found: {len(duplicates)}")
            
            if duplicates:
                self.results['issues'].append({
                    'type': 'duplicate_imports',
                    'severity': 'medium',
                    'count': len(duplicates),
                    'message': f"Found {len(duplicates)} groups of duplicate files",
                    'details': duplicates[:5]  # First 5 examples
                })
    
    def _verify_file_integrity(self):
        """Verify file sizes match expected."""
        print("\n3. Checking file integrity...")
        
        with self.tracker.lock:
            cursor = self.tracker.conn.cursor()
            
            # Check for size mismatches
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM document_imports
                WHERE session_id = ? AND size_bytes = 0
            """, (self.session_id,))
            
            zero_size_count = cursor.fetchone()['count']
            
            self.results['checks']['file_integrity'] = {
                'status': 'PASS' if zero_size_count == 0 else 'WARN',
                'zero_size_files': zero_size_count
            }
            
            print(f"  Files with zero size: {zero_size_count}")
            
            if zero_size_count > 0:
                self.results['issues'].append({
                    'type': 'zero_size_files',
                    'severity': 'low',
                    'count': zero_size_count,
                    'message': f"{zero_size_count} files have zero size"
                })
    
    def _verify_database_entries(self):
        """Verify database entries exist for all imports."""
        print("\n4. Checking database entries...")
        
        with self.tracker.lock:
            cursor = self.tracker.conn.cursor()
            
            # Get all successful imports
            cursor.execute("""
                SELECT import_id, file_path, document_uuid, source_doc_id
                FROM document_imports
                WHERE session_id = ? AND status IN ('completed', 'uploaded', 'queued')
            """, (self.session_id,))
            
            imports = [dict(row) for row in cursor.fetchall()]
        
        # Check each document in database
        missing_db = []
        for imp in imports:
            if imp['document_uuid']:
                try:
                    result = self.db_manager.client.table('source_documents')\
                        .select('id')\
                        .eq('documentid', imp['document_uuid'])\
                        .execute()
                    
                    if not result.data:
                        missing_db.append(imp)
                except Exception as e:
                    missing_db.append(imp)
        
        self.results['checks']['database_entries'] = {
            'status': 'PASS' if len(missing_db) == 0 else 'FAIL',
            'total_checked': len(imports),
            'missing_entries': len(missing_db)
        }
        
        print(f"  Documents checked: {len(imports)}")
        print(f"  Missing from database: {len(missing_db)}")
        
        if missing_db:
            self.results['issues'].append({
                'type': 'missing_database_entries',
                'severity': 'high',
                'count': len(missing_db),
                'message': f"{len(missing_db)} documents missing from database",
                'examples': [d['file_path'] for d in missing_db[:5]]
            })
    
    def _verify_s3_uploads(self):
        """Verify S3 uploads completed."""
        print("\n5. Checking S3 uploads...")
        
        with self.tracker.lock:
            cursor = self.tracker.conn.cursor()
            
            # Get documents with S3 keys
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN s3_key IS NOT NULL THEN 1 ELSE 0 END) as with_s3
                FROM document_imports
                WHERE session_id = ? AND status IN ('completed', 'uploaded', 'queued')
            """, (self.session_id,))
            
            result = cursor.fetchone()
            total = result['total']
            with_s3 = result['with_s3']
        
        upload_rate = with_s3 / total if total > 0 else 0
        
        self.results['checks']['s3_uploads'] = {
            'status': 'PASS' if upload_rate >= 0.99 else 'WARN',
            'upload_rate': upload_rate,
            'total_documents': total,
            'uploaded_to_s3': with_s3
        }
        
        print(f"  Documents with S3 keys: {with_s3}/{total} ({upload_rate*100:.1f}%)")
        
        if upload_rate < 0.99:
            self.results['issues'].append({
                'type': 's3_upload_incomplete',
                'severity': 'medium',
                'count': total - with_s3,
                'message': f"{total - with_s3} documents missing S3 keys"
            })
    
    def _verify_processing_status(self):
        """Verify document processing status."""
        print("\n6. Checking processing status...")
        
        # Get all documents with their current status
        project_id = self.session_info.get('project_id')
        
        if project_id:
            try:
                # Get processing status from source_documents
                result = self.db_manager.client.table('source_documents')\
                    .select('documentid, upload_status, celery_status, extracted_text')\
                    .eq('project_id', project_id)\
                    .execute()
                
                docs = result.data
                
                # Count statuses
                status_counts = defaultdict(int)
                for doc in docs:
                    status = doc.get('celery_status') or doc.get('upload_status', 'unknown')
                    status_counts[status] += 1
                
                # Check for completed processing
                completed = sum(1 for doc in docs if doc.get('extracted_text'))
                completion_rate = completed / len(docs) if docs else 0
                
                self.results['checks']['processing_status'] = {
                    'status': 'INFO',
                    'total_documents': len(docs),
                    'completed_processing': completed,
                    'completion_rate': completion_rate,
                    'status_breakdown': dict(status_counts)
                }
                
                print(f"  Documents in database: {len(docs)}")
                print(f"  Completed processing: {completed} ({completion_rate*100:.1f}%)")
                print(f"  Status breakdown:")
                for status, count in sorted(status_counts.items()):
                    print(f"    {status}: {count}")
                    
            except Exception as e:
                self.results['checks']['processing_status'] = {
                    'status': 'ERROR',
                    'error': str(e)
                }
                print(f"  Error checking processing status: {e}")
    
    def _verify_error_patterns(self):
        """Analyze error patterns."""
        print("\n7. Analyzing error patterns...")
        
        with self.tracker.lock:
            cursor = self.tracker.conn.cursor()
            
            # Get error statistics
            cursor.execute("""
                SELECT error_type, COUNT(*) as count
                FROM document_imports
                WHERE session_id = ? AND status = 'failed'
                GROUP BY error_type
                ORDER BY count DESC
            """, (self.session_id,))
            
            error_types = [dict(row) for row in cursor.fetchall()]
            
            # Get file types with errors
            cursor.execute("""
                SELECT mime_type, COUNT(*) as count
                FROM document_imports
                WHERE session_id = ? AND status = 'failed'
                GROUP BY mime_type
                ORDER BY count DESC
            """, (self.session_id,))
            
            error_by_type = [dict(row) for row in cursor.fetchall()]
        
        self.results['checks']['error_patterns'] = {
            'status': 'INFO',
            'error_types': error_types,
            'errors_by_file_type': error_by_type
        }
        
        if error_types:
            print(f"  Error types found:")
            for err in error_types[:5]:
                print(f"    {err['error_type']}: {err['count']}")
    
    def _verify_s3_accessibility(self):
        """Deep check: verify S3 objects are accessible."""
        print("\n8. Verifying S3 accessibility (deep check)...")
        
        with self.tracker.lock:
            cursor = self.tracker.conn.cursor()
            
            # Get sample of S3 keys to check
            cursor.execute("""
                SELECT s3_key, file_path
                FROM document_imports
                WHERE session_id = ? AND s3_key IS NOT NULL
                ORDER BY RANDOM()
                LIMIT 10
            """, (self.session_id,))
            
            samples = [dict(row) for row in cursor.fetchall()]
        
        accessible = 0
        for sample in samples:
            try:
                # Try to generate signed URL
                url = self.s3_storage.generate_signed_url(sample['s3_key'])
                if url:
                    accessible += 1
            except Exception as e:
                pass
        
        accessibility_rate = accessible / len(samples) if samples else 0
        
        self.results['checks']['s3_accessibility'] = {
            'status': 'PASS' if accessibility_rate >= 0.9 else 'FAIL',
            'samples_checked': len(samples),
            'accessible': accessible,
            'accessibility_rate': accessibility_rate
        }
        
        print(f"  Samples checked: {len(samples)}")
        print(f"  Accessible: {accessible} ({accessibility_rate*100:.1f}%)")
    
    def _verify_processing_outputs(self):
        """Deep check: verify processing outputs exist."""
        print("\n9. Verifying processing outputs (deep check)...")
        
        project_id = self.session_info.get('project_id')
        
        if project_id:
            try:
                # Check for chunks
                chunks = self.db_manager.client.table('neo4j_chunks')\
                    .select('id', func='count')\
                    .eq('project_id', project_id)\
                    .execute()
                
                chunk_count = chunks.data[0]['count'] if chunks.data else 0
                
                # Check for entities
                entities = self.db_manager.client.table('neo4j_entity_mentions')\
                    .select('id', func='count')\
                    .eq('project_id', project_id)\
                    .execute()
                
                entity_count = entities.data[0]['count'] if entities.data else 0
                
                # Check for relationships
                relationships = self.db_manager.client.table('neo4j_relationships_staging')\
                    .select('id', func='count')\
                    .eq('project_id', project_id)\
                    .execute()
                
                relationship_count = relationships.data[0]['count'] if relationships.data else 0
                
                self.results['checks']['processing_outputs'] = {
                    'status': 'INFO',
                    'chunks_created': chunk_count,
                    'entities_extracted': entity_count,
                    'relationships_created': relationship_count
                }
                
                print(f"  Chunks created: {chunk_count}")
                print(f"  Entities extracted: {entity_count}")
                print(f"  Relationships created: {relationship_count}")
                
            except Exception as e:
                self.results['checks']['processing_outputs'] = {
                    'status': 'ERROR',
                    'error': str(e)
                }
                print(f"  Error checking outputs: {e}")
    
    def _generate_summary(self):
        """Generate verification summary."""
        print("\n" + "="*60)
        print("VERIFICATION SUMMARY")
        print("="*60)
        
        # Count check results
        check_counts = defaultdict(int)
        for check, result in self.results['checks'].items():
            check_counts[result['status']] += 1
        
        self.results['statistics']['check_summary'] = dict(check_counts)
        
        print(f"Checks performed: {len(self.results['checks'])}")
        for status, count in sorted(check_counts.items()):
            print(f"  {status}: {count}")
        
        # Issue summary
        if self.results['issues']:
            print(f"\nIssues found: {len(self.results['issues'])}")
            
            severity_counts = defaultdict(int)
            for issue in self.results['issues']:
                severity_counts[issue['severity']] += 1
            
            for severity in ['high', 'medium', 'low']:
                if severity in severity_counts:
                    print(f"  {severity.upper()}: {severity_counts[severity]}")
        else:
            print("\nNo issues found!")
        
        # Overall status
        if check_counts.get('FAIL', 0) > 0:
            overall_status = 'FAIL'
        elif check_counts.get('WARN', 0) > 0:
            overall_status = 'WARN'
        else:
            overall_status = 'PASS'
        
        self.results['overall_status'] = overall_status
        print(f"\nOverall Status: {overall_status}")
    
    def save_report(self, output_path: str = None):
        """Save verification report."""
        if not output_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"import_verification_{self.session_id}_{timestamp}.json"
        
        with open(output_path, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        print(f"\nVerification report saved to: {output_path}")
        return output_path
    
    def print_recommendations(self):
        """Print recommendations based on verification."""
        print("\n" + "="*60)
        print("RECOMMENDATIONS")
        print("="*60)
        
        if not self.results['issues']:
            print("✓ Import completed successfully with no issues!")
            return
        
        # Group issues by type
        for issue in self.results['issues']:
            if issue['severity'] == 'high':
                print(f"\n⚠️  HIGH PRIORITY: {issue['message']}")
                
                if issue['type'] == 'import_failures':
                    print("   Action: Re-run import with --retry-failed flag")
                elif issue['type'] == 'missing_database_entries':
                    print("   Action: Check database connectivity and re-import affected files")
                    
            elif issue['severity'] == 'medium':
                print(f"\n⚡ MEDIUM PRIORITY: {issue['message']}")
                
                if issue['type'] == 'duplicate_imports':
                    print("   Action: Review duplicate files and consider deduplication")
                elif issue['type'] == 's3_upload_incomplete':
                    print("   Action: Check S3 permissions and re-upload missing files")
                    
            else:
                print(f"\nℹ️  LOW PRIORITY: {issue['message']}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Verify document import')
    parser.add_argument('session_id', type=int, help='Import session ID to verify')
    parser.add_argument('--deep', action='store_true', 
                       help='Perform deep verification checks')
    parser.add_argument('--output', help='Output report file path')
    
    args = parser.parse_args()
    
    # Create verifier
    verifier = ImportVerifier(args.session_id)
    
    # Run verification
    results = verifier.verify_all(deep_check=args.deep)
    
    # Save report
    report_path = verifier.save_report(args.output)
    
    # Print recommendations
    verifier.print_recommendations()


if __name__ == '__main__':
    main()