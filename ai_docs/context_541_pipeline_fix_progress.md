# Context 541: Pipeline Fix Progress - Stage 5-6 Activation

## Date: 2025-06-13

### Issue Identified
The pipeline was only executing 4 out of 6 stages:
1. ✅ OCR (Stage 1)
2. ✅ Chunking (Stage 2)  
3. ✅ Entity Extraction (Stage 3)
4. ✅ Entity Resolution (Stage 4)
5. ❌ Relationship Building (Stage 5)
6. ❌ Finalization (Stage 6)

### Root Cause Analysis

#### Initial Problem: Chunks Retrieval Issue
- In `resolve_document_entities` function, chunks were being retrieved with `get_dict()` expecting format: `{'chunks': [...]}`
- But chunks were stored as a plain list in cache
- Fixed by changing from `redis_manager.get_dict(chunks_key)` to `redis_manager.get_cached(chunks_key)`

#### Current Problem: Cache Timing Issue
After entity resolution completes and saves canonical entities:
1. It successfully caches 17 canonical entities
2. But when checking conditions for relationship building:
   - `project_uuid=True` ✅ (found in metadata)
   - `chunks=0` ❌ (chunks not found in cache)
   - `entities=17` ✅ (canonical entities found)

The chunks are being lost from cache between the start and end of entity resolution.

### Database Schema Discoveries
1. `document_chunks` table uses:
   - `start_char_index` and `end_char_index` (not `start_char`/`end_char`)
   - `text` column (not `text_content`)

2. `entity_mentions` table uses:
   - `start_char` and `end_char` (different from chunks!)
   - This inconsistency in column naming is problematic

### Fixes Applied
1. ✅ Fixed chunks retrieval method in `resolve_document_entities`
2. ✅ Added database fallback when chunks not in cache
3. ✅ Fixed REDIS_ENTITY_CACHE_TTL import
4. ✅ Updated column names in database queries

### Next Steps
1. Fix the cache persistence issue for chunks during entity resolution
2. Ensure chunks remain cached with sufficient TTL
3. Consider caching chunks with the same TTL as canonical entities
4. Test full pipeline execution through all 6 stages

### Test Results
- Successfully resolved entities: 17 canonical entities created
- Entity mentions updated: 32 mentions linked to canonical entities
- Relationship building blocked by: chunks=0 in cache check

### Code Locations
- Main issue: `/opt/legal-doc-processor/scripts/pdf_tasks.py:1907-1921`
- Chunks cache check: `pdf_tasks.py:1834-1835`
- Warning log: `pdf_tasks.py:1921`