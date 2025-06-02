#!/usr/bin/env python3
"""Check Redis state for document"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.cache import get_redis_manager, CacheKeys

doc_uuid = '0697af52-8bc6-4299-90ec-5d67b7eeb858'
redis_mgr = get_redis_manager()

# Check document state
state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
state = redis_mgr.get_dict(state_key)

print('Document State in Redis:')
if state:
    import json
    print(json.dumps(state, indent=2))
else:
    print('  No state found')