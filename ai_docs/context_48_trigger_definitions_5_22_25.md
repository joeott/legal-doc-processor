# Document Processing Pipeline: Trigger System Guide

## Overview

Your Supabase database implements a sophisticated trigger system that automatically manages data flow between tables as documents progress through your NLP preprocessing pipeline. This guide explains how each trigger functions to orchestrate the movement of data from initial document intake through final Neo4j preparation.

## Pipeline Architecture

The system uses a **staged processing approach** with these core tables:
- `source_documents` - Initial document intake
- `document_processing_queue` - Queue management
- `neo4j_documents` - Document metadata for Neo4j
- `neo4j_chunks` - Text chunks
- `neo4j_entity_mentions` - Extracted entities
- `neo4j_canonical_entities` - Resolved canonical entities
- `neo4j_relationships_staging` - Relationship preparation

## Phase 1: Document Intake & Queue Creation

### Document Registration Triggers

When a new document is inserted into `source_documents`, multiple triggers fire simultaneously:

#### 1. UUID Generation Triggers
```sql
-- Ensures every document gets a UUID
TRIGGER ensure_document_uuid_trigger 
BEFORE INSERT ON source_documents
EXECUTE FUNCTION populate_document_uuid()

TRIGGER trg_ensure_document_uuid 
BEFORE INSERT ON source_documents  
EXECUTE FUNCTION ensure_document_uuid()
```
**Purpose**: Guarantees that every document has a UUID for cross-table relationships, even if not provided during insertion.

#### 2. Queue Entry Creation Triggers
```sql
-- Modern queue entry creation
TRIGGER modernized_create_queue_entry_trigger 
AFTER INSERT ON source_documents
EXECUTE FUNCTION modernized_create_queue_entry()

-- Legacy queue creation (backup)
TRIGGER trigger_create_queue_entry 
AFTER INSERT ON source_documents
EXECUTE FUNCTION create_queue_entry_for_new_document()
```

**Function Logic (`modernized_create_queue_entry`)**:
- Checks if queue entry already exists for the document UUID
- Creates new queue entry only if none exists (prevents duplicates)
- Sets initial processing step based on document status:
  - `pre_ocr_pending` → `ocr` step
  - `pending_intake` → `intake` step
- Initializes with default priority (100), retry count (0), max retries (3)

#### 3. Processing Triggers
```sql
-- Direct processing initiation
TRIGGER auto_process_new_document 
AFTER INSERT ON source_documents
EXECUTE FUNCTION trigger_document_processing()

TRIGGER trigger_process_new_document 
AFTER INSERT ON source_documents
EXECUTE FUNCTION process_new_document()
```
**Purpose**: Can immediately start processing for certain document types or trigger external processing systems.

## Phase 2: Status Change Orchestration

### Document Status Update Triggers

When `source_documents.initial_processing_status` changes, multiple triggers coordinate the pipeline:

#### 1. Queue Synchronization
```sql
TRIGGER modernized_sync_queue_on_document_update 
AFTER UPDATE ON source_documents
WHEN (OLD.initial_processing_status IS DISTINCT FROM NEW.initial_processing_status)
EXECUTE FUNCTION modernized_sync_document_queue_status()
```

**Critical Status Transitions**:

**OCR Completion** (`ocr_complete_pending_doc_node`):
- Marks current OCR queue entry as `completed`
- Automatically creates next queue entry for `document_node_creation` step
- Prevents duplicate queue entries through existence checks

**Processing Completion** (`completed`):
- Updates queue status to `completed`
- Sets `completed_at` timestamp
- Clears any error messages
- Adds completion record to `processing_history` array

**Error Handling** (any status starting with `error` or `failed`):
- Updates queue status to `failed`  
- Captures error message from document
- Sets `completed_at` timestamp
- Logs error details in `processing_history`

**Processing Start** (`processing`):
- Updates queue status to `processing`
- Sets `started_at` timestamp if not already set
- Records processing start in history

#### 2. Notification Triggers
```sql
TRIGGER modernized_document_status_change_trigger 
AFTER UPDATE ON source_documents
WHEN (OLD.initial_processing_status IS DISTINCT FROM NEW.initial_processing_status)
EXECUTE FUNCTION modernized_notify_status_change()

TRIGGER monitoring_source_docs_trigger 
AFTER UPDATE OF initial_processing_status ON source_documents
EXECUTE FUNCTION monitoring_notify_status_change()
```
**Purpose**: Send notifications to external monitoring systems and processing coordinators.

## Phase 3: Neo4j Data Preparation

### Document Node Creation

When your pipeline creates entries in `neo4j_documents`:

#### 1. UUID Management
```sql
TRIGGER ensure_documents_uuid 
BEFORE INSERT ON neo4j_documents
EXECUTE FUNCTION set_documents_uuid_if_empty()

TRIGGER trg_ensure_document_uuids 
BEFORE INSERT ON neo4j_documents
EXECUTE FUNCTION ensure_document_uuids()
```

#### 2. ID Synchronization
```sql
TRIGGER maintain_neo4j_documents_ids 
BEFORE INSERT OR UPDATE ON neo4j_documents
EXECUTE FUNCTION sync_neo4j_documents_ids()
```
**Purpose**: Maintains consistency between SQL IDs and Neo4j UUIDs, ensuring proper relationships.

#### 3. Timestamp Management
```sql
TRIGGER set_timestamp_neo4j_documents 
BEFORE UPDATE ON neo4j_documents
EXECUTE FUNCTION trigger_set_timestamp()
```
**Purpose**: Automatically updates `updatedAt` timestamp on any record changes.

### Chunk Processing

When text chunks are created in `neo4j_chunks`:

#### 1. Chunk UUID Generation
```sql
TRIGGER ensure_chunks_uuid 
BEFORE INSERT ON neo4j_chunks
EXECUTE FUNCTION set_chunks_uuid_if_empty()

TRIGGER trg_ensure_chunk_uuids 
BEFORE INSERT ON neo4j_chunks
EXECUTE FUNCTION ensure_chunk_uuids()
```

#### 2. Parent Document Linking
```sql
TRIGGER maintain_neo4j_chunks_ids 
BEFORE INSERT OR UPDATE ON neo4j_chunks
EXECUTE FUNCTION sync_neo4j_chunks_ids()
```
**Purpose**: Ensures chunks are properly linked to their parent documents via both SQL foreign keys and UUID references.

### Entity Mention Processing

When entities are extracted and stored in `neo4j_entity_mentions`:

#### 1. Entity UUID Management
```sql
TRIGGER ensure_entity_mentions_uuid 
BEFORE INSERT ON neo4j_entity_mentions
EXECUTE FUNCTION set_entity_mentions_uuid_if_empty()

TRIGGER trg_ensure_entity_mention_uuids 
BEFORE INSERT ON neo4j_entity_mentions
EXECUTE FUNCTION ensure_entity_mention_uuids()
```

#### 2. Chunk Linking
```sql
TRIGGER ensure_entity_mention_linking 
BEFORE INSERT ON neo4j_entity_mentions
EXECUTE FUNCTION link_entity_mentions()

TRIGGER maintain_neo4j_entity_mentions_ids 
BEFORE INSERT OR UPDATE ON neo4j_entity_mentions
EXECUTE FUNCTION sync_neo4j_entity_mentions_ids()
```
**Purpose**: Automatically links entity mentions to their parent chunks via both SQL foreign keys and UUID references.

### Canonical Entity Resolution

When canonical entities are created in `neo4j_canonical_entities`:

#### 1. Canonical Entity UUIDs
```sql
TRIGGER ensure_canonical_entities_uuid 
BEFORE INSERT ON neo4j_canonical_entities
EXECUTE FUNCTION set_canonical_entities_uuid_if_empty()

TRIGGER trg_ensure_canonical_entity_uuids 
BEFORE INSERT ON neo4j_canonical_entities
EXECUTE FUNCTION ensure_canonical_entity_uuids()
```

#### 2. Document Association
```sql
TRIGGER maintain_neo4j_canonical_entities_ids 
BEFORE INSERT OR UPDATE ON neo4j_canonical_entities
EXECUTE FUNCTION sync_neo4j_canonical_entities_ids()
```
**Purpose**: Links canonical entities to their originating documents and maintains UUID consistency.

## Phase 4: Queue Management & Monitoring

### Queue Status Orchestration

The `document_processing_queue` table has its own set of triggers for advanced queue management:

#### 1. Status Change Notifications
```sql
TRIGGER modernized_queue_status_change_trigger 
AFTER UPDATE ON document_processing_queue
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION modernized_notify_status_change()

TRIGGER monitoring_queue_trigger 
AFTER UPDATE OF status ON document_processing_queue
EXECUTE FUNCTION monitoring_notify_status_change()
```

#### 2. Timestamp Management
```sql
TRIGGER trigger_update_queue_timestamp 
BEFORE UPDATE ON document_processing_queue
EXECUTE FUNCTION update_queue_timestamp()
```

#### 3. General Queue Notifications
```sql
TRIGGER queue_notify_trigger 
AFTER INSERT OR DELETE OR UPDATE ON document_processing_queue
EXECUTE FUNCTION notify_queue_status_change()
```

## Data Flow Summary

### 1. Document Intake Flow
```
Document Upload → source_documents INSERT
    ↓ (Multiple triggers fire simultaneously)
    ├── UUID generation
    ├── Queue entry creation  
    ├── Processing initiation
    └── Notification dispatch
```

### 2. Processing Status Flow
```
Status Update → source_documents UPDATE
    ↓ (Status change triggers)
    ├── Queue status synchronization
    ├── Next step queue entry creation (if applicable)
    ├── Completion/error handling
    └── Monitoring notifications
```

### 3. Neo4j Preparation Flow
```
Pipeline Processing → Neo4j table INSERTs
    ↓ (Per-table triggers)
    ├── UUID generation and validation
    ├── Cross-table relationship maintenance
    ├── Timestamp management
    └── Data consistency checks
```

## Key Benefits of This Trigger System

### 1. **Automatic Queue Management**
- Documents are automatically queued upon insertion
- Queue status stays synchronized with document processing status
- Failed documents are automatically retried with proper error tracking

### 2. **Data Consistency**
- UUIDs are automatically generated and maintained across all tables
- Foreign key relationships are kept in sync
- Cross-table references remain valid throughout processing

### 3. **Processing Orchestration**
- Next processing steps are automatically created when current steps complete
- Status changes propagate through the entire system
- Processing history is maintained for debugging and monitoring

### 4. **Error Resilience**
- Failed documents are properly marked and queued for retry
- Error messages are captured and stored
- Processing can resume from failure points

### 5. **Monitoring Integration**
- All status changes generate notifications
- External monitoring systems can track processing progress
- Performance metrics can be collected from trigger events

## Troubleshooting Common Issues

### Duplicate Queue Entries
The `modernized_create_queue_entry` function includes existence checks to prevent duplicates, but if you see duplicates:
- Check if multiple triggers are creating entries
- Verify UUID uniqueness constraints
- Review trigger execution order

### Missing UUIDs
If you encounter NULL UUIDs:
- Ensure UUID generation triggers are enabled
- Check that `gen_random_uuid()` function is available
- Verify trigger execution on INSERT operations

### Status Synchronization Issues
If queue status doesn't match document status:
- Check that status update triggers are firing
- Verify trigger conditions (WHEN clauses)
- Review status transition logic in trigger functions

### Performance Considerations
With many triggers firing on each operation:
- Monitor trigger execution time
- Consider disabling non-essential triggers during bulk operations
- Use trigger logging to identify performance bottlenecks

This trigger system provides a robust, automated foundation for your document processing pipeline, ensuring data integrity and processing orchestration without manual intervention.