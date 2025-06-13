"""
Redis Production Configuration for Live Data Testing
Ensures memory efficiency and monitoring for 450+ document processing
"""

import os
from typing import Dict, Any

# Memory Management
REDIS_MAX_MEMORY = os.getenv('REDIS_MAX_MEMORY', '1gb')
REDIS_MAX_MEMORY_POLICY = os.getenv('REDIS_MAX_MEMORY_POLICY', 'allkeys-lru')
REDIS_MAX_MEMORY_SAMPLES = int(os.getenv('REDIS_MAX_MEMORY_SAMPLES', '5'))

# Cache Size Limits per Document
MAX_CACHE_SIZE_PER_DOC_MB = int(os.getenv('MAX_CACHE_SIZE_PER_DOC_MB', '10'))
MAX_CACHED_CHUNKS_PER_DOC = int(os.getenv('MAX_CACHED_CHUNKS_PER_DOC', '1000'))
MAX_CACHED_ENTITIES_PER_DOC = int(os.getenv('MAX_CACHED_ENTITIES_PER_DOC', '5000'))

# Adjusted TTLs for Production
PRODUCTION_TTL_MULTIPLIER = float(os.getenv('PRODUCTION_TTL_MULTIPLIER', '1.0'))

# Production TTL values (in seconds)
REDIS_TTL_CONFIG = {
    # Short-lived operational data
    'lock': 300,  # 5 minutes
    'rate_limit': 3600,  # 1 hour
    'task_status': 3600,  # 1 hour
    
    # Medium-lived processing data
    'chunk_text': 86400,  # 1 day (reduced from 2 days)
    'entity_mentions': 43200,  # 12 hours
    'structured_data': 86400,  # 24 hours
    
    # Long-lived results
    'ocr_result': 259200,  # 3 days (reduced from 7 days)
    'canonical_entities': 172800,  # 2 days
    'embeddings': 604800,  # 7 days
    
    # Document state - persists until explicitly cleared
    'document_state': None,  # No expiration
    'processing_pipeline': None,  # No expiration
}

# Cache Warming Configuration
CACHE_WARMING_CONFIG = {
    'max_concurrent_warming': 10,
    'chunk_batch_size': 100,
    'entity_batch_size': 500,
    'warming_priority': ['ocr_result', 'chunks_list', 'canonical_entities'],
    'skip_if_memory_above_percent': 80
}

# Monitoring Thresholds
REDIS_MONITORING_THRESHOLDS = {
    'memory_usage_warning': 70,  # Percent
    'memory_usage_critical': 85,  # Percent
    'connection_pool_warning': 80,  # Percent of max connections
    'slow_command_threshold_ms': 100,
    'high_key_count_warning': 1000000,  # 1M keys
}

# Cleanup Configuration
REDIS_CLEANUP_CONFIG = {
    'enable_auto_cleanup': True,
    'cleanup_interval_seconds': 3600,  # 1 hour
    'cleanup_batch_size': 1000,
    'patterns_to_clean': [
        'rate:*',  # Old rate limit entries
        'task:status:*',  # Old task statuses
        'job:textract:status:*',  # Old job statuses
    ],
    'max_cleanup_time_seconds': 300  # 5 minutes max
}

# Key Namespace Configuration
REDIS_KEY_NAMESPACES = {
    'production': 'prod',
    'staging': 'stage',
    'development': 'dev',
    'testing': 'test'
}

# Get current environment
REDIS_ENVIRONMENT = os.getenv('REDIS_ENVIRONMENT', 'development')
REDIS_KEY_PREFIX = REDIS_KEY_NAMESPACES.get(REDIS_ENVIRONMENT, 'dev')

def get_redis_config() -> Dict[str, Any]:
    """Get Redis configuration for current environment"""
    config = {
        'decode_responses': True,
        'encoding': 'utf-8',
        'max_connections': 100,
        'socket_keepalive': True,
        'socket_keepalive_options': {
            1: 1,  # TCP_KEEPIDLE
            2: 2,  # TCP_KEEPINTVL
            3: 2,  # TCP_KEEPCNT
        },
        'retry_on_timeout': True,
        'retry_on_error': [ConnectionError, TimeoutError],
        'health_check_interval': 30
    }
    
    # Add monitoring hooks
    if REDIS_ENVIRONMENT in ['production', 'staging']:
        config['command_stats'] = True
        config['latency_monitor_threshold'] = 100  # milliseconds
    
    return config

def calculate_ttl(key_type: str) -> int:
    """Calculate TTL based on key type and environment"""
    base_ttl = REDIS_TTL_CONFIG.get(key_type)
    if base_ttl is None:
        return None
    
    # Apply multiplier for testing/staging environments
    if REDIS_ENVIRONMENT in ['testing', 'staging']:
        return int(base_ttl * 0.5)  # Shorter TTLs for testing
    
    return int(base_ttl * PRODUCTION_TTL_MULTIPLIER)

# Export configuration
__all__ = [
    'REDIS_MAX_MEMORY',
    'REDIS_MAX_MEMORY_POLICY',
    'REDIS_TTL_CONFIG',
    'CACHE_WARMING_CONFIG',
    'REDIS_MONITORING_THRESHOLDS',
    'REDIS_CLEANUP_CONFIG',
    'REDIS_KEY_PREFIX',
    'get_redis_config',
    'calculate_ttl'
]