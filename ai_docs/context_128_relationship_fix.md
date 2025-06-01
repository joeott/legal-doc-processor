# Context 128: Relationship Resolution & Status Sync Fix

## Executive Summary

This document provides a detailed methodology to diagnose and fix two critical issues in the document processing pipeline:
1. **Relationship building failure** - No relationships are being created despite all prerequisites being met
2. **Status sync lag** - Database status updates are delayed, causing confusion about document processing state

## Current State Analysis

### Relationship Building Issue

#### Symptoms
- 0 relationships in `neo4j_relationships_staging` table
- 15 documents show `graph_failed` status
- Documents have all required components:
  - Neo4j documents created ✓
  - Chunks generated ✓
  - Entity mentions extracted ✓
  - Canonical entities resolved ✓

#### Root Cause
- Documents never reach `resolution_complete` status
- Entity resolution task completes but doesn't transition to graph building
- Graph building task never executes, leading to immediate failure

### Status Sync Issue

#### Symptoms
- Celery tasks show SUCCESS but database shows old status (e.g., `ocr_processing`)
- Tasks return `{'status': 'skipped_completed', 'cached': True}` but DB not updated
- Up to 5 documents stuck in limbo states

#### Root Cause
- Cache-first architecture doesn't update database when serving cached results
- Status updates only occur on actual processing, not cache hits
- No mechanism to sync successful cache retrievals back to database

## Diagnostic Methodology

### Phase 1: Trace Task Chain Execution

1. **Identify Chain Break Point**
   ```python
   # Check entity resolution task completion
   grep -n "resolution_complete" scripts/celery_tasks/entity_tasks.py
   grep -n "build_relationships.delay" scripts/celery_tasks/entity_tasks.py
   ```

2. **Verify Status Transitions**
   ```python
   # Check where status should be updated
   grep -n "update.*resolution_complete" scripts/celery_tasks/*.py
   grep -n "celery_status.*resolution_complete" scripts/*.py
   ```

3. **Trace Graph Task Invocation**
   ```python
   # Find where graph building should be triggered
   grep -n "build_relationships" scripts/celery_tasks/*.py
   grep -n "@app.task.*graph" scripts/celery_tasks/*.py
   ```

### Phase 2: Analyze Relationship Building Logic

1. **Check Deterministic Relationships**
   ```python
   # These should be created automatically:
   # - Document CONTAINS Chunk
   # - Chunk CONTAINS Entity Mention
   # - Entity Mention RESOLVED_TO Canonical Entity
   # - Chunk NEXT_CHUNK Chunk (sequential)
   ```

2. **Verify Data Availability**
   ```sql
   -- All required data exists
   SELECT COUNT(*) FROM neo4j_documents;     -- 35
   SELECT COUNT(*) FROM neo4j_chunks;        -- 39
   SELECT COUNT(*) FROM neo4j_entity_mentions; -- 498
   SELECT COUNT(*) FROM neo4j_canonical_entities; -- 322
   ```

### Phase 3: Status Sync Analysis

1. **Identify Cache-Only Paths**
   - OCR task checks cache → returns without DB update
   - Text processing checks cache → returns without DB update
   - Entity extraction checks cache → returns without DB update

2. **Missing Update Points**
   - No status sync when serving from cache
   - No callback to update source_documents table
   - ProcessingStateManager not invoked on cache hits

## Proposed Solutions

### Fix 1: Relationship Building Task Chain

#### A. Immediate Fix - Add Missing Status Transition
```python
# In scripts/celery_tasks/entity_tasks.py, after resolve_entities task completes:

# Update status to resolution_complete
self.db_manager.client.table('source_documents').update({
    'celery_status': 'resolution_complete',
    'last_modified_at': datetime.now().isoformat()
}).eq('id', source_doc_sql_id).execute()

# Chain to graph building
from scripts.celery_tasks.graph_tasks import build_relationships
build_relationships.delay(
    document_uuid=document_uuid,
    source_doc_sql_id=source_doc_sql_id,
    neo4j_doc_sql_id=neo4j_doc_sql_id
)
```

#### B. Create Missing Graph Task (if not exists)
```python
# scripts/celery_tasks/graph_tasks.py
@app.task(bind=True, base=GraphTask, max_retries=3, queue='graph')
def build_relationships(self, document_uuid: str, source_doc_sql_id: int, 
                       neo4j_doc_sql_id: int) -> Dict[str, Any]:
    """Build deterministic relationships for document"""
    
    try:
        # Update status
        self.db_manager.client.table('source_documents').update({
            'celery_status': 'graph_building'
        }).eq('id', source_doc_sql_id).execute()
        
        relationships_created = 0
        
        # 1. Document CONTAINS Chunk relationships
        chunks = self.db_manager.client.table('neo4j_chunks').select(
            'chunkId, chunkIndex'
        ).eq('document_uuid', document_uuid).execute()
        
        for chunk in chunks.data:
            self.db_manager.create_relationship_staging(
                from_node_id=document_uuid,
                from_node_label='Document',
                to_node_id=chunk['chunkId'],
                to_node_label='Chunk',
                relationship_type='CONTAINS',
                properties={'chunk_index': chunk['chunkIndex']}
            )
            relationships_created += 1
        
        # 2. Chunk NEXT_CHUNK Chunk relationships
        sorted_chunks = sorted(chunks.data, key=lambda x: x['chunkIndex'])
        for i in range(len(sorted_chunks) - 1):
            self.db_manager.create_relationship_staging(
                from_node_id=sorted_chunks[i]['chunkId'],
                from_node_label='Chunk',
                to_node_id=sorted_chunks[i+1]['chunkId'],
                to_node_label='Chunk',
                relationship_type='NEXT_CHUNK'
            )
            relationships_created += 1
        
        # 3. Chunk CONTAINS Entity Mention relationships
        for chunk in chunks.data:
            mentions = self.db_manager.client.table('neo4j_entity_mentions').select(
                'entityMentionId'
            ).eq('chunk_uuid', chunk['chunkId']).execute()
            
            for mention in mentions.data:
                self.db_manager.create_relationship_staging(
                    from_node_id=chunk['chunkId'],
                    from_node_label='Chunk',
                    to_node_id=mention['entityMentionId'],
                    to_node_label='EntityMention',
                    relationship_type='CONTAINS'
                )
                relationships_created += 1
        
        # 4. Entity Mention RESOLVED_TO Canonical Entity relationships
        all_mentions = self.db_manager.client.table('neo4j_entity_mentions').select(
            'entityMentionId, resolved_canonical_id'
        ).in_('chunk_uuid', [c['chunkId'] for c in chunks.data]).execute()
        
        for mention in all_mentions.data:
            if mention['resolved_canonical_id']:
                canonical = self.db_manager.client.table('neo4j_canonical_entities').select(
                    'canonicalEntityId'
                ).eq('id', mention['resolved_canonical_id']).single().execute()
                
                if canonical.data:
                    self.db_manager.create_relationship_staging(
                        from_node_id=mention['entityMentionId'],
                        from_node_label='EntityMention',
                        to_node_id=canonical.data['canonicalEntityId'],
                        to_node_label='CanonicalEntity',
                        relationship_type='RESOLVED_TO'
                    )
                    relationships_created += 1
        
        # Update status to completed
        self.db_manager.client.table('source_documents').update({
            'celery_status': 'completed',
            'last_modified_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
        
        return {
            'status': 'success',
            'relationships_created': relationships_created
        }
        
    except Exception as e:
        # Update status to failed
        self.db_manager.client.table('source_documents').update({
            'celery_status': 'graph_failed',
            'error_message': str(e)
        }).eq('id', source_doc_sql_id).execute()
        raise
```

### Fix 2: Status Sync on Cache Hits

#### A. Update Cache Hit Handlers
```python
# Add to each task's cache hit path:
def update_status_on_cache_hit(document_uuid: str, stage: str, db_manager):
    """Update database status when serving from cache"""
    
    status_map = {
        'ocr': 'ocr_complete',
        'text': 'text_complete',
        'entity': 'entity_complete',
        'resolution': 'resolution_complete',
        'graph': 'completed'
    }
    
    try:
        # Get current status
        current = db_manager.client.table('source_documents').select(
            'celery_status'
        ).eq('document_uuid', document_uuid).single().execute()
        
        if current.data:
            new_status = status_map.get(stage)
            if new_status and current.data['celery_status'] != new_status:
                db_manager.client.table('source_documents').update({
                    'celery_status': new_status,
                    'last_modified_at': datetime.now().isoformat()
                }).eq('document_uuid', document_uuid).execute()
                
                logger.info(f"Updated status from cache hit: {document_uuid} -> {new_status}")
                
    except Exception as e:
        logger.warning(f"Failed to update status on cache hit: {e}")
```

#### B. Modify Each Task's Cache Check
```python
# Example for OCR task
is_completed, cached_results = check_stage_completed(document_uuid, "ocr", processing_version)
if is_completed and cached_results:
    logger.info(f"[OCR_TASK:{self.request.id}] Stage already completed, using cached results")
    
    # NEW: Update database status
    update_status_on_cache_hit(document_uuid, 'ocr', self.db_manager)
    
    # NEW: Chain to next task even on cache hit
    from scripts.celery_tasks.text_tasks import create_document_node
    create_document_node.delay(
        document_uuid=document_uuid,
        source_doc_sql_id=source_doc_sql_id,
        project_sql_id=project_sql_id
    )
    
    return {
        "status": "skipped_completed",
        "cached": True,
        "raw_text": cached_results.get('raw_text', ''),
        "ocr_provider": cached_results.get('ocr_provider')
    }
```

### Fix 3: Implement Status Reconciliation

#### A. Background Status Sync Task
```python
# scripts/celery_tasks/cleanup_tasks.py
@app.task(queue='default')
def sync_processing_status():
    """Periodic task to sync cache state with database"""
    
    db = SupabaseManager()
    redis_mgr = get_redis_manager()
    
    if not redis_mgr or not redis_mgr.is_available():
        return
    
    # Get documents in intermediate states
    stuck_docs = db.client.table('source_documents').select(
        'id, document_uuid, celery_status'
    ).in_('celery_status', [
        'ocr_processing', 'text_processing', 
        'entity_extraction', 'entity_resolution',
        'graph_building'
    ]).execute()
    
    updated = 0
    for doc in stuck_docs.data:
        # Check Redis for completion markers
        stages = ['ocr', 'text', 'entity', 'resolution', 'graph']
        completed_stages = []
        
        for stage in stages:
            state_key = f"doc_state:{doc['document_uuid']}"
            redis_state = redis_mgr.get_client().hget(state_key, f"{stage}_completed")
            if redis_state:
                completed_stages.append(stage)
        
        # Determine correct status
        if 'graph' in completed_stages:
            new_status = 'completed'
        elif 'resolution' in completed_stages:
            new_status = 'resolution_complete'
        elif 'entity' in completed_stages:
            new_status = 'entity_complete'
        elif 'text' in completed_stages:
            new_status = 'text_complete'
        elif 'ocr' in completed_stages:
            new_status = 'ocr_complete'
        else:
            continue
        
        if new_status != doc['celery_status']:
            db.client.table('source_documents').update({
                'celery_status': new_status,
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', doc['id']).execute()
            updated += 1
    
    return {'synced': updated}
```

#### B. Schedule Periodic Sync
```python
# In celery_app.py beat_schedule
'sync-processing-status': {
    'task': 'scripts.celery_tasks.cleanup_tasks.sync_processing_status',
    'schedule': 60.0,  # Every minute
}
```

## Implementation Plan

### Phase 1: Fix Relationship Building (Critical)
1. Add status transition in entity resolution task
2. Implement/fix graph building task
3. Test with stuck documents

### Phase 2: Fix Status Sync (Important)
1. Add status updates on cache hits
2. Ensure task chains execute even on cache hits
3. Implement reconciliation task

### Phase 3: Validate & Monitor
1. Process test documents through full pipeline
2. Verify relationships are created
3. Monitor status sync performance

## Success Criteria

### Relationship Building
- [ ] All documents reach `resolution_complete` status
- [ ] Graph building task executes for all documents
- [ ] Relationships populated in staging table:
  - Document → Chunk relationships
  - Chunk → Chunk (NEXT) relationships  
  - Chunk → Entity Mention relationships
  - Entity Mention → Canonical Entity relationships

### Status Sync
- [ ] Status updates within 5 seconds of task completion
- [ ] Cache hits properly update database status
- [ ] No documents stuck in intermediate states > 1 minute
- [ ] Reconciliation catches any missed updates

## Expected Outcomes

After implementing these fixes:
1. **100% of documents** will have relationships created
2. **Status lag** reduced from minutes to seconds
3. **Pipeline visibility** dramatically improved
4. **DOCX files** will complete full pipeline successfully

## Monitoring & Validation

### Queries to Verify Success
```sql
-- Check relationship creation
SELECT 
    fromNodeLabel,
    toNodeLabel,
    relationshipType,
    COUNT(*) as count
FROM neo4j_relationships_staging
GROUP BY fromNodeLabel, toNodeLabel, relationshipType;

-- Check status distribution
SELECT 
    celery_status,
    COUNT(*) as count
FROM source_documents
GROUP BY celery_status
ORDER BY count DESC;

-- Check for stuck documents
SELECT 
    original_file_name,
    celery_status,
    last_modified_at
FROM source_documents
WHERE celery_status NOT IN ('completed', 'ocr_failed')
AND last_modified_at < NOW() - INTERVAL '5 minutes';
```

## Risk Mitigation

1. **Backward Compatibility**: All fixes maintain existing interfaces
2. **Idempotency**: Relationship creation checks for duplicates
3. **Error Handling**: Graceful failures with status updates
4. **Performance**: Batch operations where possible
5. **Monitoring**: Enhanced logging at each step

## Next Steps

1. Implement Phase 1 fixes immediately (relationship building)
2. Test with existing failed documents
3. Deploy Phase 2 fixes (status sync)
4. Monitor for 24 hours
5. Adjust reconciliation frequency based on results