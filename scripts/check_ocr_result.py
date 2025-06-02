#!/usr/bin/env python3
"""Check OCR result for a document"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.cache import get_redis_manager, CacheKeys

doc_uuid = '0697af52-8bc6-4299-90ec-5d67b7eeb858'
redis_mgr = get_redis_manager()

# Check OCR result
ocr_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=doc_uuid)
ocr_result = redis_mgr.get_dict(ocr_key)

if ocr_result:
    print('OCR Result found!')
    print(f'Status: {ocr_result.get("status")}')
    print(f'Text type: {type(ocr_result.get("text"))}')
    print(f'Text length: {len(str(ocr_result.get("text", "")))}')
    print(f'Keys: {list(ocr_result.keys())}')
    
    # Show first 200 chars of text
    text = ocr_result.get("text", "")
    if isinstance(text, str):
        print(f'\nFirst 200 chars: {text[:200]}...')
    else:
        print(f'\nText is not a string, it is: {type(text)}')
else:
    print('No OCR result found')