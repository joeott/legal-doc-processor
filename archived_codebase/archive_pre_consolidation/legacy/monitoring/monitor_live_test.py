#!/usr/bin/env python3
"""Monitor live document testing in real-time"""

import time
import sys
import os
from datetime import datetime, timedelta

# Add scripts to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.supabase_utils import SupabaseManager

def get_processing_status():
    """Get current processing status from database"""
    db = SupabaseManager()
    
    try:
        # Get queue status counts
        queue_response = db.client.table('document_processing_queue')\
            .select('status')\
            .execute()
        
        status_counts = {}
        for item in queue_response.data:
            status = item['status']
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Get recent errors
        recent_errors = db.client.table('document_processing_queue')\
            .select('*')\
            .eq('status', 'failed')\
            .order('updated_at', desc=True)\
            .limit(5)\
            .execute()
        
        # Get recent completions
        time_threshold = (datetime.now() - timedelta(hours=1)).isoformat()
        recent_completed = db.client.table('document_processing_queue')\
            .select('*')\
            .eq('status', 'completed')\
            .gte('completed_at', time_threshold)\
            .order('completed_at', desc=True)\
            .limit(10)\
            .execute()
        
        return {
            'status_counts': status_counts,
            'recent_errors': recent_errors.data,
            'recent_completed': recent_completed.data
        }
    except Exception as e:
        return {
            'error': str(e),
            'status_counts': {},
            'recent_errors': [],
            'recent_completed': []
        }

def calculate_processing_time(item):
    """Calculate processing time for a completed item"""
    if item.get('started_at') and item.get('completed_at'):
        start = datetime.fromisoformat(item['started_at'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(item['completed_at'].replace('Z', '+00:00'))
        duration = end - start
        return str(duration).split('.')[0]  # Remove microseconds
    return "N/A"

def display_status():
    """Display current status"""
    os.system('clear' if os.name != 'nt' else 'cls')
    
    print("=" * 80)
    print(f"Document Processing Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    status = get_processing_status()
    
    if 'error' in status:
        print(f"\nError connecting to database: {status['error']}")
        return
    
    # Display queue status
    print("\n📊 Queue Status:")
    print("-" * 40)
    for status_type, count in sorted(status['status_counts'].items()):
        emoji = {
            'pending': '⏳',
            'processing': '🔄',
            'completed': '✅',
            'failed': '❌'
        }.get(status_type, '❓')
        print(f"{emoji} {status_type.capitalize()}: {count}")
    
    total = sum(status['status_counts'].values())
    print(f"\n📈 Total items: {total}")
    
    # Display recent errors
    if status['recent_errors']:
        print("\n❌ Recent Errors:")
        print("-" * 40)
        for error in status['recent_errors'][:3]:
            timestamp = error['updated_at'][:19].replace('T', ' ')
            error_msg = error.get('error_message', 'Unknown error')[:60]
            print(f"{timestamp}: {error_msg}...")
    
    # Display recent completions
    if status['recent_completed']:
        print("\n✅ Recent Completions (last hour):")
        print("-" * 40)
        for item in status['recent_completed'][:5]:
            timestamp = item['completed_at'][:19].replace('T', ' ')
            duration = calculate_processing_time(item)
            doc_id = item.get('source_document_id', 'Unknown')
            print(f"{timestamp}: Doc #{doc_id} - Duration: {duration}")
    
    # Calculate success rate
    if total > 0:
        completed = status['status_counts'].get('completed', 0)
        failed = status['status_counts'].get('failed', 0)
        processed = completed + failed
        
        if processed > 0:
            success_rate = (completed / processed) * 100
            print(f"\n📊 Success Rate: {success_rate:.1f}% ({completed}/{processed})")
    
    print("\n" + "=" * 80)
    print("Press Ctrl+C to exit")

def monitor():
    """Run monitoring loop"""
    print("Starting document processing monitor...")
    print("Refreshing every 5 seconds...")
    
    try:
        while True:
            display_status()
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    monitor()