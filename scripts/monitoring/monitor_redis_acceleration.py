#!/usr/bin/env python3
"""
Monitor Redis acceleration during document processing.
This script tracks Redis cache hits/misses and performance metrics.
"""
import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

# Add scripts directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))

from scripts.cache import get_redis_manager, CacheKeys
from scripts.db import DatabaseManager
from scripts.models import SourceDocumentMinimal
from scripts.config import REDIS_ACCELERATION_ENABLED, REDIS_ACCELERATION_TTL_HOURS

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RedisAccelerationMonitor:
    def __init__(self):
        self.redis_manager = get_redis_manager()
        self.db = DatabaseManager()
        self.start_time = datetime.now()
        self.metrics = {
            'cache_hits': 0,
            'cache_misses': 0,
            'db_queries': 0,
            'redis_writes': 0,
            'time_saved': 0.0
        }
        
    def check_redis_health(self):
        """Check if Redis is healthy and acceleration is enabled."""
        logger.info(f"Redis Acceleration Enabled: {REDIS_ACCELERATION_ENABLED}")
        logger.info(f"Redis TTL Hours: {REDIS_ACCELERATION_TTL_HOURS}")
        
        if self.redis_manager.is_redis_healthy():
            logger.info("✅ Redis is healthy and ready")
            return True
        else:
            logger.warning("❌ Redis is not healthy")
            return False
            
    def monitor_document_processing(self, document_uuid: str):
        """Monitor Redis usage during document processing."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Monitoring Redis Acceleration for Document: {document_uuid}")
        logger.info(f"{'='*60}\n")
        
        # Check initial Redis state
        self.check_redis_health()
        
        # Monitor different cache keys
        cache_keys = [
            ('OCR Result', CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)),
            ('Chunks', CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid)),
            ('Entity Mentions', CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid)),
            ('Canonical Entities', CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid)),
            ('Relationships', CacheKeys.format_key(CacheKeys.DOC_RELATIONSHIPS, document_uuid=document_uuid)),
            ('Document State', CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid))
        ]
        
        logger.info("Checking Redis cache keys:")
        for name, key in cache_keys:
            exists = self.redis_manager.exists(key)
            if exists:
                logger.info(f"  ✅ {name}: CACHED (key: {key})")
                self.metrics['cache_hits'] += 1
            else:
                logger.info(f"  ❌ {name}: NOT CACHED (key: {key})")
                self.metrics['cache_misses'] += 1
                
        # Check document status in database
        session = next(self.db.get_session())
        try:
            doc = session.query(SourceDocumentMinimal).filter_by(
                document_uuid=document_uuid
            ).first()
            
            if doc:
                logger.info(f"\nDocument Status in DB:")
                logger.info(f"  - Status: {doc.status}")
                logger.info(f"  - Has OCR text: {'Yes' if doc.raw_extracted_text else 'No'}")
                logger.info(f"  - Text length: {len(doc.raw_extracted_text) if doc.raw_extracted_text else 0}")
                self.metrics['db_queries'] += 1
        finally:
            session.close()
            
    def watch_redis_keys(self, document_uuid: str, duration: int = 60):
        """Watch Redis keys for changes over time."""
        logger.info(f"\nWatching Redis keys for {duration} seconds...")
        
        cache_keys = {
            'OCR': CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid),
            'Chunks': CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid),
            'Entities': CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid),
            'Canonical': CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid),
            'State': CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
        }
        
        start_time = time.time()
        last_state = {}
        
        while time.time() - start_time < duration:
            current_state = {}
            changes = []
            
            for name, key in cache_keys.items():
                exists = self.redis_manager.exists(key)
                current_state[name] = exists
                
                # Check for changes
                if name not in last_state:
                    last_state[name] = False
                    
                if exists != last_state[name]:
                    if exists:
                        changes.append(f"✅ {name} CACHED")
                        self.metrics['redis_writes'] += 1
                    else:
                        changes.append(f"❌ {name} REMOVED")
                        
            if changes:
                logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] Redis changes detected:")
                for change in changes:
                    logger.info(f"  {change}")
                    
            last_state = current_state
            time.sleep(2)  # Check every 2 seconds
            
    def get_cache_value_sample(self, document_uuid: str):
        """Get sample values from cache to verify content."""
        logger.info("\nSample cache values:")
        
        # Check OCR result
        ocr_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
        ocr_result = self.redis_manager.get_cached(ocr_key)
        if ocr_result:
            logger.info(f"\nOCR Result (cached):")
            if isinstance(ocr_result, dict):
                logger.info(f"  - Status: {ocr_result.get('status', 'N/A')}")
                logger.info(f"  - Text length: {len(ocr_result.get('text', ''))}")
                logger.info(f"  - Method: {ocr_result.get('method', 'N/A')}")
            
        # Check chunks
        chunks_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid)
        chunks = self.redis_manager.get_cached(chunks_key)
        if chunks:
            logger.info(f"\nChunks (cached):")
            logger.info(f"  - Number of chunks: {len(chunks) if isinstance(chunks, list) else 'N/A'}")
            
        # Check document state
        state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
        state = self.redis_manager.get_cached(state_key)
        if state:
            logger.info(f"\nDocument State (cached):")
            logger.info(f"  - Current stage: {state.get('current_stage', 'N/A')}")
            logger.info(f"  - Status: {state.get('status', 'N/A')}")
            
    def print_summary(self):
        """Print summary of Redis acceleration metrics."""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        logger.info(f"\n{'='*60}")
        logger.info("Redis Acceleration Summary")
        logger.info(f"{'='*60}")
        logger.info(f"Total monitoring duration: {duration:.2f} seconds")
        logger.info(f"Cache hits: {self.metrics['cache_hits']}")
        logger.info(f"Cache misses: {self.metrics['cache_misses']}")
        logger.info(f"Redis writes: {self.metrics['redis_writes']}")
        logger.info(f"Database queries: {self.metrics['db_queries']}")
        
        if self.metrics['cache_hits'] + self.metrics['cache_misses'] > 0:
            hit_rate = self.metrics['cache_hits'] / (self.metrics['cache_hits'] + self.metrics['cache_misses']) * 100
            logger.info(f"Cache hit rate: {hit_rate:.1f}%")
            
        logger.info(f"{'='*60}\n")


def main():
    """Main monitoring function."""
    if len(sys.argv) < 2:
        print("Usage: python monitor_redis_acceleration.py <document_uuid>")
        sys.exit(1)
        
    document_uuid = sys.argv[1]
    monitor = RedisAccelerationMonitor()
    
    # Initial check
    monitor.monitor_document_processing(document_uuid)
    
    # Get sample values
    monitor.get_cache_value_sample(document_uuid)
    
    # Watch for changes
    monitor.watch_redis_keys(document_uuid, duration=30)
    
    # Final summary
    monitor.print_summary()


if __name__ == "__main__":
    main()