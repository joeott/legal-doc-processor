# Context 492: E2E Document Processing Test Progress

## Date: January 10, 2025

## Session Objective
Run a single document from `/input_docs/` through the entire pipeline to verify:
- Workers are picking up tasks
- Database writes occur appropriately at each stage
- Cache hits are occurring
- Redis is properly sending messages to workers
- Each script's complete function completes without error

## Current Status: In Progress with Issues

### Completed Steps

1. **Document Selected**: `/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf`
   - File size: 149,104 bytes
   - Valid PDF document

2. **Workers Verified**: Celery workers are running
   ```
   ubuntu    189876  0.1  3.6 293540 145120 ?       S    Jun09   2:21 celery worker
   ubuntu    190015  0.0  3.6 302600 144248 ?       S    Jun09   0:00 celery worker
   ubuntu    217527  0.0  3.9 316104 155228 ?       S    Jun09   0:00 celery worker
   ```

3. **Monitoring Script Used**: `monitor_full_pipeline.py` (production script per CLAUDE.md)

### Issues Encountered and Fixed

1. **Issue 1**: `canonical_entities` table query error (FIXED)
   - **Problem**: Line 146-148 tried to query `document_uuid` from `canonical_entities` table
   - **Root Cause**: `canonical_entities` table has no `document_uuid` column (canonical entities are document-agnostic)
   - **Fix Applied**: Changed query to count distinct canonical entities through entity_mentions table:
   ```python
   # Old (incorrect):
   SELECT COUNT(*) FROM canonical_entities WHERE document_uuid = :uuid
   
   # New (correct):
   SELECT COUNT(DISTINCT canonical_entity_uuid) 
   FROM entity_mentions 
   WHERE document_uuid = :uuid AND canonical_entity_uuid IS NOT NULL
   ```

2. **Issue 2**: Missing CacheKeys attribute (NOT YET FIXED)
   - **Problem**: `type object 'CacheKeys' has no attribute 'DOC_CANONICAL'`
   - **Location**: Occurs after chunks are cached (36.71s into processing)
   - **Next Step**: Need to check CacheKeys class definition and add missing attribute

### Processing Progress

The document made it through:
1. ✅ Project creation (project_id: 7)
2. ✅ S3 upload (s3://samu-docs-private-upload/documents/58cd53da-15ce-46bc-b04a-d10a747b67cc.pdf)
3. ✅ Database record creation (document_id: 4, uuid: 58cd53da-15ce-46bc-b04a-d10a747b67cc)
4. ✅ OCR task submission (task_id: 9325f0f7-42ac-48ef-9a90-6537cf0ca0ff)
5. ✅ State caching (2.36s)
6. ✅ Chunks caching (36.71s)
7. ❌ Failed at canonical entities stage

### Cache Performance
- Hits: 96 (27.6% hit rate)
- Misses: 252
- Writes: 3
- Shows Redis acceleration is working

## Next Steps for Resuming

1. **Fix CacheKeys.DOC_CANONICAL issue**:
   ```bash
   # Check CacheKeys definition
   grep -n "class CacheKeys" scripts/cache.py
   grep -n "DOC_CANONICAL" scripts/*.py
   
   # Add missing attribute to CacheKeys class if needed
   ```

2. **Re-run the monitor**:
   ```bash
   cd /opt/legal-doc-processor
   export $(cat .env | grep -v '^#' | xargs)
   python3 monitor_full_pipeline.py
   ```

3. **Monitor specific stages**:
   - Watch for OCR completion
   - Verify chunking creates records in document_chunks table
   - Check entity extraction creates records in entity_mentions table
   - Verify entity resolution updates canonical_entity_uuid in mentions
   - Check relationship extraction populates relationship_staging table

4. **Verify with CLI monitor**:
   ```bash
   python3 scripts/cli/monitor.py live
   ```

## Important Configuration Notes

- CONFORMANCE VALIDATION is BYPASSED (SKIP_CONFORMANCE_CHECK=true)
- Using minimal models for reduced conformance requirements
- Redis acceleration is ENABLED
- S3 bucket region mismatch warning exists but doesn't block processing

## Files Modified
- `/opt/legal-doc-processor/monitor_full_pipeline.py` - Fixed canonical entities query (line 146-151)

## Logs Generated
- `pipeline_report_20250610_120117.json` - First attempt (failed on canonical_entities query)
- `pipeline_report_20250610_120652.json` - Second attempt (failed on CacheKeys.DOC_CANONICAL)
- `full_pipeline_monitor_20250610_120458.log` - Full output log

## Summary for Next Instance

The E2E test is partially working. The pipeline successfully processes through OCR and chunking stages but fails when trying to cache canonical entity data due to a missing CacheKeys attribute. The next instance should:
1. Fix the CacheKeys.DOC_CANONICAL attribute issue
2. Re-run the monitor to complete the full pipeline test
3. Verify all stages complete successfully
4. Check that all expected database records are created
5. Confirm Redis caching is working properly throughout

The test document has already been uploaded to S3 and partially processed, so you may want to either:
- Clear the test data and start fresh, OR
- Continue with the existing document UUID: 58cd53da-15ce-46bc-b04a-d10a747b67cc