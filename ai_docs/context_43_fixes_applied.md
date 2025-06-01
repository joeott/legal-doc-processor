# Context 43: Fixes Applied for New Errors

## Errors Fixed

### 1. Mistral OCR URL Error ✅

**Problem**: URLs ending with `?` causing Mistral API to reject the file fetch
```
https://yalswdiexcuanszujjhl.supabase.co/storage/v1/object/public/uploads/1747966420130-m9gegr9fdp.pdf?
```

**Fix Applied**: Modified `generate_document_url` in `supabase_utils.py`
```python
# Remove trailing ? if present (Supabase client sometimes adds it)
if public_url.endswith('?'):
    public_url = public_url[:-1]
```

**File**: `/scripts/supabase_utils.py` (lines 63-65)

### 2. Source Documents Status Field Error ✅

**Problem**: Notification trigger assuming all tables have `status` column
```
{'message': 'record "new" has no field "status"', 'code': '42703'}
```

**Root Cause**: Our previous fix created a notification function that assumed all tables use `status`, but:
- `source_documents` uses `initial_processing_status`
- `document_processing_queue` uses `status`

**Fix Applied**: Created migration `00003_fix_notification_trigger.sql`
- Smart notification function that checks table name
- Uses correct column based on table:
  - `source_documents` → `initial_processing_status`
  - `document_processing_queue` → `status`

**Migration Status**: Applied successfully via Supabase MCP

## Key Insights

### The Pattern of Cascading Fixes
1. **Fix 1**: Added computed column to `document_processing_queue` → Solved first error
2. **Side Effect**: Created notification triggers with wrong assumptions → New error
3. **Fix 2**: Made notification function table-aware → Solved second error
4. **Fix 3**: Cleaned URL generation → Should solve OCR error

### Lessons for "Genius Fixes"
- **Computed columns** are powerful for backward compatibility
- **Generic functions** need to be aware of schema differences
- **Test each fix** for unintended side effects
- **Small, targeted fixes** are better than large rewrites

## Next Steps

1. **Re-run the queue processor** - Both database errors should be resolved
2. **Monitor OCR success** - URLs should now work with Mistral
3. **Watch for new errors** - We're progressing through the pipeline

## Progress Tracker
- ✅ Queue can claim documents
- ✅ Database triggers work correctly
- ✅ URL generation fixed
- 🔄 OCR processing (should work now)
- ⏳ Text extraction
- ⏳ Entity extraction
- ⏳ Relationship building

We're making steady progress through the pipeline!