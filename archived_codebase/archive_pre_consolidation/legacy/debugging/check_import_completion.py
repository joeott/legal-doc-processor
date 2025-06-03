#!/usr/bin/env python3
"""
Check import session completion and document processing status.
Enhanced version of check_celery_status.py with import session support.
"""

import os
import sys
import argparse
from datetime import datetime
from typing import Dict, List, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager


class ImportCompletionChecker:
    """Check import session and document processing completion"""
    
    STATUS_EMOJIS = {
        'pending': '⏳',
        'processing': '🔄',
        'ocr_processing': '📄',
        'ocr_complete': '📝',
        'text_processing': '🔤',
        'entity_extraction': '🏷️',
        'entity_resolution': '🔗',
        'graph_building': '🕸️',
        'completed': '✅',
        'ocr_failed': '❌',
        'text_failed': '❌',
        'entity_failed': '❌',
        'resolution_failed': '❌',
        'graph_failed': '❌'
    }
    
    def __init__(self):
        self.db = SupabaseManager()
    
    def check_session(self, session_id: str):
        """Check specific import session status"""
        print(f"\n📊 Import Session Status Report")
        print("=" * 80)
        
        # Get session info
        try:
            session_result = self.db.client.table('import_sessions')\
                .select('*')\
                .eq('id', session_id)\
                .single()\
                .execute()
            
            if not session_result.data:
                print(f"❌ Session not found: {session_id}")
                return
            
            session = session_result.data
            self._print_session_header(session)
            
            # Get documents in this session
            docs_result = self.db.client.table('source_documents')\
                .select('id, original_file_name, celery_status, celery_task_id, error_message, created_at')\
                .eq('import_session_id', session_id)\
                .order('created_at')\
                .execute()
            
            self._print_documents(docs_result.data)
            self._print_summary(session, docs_result.data)
            
            # Get cost breakdown
            self._print_costs(session_id)
            
        except Exception as e:
            print(f"❌ Error retrieving session: {e}")
    
    def check_recent_imports(self, hours: int = 24):
        """Check recent import sessions"""
        print(f"\n📊 Recent Import Sessions (last {hours} hours)")
        print("=" * 80)
        
        try:
            # Get recent sessions
            result = self.db.client.table('import_session_summary')\
                .select('*')\
                .gte('started_at', f"now() - interval '{hours} hours'")\
                .order('started_at', desc=True)\
                .execute()
            
            if not result.data:
                print("No recent import sessions found")
                return
            
            # Display sessions
            for session in result.data:
                self._print_session_summary(session)
                
        except Exception as e:
            print(f"❌ Error retrieving sessions: {e}")
    
    def _print_session_header(self, session: Dict):
        """Print session header information"""
        print(f"Case: {session['case_name']}")
        print(f"Project: {session.get('project_id', 'N/A')}")
        print(f"Started: {session['started_at']}")
        
        if session.get('completed_at'):
            print(f"Completed: {session['completed_at']}")
            # Calculate duration
            start = datetime.fromisoformat(session['started_at'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(session['completed_at'].replace('Z', '+00:00'))
            duration = end - start
            print(f"Duration: {duration}")
        else:
            print("Status: Still running...")
        
        print(f"Total files: {session.get('total_files', 0)}")
        print("-" * 80)
    
    def _print_documents(self, documents: List[Dict]):
        """Print document details"""
        if not documents:
            print("No documents found")
            return
        
        print("\nDocuments:")
        for doc in documents:
            status = doc.get('celery_status', 'unknown')
            emoji = self.STATUS_EMOJIS.get(status, '❓')
            task_id = doc.get('celery_task_id', '')[:8] + '...' if doc.get('celery_task_id') else 'None'
            
            print(f"{emoji} ID: {doc['id']:4d} | {doc['original_file_name'][:40]:40s} | {status:20s} | Task: {task_id}")
            
            if doc.get('error_message'):
                print(f"   └─ Error: {doc['error_message'][:70]}...")
    
    def _print_summary(self, session: Dict, documents: List[Dict]):
        """Print processing summary"""
        print("\n📈 Processing Summary:")
        
        # Count statuses
        status_counts = {}
        for doc in documents:
            status = doc.get('celery_status', 'no_status')
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Display counts
        for status, count in sorted(status_counts.items()):
            emoji = self.STATUS_EMOJIS.get(status, '❓')
            print(f"  {emoji} {status}: {count}")
        
        # Calculate completion rate
        total = len(documents)
        completed = status_counts.get('completed', 0)
        failed = sum(count for status, count in status_counts.items() if status.endswith('_failed'))
        
        if total > 0:
            completion_rate = (completed / total) * 100
            failure_rate = (failed / total) * 100
            print(f"\n  Completion rate: {completion_rate:.1f}%")
            print(f"  Failure rate: {failure_rate:.1f}%")
    
    def _print_costs(self, session_id: str):
        """Print cost breakdown"""
        try:
            # Get cost summary
            result = self.db.client.table('processing_costs')\
                .select('service')\
                .select('total_cost')\
                .eq('import_session_id', session_id)\
                .execute()
            
            if not result.data:
                return
            
            print("\n💰 Cost Breakdown:")
            
            # Aggregate by service
            costs_by_service = {}
            total_cost = 0
            
            for cost in result.data:
                service = cost['service']
                amount = float(cost['total_cost'])
                costs_by_service[service] = costs_by_service.get(service, 0) + amount
                total_cost += amount
            
            # Display costs
            for service, amount in sorted(costs_by_service.items()):
                print(f"  {service}: ${amount:.4f}")
            
            print(f"  ─────────────")
            print(f"  Total: ${total_cost:.4f}")
            
        except Exception as e:
            print(f"\n⚠️  Could not retrieve cost data: {e}")
    
    def _print_session_summary(self, session: Dict):
        """Print compact session summary"""
        status_emoji = '✅' if session['status'] == 'completed' else '🔄' if session['status'] == 'active' else '❌'
        
        print(f"\n{status_emoji} {session['case_name']} (Session: {session['id'][:8]}...)")
        print(f"   Project: {session.get('project_name', 'Unknown')}")
        print(f"   Progress: {session.get('processed_files', 0)}/{session.get('total_files', 0)} " +
              f"({session.get('progress_percent', 0):.1f}%)")
        
        if session.get('failed_files', 0) > 0:
            print(f"   ⚠️  Failed: {session['failed_files']}")
        
        if session.get('total_cost'):
            print(f"   💰 Cost: ${session['total_cost']:.2f}")
        
        if session.get('duration'):
            # Parse PostgreSQL interval
            duration_str = session['duration']
            print(f"   ⏱️  Duration: {duration_str}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Check import completion status')
    parser.add_argument('--session', '-s', help='Check specific session ID')
    parser.add_argument('--recent', '-r', type=int, default=24, 
                       help='Show recent sessions (hours)')
    parser.add_argument('--all', '-a', action='store_true', 
                       help='Show all documents (no session filter)')
    
    args = parser.parse_args()
    
    checker = ImportCompletionChecker()
    
    if args.session:
        checker.check_session(args.session)
    elif args.all:
        # Fallback to original check_celery_status behavior
        from scripts.check_celery_status import check_status
        check_status()
    else:
        checker.check_recent_imports(args.recent)


if __name__ == '__main__':
    main()