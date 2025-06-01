#!/usr/bin/env python3
"""
Health Check Script for Document Processing Pipeline
Monitors pipeline health and identifies stuck documents
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict
import time
from supabase_utils import SupabaseManager
from redis_utils import get_redis_manager

logger = logging.getLogger(__name__)

class PipelineHealthChecker:
    def __init__(self):
        self.db = SupabaseManager()
        self.issues = []
        
    def check_stuck_documents(self, hours_threshold: int = 1) -> List[Dict]:
        """Find documents stuck in processing for too long"""
        try:
            # Calculate cutoff time
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_threshold)
            
            # Find stuck documents
            stuck_docs = self.db.client.table('source_documents').select(
                'id', 'original_file_name', 'initial_processing_status', 'last_modified_at'
            ).in_('initial_processing_status', ['pending_ocr', 'processing']).lt(
                'last_modified_at', cutoff_time.isoformat()
            ).execute()
            
            if stuck_docs.data:
                for doc in stuck_docs.data:
                    hours_stuck = (datetime.now(timezone.utc) - datetime.fromisoformat(
                        doc['last_modified_at'].replace('Z', '+00:00')
                    )).total_seconds() / 3600
                    
                    self.issues.append({
                        'type': 'stuck_document',
                        'severity': 'warning',
                        'document_id': doc['id'],
                        'file_name': doc['original_file_name'],
                        'status': doc['initial_processing_status'],
                        'hours_stuck': round(hours_stuck, 2)
                    })
                    
            return stuck_docs.data
        except Exception as e:
            logger.error(f"Error checking stuck documents: {e}")
            self.issues.append({
                'type': 'health_check_error',
                'severity': 'error',
                'message': f"Could not check stuck documents: {str(e)}"
            })
            return []
    
    def check_failed_textract_jobs(self) -> List[Dict]:
        """Find failed Textract jobs"""
        try:
            failed_jobs = self.db.client.table('textract_jobs').select(
                'job_id', 'source_document_id', 'error_message', 'created_at'
            ).in_('job_status', ['failed', 'FAILED']).execute()
            
            if failed_jobs.data:
                for job in failed_jobs.data:
                    self.issues.append({
                        'type': 'failed_textract_job',
                        'severity': 'error',
                        'job_id': job['job_id'][:20] + '...',
                        'document_id': job['source_document_id'],
                        'error': job.get('error_message', 'Unknown error')[:100]
                    })
                    
            return failed_jobs.data
        except Exception as e:
            logger.error(f"Error checking failed Textract jobs: {e}")
            return []
    
    def check_queue_health(self) -> Dict:
        """Check Celery queue health via Redis"""
        try:
            redis_mgr = get_redis_manager()
            if not redis_mgr or not redis_mgr.is_available():
                return {
                    'healthy': False,
                    'error': 'Redis not available'
                }
            
            redis_client = redis_mgr.get_client()
            
            # Check Celery queues in Redis
            queue_lengths = {}
            for queue in ['default', 'ocr', 'text', 'entity', 'graph']:
                try:
                    length = redis_client.llen(queue)
                    queue_lengths[queue] = length
                except:
                    queue_lengths[queue] = 0
            
            # Get Celery-based status from source_documents
            response = self.db.client.table('source_documents').select(
                'celery_status'
            ).execute()
            
            celery_status_counts = {}
            for item in response.data:
                status = item.get('celery_status', 'unknown')
                celery_status_counts[status] = celery_status_counts.get(status, 0) + 1
            
            # Calculate total queued tasks
            total_queued = sum(queue_lengths.values())
            
            # Determine health status
            healthy = True
            if total_queued > 1000:
                healthy = False
                self.issues.append({
                    'type': 'queue_backlog',
                    'severity': 'warning',
                    'message': f'High queue depth: {total_queued} tasks pending'
                })
            
            # Check for too many errors
            error_count = sum(1 for status, count in celery_status_counts.items() 
                            if status.endswith('_failed') or status.startswith('error_'))
            if error_count > 10:
                healthy = False
                self.issues.append({
                    'type': 'high_error_rate',
                    'severity': 'error',
                    'message': f'{error_count} documents in error state'
                })
            
            return {
                'healthy': healthy,
                'queue_lengths': queue_lengths,
                'total_queued': total_queued,
                'celery_status_counts': celery_status_counts,
                'error_count': error_count
            }
        except Exception as e:
            logger.error(f"Error checking queue health: {e}")
            return {}
    
    def check_database_triggers(self) -> bool:
        """Test if database triggers are causing issues"""
        try:
            # Try a simple update that might trigger the error
            test_doc = self.db.client.table('source_documents').select(
                'id'
            ).limit(1).execute()
            
            if test_doc.data:
                doc_id = test_doc.data[0]['id']
                # Try to update last_modified_at which should be safe
                self.db.client.table('source_documents').update({
                    'last_modified_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', doc_id).execute()
                
            return True
        except Exception as e:
            if 'record "new" has no field "status"' in str(e):
                self.issues.append({
                    'type': 'trigger_error',
                    'severity': 'critical',
                    'message': 'Database trigger referencing non-existent status field'
                })
                return False
            return True
    
    def check_redis_health(self) -> Dict:
        """Check Redis connection and performance"""
        try:
            redis_mgr = get_redis_manager()
            
            # Test connection
            start_time = time.time()
            is_available = redis_mgr.is_available()
            ping_time = (time.time() - start_time) * 1000  # ms
            
            if not is_available:
                self.issues.append({
                    'type': 'redis_unavailable',
                    'severity': 'warning',
                    'message': 'Redis connection unavailable - caching disabled'
                })
                return {'available': False}
            
            # Get Redis info
            client = redis_mgr.get_client()
            info = client.info()
            
            # Check memory usage
            used_memory_mb = info.get('used_memory', 0) / (1024 * 1024)
            max_memory_mb = info.get('maxmemory', 0) / (1024 * 1024)
            
            if max_memory_mb > 0 and used_memory_mb / max_memory_mb > 0.9:
                self.issues.append({
                    'type': 'redis_memory_high',
                    'severity': 'warning',
                    'message': f'Redis memory usage high: {used_memory_mb:.1f}/{max_memory_mb:.1f} MB'
                })
            
            # Get cache metrics
            cache_metrics = redis_mgr._metrics.get_metrics()
            
            # Log pool stats (this will only log if interval has passed)
            redis_mgr.log_pool_stats()
            
            return {
                'available': True,
                'ping_ms': round(ping_time, 2),
                'used_memory_mb': round(used_memory_mb, 2),
                'max_memory_mb': round(max_memory_mb, 2) if max_memory_mb > 0 else 'unlimited',
                'connected_clients': info.get('connected_clients', 0),
                'total_commands_processed': info.get('total_commands_processed', 0),
                'keyspace_hits': info.get('keyspace_hits', 0),
                'keyspace_misses': info.get('keyspace_misses', 0),
                'hit_rate': round(info.get('keyspace_hits', 0) / 
                               max(info.get('keyspace_hits', 0) + info.get('keyspace_misses', 0), 1) * 100, 2),
                'cache_metrics': cache_metrics,
                'evicted_keys': info.get('evicted_keys', 0),
                'expired_keys': info.get('expired_keys', 0)
            }
        except Exception as e:
            logger.error(f"Error checking Redis health: {e}")
            self.issues.append({
                'type': 'redis_health_check_error',
                'severity': 'error',
                'message': f'Failed to check Redis health: {str(e)}'
            })
            return {'available': False, 'error': str(e)}
    
    def generate_report(self) -> Dict:
        """Generate comprehensive health report"""
        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': 'healthy',
            'issues': self.issues,
            'metrics': {}
        }
        
        # Run all checks
        logger.info("Running pipeline health checks...")
        
        # Check stuck documents
        stuck_docs = self.check_stuck_documents(hours_threshold=1)
        report['metrics']['stuck_documents'] = len(stuck_docs)
        
        # Check failed jobs
        failed_jobs = self.check_failed_textract_jobs()
        report['metrics']['failed_textract_jobs'] = len(failed_jobs)
        
        # Check queue health
        queue_stats = self.check_queue_health()
        report['metrics']['queue_stats'] = queue_stats
        
        # Check triggers
        triggers_ok = self.check_database_triggers()
        report['metrics']['database_triggers_ok'] = triggers_ok
        
        # Check Redis health
        redis_health = self.check_redis_health()
        report['metrics']['redis_health'] = redis_health
        
        # Determine overall status
        if any(issue['severity'] == 'critical' for issue in self.issues):
            report['status'] = 'critical'
        elif any(issue['severity'] == 'error' for issue in self.issues):
            report['status'] = 'unhealthy'
        elif any(issue['severity'] == 'warning' for issue in self.issues):
            report['status'] = 'degraded'
            
        return report
    
    def print_report(self, report: Dict):
        """Print formatted health report"""
        print("\n" + "="*60)
        print("DOCUMENT PIPELINE HEALTH REPORT")
        print("="*60)
        print(f"Timestamp: {report['timestamp']}")
        print(f"Overall Status: {report['status'].upper()}")
        print("\nMETRICS:")
        print(f"  Stuck Documents: {report['metrics'].get('stuck_documents', 0)}")
        print(f"  Failed Textract Jobs: {report['metrics'].get('failed_textract_jobs', 0)}")
        
        if 'queue_stats' in report['metrics']:
            print("\nQUEUE STATUS:")
            for status, count in report['metrics']['queue_stats'].items():
                print(f"  {status}: {count}")
        
        if 'redis_health' in report['metrics'] and report['metrics']['redis_health'].get('available'):
            redis = report['metrics']['redis_health']
            print("\nREDIS STATUS:")
            print(f"  Available: {redis.get('available', False)}")
            print(f"  Ping: {redis.get('ping_ms', 'N/A')} ms")
            print(f"  Memory: {redis.get('used_memory_mb', 0):.1f}/{redis.get('max_memory_mb', 'unlimited')} MB")
            print(f"  Hit Rate: {redis.get('hit_rate', 0)}%")
            print(f"  Connected Clients: {redis.get('connected_clients', 0)}")
            
            if 'cache_metrics' in redis and not redis['cache_metrics'].get('error'):
                metrics = redis['cache_metrics']
                print(f"\n  Cache Performance:")
                print(f"    Hits: {metrics.get('hits', 0)}")
                print(f"    Misses: {metrics.get('misses', 0)}")
                print(f"    Sets: {metrics.get('sets', 0)}")
                print(f"    Hit Rate: {metrics.get('hit_rate', 0)}%")
        
        if report['issues']:
            print(f"\nISSUES FOUND ({len(report['issues'])}):")
            for issue in report['issues']:
                print(f"\n  [{issue['severity'].upper()}] {issue['type']}")
                for key, value in issue.items():
                    if key not in ['type', 'severity']:
                        print(f"    {key}: {value}")
        else:
            print("\nNo issues found - system healthy!")
            
        print("\n" + "="*60)


def main():
    """Run health check and print report"""
    checker = PipelineHealthChecker()
    report = checker.generate_report()
    checker.print_report(report)
    
    # Return exit code based on status
    if report['status'] == 'critical':
        return 2
    elif report['status'] == 'unhealthy':
        return 1
    else:
        return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())