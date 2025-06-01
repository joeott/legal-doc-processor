# Context 42: New Errors After Initial Fix - Diagnosis

## Error 1: Mistral OCR Cannot Fetch File ❌

### Error Details
```json
{
  "object": "error",
  "message": "An error happened when fetching file from url https://yalswdiexcuanszujjhl.supabase.co/storage/v...bject/public/uploads/1747966420130-m9gegr9fdp.pdf?",
  "type": "invalid_file",
  "param": null,
  "code": "1901"
}
```

### Root Cause
The URL ends with a `?` character, which likely makes it invalid. The URL generation is adding an unnecessary query string terminator.

### Generated URL
```
https://yalswdiexcuanszujjhl.supabase.co/storage/v1/object/public/uploads/1747966420130-m9gegr9fdp.pdf?
```

### Fix Required
Remove the trailing `?` from the URL generation in `generate_document_url` function.

## Error 2: Source Documents Status Field ❌

### Error Details
```
{'message': 'record "new" has no field "status"', 'code': '42703', 'hint': None, 'details': None}
```

### Occurrence
When trying to update `source_documents` table with:
```python
db_manager.update_source_document_text(source_doc_sql_id, None, status="extraction_failed")
```

### Root Cause Analysis
This is the SAME type of error as before, but now affecting the `source_documents` table. A trigger on `source_documents` is trying to access a field called `status` that doesn't exist.

### The Pattern
1. First error: Trigger on `document_processing_queue` looking for `initial_processing_status`
2. Second error: Trigger on `source_documents` looking for `status`

The migration we applied earlier created new triggers, and one of them is incorrectly referencing `NEW.status` on `source_documents` table.

## Quick Diagnosis Check

Let me check what columns actually exist on `source_documents`:

```sql
SELECT column_name 
FROM information_schema.columns 
WHERE table_name = 'source_documents' 
ORDER BY ordinal_position;
```

Expected: The table has `initial_processing_status` but NOT `status`.

## The Problem in Our Migration

Looking at the migration we just applied (`00002_fix_queue_triggers.sql`), the notification function we created is the culprit:

```sql
CREATE OR REPLACE FUNCTION notify_queue_status_change()
RETURNS TRIGGER AS $$
BEGIN
    -- Simple notification without referencing non-existent columns
    PERFORM pg_notify(
        'document_status_change',
        json_build_object(
            'table', TG_TABLE_NAME,
            'action', TG_OP,
            'id', CASE 
                WHEN TG_OP = 'DELETE' THEN OLD.id 
                ELSE NEW.id 
            END,
            'status', CASE 
                WHEN TG_OP = 'DELETE' THEN OLD.status 
                ELSE NEW.status   -- THIS IS THE PROBLEM!
            END,
            'timestamp', NOW()
        )::text
    );
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
```

This function assumes ALL tables have a `status` column, but `source_documents` uses `initial_processing_status` instead.

## Immediate Fix Required

### Fix 1: URL Generation
```python
# In generate_document_url function, remove trailing ?
url = f"{base_url}/storage/v1/object/public/{bucket_name}/{file_key}"
# NOT: url = f"{base_url}/storage/v1/object/public/{bucket_name}/{file_key}?"
```

### Fix 2: Smart Notification Function
```sql
CREATE OR REPLACE FUNCTION notify_queue_status_change()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'document_status_change',
        json_build_object(
            'table', TG_TABLE_NAME,
            'action', TG_OP,
            'id', CASE 
                WHEN TG_OP = 'DELETE' THEN OLD.id 
                ELSE NEW.id 
            END,
            'status', CASE 
                WHEN TG_TABLE_NAME = 'source_documents' THEN
                    CASE 
                        WHEN TG_OP = 'DELETE' THEN OLD.initial_processing_status 
                        ELSE NEW.initial_processing_status 
                    END
                WHEN TG_TABLE_NAME = 'document_processing_queue' THEN
                    CASE 
                        WHEN TG_OP = 'DELETE' THEN OLD.status 
                        ELSE NEW.status 
                    END
                ELSE NULL
            END,
            'timestamp', NOW()
        )::text
    );
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
```

## Progress Made
1. ✅ Fixed `document_processing_queue` trigger errors
2. ❌ Introduced new trigger error on `source_documents`
3. ❌ URL generation has a bug preventing OCR

We're making progress - the queue processor successfully claimed documents and attempted to process them!