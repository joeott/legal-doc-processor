#!/usr/bin/env python3
"""Trigger pipeline continuation with proper arguments"""
from scripts.cache import get_redis_manager, CacheKeys
from scripts.pdf_tasks import continue_pipeline_after_ocr, chunk_document_text

doc_uuid = "4dcc5583-b2cc-4d68-bdd0-6e227a98cf8b"
redis = get_redis_manager()

# Get OCR result from cache
ocr_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=doc_uuid)
ocr_result = redis.get_dict(ocr_key)

if ocr_result and ocr_result.get('status') == 'success':
    text = ocr_result.get('text', '')
    print(f"Found OCR text: {len(text)} characters")
    
    # Option 1: Trigger continue_pipeline (which calls chunking)
    # print("Triggering continue_pipeline_after_ocr...")
    # task = continue_pipeline_after_ocr.delay(doc_uuid, text)
    # print(f"Task ID: {task.id}")
    
    # Option 2: Go directly to chunking
    print("Triggering chunk_document_text directly...")
    task = chunk_document_text.delay(doc_uuid, text, chunk_size=1000, overlap=100)
    print(f"Chunking task ID: {task.id}")
else:
    print("No OCR result found in cache")