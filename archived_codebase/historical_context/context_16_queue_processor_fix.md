# Queue Processor Fix Analysis

## Problem Identification

### Primary Error
The queue processor fails with the following error:
```
APIError: {'message': 'Could not find the function public.execute_query(query) in the schema cache', 'code': 'PGRST202', 'hint': 'Perhaps you meant to call the function public.process_document_queue'}
```

**Location**: `/scripts/queue_processor.py:72`
```python
response = self.db_manager.client.rpc('execute_query', {"query": claim_query}).execute()
```

**Root Cause**: The queue processor attempts to use a non-existent RPC function `execute_query()` to execute raw SQL queries, but this function is not defined in the Supabase database schema.

## Affected Code Locations

### Direct RPC Execute_Query Calls
1. **queue_processor.py:72** - Document claiming query
2. **queue_processor.py:198** - Stalled document reset query
3. **queue_processor.py:199** - Failed stalled document query
4. **supabase_utils.py:588** - Entity extraction query

### Raw SQL Usage Pattern
The following locations use complex SQL queries that cannot be easily converted to standard Supabase API calls:

#### queue_processor.py
- **Lines 48-68**: Complex CTE query with `FOR UPDATE SKIP LOCKED` for atomic document claiming
- **Lines 155-174**: Stalled document detection and reset with temporal logic
- **Lines 176-196**: Failed document handling with attempt counting

#### supabase_utils.py
- **Lines 567-586**: Complex JOIN query with JSON aggregation for entity extraction

## Schema Conflicts and Missing Functions

### Missing Database Functions
1. **execute_query()** - Expected to execute arbitrary SQL, but not defined
2. **process_document_queue()** - Hinted by error message but usage unclear

### Schema Column Mismatches
Based on error patterns and code analysis:

1. **document_processing_queue table** expects columns:
   - `status, attempts, max_attempts, priority, created_at`
   - `last_attempt_at, processing_started_at, processor_id, updated_at`
   - `source_document_id, source_document_uuid`

2. **Potential missing columns** referenced in code:
   - `processing_completed_at` (queue_processor.py:130)

## Proposed Fixes

### Immediate Fix: Replace RPC Calls with Supabase API

#### 1. Fix Document Claiming (queue_processor.py:35-122)

**Problem**: Complex atomic claiming requires `FOR UPDATE SKIP LOCKED`
**Solution**: Use simpler Supabase API with retry logic

```python
def claim_pending_documents(self) -> List[Dict]:
    """Simplified document claiming using Supabase API"""
    try:
        # Get project info
        project_sql_id, project_uuid = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL, "My Legal Project")
        
        # Simple query for pending documents
        response = self.db_manager.client.table('document_processing_queue')\
            .select('*')\
            .eq('status', 'pending')\
            .lt('attempts', 3)\
            .order('priority.asc,created_at.asc')\
            .limit(self.batch_size)\
            .execute()
        
        claimed_items = []
        for item in response.data:
            # Attempt to claim each document individually
            try:
                update_response = self.db_manager.client.table('document_processing_queue')\
                    .update({
                        'status': 'processing',
                        'attempts': item['attempts'] + 1,
                        'last_attempt_at': datetime.now().isoformat(),
                        'processing_started_at': datetime.now().isoformat(),
                        'processor_id': self.processor_id,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('id', item['id'])\
                    .eq('status', 'pending')\
                    .execute()
                
                if update_response.data:
                    claimed_items.append(item)
                    
            except Exception as e:
                logger.warning(f"Could not claim document {item['id']}: {e}")
                continue
                
        # Process claimed documents...
        return self._process_claimed_documents(claimed_items, project_sql_id)
        
    except Exception as e:
        logger.error(f"Error claiming documents: {e}")
        return []
```

#### 2. Fix Stalled Document Check (queue_processor.py:150-217)

**Problem**: Complex temporal queries with bulk updates
**Solution**: Simple API calls with individual updates

```python
def check_for_stalled_documents(self):
    """Check for stalled documents using Supabase API"""
    try:
        stalled_threshold = (datetime.now() - self.max_processing_time).isoformat()
        
        # Find stalled documents
        response = self.db_manager.client.table('document_processing_queue')\
            .select('*')\
            .eq('status', 'processing')\
            .lt('processing_started_at', stalled_threshold)\
            .limit(10)\
            .execute()
        
        for doc in response.data:
            if doc['attempts'] < doc.get('max_attempts', 3):
                # Reset to pending
                self.db_manager.client.table('document_processing_queue')\
                    .update({
                        'status': 'pending',
                        'last_error': f'Processing timed out by processor_id={doc["processor_id"]}. Resetting.',
                        'processing_started_at': None,
                        'processor_id': None,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('id', doc['id'])\
                    .execute()
            else:
                # Mark as failed
                self.mark_queue_item_failed(doc['id'], 'Processing timed out. Max attempts reached.', doc['source_document_id'])
                
    except Exception as e:
        logger.error(f"Error checking stalled documents: {e}")
```

#### 3. Fix Entity Extraction Query (supabase_utils.py:561-594)

**Problem**: Complex JOIN with JSON aggregation
**Solution**: Separate queries with client-side aggregation

```python
def get_documents_for_entity_extraction(self, limit: int = 20) -> List[Dict]:
    """Get documents for entity extraction using separate API calls"""
    try:
        # Get documents ready for entity extraction
        docs_response = self.client.table('neo4j_documents')\
            .select('*')\
            .eq('processingStatus', 'pending_entities')\
            .limit(limit)\
            .execute()
        
        documents_with_chunks = []
        for doc in docs_response.data:
            # Get chunks for each document
            chunks_response = self.client.table('neo4j_chunks')\
                .select('*')\
                .eq('document_id', doc['id'])\
                .order('chunkIndex.asc')\
                .execute()
            
            # Add chunks to document
            doc['chunks'] = chunks_response.data
            documents_with_chunks.append(doc)
        
        logger.info(f"Found {len(documents_with_chunks)} documents for entity extraction")
        return documents_with_chunks
        
    except Exception as e:
        logger.error(f"Error fetching documents for entity extraction: {e}")
        raise
```

### Database Schema Recommendations

#### Required Database Functions (if RPC approach preferred)
```sql
-- Create execute_query function (not recommended for security)
CREATE OR REPLACE FUNCTION public.execute_query(query text)
RETURNS TABLE(result jsonb)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- This is a security risk and should be avoided
    -- Only shown for completeness
    RETURN QUERY EXECUTE query;
END;
$$;

-- Better: Create specific functions for each use case
CREATE OR REPLACE FUNCTION public.claim_pending_documents(
    p_batch_size int,
    p_processor_id text
)
RETURNS TABLE(
    queue_id int,
    source_document_id int,
    source_document_uuid uuid,
    attempts int
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH selected_rows AS (
        SELECT id
        FROM document_processing_queue
        WHERE status = 'pending' AND attempts < max_attempts
        ORDER BY priority ASC, created_at ASC
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    )
    UPDATE document_processing_queue q
    SET
        status = 'processing',
        attempts = q.attempts + 1,
        last_attempt_at = NOW(),
        processing_started_at = NOW(),
        processor_id = p_processor_id,
        updated_at = NOW()
    FROM selected_rows sr
    WHERE q.id = sr.id
    RETURNING q.id, q.source_document_id, q.source_document_uuid, q.attempts;
END;
$$;
```

#### Required Schema Updates
```sql
-- Ensure document_processing_queue has all required columns
ALTER TABLE document_processing_queue 
ADD COLUMN IF NOT EXISTS processing_completed_at timestamp with time zone;

-- Add any missing indexes for performance
CREATE INDEX IF NOT EXISTS idx_queue_status_priority 
ON document_processing_queue(status, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_queue_processing_started
ON document_processing_queue(processing_started_at) 
WHERE status = 'processing';
```

## Recommended Implementation Approach

### Phase 1: Quick Fix (Immediate)
1. Replace all `execute_query` RPC calls with equivalent Supabase API calls
2. Accept potential race conditions in document claiming (can be mitigated with retry logic)
3. Test queue processor functionality

### Phase 2: Optimal Solution (Future)
1. Create specific RPC functions for complex operations requiring atomicity
2. Implement proper database functions for document claiming with `FOR UPDATE SKIP LOCKED`
3. Add comprehensive error handling and monitoring

### Phase 3: Performance Optimization
1. Add database indexes for queue operations
2. Implement connection pooling if needed
3. Add metrics and monitoring for queue performance

## Security Considerations

- **Never implement generic `execute_query` function** - major SQL injection risk
- Use parameterized queries and specific RPC functions instead
- Validate all inputs before database operations
- Implement proper error handling to avoid information leakage

## Testing Strategy

1. **Unit Tests**: Test each fixed function individually
2. **Integration Tests**: Test complete queue processing workflow
3. **Load Tests**: Verify performance with multiple concurrent processors
4. **Edge Cases**: Test error conditions, stalled documents, and recovery scenarios

## Migration Steps

1. Update `queue_processor.py` with API-based implementations
2. Update `supabase_utils.py` entity extraction method
3. Test with single document processing
4. Deploy and monitor queue processor behavior
5. Implement database functions for atomicity if needed