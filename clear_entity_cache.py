#!/usr/bin/env python3
"""Clear entity cache for testing"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.cache import get_redis_manager

redis = get_redis_manager()
client = redis.get_client()

# Clear all entity caches
pattern = "entity:chunk:*"
keys = list(client.scan_iter(pattern))
if keys:
    for key in keys:
        client.delete(key)
    print(f"Cleared {len(keys)} entity cache entries")
else:
    print("No entity cache entries found")

# Also clear doc entity mentions
pattern = "doc:entity_mentions:*"  
keys = list(client.scan_iter(pattern))
if keys:
    for key in keys:
        client.delete(key)
    print(f"Cleared {len(keys)} document entity cache entries")

print("Cache cleared!")