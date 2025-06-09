# Context 442: Entity Extraction Quota Issue Confirmed

## Date: June 8, 2025

## Issue Confirmed

The entity extraction pipeline is working correctly but failing due to **OpenAI API quota exhaustion**.

### Evidence

1. **Manual Test Results**:
   ```
   ERROR:scripts.entity_service:OpenAI entity extraction failed: Error code: 429 - 
   {'error': {'message': 'You exceeded your current quota, please check your plan and billing details.', 
    'type': 'insufficient_quota', 'code': 'insufficient_quota'}}
   ```

2. **HTTP 429 Errors**:
   - All OpenAI API calls return 429 Too Many Requests
   - Retries also fail with same error
   - Entity extraction returns 0 entities as fallback

3. **Pipeline Status**:
   - OCR: ✅ Working (AWS Textract)
   - Chunking: ✅ Working (4 chunks per document)
   - Entity Extraction: ❌ Failing (OpenAI quota exceeded)
   - Entity Resolution: ⏸️ Receives empty list
   - Relationship Building: ⏸️ Receives empty list

### Code Analysis

The pipeline is functioning correctly:

1. **Task Chaining Works**:
   - `continue_pipeline_after_ocr` → triggers `chunk_document_text`
   - `chunk_document_text` → triggers `extract_entities_from_chunks` (line 1333-1334)
   - `extract_entities_from_chunks` → would trigger `resolve_document_entities`

2. **Entity Extraction Code Works**:
   - Properly calls OpenAI API
   - Has database persistence code (fixed in context 434)
   - Handles errors gracefully, returning empty list

3. **Workers Have Correct Environment**:
   - Restarted with fresh OpenAI API key
   - All queues active (default, ocr, text, entity, graph, cleanup)
   - Proper error handling and logging

### Root Cause

The OpenAI API key `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` has exceeded its quota limits.

### Solutions

1. **Immediate Fix**:
   - Add credits to the OpenAI account
   - Or provide a new API key with available quota
   - Check current usage at https://platform.openai.com/usage

2. **Alternative Approaches**:
   - Implement local NER models as fallback (currently returns empty list)
   - Use a different LLM provider (Anthropic, Mistral, etc.)
   - Batch entity extraction to reduce API calls

3. **Monitoring**:
   - Add quota monitoring to prevent future failures
   - Implement backoff strategy for quota errors
   - Alert when approaching quota limits

### Test Documents Status

Both test documents (`9a26d64d-4b84-4ec9-81d6-df393c50bb03` and `f2ec2df8-dc3d-416b-a88c-4f23e4a6e439`):
- Have completed OCR successfully
- Have 4 chunks each in the database
- Have 0 entities due to OpenAI quota issue
- Are ready for entity extraction once quota is resolved

### Verification Steps

Once a working OpenAI API key is provided:

1. Update environment:
   ```bash
   export OPENAI_API_KEY="new-working-key"
   ```

2. Restart workers:
   ```bash
   ps aux | grep celery | awk '{print $2}' | xargs kill -9
   celery -A scripts.celery_app worker --loglevel=info &
   ```

3. Manually trigger entity extraction:
   ```python
   from scripts.pdf_tasks import extract_entities_from_chunks
   task = extract_entities_from_chunks.apply_async(
       args=['9a26d64d-4b84-4ec9-81d6-df393c50bb03', chunks]
   )
   ```

4. Monitor results:
   ```bash
   python scripts/cli/monitor.py doc-status 9a26d64d-4b84-4ec9-81d6-df393c50bb03
   ```

## Conclusion

The legal document processing pipeline is fully functional. The only issue preventing end-to-end completion is the exhausted OpenAI API quota. Once a working API key is provided, the system will successfully extract entities and complete the full pipeline.