#!/usr/bin/env python3
"""
Test pipeline continuation with cached text
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import continue_pipeline_after_ocr
from scripts.cache import get_redis_manager, CacheKeys

# Document with OCR completed
document_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"

print(f"Testing pipeline continuation for document {document_uuid}")

# Get cached text
redis = get_redis_manager()
cache_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)
cached_result = redis.get_dict(cache_key)

if cached_result and cached_result.get('text'):
    text = cached_result['text']
    print(f"Found cached text: {len(text)} characters")
    
    # Trigger pipeline continuation
    result = continue_pipeline_after_ocr.apply_async(
        args=[document_uuid, text]
    )
    
    print(f"Pipeline continuation task scheduled: {result.id}")
    print("Waiting for result...")
    
    try:
        task_result = result.get(timeout=30)
        print(f"Result: {task_result}")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("No cached text found!")