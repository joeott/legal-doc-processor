#!/usr/bin/env python3
"""
Standalone Pipeline Monitor - Works without complex imports
"""

import os
import sys
import time
import json
import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, Counter
import traceback

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))

# Import with proper error handling
try:
    from supabase_utils import SupabaseManager
    from redis_utils import get_redis_manager, CacheMetrics
    from cache_keys import CacheKeys
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure you're running from the project directory")
    sys.exit(1)

# Suppress logging during monitoring
logging.getLogger().setLevel(logging.ERROR)

class StandalonePipelineMonitor:
    """Standalone monitoring class for the OCR pipeline"""
    
    def __init__(self, refresh_interval: int = 10):
        """Initialize the monitor with connections to all services"""
        self.refresh_interval = refresh_interval
        self.start_time = datetime.now()
        
        # Initialize connections
        try:
            self.db_manager = SupabaseManager()
            self.redis_manager = get_redis_manager()
            self.redis_client = self.redis_manager.get_client()
            self.cache_metrics = CacheMetrics(self.redis_manager)
        except Exception as e:
            print(f"Failed to initialize connections: {e}")
            sys.exit(1)
        
        # Thresholds
        self.STALLED_PROCESSING_MINUTES = 30
        self.RECENT_HOURS = 1
        self.DAILY_HOURS = 24
        self.MAX_RETRIES = 3  # Default max retries
        
        # Status emojis
        self.STATUS_EMOJIS = {
            'pending': '⏳',
            'processing': '⚙️',
            'completed': '✅',
            'failed': '❌',
            'healthy': '🟢',
            'warning': '🟡',
            'error': '🔴',
            'info': 'ℹ️'
        }
        
        # Celery queue names
        self.CELERY_QUEUES = ['default', 'ocr', 'text', 'entity', 'graph', 'embeddings']
        
        # Import session tracking
        self.show_imports = False
    
    def clear_screen(self):
        """Clear the terminal screen"""
        os.system('clear' if os.name == 'posix' else 'cls')
    
    def get_supabase_queue_stats(self) -> Dict[str, Any]:
        """Get statistics from source_documents using celery_status"""
        try:
            # Get celery status counts
            response = self.db_manager.client.table('source_documents')\
                .select('celery_status, initial_processing_status')\
                .execute()
            
            celery_status_counts = Counter(item.get('celery_status', 'unknown') for item in response.data)
            
            # Get documents by processing stage (including image processing)
            stages = {
                'pending': 0,
                'ocr_processing': 0,
                'ocr_complete': 0,
                'image_queued': 0,
                'image_processing': 0,
                'image_completed': 0,
                'image_failed': 0,
                'image_failed_with_fallback': 0,
                'text_processing': 0,
                'entity_extraction': 0,
                'entity_resolution': 0,
                'graph_building': 0,
                'completed': 0,
                'errors': 0
            }
            
            for item in response.data:
                status = item.get('celery_status', '')
                if status.endswith('_failed') or status.startswith('error_'):
                    stages['errors'] += 1
                elif status in stages:
                    stages[status] += 1
                elif status == 'processing':
                    stages['ocr_processing'] += 1
                else:
                    stages['pending'] += 1
            
            # Get average age of pending items
            pending_response = self.db_manager.client.table('source_documents')\
                .select('created_at')\
                .or_('celery_status.eq.pending,celery_status.is.null')\
                .execute()
            
            avg_pending_age = None
            if pending_response.data:
                now = datetime.now(timezone.utc)
                ages = []
                for item in pending_response.data:
                    created = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
                    ages.append((now - created).total_seconds())
                avg_pending_age = sum(ages) / len(ages) / 60  # Convert to minutes
            
            # Get stalled processing items
            stalled_time = datetime.now(timezone.utc) - timedelta(minutes=self.STALLED_PROCESSING_MINUTES)
            stalled_response = self.db_manager.client.table('source_documents')\
                .select('id, document_uuid, file_name, celery_status, last_modified_at')\
                .in_('celery_status', ['ocr_processing', 'text_processing', 'entity_extraction', 
                                      'entity_resolution', 'graph_building'])\
                .lt('last_modified_at', stalled_time.isoformat())\
                .execute()
            
            stalled_items = stalled_response.data
            
            # Get recent failed items
            failed_response = self.db_manager.client.table('source_documents')\
                .select('id, document_uuid, file_name, celery_status, error_message, last_modified_at')\
                .or_('celery_status.like.%_failed,initial_processing_status.like.error_%')\
                .order('last_modified_at', desc=True)\
                .limit(5)\
                .execute()
            
            recent_failures = failed_response.data
            
            return {
                'celery_stages': stages,
                'celery_status_counts': dict(celery_status_counts),
                'avg_pending_age': avg_pending_age,
                'stalled_items': stalled_items,
                'recent_failures': recent_failures,
                'total_documents': len(response.data)
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_image_processing_stats(self) -> Dict[str, Any]:
        """Get detailed image processing statistics and costs"""
        try:
            # Get image processing stats
            image_stats = self.db_manager.get_image_processing_stats()
            
            # Get image processing costs
            image_costs = self.db_manager.get_image_processing_costs()
            
            # Get recent image processing activity (last hour)
            recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
            recent_response = self.db_manager.client.table('source_documents')\
                .select('celery_status, image_analysis_confidence, image_type, o4_mini_tokens_used')\
                .eq('file_category', 'image')\
                .gte('last_modified_at', recent_time.isoformat())\
                .execute()
            
            recent_activity = {
                'processed_last_hour': len(recent_response.data),
                'avg_confidence': 0.0,
                'total_tokens_last_hour': 0
            }
            
            if recent_response.data:
                confidences = [doc.get('image_analysis_confidence', 0) or 0 for doc in recent_response.data]
                tokens = [doc.get('o4_mini_tokens_used', 0) or 0 for doc in recent_response.data]
                
                recent_activity['avg_confidence'] = sum(confidences) / len(confidences) if confidences else 0.0
                recent_activity['total_tokens_last_hour'] = sum(tokens)
            
            return {
                'stats': image_stats,
                'costs': image_costs,
                'recent_activity': recent_activity
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def get_celery_queue_stats(self) -> Dict[str, Any]:
        """Get statistics from Celery queues via Redis"""
        try:
            queue_stats = {}
            
            # Get queue lengths for all defined queues
            for queue_name in self.CELERY_QUEUES:
                try:
                    # Celery uses the queue name directly as a Redis list key
                    queue_length = self.redis_client.llen(queue_name)
                    queue_stats[queue_name] = queue_length
                except:
                    queue_stats[queue_name] = 0
            
            # Get active tasks count (Redis pattern for Celery active tasks)
            active_pattern = 'celery-task-meta-*'
            active_keys = []
            try:
                active_keys = list(self.redis_client.scan_iter(match=active_pattern, count=100))
            except:
                pass
            
            # Categorize active tasks by type
            active_by_type = defaultdict(int)
            for key in active_keys[:50]:  # Sample first 50 for performance
                try:
                    task_data = self.redis_client.get(key)
                    if task_data:
                        task_info = json.loads(task_data)
                        task_name = task_info.get('task', '').split('.')[-1]
                        if 'ocr' in task_name:
                            active_by_type['ocr'] += 1
                        elif 'text' in task_name:
                            active_by_type['text'] += 1
                        elif 'entity' in task_name:
                            active_by_type['entity'] += 1
                        elif 'graph' in task_name:
                            active_by_type['graph'] += 1
                        else:
                            active_by_type['other'] += 1
                except:
                    pass
            
            return {
                'queue_lengths': queue_stats,
                'total_active_tasks': len(active_keys),
                'active_by_type': dict(active_by_type)
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_redis_cache_stats(self) -> Dict[str, Any]:
        """Get Redis cache and state statistics"""
        try:
            # Get cache metrics
            metrics = self.cache_metrics.get_metrics()
            
            # Count document state keys using the get_pattern method
            doc_state_pattern = CacheKeys.get_pattern(CacheKeys.DOC_STATE)
            doc_state_count = 0
            try:
                doc_state_count = len(list(self.redis_client.scan_iter(match=doc_state_pattern, count=100)))
            except:
                pass
            
            # Count processing locks
            lock_pattern = CacheKeys.get_pattern(CacheKeys.DOC_PROCESSING_LOCK)
            lock_count = 0
            try:
                lock_count = len(list(self.redis_client.scan_iter(match=lock_pattern, count=100)))
            except:
                pass
            
            # Count Textract job status keys
            textract_pattern = CacheKeys.get_pattern(CacheKeys.TEXTRACT_JOB_STATUS)
            textract_count = 0
            try:
                textract_count = len(list(self.redis_client.scan_iter(match=textract_pattern, count=100)))
            except:
                pass
            
            # Test Redis connection
            ping_response = False
            try:
                ping_response = self.redis_client.ping()
            except:
                pass
            
            return {
                'connected': ping_response,
                'cache_metrics': metrics,
                'doc_state_count': doc_state_count,
                'lock_count': lock_count,
                'textract_job_count': textract_count
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_database_table_stats(self) -> Dict[str, Any]:
        """Get statistics from various Supabase tables"""
        try:
            stats = {}
            
            # Source documents by status
            try:
                source_docs = self.db_manager.client.table('source_documents')\
                    .select('initial_processing_status', count='exact')\
                    .execute()
                
                source_status_counts = Counter(item['initial_processing_status'] for item in source_docs.data)
                stats['source_documents'] = {
                    'total': source_docs.count,
                    'by_status': dict(source_status_counts)
                }
            except:
                stats['source_documents'] = {'error': 'Failed to fetch'}
            
            # Neo4j documents by status
            try:
                neo4j_docs = self.db_manager.client.table('neo4j_documents')\
                    .select('processingStatus', count='exact')\
                    .execute()
                
                neo4j_status_counts = Counter(item['processingStatus'] for item in neo4j_docs.data)
                stats['neo4j_documents'] = {
                    'total': neo4j_docs.count,
                    'by_status': dict(neo4j_status_counts)
                }
            except:
                stats['neo4j_documents'] = {'error': 'Failed to fetch'}
            
            # Textract jobs by status
            try:
                textract_jobs = self.db_manager.client.table('textract_jobs')\
                    .select('job_status', count='exact')\
                    .execute()
                
                textract_status_counts = Counter(item['job_status'] for item in textract_jobs.data)
                stats['textract_jobs'] = {
                    'total': textract_jobs.count,
                    'by_status': dict(textract_status_counts)
                }
            except:
                stats['textract_jobs'] = {'error': 'Failed to fetch'}
            
            # Get counts for other tables
            for table_name in ['neo4j_chunks', 'neo4j_entity_mentions', 
                              'neo4j_canonical_entities', 'neo4j_relationships_staging']:
                try:
                    response = self.db_manager.client.table(table_name)\
                        .select('*', count='exact', head=True)\
                        .execute()
                    stats[table_name] = response.count
                except:
                    stats[table_name] = 0
            
            return stats
        except Exception as e:
            return {'error': str(e)}
    
    def get_pipeline_throughput(self) -> Dict[str, Any]:
        """Get overall pipeline throughput and health metrics"""
        try:
            now = datetime.now(timezone.utc)
            hour_ago = now - timedelta(hours=self.RECENT_HOURS)
            day_ago = now - timedelta(hours=self.DAILY_HOURS)
            
            # Documents completed in last hour
            hourly_count = 0
            try:
                hourly_response = self.db_manager.client.table('source_documents')\
                    .select('id, intake_timestamp, ocr_completed_at')\
                    .eq('initial_processing_status', 'completed')\
                    .gte('ocr_completed_at', hour_ago.isoformat())\
                    .execute()
                hourly_count = len(hourly_response.data)
            except:
                pass
            
            # Documents completed in last 24 hours
            daily_count = 0
            processing_times = []
            try:
                daily_response = self.db_manager.client.table('source_documents')\
                    .select('id, intake_timestamp, ocr_completed_at')\
                    .eq('initial_processing_status', 'completed')\
                    .gte('ocr_completed_at', day_ago.isoformat())\
                    .execute()
                
                daily_count = len(daily_response.data)
                
                # Calculate average processing times
                for doc in daily_response.data[:50]:  # Sample for performance
                    if doc.get('intake_timestamp') and doc.get('ocr_completed_at'):
                        try:
                            start = datetime.fromisoformat(doc['intake_timestamp'].replace('Z', '+00:00'))
                            end = datetime.fromisoformat(doc['ocr_completed_at'].replace('Z', '+00:00'))
                            processing_times.append((end - start).total_seconds())
                        except:
                            pass
            except:
                pass
            
            avg_processing_time = None
            p95_processing_time = None
            if processing_times:
                avg_processing_time = sum(processing_times) / len(processing_times) / 60  # Minutes
                sorted_times = sorted(processing_times)
                p95_index = int(len(sorted_times) * 0.95)
                p95_processing_time = sorted_times[p95_index] / 60 if p95_index < len(sorted_times) else None
            
            # Error rate calculation
            failed_count = 0
            try:
                failed_response = self.db_manager.client.table('source_documents')\
                    .select('id', count='exact')\
                    .eq('initial_processing_status', 'failed')\
                    .gte('updated_at', day_ago.isoformat())\
                    .execute()
                failed_count = failed_response.count
            except:
                pass
            
            total_processed = daily_count + failed_count
            error_rate = (failed_count / total_processed * 100) if total_processed > 0 else 0
            
            return {
                'hourly_completed': hourly_count,
                'daily_completed': daily_count,
                'avg_processing_time': avg_processing_time,
                'p95_processing_time': p95_processing_time,
                'error_rate': error_rate,
                'total_processed_24h': total_processed
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_import_sessions(self) -> List[Dict[str, Any]]:
        """Get active import sessions"""
        try:
            # Check if import_sessions table exists
            result = self.db_manager.client.table('import_sessions')\
                .select('id, case_name, total_files, processed_files, failed_files, total_cost, status')\
                .eq('status', 'active')\
                .order('started_at', desc=True)\
                .limit(5)\
                .execute()
            
            return result.data if result.data else []
        except Exception:
            # Table might not exist yet
            return []
    
    def format_time_delta(self, minutes: Optional[float]) -> str:
        """Format time delta in human-readable format"""
        if minutes is None:
            return "N/A"
        
        if minutes < 60:
            return f"{minutes:.1f}m"
        elif minutes < 1440:  # Less than 24 hours
            return f"{minutes/60:.1f}h"
        else:
            return f"{minutes/1440:.1f}d"
    
    def display_dashboard(self, stats: Dict[str, Any]):
        """Display the monitoring dashboard"""
        self.clear_screen()
        
        # Header
        print("=" * 80)
        print(f"🔍 OCR Document Processing Pipeline Monitor (Standalone)")
        print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ⏱️  Refresh: {self.refresh_interval}s")
        print(f"⏳ Uptime: {str(datetime.now() - self.start_time).split('.')[0]}")
        print("=" * 80)
        print()
        
        # Supabase Queue Stats
        queue_stats = stats.get('supabase_queue', {})
        if 'error' in queue_stats:
            print(f"{self.STATUS_EMOJIS['error']} Supabase Queue Error: {queue_stats['error']}")
        else:
            print(f"📋 Document Processing Status (Celery-based)")
            print("-" * 40)
            
            stages = queue_stats.get('celery_stages', {})
            print(f"  {self.STATUS_EMOJIS['pending']} Pending: {stages.get('pending', 0)}")
            print(f"  ⚙️ OCR Processing: {stages.get('ocr_processing', 0)}")
            print(f"  ✓ OCR Complete: {stages.get('ocr_complete', 0)}")
            print(f"  📝 Text Processing: {stages.get('text_processing', 0)}")
            print(f"  🔍 Entity Extraction: {stages.get('entity_extraction', 0)}")
            print(f"  🔗 Entity Resolution: {stages.get('entity_resolution', 0)}")
            print(f"  🕸️ Graph Building: {stages.get('graph_building', 0)}")
            print(f"  {self.STATUS_EMOJIS['completed']} Completed: {stages.get('completed', 0)}")
            print(f"  {self.STATUS_EMOJIS['failed']} Errors: {stages.get('errors', 0)}")
            print(f"  📊 Total Documents: {queue_stats.get('total_documents', 0)}")
            
            if queue_stats.get('avg_pending_age'):
                print(f"  ⏰ Avg Pending Age: {self.format_time_delta(queue_stats['avg_pending_age'])}")
            
            if queue_stats.get('stalled_items'):
                print(f"  🚨 Stalled Items (>{self.STALLED_PROCESSING_MINUTES}m): {len(queue_stats['stalled_items'])}")
                for item in queue_stats['stalled_items'][:3]:
                    doc_uuid = str(item.get('document_uuid', 'Unknown'))[:8]
                    file_name = item.get('file_name', 'Unknown')[:20]
                    status = item.get('celery_status', 'Unknown')
                    print(f"     - {file_name}... ({status})")
        
        print()
        
        # Celery Queue Stats
        celery_stats = stats.get('celery_queues', {})
        if 'error' in celery_stats:
            print(f"{self.STATUS_EMOJIS['error']} Celery Queue Error: {celery_stats['error']}")
        else:
            print(f"🎯 Celery Task Queues (Redis)")
            print("-" * 40)
            
            queue_lengths = celery_stats.get('queue_lengths', {})
            for queue_name, length in queue_lengths.items():
                emoji = '📥' if length > 0 else '📭'
                print(f"  {emoji} {queue_name}: {length}")
            
            print(f"  🔄 Active Tasks: {celery_stats.get('total_active_tasks', 0)}")
            
            active_by_type = celery_stats.get('active_by_type', {})
            if active_by_type:
                print("  📊 Active by Type:")
                for task_type, count in active_by_type.items():
                    print(f"     - {task_type}: {count}")
        
        print()
        
        # Redis Cache Stats
        redis_stats = stats.get('redis_cache', {})
        if 'error' in redis_stats:
            print(f"{self.STATUS_EMOJIS['error']} Redis Error: {redis_stats['error']}")
        else:
            print(f"💾 Redis Cache & State")
            print("-" * 40)
            
            status_emoji = self.STATUS_EMOJIS['healthy'] if redis_stats.get('connected') else self.STATUS_EMOJIS['error']
            print(f"  {status_emoji} Connection: {'Connected' if redis_stats.get('connected') else 'Disconnected'}")
            
            cache_metrics = redis_stats.get('cache_metrics', {})
            if cache_metrics:
                print(f"  📊 Cache Performance:")
                print(f"     - Hits: {cache_metrics.get('hits', 0)}")
                print(f"     - Misses: {cache_metrics.get('misses', 0)}")
                print(f"     - Hit Rate: {cache_metrics.get('hit_rate', 0):.1f}%")
            
            print(f"  📄 Document States: {redis_stats.get('doc_state_count', 0)}")
            print(f"  🔒 Processing Locks: {redis_stats.get('lock_count', 0)}")
            print(f"  📋 Textract Jobs: {redis_stats.get('textract_job_count', 0)}")
        
        print()
        
        # Database Table Stats
        db_stats = stats.get('database_tables', {})
        if 'error' in db_stats:
            print(f"{self.STATUS_EMOJIS['error']} Database Error: {db_stats['error']}")
        else:
            print(f"🗄️  Database Tables (Supabase)")
            print("-" * 40)
            
            # Source documents
            source_docs = db_stats.get('source_documents', {})
            if isinstance(source_docs, dict) and 'error' not in source_docs:
                print(f"  📄 Source Documents: {source_docs.get('total', 0)}")
                for status, count in source_docs.get('by_status', {}).items():
                    if status and count > 0:
                        print(f"     - {status}: {count}")
            
            # Neo4j documents
            neo4j_docs = db_stats.get('neo4j_documents', {})
            if isinstance(neo4j_docs, dict) and 'error' not in neo4j_docs:
                print(f"  🔗 Neo4j Documents: {neo4j_docs.get('total', 0)}")
            
            # Other tables
            print(f"  📝 Chunks: {db_stats.get('neo4j_chunks', 0)}")
            print(f"  👤 Entity Mentions: {db_stats.get('neo4j_entity_mentions', 0)}")
            print(f"  🏢 Canonical Entities: {db_stats.get('neo4j_canonical_entities', 0)}")
            print(f"  🔗 Relationships: {db_stats.get('neo4j_relationships_staging', 0)}")
        
        print()
        
        # Image Processing Stats (New Section)
        image_stats = stats.get('image_processing', {})
        if 'error' in image_stats:
            print(f"{self.STATUS_EMOJIS['error']} Image Processing Error: {image_stats['error']}")
        else:
            print(f"🖼️  Image Processing (o4-mini Vision)")
            print("-" * 40)
            
            img_stats = image_stats.get('stats', {})
            img_costs = image_stats.get('costs', {})
            img_recent = image_stats.get('recent_activity', {})
            
            # Status breakdown
            print(f"  📊 Total Images: {img_stats.get('total_images', 0)}")
            if img_stats.get('image_completed', 0) > 0:
                print(f"  ✅ Completed: {img_stats.get('image_completed', 0)}")
            if img_stats.get('image_processing', 0) > 0:
                print(f"  ⚙️  Processing: {img_stats.get('image_processing', 0)}")
            if img_stats.get('image_queued', 0) > 0:
                print(f"  ⏳ Queued: {img_stats.get('image_queued', 0)}")
            if img_stats.get('image_failed', 0) > 0:
                print(f"  ❌ Failed: {img_stats.get('image_failed', 0)}")
            if img_stats.get('image_failed_with_fallback', 0) > 0:
                print(f"  ⚠️  Failed (with fallback): {img_stats.get('image_failed_with_fallback', 0)}")
            
            # Cost information
            if img_costs.get('total_cost', 0) > 0:
                print(f"  💰 Total Cost: ${img_costs.get('total_cost', 0.0):.4f}")
                print(f"  💵 Avg Cost/Image: ${img_costs.get('average_cost_per_image', 0.0):.4f}")
                print(f"  🔢 Total Tokens: {img_costs.get('total_tokens', 0):,}")
            
            # Recent activity
            if img_recent.get('processed_last_hour', 0) > 0:
                print(f"  🕐 Processed (1h): {img_recent.get('processed_last_hour', 0)}")
                if img_recent.get('avg_confidence', 0) > 0:
                    print(f"  🎯 Avg Confidence: {img_recent.get('avg_confidence', 0.0):.2f}")
                print(f"  🔤 Tokens (1h): {img_recent.get('total_tokens_last_hour', 0):,}")

        print()
        
        # Pipeline Throughput
        throughput = stats.get('pipeline_throughput', {})
        if 'error' in throughput:
            print(f"{self.STATUS_EMOJIS['error']} Throughput Error: {throughput['error']}")
        else:
            print(f"📈 Pipeline Throughput & Performance")
            print("-" * 40)
            
            print(f"  ✅ Completed (1h): {throughput.get('hourly_completed', 0)}")
            print(f"  ✅ Completed (24h): {throughput.get('daily_completed', 0)}")
            
            if throughput.get('avg_processing_time'):
                print(f"  ⏱️  Avg Processing Time: {self.format_time_delta(throughput['avg_processing_time'])}")
            
            if throughput.get('p95_processing_time'):
                print(f"  ⏱️  P95 Processing Time: {self.format_time_delta(throughput['p95_processing_time'])}")
            
            error_rate = throughput.get('error_rate', 0)
            error_emoji = self.STATUS_EMOJIS['healthy'] if error_rate < 5 else (
                self.STATUS_EMOJIS['warning'] if error_rate < 10 else self.STATUS_EMOJIS['error']
            )
            print(f"  {error_emoji} Error Rate (24h): {error_rate:.1f}%")
        
        print()
        
        # Recent Failures
        if queue_stats and queue_stats.get('recent_failures'):
            print(f"❌ Recent Failures")
            print("-" * 40)
            for failure in queue_stats['recent_failures'][:3]:
                doc_uuid = str(failure.get('document_uuid', 'Unknown'))[:8]
                file_name = failure.get('file_name', 'Unknown')[:25]
                status = failure.get('celery_status', failure.get('initial_processing_status', 'Unknown'))
                error = failure.get('error_message', 'No error message')[:50]
                print(f"  • {file_name} ({status}): {error}...")
        
        # Import Sessions (if available)
        import_sessions = self.get_import_sessions()
        if import_sessions:
            print()
            print(f"📦 Active Import Sessions")
            print("-" * 40)
            for session in import_sessions[:3]:  # Show top 3
                progress = (session.get('processed_files', 0) / session.get('total_files', 1)) * 100
                status_emoji = '🔄' if session['status'] == 'active' else '✅'
                print(f"  {status_emoji} {session['case_name'][:30]}")
                print(f"     Progress: {session.get('processed_files', 0)}/{session.get('total_files', 0)} ({progress:.1f}%)")
                if session.get('failed_files', 0) > 0:
                    print(f"     ⚠️  Failed: {session['failed_files']}")
                if session.get('total_cost'):
                    print(f"     💰 Cost: ${session['total_cost']:.2f}")
        
        print()
        print("=" * 80)
        print("Press Ctrl+C to exit")
    
    def run(self):
        """Main monitoring loop"""
        try:
            while True:
                try:
                    # Gather all statistics
                    all_stats = {
                        'supabase_queue': self.get_supabase_queue_stats(),
                        'celery_queues': self.get_celery_queue_stats(),
                        'redis_cache': self.get_redis_cache_stats(),
                        'database_tables': self.get_database_table_stats(),
                        'pipeline_throughput': self.get_pipeline_throughput(),
                        'image_processing': self.get_image_processing_stats()
                    }
                    
                    # Display dashboard
                    self.display_dashboard(all_stats)
                    
                    # Wait for refresh interval
                    time.sleep(self.refresh_interval)
                    
                except Exception as e:
                    self.clear_screen()
                    print(f"{self.STATUS_EMOJIS['error']} Monitoring Error: {str(e)}")
                    print(f"\nTraceback:\n{traceback.format_exc()}")
                    print(f"\nRetrying in {self.refresh_interval} seconds...")
                    time.sleep(self.refresh_interval)
                    
        except KeyboardInterrupt:
            print("\n\n👋 Monitoring stopped by user.")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Monitor the OCR Document Processing Pipeline (Standalone)'
    )
    parser.add_argument(
        '--refresh-interval',
        type=int,
        default=10,
        help='Refresh interval in seconds (default: 10)'
    )
    parser.add_argument(
        '--stalled-threshold',
        type=int,
        default=30,
        help='Minutes before marking processing items as stalled (default: 30)'
    )
    
    args = parser.parse_args()
    
    # Create and run monitor
    monitor = StandalonePipelineMonitor(refresh_interval=args.refresh_interval)
    if args.stalled_threshold:
        monitor.STALLED_PROCESSING_MINUTES = args.stalled_threshold
    
    print("🚀 Starting Standalone Pipeline Monitor...")
    print(f"Refresh interval: {args.refresh_interval} seconds")
    print(f"Stalled threshold: {args.stalled_threshold} minutes")
    print("\nConnecting to services...")
    time.sleep(1)
    
    monitor.run()


if __name__ == '__main__':
    main()