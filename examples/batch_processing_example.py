#!/usr/bin/env python3
"""
Example script demonstrating batch processing capabilities.
"""

import sys
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime
import time

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.batch_tasks import submit_batch, get_batch_status
from scripts.batch_recovery import recover_failed_batch, analyze_batch_failures
from scripts.batch_metrics import BatchMetricsCollector, get_metrics_collector
from scripts.cache_warmer import warm_cache_before_batch


def example_submit_batch():
    """Example: Submit a batch of documents for processing."""
    print("\n=== Batch Processing Example ===\n")
    
    # Prepare batch documents
    documents = [
        {
            'document_uuid': str(uuid4()),
            'file_path': f's3://legal-docs/batch/document_{i}.pdf'
        }
        for i in range(10)
    ]
    
    project_uuid = str(uuid4())
    
    # Submit high priority batch
    print("Submitting high priority batch...")
    result = submit_batch(
        documents=documents[:3],
        project_uuid=project_uuid,
        priority='high',
        options={
            'warm_cache': True,
            'entity_resolution': True
        }
    )
    
    print(f"High priority batch submitted:")
    print(f"  Batch ID: {result['batch_id']}")
    print(f"  Task ID: {result['task_id']}")
    print(f"  Documents: {result['document_count']}")
    
    # Submit normal priority batch
    print("\nSubmitting normal priority batch...")
    result = submit_batch(
        documents=documents[3:7],
        project_uuid=project_uuid,
        priority='normal'
    )
    
    print(f"Normal priority batch submitted:")
    print(f"  Batch ID: {result['batch_id']}")
    print(f"  Documents: {result['document_count']}")
    
    # Submit low priority batch
    print("\nSubmitting low priority batch...")
    result = submit_batch(
        documents=documents[7:],
        project_uuid=project_uuid,
        priority='low',
        options={
            'warm_cache': False  # Skip cache warming for low priority
        }
    )
    
    print(f"Low priority batch submitted:")
    print(f"  Batch ID: {result['batch_id']}")
    print(f"  Documents: {result['document_count']}")
    
    return result['batch_id']


def example_monitor_batch(batch_id):
    """Example: Monitor batch processing progress."""
    print(f"\n=== Monitoring Batch {batch_id} ===\n")
    
    # Check status periodically
    for i in range(5):
        status = get_batch_status.apply_async(args=[batch_id]).get()
        
        print(f"Status at {datetime.utcnow().strftime('%H:%M:%S')}:")
        print(f"  Status: {status.get('status', 'unknown')}")
        print(f"  Progress: {status.get('progress_percentage', 0):.1f}%")
        print(f"  Completed: {status.get('completed', 0)}")
        print(f"  Failed: {status.get('failed', 0)}")
        print(f"  Success Rate: {status.get('success_rate', 0):.1f}%")
        
        if 'estimated_time_remaining' in status:
            print(f"  ETA: {status['estimated_time_remaining']}")
        
        if status.get('status') == 'completed':
            print("\nBatch processing completed!")
            break
            
        print()
        time.sleep(5)


def example_batch_recovery():
    """Example: Recover failed documents in a batch."""
    print("\n=== Batch Recovery Example ===\n")
    
    # Simulate a batch with failures
    batch_id = 'example-batch-with-failures'
    
    print("Analyzing batch failures...")
    analysis = analyze_batch_failures.apply_async(args=[batch_id]).get()
    
    print(f"Failure Analysis:")
    print(f"  Total Failures: {analysis['total_failures']}")
    print(f"  Recoverable: {analysis['recoverable_count']}")
    
    if analysis['failure_analysis']['by_category']:
        print("\nFailures by Category:")
        for category, count in analysis['failure_analysis']['by_category'].items():
            print(f"    {category}: {count}")
    
    if analysis['recommendations']:
        print("\nRecommendations:")
        for rec in analysis['recommendations']:
            print(f"  - {rec}")
    
    # Attempt recovery if there are recoverable failures
    if analysis['recoverable_count'] > 0:
        print("\nAttempting recovery...")
        recovery_result = recover_failed_batch.apply_async(
            args=[batch_id],
            kwargs={
                'options': {
                    'max_retries': 3,
                    'retry_all': False,
                    'priority': 'high'
                }
            }
        ).get()
        
        print(f"Recovery initiated:")
        print(f"  Recovery Batch ID: {recovery_result['recovery_batch_id']}")
        print(f"  Documents to Retry: {recovery_result['documents_to_retry']}")
        print(f"  Skipped Documents: {recovery_result['skipped_documents']}")


def example_batch_metrics():
    """Example: View batch processing metrics."""
    print("\n=== Batch Metrics Example ===\n")
    
    collector = get_metrics_collector()
    
    # Get metrics for last 24 hours
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=24)
    
    metrics = collector.get_batch_metrics(start_time, end_time)
    
    print("Batch Processing Metrics (Last 24 Hours):")
    print(f"  Total Batches: {metrics['summary']['total_batches']}")
    print(f"  Total Documents: {metrics['summary']['total_documents']}")
    print(f"  Completed: {metrics['summary']['total_completed']}")
    print(f"  Failed: {metrics['summary']['total_failed']}")
    print(f"  Success Rate: {metrics['summary']['overall_success_rate']:.1f}%")
    
    if metrics['by_priority']:
        print("\nBy Priority:")
        for priority, stats in metrics['by_priority'].items():
            print(f"  {priority.upper()}:")
            print(f"    Batches: {stats['count']}")
            print(f"    Documents: {stats['documents']}")
            print(f"    Completed: {stats['completed']}")
    
    # Get error summary
    error_summary = collector.get_error_summary(hours=1)
    
    if error_summary['total_errors'] > 0:
        print(f"\nRecent Errors (Last Hour):")
        print(f"  Total: {error_summary['total_errors']}")
        print(f"  By Type:")
        for error_type, count in error_summary['by_type'].items():
            print(f"    {error_type}: {count}")


def example_cache_warming():
    """Example: Pre-warm cache for batch processing."""
    print("\n=== Cache Warming Example ===\n")
    
    # Prepare batch manifest
    batch_manifest = {
        'batch_id': str(uuid4()),
        'documents': [
            {'document_uuid': str(uuid4()), 'file_path': f'doc_{i}.pdf'}
            for i in range(20)
        ],
        'project_uuid': str(uuid4()),
        'options': {
            'entity_resolution': True
        }
    }
    
    print("Warming cache for batch processing...")
    result = warm_cache_before_batch(batch_manifest, wait=True)
    
    if result:
        print(f"Cache Warming Results:")
        print(f"  Status: {result['status']}")
        print(f"  Duration: {result.get('duration_seconds', 0):.2f} seconds")
        
        if result.get('warmed'):
            print("  Warmed:")
            for cache_type, count in result['warmed'].items():
                print(f"    {cache_type}: {count}")
        
        if result.get('memory_usage'):
            print(f"  Memory Usage:")
            print(f"    Before: {result['memory_usage']['before_mb']:.2f} MB")
            print(f"    Added: {result['memory_usage']['estimated_mb']:.2f} MB")
        
        if result.get('errors'):
            print(f"  Errors: {len(result['errors'])}")


def main():
    """Run all examples."""
    print("Legal Document Batch Processing Examples")
    print("=" * 50)
    
    # Example 1: Submit batches
    batch_id = example_submit_batch()
    
    # Example 2: Monitor batch
    if batch_id:
        example_monitor_batch(batch_id)
    
    # Example 3: Recovery (commented out unless you have actual failures)
    # example_batch_recovery()
    
    # Example 4: View metrics
    example_batch_metrics()
    
    # Example 5: Cache warming
    example_cache_warming()
    
    print("\n" + "=" * 50)
    print("Examples completed!")


if __name__ == '__main__':
    main()