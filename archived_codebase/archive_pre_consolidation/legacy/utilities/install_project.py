#!/usr/bin/env python3
"""
Project Installation Script
Processes documents for a specific legal case/project
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from supabase_utils import SupabaseManager
from celery_submission import submit_document_to_celery
import argparse
from pathlib import Path
import json
from datetime import datetime
import time

class ProjectInstaller:
    def __init__(self):
        self.db = SupabaseManager()
        
    def create_project(self, project_name: str, project_id: str = None) -> tuple[str, int]:
        """Create a new project or get existing one"""
        
        if not project_id:
            # Generate a meaningful project ID from the name
            import re
            project_id = re.sub(r'[^a-zA-Z0-9-]', '-', project_name.lower())
            project_id = re.sub(r'-+', '-', project_id).strip('-')
            
        print(f"\n📁 Creating/retrieving project: {project_name}")
        print(f"   Project ID: {project_id}")
        
        try:
            sql_id, uuid = self.db.get_or_create_project(project_id, project_name)
            print(f"✓ Project ready: SQL ID={sql_id}, UUID={uuid}")
            return uuid, sql_id
        except Exception as e:
            print(f"❌ Error creating project: {e}")
            raise
    
    def process_directory(self, directory: Path, project_uuid: str, project_sql_id: int) -> dict:
        """Process all documents in a directory"""
        
        # Supported file extensions
        supported_extensions = {'.pdf', '.docx', '.doc', '.txt', '.rtf', '.wav', '.mp3', '.m4a'}
        
        # Find all files
        all_files = []
        for ext in supported_extensions:
            all_files.extend(directory.rglob(f'*{ext}'))
        
        # Also find files with uppercase extensions
        for ext in supported_extensions:
            all_files.extend(directory.rglob(f'*{ext.upper()}'))
        
        # Remove duplicates and sort
        all_files = sorted(set(all_files))
        
        print(f"\n📂 Found {len(all_files)} documents in {directory}")
        
        results = {
            'total': len(all_files),
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'files': []
        }
        
        for i, file_path in enumerate(all_files, 1):
            relative_path = file_path.relative_to(directory)
            print(f"\n[{i}/{len(all_files)}] Processing: {relative_path}")
            
            try:
                # Check if already processed
                existing = self.db.client.table('source_documents').select(
                    'document_uuid, celery_status'
                ).eq('original_file_name', file_path.name).eq('project_uuid', project_uuid).execute()
                
                if existing.data:
                    status = existing.data[0]['celery_status']
                    if status == 'completed':
                        print(f"  ⏭️  Already completed, skipping")
                        results['skipped'] += 1
                        results['files'].append({
                            'path': str(relative_path),
                            'status': 'skipped',
                            'reason': 'already_completed'
                        })
                        continue
                    else:
                        print(f"  ⚠️  Previous status: {status}, reprocessing...")
                
                # Create source document entry
                doc_id, doc_uuid = self.db.create_source_document_entry(
                    project_fk_id=project_sql_id,
                    project_uuid=project_uuid,
                    original_file_path=str(file_path),
                    original_file_name=file_path.name,
                    detected_file_type=file_path.suffix.lower().lstrip('.')
                )
                
                # Submit to Celery for processing
                task = submit_document_to_celery(
                    document_uuid=doc_uuid,
                    source_doc_sql_id=doc_id,
                    project_sql_id=project_sql_id
                )
                
                if task and task.id:
                    print(f"  ✓ Submitted: {doc_uuid} (Task: {task.id})")
                    results['successful'] += 1
                    results['files'].append({
                        'path': str(relative_path),
                        'status': 'submitted',
                        'document_uuid': doc_uuid,
                        'task_id': task.id
                    })
                else:
                    print(f"  ❌ Failed to submit to Celery")
                    results['failed'] += 1
                    results['files'].append({
                        'path': str(relative_path),
                        'status': 'failed',
                        'reason': 'celery_submission_failed'
                    })
                    
            except Exception as e:
                print(f"  ❌ Error: {e}")
                results['failed'] += 1
                results['files'].append({
                    'path': str(relative_path),
                    'status': 'error',
                    'error': str(e)
                })
            
            # Small delay to avoid overwhelming the system
            time.sleep(0.5)
        
        return results
    
    def monitor_processing(self, project_uuid: str, timeout: int = 3600):
        """Monitor document processing status"""
        
        start_time = time.time()
        
        print(f"\n📊 Monitoring processing status (timeout: {timeout}s)...")
        
        while time.time() - start_time < timeout:
            # Get status counts
            status_result = self.db.client.table('source_documents').select(
                'celery_status'
            ).eq('project_uuid', project_uuid).execute()
            
            status_counts = {}
            for doc in status_result.data:
                status = doc.get('celery_status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            # Calculate totals
            total = sum(status_counts.values())
            completed = status_counts.get('completed', 0)
            failed = status_counts.get('ocr_failed', 0)
            processing = total - completed - failed
            
            # Clear line and print status
            print(f"\r⏳ Total: {total} | ✅ Completed: {completed} | "
                  f"❌ Failed: {failed} | ⚙️  Processing: {processing}", end='', flush=True)
            
            # If all done, break
            if processing == 0:
                print("\n✓ All documents processed!")
                break
            
            time.sleep(5)
        else:
            print(f"\n⏱️  Timeout reached after {timeout}s")
        
        # Print final summary
        print("\n📈 Final Status Summary:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")
        
        return status_counts
    
    def generate_report(self, project_name: str, project_uuid: str, 
                       installation_results: dict, final_status: dict):
        """Generate installation report"""
        
        report = {
            'project': {
                'name': project_name,
                'uuid': project_uuid,
                'installation_time': datetime.now().isoformat()
            },
            'installation': installation_results,
            'final_status': final_status,
            'summary': {
                'total_files': installation_results['total'],
                'successfully_submitted': installation_results['successful'],
                'submission_failed': installation_results['failed'],
                'skipped': installation_results['skipped'],
                'final_completed': final_status.get('completed', 0),
                'final_failed': final_status.get('ocr_failed', 0)
            }
        }
        
        # Save report
        report_file = f"project_report_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n📄 Report saved to: {report_file}")
        
        # Print summary
        print("\n" + "="*60)
        print(f"PROJECT INSTALLATION COMPLETE: {project_name}")
        print("="*60)
        print(f"Total Files Found:        {report['summary']['total_files']}")
        print(f"Successfully Submitted:   {report['summary']['successfully_submitted']}")
        print(f"Submission Failed:        {report['summary']['submission_failed']}")
        print(f"Skipped (Already Done):   {report['summary']['skipped']}")
        print("-"*60)
        print(f"Final Completed:          {report['summary']['final_completed']}")
        print(f"Final Failed:             {report['summary']['final_failed']}")
        print("="*60)

def main():
    parser = argparse.ArgumentParser(
        description='Install a legal case project by processing all documents',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Install a project from a directory
  python install_project.py --name "Smith v. Jones Case" --dir /path/to/case/documents
  
  # Install with custom project ID
  python install_project.py --name "Smith v. Jones" --id "smith-v-jones-2024" --dir ./documents
  
  # Install without monitoring (just submit)
  python install_project.py --name "Test Case" --dir ./test_docs --no-monitor
  
  # Install with custom timeout
  python install_project.py --name "Large Case" --dir ./big_case --timeout 7200
        """
    )
    
    parser.add_argument('--name', required=True,
                       help='Project name (e.g., "Smith v. Jones Case")')
    parser.add_argument('--dir', required=True, type=Path,
                       help='Directory containing documents to process')
    parser.add_argument('--id', type=str,
                       help='Project ID (generated from name if not provided)')
    parser.add_argument('--no-monitor', action='store_true',
                       help='Skip monitoring phase (just submit documents)')
    parser.add_argument('--timeout', type=int, default=3600,
                       help='Monitoring timeout in seconds (default: 3600)')
    
    args = parser.parse_args()
    
    # Validate directory
    if not args.dir.exists():
        print(f"❌ Directory not found: {args.dir}")
        sys.exit(1)
    
    if not args.dir.is_dir():
        print(f"❌ Not a directory: {args.dir}")
        sys.exit(1)
    
    # Create installer
    installer = ProjectInstaller()
    
    try:
        # Create project
        project_uuid, project_sql_id = installer.create_project(args.name, args.id)
        
        # Process documents
        results = installer.process_directory(args.dir, project_uuid, project_sql_id)
        
        # Monitor if requested
        if not args.no_monitor and results['successful'] > 0:
            final_status = installer.monitor_processing(project_uuid, args.timeout)
        else:
            final_status = {}
        
        # Generate report
        installer.generate_report(args.name, project_uuid, results, final_status)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Installation interrupted by user")
    except Exception as e:
        print(f"\n❌ Installation failed: {e}")
        raise

if __name__ == "__main__":
    main()