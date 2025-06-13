#!/usr/bin/env python3
"""
Enhanced Pipeline Monitor with Comprehensive Cache Visualization
"""

import sys
import os
import time
import json
import argparse
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys
from scripts.cache_metrics import CacheMetrics

class EnhancedPipelineMonitor:
    """Enhanced monitoring with cache visualization"""
    
    STATUS_EMOJIS = {
        'pending': '⏳',
        'processing': '🔄',
        'completed': '✅',
        'failed': '❌',
        'error': '❌',
        'healthy': '✅',
        'warning': '⚠️'
    }
    
    def __init__(self, refresh_interval: int = 10):
        self.refresh_interval = refresh_interval
        self.start_time = datetime.now()
        self.db_manager = SupabaseManager()
        self.redis_mgr = get_redis_manager()
        self.cache_metrics = CacheMetrics()
        
    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def get_cache_details(self) -> Dict[str, Any]:
        """Get detailed cache statistics"""
        if not self.redis_mgr or not self.redis_mgr.is_available():
            return {'error': 'Redis not available'}
        
        try:
            client = self.redis_mgr.get_client()
            
            # Get memory info
            memory_info = client.info('memory')
            
            # Count different cache types
            cache_patterns = {
                'OCR Results': CacheKeys.DOC_OCR_RESULT.replace('{document_uuid}', '*'),
                'Cleaned Text': CacheKeys.DOC_CLEANED_TEXT.replace('{document_uuid}', '*'),
                'Chunk Lists': CacheKeys.DOC_CHUNKS_LIST.replace('{document_uuid}', '*'),
                'Chunk Texts': CacheKeys.DOC_CHUNK_TEXT.replace('{chunk_uuid}', '*'),
                'Entity Mentions': CacheKeys.DOC_ALL_EXTRACTED_MENTIONS.replace('{document_uuid}', '*'),
                'Canonical Entities': CacheKeys.DOC_CANONICAL_ENTITIES.replace('{document_uuid}', '*'),
                'Resolved Mentions': CacheKeys.DOC_RESOLVED_MENTIONS.replace('{document_uuid}', '*'),
                'Document States': CacheKeys.DOC_STATE.replace('{document_uuid}', '*'),
                'Processing Locks': 'processing_lock:*',
                'Cache Locks': 'lock:cache_update:*'
            }
            
            cache_counts = {}
            total_keys = 0
            
            for cache_type, pattern in cache_patterns.items():
                count = 0
                for _ in client.scan_iter(match=pattern + '*', count=1000):
                    count += 1
                    if count >= 10000:  # Limit scanning
                        count = '10000+'
                        break
                cache_counts[cache_type] = count
                if isinstance(count, int):
                    total_keys += count
            
            # Get cache hit/miss stats
            metrics = self.cache_metrics.get_metrics()
            
            # Calculate hit rate
            total_requests = metrics.get('hits', 0) + metrics.get('misses', 0)
            hit_rate = (metrics.get('hits', 0) / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'memory': {
                    'used': memory_info.get('used_memory_human', 'N/A'),
                    'peak': memory_info.get('used_memory_peak_human', 'N/A'),
                    'rss': memory_info.get('used_memory_rss_human', 'N/A'),
                    'dataset_percent': memory_info.get('used_memory_dataset_perc', 'N/A')
                },
                'cache_counts': cache_counts,
                'total_keys': total_keys,
                'performance': {
                    'hits': metrics.get('hits', 0),
                    'misses': metrics.get('misses', 0),
                    'hit_rate': f"{hit_rate:.1f}%",
                    'total_requests': total_requests
                }
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_processing_times(self) -> Dict[str, Any]:
        """Get average processing times by stage"""
        try:
            # Get recent completed documents
            one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            
            recent_docs = self.db_manager.client.table('source_documents').select(
                'document_uuid, created_at, last_modified_at, processing_version'
            ).eq('processing_status', 'completed').gte(
                'last_modified_at', one_hour_ago
            ).execute()
            
            if not recent_docs.data:
                return {'message': 'No recently completed documents'}
            
            # Calculate processing times
            times_by_version = defaultdict(list)
            
            for doc in recent_docs.data:
                created = datetime.fromisoformat(doc['created_at'].replace('Z', '+00:00'))
                modified = datetime.fromisoformat(doc['last_modified_at'].replace('Z', '+00:00'))
                processing_time = (modified - created).total_seconds()
                version = doc.get('processing_version', 1)
                times_by_version[version].append(processing_time)
            
            # Calculate averages
            avg_times = {}
            for version, times in times_by_version.items():
                avg_times[f"v{version}"] = {
                    'avg_seconds': round(sum(times) / len(times), 1),
                    'count': len(times)
                }
            
            # Calculate improvement if multiple versions
            improvement = None
            if 1 in times_by_version and len(times_by_version) > 1:
                v1_avg = sum(times_by_version[1]) / len(times_by_version[1])
                latest_version = max(times_by_version.keys())
                latest_avg = sum(times_by_version[latest_version]) / len(times_by_version[latest_version])
                improvement = round((v1_avg - latest_avg) / v1_avg * 100, 1)
            
            return {
                'by_version': avg_times,
                'improvement_percent': improvement
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def get_stage_timings(self) -> Dict[str, Any]:
        """Get timing for each processing stage"""
        if not self.redis_mgr or not self.redis_mgr.is_available():
            return {'error': 'Redis not available'}
        
        try:
            # Sample recent documents
            recent_docs = self.db_manager.client.table('source_documents').select(
                'document_uuid'
            ).eq('processing_status', 'completed').limit(10).execute()
            
            if not recent_docs.data:
                return {'message': 'No completed documents'}
            
            stage_timings = defaultdict(list)
            
            for doc in recent_docs.data:
                document_uuid = doc['document_uuid']
                state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
                
                # Get state from Redis
                state = self.redis_mgr.hgetall(state_key)
                
                # Extract stage timestamps
                stages = ['ocr', 'doc_node_creation', 'chunking', 'ner', 'resolution', 'relationships']
                prev_time = None
                
                for stage in stages:
                    start_key = f"{stage}_timestamp"
                    if start_key in state and state.get(f"{stage}_status") == 'completed':
                        timestamp = datetime.fromisoformat(state[start_key])
                        if prev_time:
                            duration = (timestamp - prev_time).total_seconds()
                            stage_timings[stage].append(duration)
                        prev_time = timestamp
            
            # Calculate averages
            avg_timings = {}
            for stage, times in stage_timings.items():
                if times:
                    avg_timings[stage] = round(sum(times) / len(times), 1)
            
            return avg_timings
            
        except Exception as e:
            return {'error': str(e)}
    
    def display_dashboard(self):
        """Display the enhanced monitoring dashboard"""
        self.clear_screen()
        
        # Header
        print("=" * 100)
        print(f"🚀 Enhanced Pipeline Monitor with Cache Analytics")
        print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ⏱️  Refresh: {self.refresh_interval}s")
        print(f"⏳ Uptime: {str(datetime.now() - self.start_time).split('.')[0]}")
        print("=" * 100)
        print()
        
        # Cache Details
        cache_details = self.get_cache_details()
        if 'error' not in cache_details:
            print("💾 Redis Cache Analytics")
            print("-" * 50)
            
            # Memory usage
            memory = cache_details.get('memory', {})
            print(f"  📊 Memory Usage:")
            print(f"     Used: {memory.get('used', 'N/A')} | Peak: {memory.get('peak', 'N/A')}")
            print(f"     Dataset: {memory.get('dataset_percent', 'N/A')} | RSS: {memory.get('rss', 'N/A')}")
            
            # Cache performance
            perf = cache_details.get('performance', {})
            print(f"\n  📈 Cache Performance:")
            print(f"     Hits: {perf.get('hits', 0):,} | Misses: {perf.get('misses', 0):,}")
            print(f"     Hit Rate: {perf.get('hit_rate', '0%')} | Total Requests: {perf.get('total_requests', 0):,}")
            
            # Cache counts
            print(f"\n  📦 Cached Items (Total: {cache_details.get('total_keys', 0):,}):")
            for cache_type, count in cache_details.get('cache_counts', {}).items():
                if count > 0:
                    print(f"     {cache_type}: {count}")
        else:
            print(f"❌ Cache Error: {cache_details['error']}")
        
        print()
        
        # Processing times
        proc_times = self.get_processing_times()
        if 'error' not in proc_times and 'message' not in proc_times:
            print("⏱️  Processing Time Analysis (Last Hour)")
            print("-" * 50)
            
            for version, stats in proc_times.get('by_version', {}).items():
                print(f"  {version}: {stats['avg_seconds']}s avg ({stats['count']} docs)")
            
            if proc_times.get('improvement_percent'):
                print(f"  🚀 Cache Improvement: {proc_times['improvement_percent']}% faster")
        
        print()
        
        # Stage timings
        stage_timings = self.get_stage_timings()
        if isinstance(stage_timings, dict) and 'error' not in stage_timings and 'message' not in stage_timings:
            print("📊 Average Stage Processing Times")
            print("-" * 50)
            
            stage_names = {
                'ocr': '📄 OCR',
                'doc_node_creation': '📝 Doc Creation',
                'chunking': '✂️ Chunking',
                'ner': '🔍 Entity Extraction',
                'resolution': '🔗 Resolution',
                'relationships': '🕸️ Relationships'
            }
            
            for stage, avg_time in stage_timings.items():
                display_name = stage_names.get(stage, stage)
                print(f"  {display_name}: {avg_time}s")
        
        print()
        
        # Queue status
        queue_stats = self.get_queue_stats()
        print("📋 Document Processing Queue")
        print("-" * 50)
        
        stages = queue_stats.get('by_stage', {})
        for stage, count in stages.items():
            if count > 0:
                print(f"  {stage}: {count}")
        
        print(f"\n  Total Active: {queue_stats.get('total_active', 0)}")
        print(f"  Completed (24h): {queue_stats.get('completed_24h', 0)}")
        
        print()
        print("=" * 100)
        print("Press Ctrl+C to exit | 📊 = Stats | 💾 = Cache | ⏱️ = Timing")
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get current queue statistics"""
        try:
            # Count by processing status
            statuses = ['pending', 'ocr_processing', 'text_processing', 'entity_extraction', 
                       'entity_resolution', 'graph_building', 'completed', 'failed']
            
            by_stage = {}
            total_active = 0
            
            for status in statuses:
                count_result = self.db_manager.client.table('source_documents').select(
                    'id', count='exact'
                ).eq('processing_status', status).execute()
                
                count = count_result.count if hasattr(count_result, 'count') else 0
                if count > 0:
                    by_stage[status] = count
                    if status not in ['completed', 'failed']:
                        total_active += count
            
            # Count completed in last 24 hours
            yesterday = (datetime.now() - timedelta(days=1)).isoformat()
            completed_24h = self.db_manager.client.table('source_documents').select(
                'id', count='exact'
            ).eq('processing_status', 'completed').gte('last_modified_at', yesterday).execute()
            
            return {
                'by_stage': by_stage,
                'total_active': total_active,
                'completed_24h': completed_24h.count if hasattr(completed_24h, 'count') else 0
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def run(self):
        """Main monitoring loop"""
        try:
            while True:
                try:
                    self.display_dashboard()
                    time.sleep(self.refresh_interval)
                except Exception as e:
                    self.clear_screen()
                    print(f"Error: {e}")
                    time.sleep(5)
        except KeyboardInterrupt:
            self.clear_screen()
            print("\n👋 Monitoring stopped")


def main():
    parser = argparse.ArgumentParser(description='Enhanced Pipeline Monitor')
    parser.add_argument('--refresh', type=int, default=10, 
                        help='Refresh interval in seconds')
    
    args = parser.parse_args()
    
    monitor = EnhancedPipelineMonitor(refresh_interval=args.refresh)
    print("🚀 Starting Enhanced Pipeline Monitor...")
    time.sleep(1)
    monitor.run()


if __name__ == '__main__':
    main()