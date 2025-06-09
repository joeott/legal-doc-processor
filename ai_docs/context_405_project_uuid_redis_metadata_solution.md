# Context 405: Project UUID Redis Metadata Solution

**Date**: June 5, 2025  
**Time**: 02:20 AM UTC  
**Status**: CRITICAL ARCHITECTURE ISSUE  
**Issue**: Pipeline fails after OCR because project_uuid is not found in Redis metadata

## Problem Analysis

### Root Cause
The pipeline architecture has a critical disconnect between database storage and Redis metadata flow:

1. **Database Schema**: The `source_documents` table has BOTH columns:
   - `project_fk_id` (integer foreign key to projects.id)
   - `project_uuid` (UUID field, currently NULL)

2. **Current Implementation**:
   - `create_document_record()` only sets `project_fk_id`
   - `project_uuid` remains NULL in the database
   - No Redis metadata is created when documents are submitted

3. **Pipeline Expectation**:
   - Tasks expect to find `project_uuid` in Redis at key `doc:metadata:{document_uuid}`
   - This metadata is NEVER created, causing pipeline failure after OCR

### Evidence

1. **OCR Success**:
   ```json
   {
     "ocr": {
       "status": "completed",
       "confidence": 98.55,
       "pages": 2
     }
   }
   ```

2. **Pipeline Failure**:
   ```
   ERROR: No project_uuid found for document 43ed6fe8-5402-40a4-b01f-aa0dcaeec47b
   ```

3. **Redis State**:
   - Key `doc:metadata:43ed6fe8-5402-40a4-b01f-aa0dcaeec47b` does NOT exist
   - Only keys found: `doc:state:*`, `textract:result:*`, `doc:status:*`

4. **Database State**:
   ```sql
   document_uuid: 43ed6fe8-5402-40a4-b01f-aa0dcaeec47b
   project_fk_id: 1
   project_uuid: NULL
   ```

### Data Flow Analysis

1. **Document Creation** (batch_processor.py):
   - Creates database record with `project_fk_id`
   - Submits Celery tasks
   - Does NOT create Redis metadata

2. **OCR Task** (pdf_tasks.py):
   - Validates document exists in database
   - Processes OCR successfully
   - Stores result in Redis
   - Calls `continue_pipeline_after_ocr`

3. **Pipeline Continuation** (pdf_tasks.py):
   - Tries to read `doc:metadata:{uuid}` from Redis
   - Expects to find `project_uuid`
   - FAILS because metadata was never created

4. **Downstream Tasks**:
   - Entity resolution needs `project_uuid` for canonical entity creation
   - Relationship building needs `project_uuid` for graph context
   - All fail due to missing metadata

## Proposed Solution

### Option 1: Populate Redis Metadata at Document Creation (Recommended)

**Advantages**:
- Maintains existing pipeline architecture
- Minimal code changes
- Clear separation of concerns

**Implementation**:

1. **Generate UUID for Projects**:
   ```python
   # In production_processor.py ensure_project_exists()
   def ensure_project_exists(self, project_id: int, project_name: str) -> str:
       """Ensure project exists and return its UUID."""
       for session in self.db_manager.get_session():
           # Check if project exists
           project = session.execute(text(
               "SELECT id, project_uuid FROM projects WHERE id = :id"
           ), {'id': project_id}).fetchone()
           
           if not project:
               # Generate UUID for new project
               project_uuid = str(uuid.uuid4())
               session.execute(text("""
                   INSERT INTO projects (id, name, project_uuid, created_at, updated_at)
                   VALUES (:id, :name, :uuid, NOW(), NOW())
               """), {
                   'id': project_id,
                   'name': project_name,
                   'uuid': project_uuid
               })
               session.commit()
               return project_uuid
           else:
               # Return existing UUID or generate if NULL
               if project[1]:
                   return project[1]
               else:
                   # Update existing project with UUID
                   project_uuid = str(uuid.uuid4())
                   session.execute(text(
                       "UPDATE projects SET project_uuid = :uuid WHERE id = :id"
                   ), {'uuid': project_uuid, 'id': project_id})
                   session.commit()
                   return project_uuid
   ```

2. **Store Metadata in Redis During Document Creation**:
   ```python
   # In batch_processor.py after create_document_record()
   def submit_batch_for_processing(self, batch: BatchManifest, project_id: int = 1) -> BatchJobId:
       # ... existing code ...
       
       # Get project UUID
       project_uuid = self._get_project_uuid(project_id)
       
       for doc in batch.documents:
           try:
               # CREATE DATABASE RECORD FIRST
               for session in self.db_manager.get_session():
                   document_uuid = create_document_record(
                       session,
                       original_filename=doc.get('filename'),
                       s3_bucket=doc.get('s3_bucket'),
                       s3_key=doc.get('s3_key'),
                       file_size_mb=doc.get('file_size_mb', 0.0),
                       mime_type=doc.get('mime_type', 'application/pdf'),
                       project_id=project_id,
                       project_uuid=project_uuid  # Add this
                   )
                   
               # STORE METADATA IN REDIS
               metadata_key = f"doc:metadata:{document_uuid}"
               metadata = {
                   'project_uuid': project_uuid,
                   'project_id': project_id,
                   'document_metadata': {
                       'filename': doc.get('filename'),
                       's3_bucket': doc.get('s3_bucket'),
                       's3_key': doc.get('s3_key'),
                       'uploaded_at': datetime.now().isoformat()
                   }
               }
               self.redis.set_dict(metadata_key, metadata, ttl=86400)  # 24 hours
   ```

3. **Update create_document_record to include project_uuid**:
   ```python
   def create_document_record(session, original_filename: str, s3_bucket: str, s3_key: str, 
                             file_size_mb: float, mime_type: str, project_id: int = 1,
                             project_uuid: str = None) -> str:
       # ... existing code ...
       
       session.execute(text("""
           INSERT INTO source_documents (
               document_uuid, original_file_name, file_name, s3_bucket, s3_key,
               file_size_bytes, file_type, detected_file_type, status,
               created_at, updated_at, project_fk_id, project_uuid
           ) VALUES (
               :uuid, :filename, :filename, :bucket, :key,
               :size_bytes, :file_type, :file_type, 'pending',
               NOW(), NOW(), :project_id, :project_uuid
           )
       """), {
           'uuid': document_uuid,
           'filename': original_filename,
           'bucket': s3_bucket,
           'key': s3_key,
           'size_bytes': file_size_bytes,
           'file_type': mime_type,
           'project_id': project_id,
           'project_uuid': project_uuid
       })
   ```

### Option 2: Read from Database in Pipeline Tasks

**Advantages**:
- No Redis metadata needed
- Single source of truth (database)

**Disadvantages**:
- Requires database queries in every task
- Performance impact
- Major refactoring of pipeline tasks

**Implementation**:
```python
# In pdf_tasks.py continue_pipeline_after_ocr()
def continue_pipeline_after_ocr(self, document_uuid: str, text: str) -> Dict[str, Any]:
    # Get project info from database instead of Redis
    session = next(self.db_manager.get_session())
    try:
        doc_info = session.execute(text("""
            SELECT project_uuid, project_fk_id 
            FROM source_documents 
            WHERE document_uuid = :uuid
        """), {'uuid': document_uuid}).fetchone()
        
        if not doc_info or not doc_info[0]:
            # Fallback: generate project_uuid if missing
            project_uuid = str(uuid.uuid4())
            session.execute(text("""
                UPDATE source_documents 
                SET project_uuid = :p_uuid 
                WHERE document_uuid = :d_uuid
            """), {'p_uuid': project_uuid, 'd_uuid': document_uuid})
            session.commit()
        else:
            project_uuid = doc_info[0]
    finally:
        session.close()
```

### Option 3: Hybrid Approach (Best Long-term)

Combine both approaches for reliability:

1. **Always populate project_uuid in database** when creating documents
2. **Cache in Redis** for performance
3. **Fallback to database** if Redis cache misses
4. **Auto-heal**: If project_uuid is NULL, generate and update

## Implementation Priority

### Phase 1: Immediate Fix (Option 1)
1. Update `ensure_project_exists` to handle project UUIDs
2. Modify `create_document_record` to accept project_uuid
3. Add Redis metadata creation in `submit_batch_for_processing`
4. Test with single document

### Phase 2: Robustness (Option 3)
1. Add database fallback in pipeline tasks
2. Implement auto-healing for NULL project_uuids
3. Add monitoring for metadata consistency

### Phase 3: Architecture Cleanup
1. Standardize on project_uuid vs project_id usage
2. Remove redundant project_fk_id where possible
3. Document the data flow clearly

## Testing Strategy

1. **Unit Tests**:
   - Test project UUID generation
   - Test Redis metadata creation
   - Test fallback mechanisms

2. **Integration Tests**:
   - Full pipeline with metadata
   - Recovery from missing metadata
   - Project association validation

3. **Production Verification**:
   - Monitor Redis metadata creation
   - Track pipeline success rates
   - Verify project associations

## Benefits

1. **Immediate**: Unblocks pipeline processing
2. **Reliability**: Consistent project tracking
3. **Performance**: Redis caching for fast access
4. **Maintainability**: Clear data flow
5. **Scalability**: Supports multi-project processing

## Risks and Mitigation

1. **Risk**: Redis cache inconsistency
   - **Mitigation**: TTL and database fallback

2. **Risk**: NULL project_uuids in legacy data
   - **Mitigation**: Auto-generation on first access

3. **Risk**: Performance impact of database queries
   - **Mitigation**: Redis caching with proper TTL

## Conclusion

The project UUID issue stems from an architectural mismatch between database schema and pipeline expectations. The recommended solution (Option 1) provides a quick fix by populating Redis metadata during document creation, while the hybrid approach (Option 3) offers long-term reliability with automatic fallbacks and self-healing capabilities.

This fix is essential for enabling full pipeline processing and must be implemented before production deployment.