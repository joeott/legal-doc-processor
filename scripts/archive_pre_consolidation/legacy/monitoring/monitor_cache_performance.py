#!/usr/bin/env python3
"""
Monitor Redis Cache Performance Metrics
Tracks cache hit/miss rates, memory usage, and performance improvements.
"""

import sys
import os
import time
import json
from datetime import datetime, timedelta
from collections import defaultdict
import logging

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys
from scripts.supabase_utils import SupabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CachePerformanceMonitor:
    """Monitor and track Redis cache performance metrics."""
    
    def __init__(self):
        self.redis_mgr = get_redis_manager()
        self.db_manager = SupabaseManager()
        self.metrics = defaultdict(lambda: {'hits': 0, 'misses': 0, 'total': 0})
        self.start_time = time.time()
    
    def get_redis_memory_info(self):
        """Get Redis memory usage information."""
        if not self.redis_mgr or not self.redis_mgr.is_available():
            return None
        
        try:
            client = self.redis_mgr.get_client()
            info = client.info('memory')
            
            return {
                'used_memory_human': info.get('used_memory_human', 'N/A'),
                'used_memory_peak_human': info.get('used_memory_peak_human', 'N/A'),
                'used_memory_dataset': info.get('used_memory_dataset', 0),
                'used_memory_dataset_perc': info.get('used_memory_dataset_perc', '0%'),
                'mem_fragmentation_ratio': info.get('mem_fragmentation_ratio', 0),
                'total_system_memory_human': info.get('total_system_memory_human', 'N/A')
            }
        except Exception as e:
            logger.error(f"Failed to get Redis memory info: {e}")
            return None
    
    def analyze_cache_patterns(self):
        """Analyze cache usage patterns."""
        if not self.redis_mgr or not self.redis_mgr.is_available():
            return {}
        
        try:
            client = self.redis_mgr.get_client()
            
            # Get all cache keys
            patterns = {
                'ocr_results': f"{CacheKeys.DOC_OCR_RESULT.replace('{document_uuid}', '*')}*",
                'cleaned_text': f"{CacheKeys.DOC_CLEANED_TEXT.replace('{document_uuid}', '*')}*",
                'chunks_list': f"{CacheKeys.DOC_CHUNKS_LIST.replace('{document_uuid}', '*')}*",
                'chunk_texts': f"{CacheKeys.DOC_CHUNK_TEXT.replace('{chunk_uuid}', '*')}*",
                'entity_mentions': f"{CacheKeys.DOC_ALL_EXTRACTED_MENTIONS.replace('{document_uuid}', '*')}*",
                'canonical_entities': f"{CacheKeys.DOC_CANONICAL_ENTITIES.replace('{document_uuid}', '*')}*",
                'resolved_mentions': f"{CacheKeys.DOC_RESOLVED_MENTIONS.replace('{document_uuid}', '*')}*",
                'doc_states': f"{CacheKeys.DOC_STATE.replace('{document_uuid}', '*')}*"
            }
            
            cache_stats = {}
            total_keys = 0
            
            for cache_type, pattern in patterns.items():
                keys = list(client.scan_iter(match=pattern, count=1000))
                count = len(keys)
                total_keys += count
                
                # Sample a few keys to check sizes
                sizes = []
                ttls = []
                for key in keys[:10]:  # Sample first 10
                    try:
                        # Get memory usage for this key
                        memory = client.memory_usage(key)
                        if memory:
                            sizes.append(memory)
                        
                        # Get TTL
                        ttl = client.ttl(key)
                        if ttl > 0:
                            ttls.append(ttl)
                    except:
                        pass
                
                avg_size = sum(sizes) / len(sizes) if sizes else 0
                avg_ttl = sum(ttls) / len(ttls) if ttls else 0
                
                cache_stats[cache_type] = {
                    'count': count,
                    'avg_size_bytes': int(avg_size),
                    'avg_size_kb': round(avg_size / 1024, 2),
                    'total_size_mb': round((avg_size * count) / (1024 * 1024), 2),
                    'avg_ttl_hours': round(avg_ttl / 3600, 2) if avg_ttl else 0
                }
            
            cache_stats['total_keys'] = total_keys
            return cache_stats
            
        except Exception as e:
            logger.error(f"Failed to analyze cache patterns: {e}")
            return {}
    
    def measure_processing_times(self, limit: int = 10):
        """Measure processing times with and without cache."""
        # Get recently processed documents
        recent_docs = self.db_manager.client.table('source_documents').select(
            'document_uuid, processing_status, created_at, last_modified_at, processing_version'
        ).eq('processing_status', 'completed').order(
            'last_modified_at', desc=True
        ).limit(limit).execute()
        
        if not recent_docs.data:
            return {}
        
        processing_times = {
            'with_cache': [],
            'without_cache': [],
            'by_version': defaultdict(list)
        }
        
        for doc in recent_docs.data:
            created = datetime.fromisoformat(doc['created_at'].replace('Z', '+00:00'))
            modified = datetime.fromisoformat(doc['last_modified_at'].replace('Z', '+00:00'))
            processing_time = (modified - created).total_seconds()
            
            version = doc.get('processing_version', 1)
            processing_times['by_version'][version].append(processing_time)
            
            # Assume version 1 is without cache, higher versions with cache
            if version == 1:
                processing_times['without_cache'].append(processing_time)
            else:
                processing_times['with_cache'].append(processing_time)
        
        # Calculate averages
        stats = {}
        if processing_times['without_cache']:
            stats['avg_time_without_cache'] = round(
                sum(processing_times['without_cache']) / len(processing_times['without_cache']), 2
            )
        
        if processing_times['with_cache']:
            stats['avg_time_with_cache'] = round(
                sum(processing_times['with_cache']) / len(processing_times['with_cache']), 2
            )
            
            if 'avg_time_without_cache' in stats:
                improvement = (
                    (stats['avg_time_without_cache'] - stats['avg_time_with_cache']) 
                    / stats['avg_time_without_cache'] * 100
                )
                stats['performance_improvement'] = f"{round(improvement, 1)}%"
        
        return stats
    
    def track_cache_effectiveness(self):
        """Track cache hit/miss rates by monitoring Redis operations."""
        # This would require instrumenting the Redis client or analyzing logs
        # For now, we'll estimate based on document reprocessing
        
        reprocessed = self.db_manager.client.table('source_documents').select(
            'document_uuid, processing_version'
        ).gt('processing_version', 1).execute()
        
        total_reprocessed = len(reprocessed.data) if reprocessed.data else 0
        
        # Check how many have completed stages that could use cache
        cache_opportunities = 0
        cache_utilized = 0
        
        for doc in (reprocessed.data or []):
            document_uuid = doc['document_uuid']
            version = doc['processing_version']
            
            # Check if previous version's cache exists
            if self.redis_mgr and self.redis_mgr.is_available():
                # Check OCR cache
                ocr_key = CacheKeys.format_key(
                    CacheKeys.DOC_OCR_RESULT,
                    version=version-1,
                    document_uuid=document_uuid
                )
                if self.redis_mgr.get_cached(ocr_key):
                    cache_utilized += 1
                cache_opportunities += 1
        
        hit_rate = (cache_utilized / cache_opportunities * 100) if cache_opportunities > 0 else 0
        
        return {
            'total_reprocessed': total_reprocessed,
            'cache_opportunities': cache_opportunities,
            'cache_utilized': cache_utilized,
            'estimated_hit_rate': f"{round(hit_rate, 1)}%"
        }
    
    def estimate_db_query_reduction(self):
        """Estimate database query reduction from caching."""
        # Count documents processed in last hour
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        
        recent_processing = self.db_manager.client.table('source_documents').select(
            'document_uuid', count='exact'
        ).gte('last_modified_at', one_hour_ago).execute()
        
        docs_processed = recent_processing.count if hasattr(recent_processing, 'count') else 0
        
        # Estimate queries saved per document with cache
        # Without cache: ~20 queries per document (chunks, mentions, etc.)
        # With cache: ~5 queries per document
        queries_without_cache = docs_processed * 20
        queries_with_cache = docs_processed * 5
        queries_saved = queries_without_cache - queries_with_cache
        
        reduction_percent = (queries_saved / queries_without_cache * 100) if queries_without_cache > 0 else 0
        
        return {
            'docs_processed_last_hour': docs_processed,
            'estimated_queries_without_cache': queries_without_cache,
            'estimated_queries_with_cache': queries_with_cache,
            'queries_saved': queries_saved,
            'reduction_percent': f"{round(reduction_percent, 1)}%"
        }
    
    def get_optimal_ttl_recommendations(self):
        """Recommend optimal TTL values based on usage patterns."""
        cache_stats = self.analyze_cache_patterns()
        
        recommendations = {
            'ocr_results': {
                'current_ttl_days': 7,
                'recommended_ttl_days': 7,
                'reason': 'OCR is expensive, keep for full week'
            },
            'cleaned_text': {
                'current_ttl_days': 3,
                'recommended_ttl_days': 3,
                'reason': 'Moderate size, frequently accessed'
            },
            'chunks_list': {
                'current_ttl_days': 2,
                'recommended_ttl_days': 2,
                'reason': 'Small size, good for reprocessing'
            },
            'entity_mentions': {
                'current_ttl_days': 2,
                'recommended_ttl_days': 3,
                'reason': 'Increase TTL - frequently needed for resolution'
            },
            'canonical_entities': {
                'current_ttl_days': 3,
                'recommended_ttl_days': 5,
                'reason': 'Increase TTL - final output, frequently accessed'
            }
        }
        
        # Adjust based on actual usage
        for cache_type, stats in cache_stats.items():
            if cache_type in recommendations and stats.get('count', 0) > 100:
                # High usage items should have longer TTL
                if stats['count'] > 1000:
                    recommendations[cache_type]['recommended_ttl_days'] += 2
                    recommendations[cache_type]['reason'] += ' (high usage detected)'
        
        return recommendations
    
    def generate_report(self):
        """Generate comprehensive cache performance report."""
        logger.info("\n" + "="*60)
        logger.info("REDIS CACHE PERFORMANCE REPORT")
        logger.info("="*60)
        logger.info(f"Report generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Memory usage
        memory_info = self.get_redis_memory_info()
        if memory_info:
            logger.info("\nREDIS MEMORY USAGE:")
            logger.info(f"  Used Memory: {memory_info['used_memory_human']}")
            logger.info(f"  Peak Memory: {memory_info['used_memory_peak_human']}")
            logger.info(f"  Dataset Size: {memory_info['used_memory_dataset_perc']}")
            logger.info(f"  System Memory: {memory_info['total_system_memory_human']}")
        
        # Cache patterns
        cache_stats = self.analyze_cache_patterns()
        if cache_stats:
            logger.info("\nCACHE USAGE PATTERNS:")
            total_size_mb = 0
            for cache_type, stats in cache_stats.items():
                if cache_type != 'total_keys':
                    logger.info(f"\n  {cache_type}:")
                    logger.info(f"    Count: {stats['count']}")
                    logger.info(f"    Avg Size: {stats['avg_size_kb']} KB")
                    logger.info(f"    Total Size: {stats['total_size_mb']} MB")
                    if stats['avg_ttl_hours']:
                        logger.info(f"    Avg TTL: {stats['avg_ttl_hours']} hours")
                    total_size_mb += stats['total_size_mb']
            
            logger.info(f"\n  Total Keys: {cache_stats.get('total_keys', 0)}")
            logger.info(f"  Total Cache Size: {round(total_size_mb, 2)} MB")
        
        # Processing times
        time_stats = self.measure_processing_times()
        if time_stats:
            logger.info("\nPROCESSING TIME ANALYSIS:")
            if 'avg_time_without_cache' in time_stats:
                logger.info(f"  Avg Time Without Cache: {time_stats['avg_time_without_cache']} seconds")
            if 'avg_time_with_cache' in time_stats:
                logger.info(f"  Avg Time With Cache: {time_stats['avg_time_with_cache']} seconds")
            if 'performance_improvement' in time_stats:
                logger.info(f"  Performance Improvement: {time_stats['performance_improvement']}")
        
        # Cache effectiveness
        effectiveness = self.track_cache_effectiveness()
        logger.info("\nCACHE EFFECTIVENESS:")
        logger.info(f"  Documents Reprocessed: {effectiveness['total_reprocessed']}")
        logger.info(f"  Cache Hit Rate: {effectiveness['estimated_hit_rate']}")
        
        # DB query reduction
        db_stats = self.estimate_db_query_reduction()
        logger.info("\nDATABASE QUERY REDUCTION:")
        logger.info(f"  Docs Processed (Last Hour): {db_stats['docs_processed_last_hour']}")
        logger.info(f"  Queries Saved: {db_stats['queries_saved']}")
        logger.info(f"  Query Reduction: {db_stats['reduction_percent']}")
        
        # TTL recommendations
        ttl_recs = self.get_optimal_ttl_recommendations()
        logger.info("\nTTL RECOMMENDATIONS:")
        for cache_type, rec in ttl_recs.items():
            if rec['current_ttl_days'] != rec['recommended_ttl_days']:
                logger.info(f"\n  {cache_type}:")
                logger.info(f"    Current: {rec['current_ttl_days']} days")
                logger.info(f"    Recommended: {rec['recommended_ttl_days']} days")
                logger.info(f"    Reason: {rec['reason']}")
        
        logger.info("\n" + "="*60)
        
        # Return summary for programmatic use
        return {
            'memory': memory_info,
            'cache_stats': cache_stats,
            'processing_times': time_stats,
            'effectiveness': effectiveness,
            'db_reduction': db_stats,
            'ttl_recommendations': ttl_recs
        }


def continuous_monitoring(interval: int = 300):
    """Run continuous monitoring with periodic reports."""
    monitor = CachePerformanceMonitor()
    
    logger.info(f"Starting continuous cache monitoring (reporting every {interval} seconds)")
    logger.info("Press Ctrl+C to stop")
    
    try:
        while True:
            monitor.generate_report()
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("\nMonitoring stopped by user")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Monitor Redis cache performance')
    parser.add_argument('--continuous', action='store_true', 
                        help='Run continuous monitoring')
    parser.add_argument('--interval', type=int, default=300,
                        help='Reporting interval in seconds (default: 300)')
    
    args = parser.parse_args()
    
    if args.continuous:
        continuous_monitoring(args.interval)
    else:
        # Run single report
        monitor = CachePerformanceMonitor()
        monitor.generate_report()