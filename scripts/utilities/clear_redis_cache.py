#!/usr/bin/env python3
"""
Clear all Redis cache entries for fresh start.
This script removes all cached data including:
- Document states
- OCR results
- Entity caches
- Chunks
- Processing locks
- All other cache entries
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Add the project root to Python path
sys.path.append('/opt/legal-doc-processor')

# Load environment variables from .env file
env_path = Path('/opt/legal-doc-processor/.env')
if env_path.exists():
    load_dotenv(env_path)

# Set environment variables for minimal models
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.cache import get_redis_manager, CacheKeys

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clear_all_redis_cache():
    """Clear all Redis cache entries."""
    try:
        # Get Redis manager
        redis_manager = get_redis_manager()
        client = redis_manager.get_client()
        
        logger.info("Starting Redis cache clearing...")
        
        # Define all cache patterns to clear
        patterns = [
            "doc:*",           # All document-related keys
            "entity:*",        # All entity-related keys
            "chunk:*",         # All chunk-related keys
            "llm:*",           # All LLM cache keys
            "ocr:*",           # All OCR cache keys
            "structured:*",    # All structured extraction keys
            "processing:*",    # All processing-related keys
            "job:*",           # All job-related keys
            "state:*",         # All state keys
            "lock:*",          # All lock keys
            "queue:*",         # All queue-related keys
            "batch:*",         # All batch-related keys
            "test:*",          # All test-related keys
        ]
        
        total_deleted = 0
        
        for pattern in patterns:
            logger.info(f"Clearing pattern: {pattern}")
            
            # Use SCAN to find all matching keys
            cursor = 0
            pattern_deleted = 0
            
            while True:
                cursor, keys = client.scan(cursor, match=pattern, count=1000)
                
                if keys:
                    # Delete in batches for efficiency
                    for i in range(0, len(keys), 1000):
                        batch = keys[i:i+1000]
                        deleted = client.delete(*batch)
                        pattern_deleted += deleted
                        total_deleted += deleted
                
                if cursor == 0:
                    break
            
            if pattern_deleted > 0:
                logger.info(f"  Deleted {pattern_deleted} keys matching '{pattern}'")
        
        # Also clear all keys if running in test/development mode
        if os.getenv('CLEAR_ALL_REDIS', 'false').lower() == 'true':
            logger.warning("CLEAR_ALL_REDIS is set - flushing entire database")
            client.flushdb()
            logger.info("Flushed entire Redis database")
        else:
            logger.info(f"Total keys deleted: {total_deleted}")
        
        # Verify cache is clear by checking key count
        remaining_keys = client.dbsize()
        logger.info(f"Remaining keys in Redis: {remaining_keys}")
        
        logger.info("Redis cache clearing completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Error clearing Redis cache: {str(e)}")
        return False


if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="Clear Redis cache")
    parser.add_argument('--flush-all', action='store_true', 
                        help='Flush entire Redis database (use with caution)')
    args = parser.parse_args()
    
    if args.flush_all:
        os.environ['CLEAR_ALL_REDIS'] = 'true'
        logger.warning("WARNING: Will flush entire Redis database!")
        response = input("Are you sure you want to flush ALL Redis data? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Aborted.")
            sys.exit(0)
    
    success = clear_all_redis_cache()
    sys.exit(0 if success else 1)