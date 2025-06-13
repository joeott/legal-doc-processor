#!/usr/bin/env python3
"""
Migrate Redis data from single database to multiple databases.

This script safely migrates existing Redis data to the new multi-database architecture:
- DB 0 (broker): Celery broker data (remains)
- DB 1 (results): Celery results (migrate from DB 0)
- DB 2 (cache): Application cache (doc:*, chunk:*, entity:*)
- DB 3 (rate_limit): Rate limiting data
- DB 4 (batch): Batch processing metadata (batch:*)
- DB 5 (metrics): Performance metrics
"""

import redis
import logging
import sys
from datetime import datetime
from typing import Dict, List, Tuple

from scripts.config import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_USERNAME, REDIS_SSL,
    REDIS_DB_BROKER, REDIS_DB_RESULTS, REDIS_DB_CACHE,
    REDIS_DB_RATE_LIMIT, REDIS_DB_BATCH, REDIS_DB_METRICS,
    get_redis_db_config
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RedisMigrator:
    """Handles migration of Redis data between databases."""
    
    def __init__(self):
        self.clients = {}
        self._initialize_clients()
        
    def _initialize_clients(self):
        """Initialize Redis clients for all databases."""
        databases = {
            'source': 0,  # Original database
            'broker': REDIS_DB_BROKER,
            'results': REDIS_DB_RESULTS,
            'cache': REDIS_DB_CACHE,
            'rate_limit': REDIS_DB_RATE_LIMIT,
            'batch': REDIS_DB_BATCH,
            'metrics': REDIS_DB_METRICS
        }
        
        for name, db_num in databases.items():
            try:
                if name == 'source':
                    # Use basic config for source
                    config = {
                        'host': REDIS_HOST,
                        'port': REDIS_PORT,
                        'db': db_num,
                        'password': REDIS_PASSWORD,
                        'decode_responses': False  # Keep binary for accurate migration
                    }
                else:
                    # Use database-specific config
                    config = get_redis_db_config(name)
                    config['decode_responses'] = False  # Keep binary
                
                if REDIS_USERNAME:
                    config['username'] = REDIS_USERNAME
                    
                self.clients[name] = redis.Redis(**config)
                self.clients[name].ping()
                logger.info(f"Connected to Redis database '{name}' (DB {db_num})")
                
            except Exception as e:
                logger.error(f"Failed to connect to database '{name}': {e}")
                self.clients[name] = None
    
    def get_key_patterns(self) -> Dict[str, List[str]]:
        """Define key patterns and their target databases."""
        return {
            'cache': [
                'doc:*',
                'chunk:*',
                'entity:*',
                'cache:*',
                'llm:*',
                'ocr:*'
            ],
            'batch': [
                'batch:*',
                'batch_*'
            ],
            'metrics': [
                'metrics:*',
                'metric_*',
                'stats:*'
            ],
            'rate_limit': [
                'rate:*',
                'limit:*',
                'throttle:*'
            ],
            'results': [
                'celery-task-meta-*',
                'chord-unlock-*',
                'group-*'
            ]
        }
    
    def scan_keys(self, pattern: str) -> List[bytes]:
        """Scan for keys matching pattern in source database."""
        source = self.clients.get('source')
        if not source:
            return []
        
        keys = []
        cursor = 0
        
        while True:
            cursor, batch = source.scan(cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
                
        return keys
    
    def migrate_key(self, key: bytes, target_db: str) -> bool:
        """Migrate a single key to target database."""
        source = self.clients.get('source')
        target = self.clients.get(target_db)
        
        if not source or not target:
            return False
        
        try:
            # Get key type
            key_type = source.type(key).decode('utf-8')
            
            # Get TTL
            ttl = source.ttl(key)
            
            # Migrate based on type
            if key_type == 'string':
                value = source.get(key)
                if ttl > 0:
                    target.setex(key, ttl, value)
                else:
                    target.set(key, value)
                    
            elif key_type == 'hash':
                data = source.hgetall(key)
                if data:
                    target.hset(key, mapping=data)
                    if ttl > 0:
                        target.expire(key, ttl)
                        
            elif key_type == 'list':
                values = source.lrange(key, 0, -1)
                if values:
                    target.rpush(key, *values)
                    if ttl > 0:
                        target.expire(key, ttl)
                        
            elif key_type == 'set':
                members = source.smembers(key)
                if members:
                    target.sadd(key, *members)
                    if ttl > 0:
                        target.expire(key, ttl)
                        
            elif key_type == 'zset':
                members = source.zrange(key, 0, -1, withscores=True)
                if members:
                    target.zadd(key, dict(members))
                    if ttl > 0:
                        target.expire(key, ttl)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to migrate key {key}: {e}")
            return False
    
    def migrate_database(self, dry_run: bool = True) -> Dict[str, int]:
        """
        Migrate all data to appropriate databases.
        
        Args:
            dry_run: If True, only report what would be migrated
            
        Returns:
            Dictionary with migration statistics
        """
        patterns = self.get_key_patterns()
        stats = {db: 0 for db in patterns}
        stats['skipped'] = 0
        stats['errors'] = 0
        
        logger.info(f"Starting migration {'(DRY RUN)' if dry_run else ''}")
        
        # Process each pattern
        for target_db, pattern_list in patterns.items():
            for pattern in pattern_list:
                keys = self.scan_keys(pattern)
                logger.info(f"Found {len(keys)} keys matching '{pattern}' for database '{target_db}'")
                
                for key in keys:
                    if dry_run:
                        stats[target_db] += 1
                        logger.debug(f"Would migrate {key} to {target_db}")
                    else:
                        if self.migrate_key(key, target_db):
                            stats[target_db] += 1
                        else:
                            stats['errors'] += 1
        
        # Check for unmatched keys
        all_keys = self.scan_keys('*')
        migrated_patterns = set()
        for pattern_list in patterns.values():
            for pattern in pattern_list:
                migrated_patterns.update(self.scan_keys(pattern))
        
        unmatched = set(all_keys) - migrated_patterns
        if unmatched:
            logger.warning(f"Found {len(unmatched)} keys that don't match any pattern:")
            for key in list(unmatched)[:10]:  # Show first 10
                logger.warning(f"  - {key}")
            stats['skipped'] = len(unmatched)
        
        return stats
    
    def verify_migration(self) -> Dict[str, Dict[str, int]]:
        """Verify the migration by checking key counts in each database."""
        results = {}
        
        for name, client in self.clients.items():
            if client and name != 'source':
                try:
                    info = client.info('keyspace')
                    db_key = f'db{client.connection_pool.connection_kwargs["db"]}'
                    
                    if db_key in info:
                        results[name] = {
                            'keys': info[db_key]['keys'],
                            'expires': info[db_key]['expires'],
                            'avg_ttl': info[db_key].get('avg_ttl', 0)
                        }
                    else:
                        results[name] = {'keys': 0, 'expires': 0, 'avg_ttl': 0}
                        
                except Exception as e:
                    logger.error(f"Failed to get info for database '{name}': {e}")
                    results[name] = {'error': str(e)}
        
        return results


def main():
    """Main migration function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate Redis data to multi-database setup')
    parser.add_argument('--execute', action='store_true', 
                       help='Execute migration (default is dry run)')
    parser.add_argument('--verify', action='store_true',
                       help='Verify migration results')
    args = parser.parse_args()
    
    migrator = RedisMigrator()
    
    if args.verify:
        # Verify current state
        logger.info("Verifying database state...")
        results = migrator.verify_migration()
        
        print("\nDatabase Statistics:")
        print("-" * 50)
        for db, stats in results.items():
            if 'error' in stats:
                print(f"{db:12} : ERROR - {stats['error']}")
            else:
                print(f"{db:12} : {stats['keys']:6} keys, {stats['expires']:6} expiring")
        
    else:
        # Run migration
        stats = migrator.migrate_database(dry_run=not args.execute)
        
        print("\nMigration Summary:")
        print("-" * 50)
        for db, count in stats.items():
            print(f"{db:12} : {count:6} keys")
        
        if not args.execute:
            print("\nThis was a DRY RUN. Use --execute to perform actual migration.")
        else:
            print("\nMigration completed. Use --verify to check results.")


if __name__ == "__main__":
    main()