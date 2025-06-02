#!/usr/bin/env python3
"""Check pipeline state and trigger next stage if needed"""
import json
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.pdf_tasks import chunk_document_text, continue_pipeline_after_ocr

# Check document in database
doc_uuid = "4dcc5583-b2cc-4d68-bdd0-6e227a98cf8b"
db = DatabaseManager(validate_conformance=False)
doc = db.get_source_document(doc_uuid)

print(f"Document status in DB:")
print(f"  - Status: {doc.status}")
print(f"  - Celery Status: {doc.celery_status}")
print(f"  - OCR Completed: {doc.ocr_completed_at}")
print(f"  - Raw Text: {'Yes' if doc.raw_extracted_text else 'No'}")
print(f"  - Text length: {len(doc.raw_extracted_text) if doc.raw_extracted_text else 0}")

# Check Redis state
redis = get_redis_manager()
state = redis.get_dict(CacheKeys.DOC_STATE.format(document_uuid=doc_uuid))
print(f"\nRedis state:")
if state:
    print(json.dumps(state, indent=2))
    
# Check OCR result cache
ocr_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=doc_uuid)
ocr_result = redis.get_dict(ocr_key)
if ocr_result:
    print(f"\nOCR result in cache: {ocr_result.get('status')}")
    if ocr_result.get('text'):
        print(f"  - Text length: {len(ocr_result['text'])}")
    
# Check if we need to trigger continuation
if doc.raw_extracted_text or (ocr_result and ocr_result.get('status') == 'success'):
    print("\n✅ OCR is complete, triggering pipeline continuation...")
    task = continue_pipeline_after_ocr.delay(doc_uuid)
    print(f"Continue pipeline task: {task.id}")
else:
    print("\n❌ OCR not complete yet")