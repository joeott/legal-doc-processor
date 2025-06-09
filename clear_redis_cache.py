#!/usr/bin/env python3
"""Clear all Redis cache entries related to document processing."""

from scripts.cache import get_redis_manager

def clear_redis_cache():
    """Clear all document-related cache entries."""
    redis = get_redis_manager()
    client = redis.get_client()
    
    print("Clearing Redis cache...")
    
    # Patterns to clear
    patterns = [
        "doc:*",
        "batch:*",
        "chunks:*",
        "entities:*",
        "ocr:*",
        "entity_cache:*",
        "chunk_cache:*",
        "validation:*"
    ]
    
    total_deleted = 0
    
    for pattern in patterns:
        keys = client.keys(pattern)
        if keys:
            deleted = client.delete(*keys)
            print(f"  Deleted {deleted} keys matching '{pattern}'")
            total_deleted += deleted
    
    print(f"\nTotal keys deleted: {total_deleted}")
    print("Redis cache cleared successfully!")

if __name__ == "__main__":
    clear_redis_cache()