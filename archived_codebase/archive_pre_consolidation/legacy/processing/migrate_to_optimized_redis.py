#!/usr/bin/env python3
"""
Migration script to update Redis keys to new standardized naming convention.
This script safely migrates existing Redis keys to the new format defined in cache_keys.py.
"""

import logging
import argparse
import time
from typing import Dict, List, Tuple

from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys

logger = logging.getLogger(__name__)


class RedisKeyMigrator:
    """Handles migration of Redis keys to new naming convention."""
    
    def __init__(self, dry_run: bool = False):
        """
        Initialize migrator.
        
        Args:
            dry_run: If True, only show what would be migrated without making changes
        """
        self.redis_mgr = get_redis_manager()
        self.dry_run = dry_run
        self.migration_stats = {
            'scanned': 0,
            'migrated': 0,
            'skipped': 0,
            'errors': 0
        }
        
        if not self.redis_mgr.is_available():
            raise RuntimeError("Redis is not available for migration")
    
    def get_migration_mappings(self) -> List[Tuple[str, str]]:
        """
        Define migration mappings from old patterns to new patterns.
        
        Returns:
            List of (old_pattern, new_prefix) tuples
        """
        return [
            # Document state keys
            (r"doc_state:*", "doc:state:"),
            
            # Textract result keys
            (r"textract:result:*", "doc:ocr:"),
            (r"ocr:result:*", "doc:ocr:"),
            
            # Entity extraction keys
            (r"entity:openai:*", "doc:entities:"),
            (r"entity:local:*", "doc:entities:"),
            
            # Structured extraction keys
            (r"structured:*", "doc:structured:"),
            
            # Rate limiting keys
            (r"rate_limit:*", "rate:"),
            
            # Job tracking keys
            (r"textract:job:*", "job:textract:status:"),
            
            # Queue locks
            (r"queue_lock:*", "queue:lock:"),
            
            # Worker keys
            (r"worker:*", "workers:"),
            
            # Metrics keys
            (r"metrics:*", "cache:metrics:"),
        ]
    
    def extract_key_suffix(self, old_key: str, pattern: str) -> str:
        """
        Extract the suffix from an old key based on pattern.
        
        Args:
            old_key: The old Redis key
            pattern: The pattern used to match (with wildcard)
            
        Returns:
            The extracted suffix
        """
        # Remove the wildcard from pattern
        prefix = pattern.rstrip('*')
        
        # Extract suffix
        if old_key.startswith(prefix):
            return old_key[len(prefix):]
        
        # For colon-separated keys
        parts = old_key.split(':', 1)
        if len(parts) > 1:
            return parts[1]
        
        return old_key
    
    def migrate_key(self, old_key: str, new_prefix: str) -> bool:
        """
        Migrate a single key to new format.
        
        Args:
            old_key: Current key name
            new_prefix: New key prefix
            
        Returns:
            True if successful, False otherwise
        """
        try:
            client = self.redis_mgr.get_client()
            
            # Extract suffix
            suffix = self.extract_key_suffix(old_key, old_key.split(':')[0] + ':*')
            new_key = new_prefix + suffix
            
            # Skip if already in new format
            if old_key == new_key:
                logger.debug(f"Key {old_key} already in new format")
                self.migration_stats['skipped'] += 1
                return True
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would migrate: {old_key} -> {new_key}")
                return True
            
            # Get value and TTL
            value = client.get(old_key)
            ttl = client.ttl(old_key)
            
            if value is None:
                logger.warning(f"Key {old_key} has no value, skipping")
                self.migration_stats['skipped'] += 1
                return False
            
            # Set new key
            client.set(new_key, value)
            
            # Preserve TTL if exists
            if ttl > 0:
                client.expire(new_key, ttl)
            
            # Delete old key
            client.delete(old_key)
            
            logger.info(f"Migrated: {old_key} -> {new_key}")
            self.migration_stats['migrated'] += 1
            return True
            
        except Exception as e:
            logger.error(f"Error migrating key {old_key}: {e}")
            self.migration_stats['errors'] += 1
            return False
    
    def migrate_hash_keys(self) -> int:
        """
        Special handling for hash-based keys (like document states).
        
        Returns:
            Number of hash keys migrated
        """
        client = self.redis_mgr.get_client()
        migrated = 0
        
        # Document state hashes
        for old_key in client.scan_iter(match="doc_state:*"):
            try:
                # Get all hash fields
                hash_data = client.hgetall(old_key)
                if not hash_data:
                    continue
                
                # Extract document UUID
                doc_uuid = old_key.split(':', 1)[1]
                new_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=doc_uuid)
                
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would migrate hash: {old_key} -> {new_key}")
                    continue
                
                # Copy hash to new key
                for field, value in hash_data.items():
                    client.hset(new_key, field, value)
                
                # Get TTL and apply to new key
                ttl = client.ttl(old_key)
                if ttl > 0:
                    client.expire(new_key, ttl)
                
                # Delete old key
                client.delete(old_key)
                
                logger.info(f"Migrated hash: {old_key} -> {new_key}")
                migrated += 1
                
            except Exception as e:
                logger.error(f"Error migrating hash {old_key}: {e}")
                self.migration_stats['errors'] += 1
        
        return migrated
    
    def run_migration(self) -> Dict:
        """
        Run the complete migration process.
        
        Returns:
            Migration statistics
        """
        logger.info("Starting Redis key migration...")
        if self.dry_run:
            logger.info("Running in DRY RUN mode - no changes will be made")
        
        client = self.redis_mgr.get_client()
        start_time = time.time()
        
        # First, migrate hash-based keys
        hash_count = self.migrate_hash_keys()
        self.migration_stats['migrated'] += hash_count
        
        # Then migrate regular keys
        mappings = self.get_migration_mappings()
        
        for old_pattern, new_prefix in mappings:
            logger.info(f"Processing pattern: {old_pattern}")
            
            for old_key in client.scan_iter(match=old_pattern, count=100):
                self.migration_stats['scanned'] += 1
                self.migrate_key(old_key, new_prefix)
        
        # Calculate duration
        duration = time.time() - start_time
        self.migration_stats['duration_seconds'] = round(duration, 2)
        
        logger.info("Migration complete!")
        logger.info(f"Statistics: {self.migration_stats}")
        
        return self.migration_stats
    
    def backup_keys(self, backup_file: str = "redis_backup.json"):
        """
        Backup all Redis keys before migration.
        
        Args:
            backup_file: Path to backup file
        """
        import json
        
        logger.info(f"Backing up Redis keys to {backup_file}...")
        
        client = self.redis_mgr.get_client()
        backup_data = {}
        
        for key in client.scan_iter(count=100):
            key_type = client.type(key)
            
            if key_type == 'string':
                backup_data[key] = {
                    'type': 'string',
                    'value': client.get(key),
                    'ttl': client.ttl(key)
                }
            elif key_type == 'hash':
                backup_data[key] = {
                    'type': 'hash',
                    'value': client.hgetall(key),
                    'ttl': client.ttl(key)
                }
            elif key_type == 'list':
                backup_data[key] = {
                    'type': 'list',
                    'value': client.lrange(key, 0, -1),
                    'ttl': client.ttl(key)
                }
            elif key_type == 'set':
                backup_data[key] = {
                    'type': 'set',
                    'value': list(client.smembers(key)),
                    'ttl': client.ttl(key)
                }
        
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f, indent=2)
        
        logger.info(f"Backed up {len(backup_data)} keys to {backup_file}")
    
    def verify_migration(self) -> bool:
        """
        Verify that migration was successful.
        
        Returns:
            True if verification passed
        """
        logger.info("Verifying migration...")
        
        client = self.redis_mgr.get_client()
        old_patterns = [pattern for pattern, _ in self.get_migration_mappings()]
        
        # Check for any remaining old keys
        old_keys_found = 0
        for pattern in old_patterns:
            for key in client.scan_iter(match=pattern, count=100):
                logger.warning(f"Found unmigrated key: {key}")
                old_keys_found += 1
        
        if old_keys_found > 0:
            logger.error(f"Verification failed: {old_keys_found} old keys still exist")
            return False
        
        logger.info("Verification passed: All keys migrated successfully")
        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate Redis keys to new standardized naming convention"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        help='Backup Redis keys before migration'
    )
    parser.add_argument(
        '--backup-file',
        default='redis_backup.json',
        help='Path to backup file (default: redis_backup.json)'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify migration after completion'
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Set logging level'
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        migrator = RedisKeyMigrator(dry_run=args.dry_run)
        
        # Backup if requested
        if args.backup:
            migrator.backup_keys(args.backup_file)
        
        # Run migration
        stats = migrator.run_migration()
        
        # Verify if requested and not dry run
        if args.verify and not args.dry_run:
            if migrator.verify_migration():
                print("\n✅ Migration completed successfully!")
            else:
                print("\n❌ Migration verification failed!")
                return 1
        
        # Print summary
        print("\nMigration Summary:")
        print(f"  Keys scanned: {stats['scanned']}")
        print(f"  Keys migrated: {stats['migrated']}")
        print(f"  Keys skipped: {stats['skipped']}")
        print(f"  Errors: {stats['errors']}")
        print(f"  Duration: {stats.get('duration_seconds', 0):.2f} seconds")
        
        return 0 if stats['errors'] == 0 else 1
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())