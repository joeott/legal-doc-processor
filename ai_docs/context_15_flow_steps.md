# Document Processing Flow - Complete Step-by-Step Guide

This document provides a comprehensive overview of the document processing pipeline, detailing each phase, the scripts involved, trigger mechanisms, and verification methods.

## Pipeline Architecture Overview

The document processing system operates in two modes:
- **Direct Mode**: Processes files immediately from local/S3 storage
- **Queue Mode**: Uses `document_processing_queue` table for distributed processing with worker processes

## Complete Processing Flow

### **Phase 0: Document Intake & Queue Creation**

**Purpose**: Initial document upload and queue entry creation

**Scripts Involved**:
- Frontend: Vercel upload interface
- Database: Automatic trigger `create_queue_entry_for_new_document()`

**Trigger Mechanism**:
- User uploads PDF via Vercel frontend
- File stored in Supabase Storage 'documents' bucket
- Edge function creates `source_documents` entry
- Database trigger automatically creates `document_processing_queue` entry

**Status Changes**:
- `source_documents.initial_processing_status`: `'pending_intake'`
- `document_processing_queue.status`: `'pending'`
- `document_processing_queue.processing_step`: `'intake'`

**Verification**:
```sql
-- Check document was uploaded
SELECT id, original_file_name, initial_processing_status, intake_timestamp 
FROM source_documents ORDER BY intake_timestamp DESC LIMIT 5;

-- Verify queue entry exists
SELECT id, status, processing_step, created_at
FROM document_processing_queue 
WHERE status = 'pending' ORDER BY created_at DESC LIMIT 5;
```

---

### **Phase 1: Text Extraction (OCR)**

**Purpose**: Extract text content from uploaded documents

**Scripts Involved**:
- Primary: `ocr_extraction.py`
- Utilities: `mistral_utils.py`, `models_init.py`
- Orchestrator: `main_pipeline.py`

**Trigger Mechanism**:
- Queue processor (`queue_processor.py`) runs periodically
- Claims pending documents using `FOR UPDATE SKIP LOCKED`
- Calls `main_pipeline.process_single_document()`
- Routes to appropriate OCR method based on file type

**OCR Methods by File Type**:
- **PDF**: 
  - Primary: Mistral OCR API (`extract_text_from_pdf_mistral_ocr`)
  - Fallback: Qwen2-VL OCR (`extract_text_from_pdf_qwen_vl_ocr`)
- **DOCX**: `python-docx` library extraction
- **TXT**: Direct file read
- **EML**: Email parsing with HTML content stripping
- **Audio**: Whisper transcription model

**Status Changes**:
- Success: `source_documents.initial_processing_status`: `'ocr_complete_pending_doc_node'`
- Failure: `'extraction_failed'` or `'extraction_unsupported'`
- Queue: Updates to `'processing'` during execution

**Manual Trigger**:
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5/scripts
python queue_processor.py --single-run --log-level DEBUG
```

**Verification**:
```sql
-- Check OCR completion
SELECT id, original_file_name, initial_processing_status, 
       LENGTH(raw_extracted_text) as text_length,
       ocr_metadata_json->0->>'method' as ocr_method
FROM source_documents 
WHERE initial_processing_status = 'ocr_complete_pending_doc_node'
ORDER BY intake_timestamp DESC;

-- Check OCR metadata
SELECT original_file_name,
       ocr_metadata_json->0->>'method' as method,
       ocr_metadata_json->0->>'processing_time_seconds' as processing_time
FROM source_documents 
WHERE ocr_metadata_json IS NOT NULL;
```

---

### **Phase 2: Neo4j Document Node Creation**

**Purpose**: Create structured document entry in Neo4j schema

**Scripts Involved**:
- Primary: `main_pipeline.py`
- Database: `supabase_utils.py` (`SupabaseManager.create_or_get_neo4j_document`)

**Trigger Mechanism**:
- Automatically triggered after successful OCR
- Part of `main_pipeline.process_single_document()` flow

**Process**:
1. Create UUID for document
2. Insert into `neo4j_documents` table
3. Link to project via `project_id`
4. Set initial processing status

**Status Changes**:
- `neo4j_documents.processingStatus`: `'pending_metadata'`
- Document UUID created and linked

**Verification**:
```sql
-- Check Neo4j document creation
SELECT id, name, "processingStatus", "createdAt", project_id
FROM neo4j_documents 
ORDER BY "createdAt" DESC LIMIT 5;

-- Verify linking to source document
SELECT sd.original_file_name, nd.name, nd."processingStatus"
FROM source_documents sd
JOIN neo4j_documents nd ON sd.document_uuid = nd.id
ORDER BY sd.intake_timestamp DESC;
```

---

### **Phase 3: Text Cleaning & Document Categorization**

**Purpose**: Clean OCR artifacts and categorize document type

**Scripts Involved**:
- Primary: `text_processing.py`
- Functions: `clean_extracted_text()`, `categorize_document_text()`, `generate_simple_markdown()`

**Trigger Mechanism**:
- Automatically triggered after Neo4j document creation
- Part of `main_pipeline.process_single_document()` flow

**Process**:
1. **Text Cleaning**: Remove OCR artifacts, extra whitespace, fix encoding
2. **Document Categorization**: Classify document type using LLM
3. **Markdown Generation**: Structure text for downstream chunking
4. **Metadata Enhancement**: Add document type and processing metadata

**Status Changes**:
- `neo4j_documents.processingStatus`: `'pending_chunking'`
- Document category and cleaned text stored

**Verification**:
```sql
-- Check text processing completion
SELECT id, name, "processingStatus", "documentType", "wordCount"
FROM neo4j_documents 
WHERE "processingStatus" = 'pending_chunking'
ORDER BY "createdAt" DESC;
```

---

### **Phase 4: Document Chunking with Structured Extraction**

**Purpose**: Break document into semantic chunks for entity extraction

**Scripts Involved**:
- Primary: `chunking_utils.py`
- Enhancement: `structured_extraction.py`

**Trigger Mechanism**:
- Automatically triggered after text cleaning
- Part of `main_pipeline.process_single_document()` flow

**Process**:
1. **Markdown Guide Generation**: Create structure from cleaned text
2. **Semantic Chunking**: Use `chunk_markdown_text()` to create initial chunks
3. **Chunk Refinement**: Apply `refine_chunks()` with minimum 300 character requirement
4. **Structured Extraction** (Optional): Use LLM to extract structured data per chunk
5. **Database Storage**: Insert chunks into `neo4j_chunks` table

**Chunking Strategy**:
- Semantic boundaries (paragraphs, sections)
- Size limits: 300-2000 characters per chunk
- Overlap for context preservation
- Structured metadata extraction per chunk

**Status Changes**:
- `neo4j_documents.processingStatus`: `'pending_ner'`
- Multiple `neo4j_chunks` entries created

**Verification**:
```sql
-- Check chunking completion
SELECT d.name, d."processingStatus", COUNT(c.id) as chunk_count,
       AVG(LENGTH(c.text)) as avg_chunk_length
FROM neo4j_documents d
LEFT JOIN neo4j_chunks c ON d.id = c.document_id
WHERE d."processingStatus" = 'pending_ner'
GROUP BY d.id, d.name, d."processingStatus"
ORDER BY d."createdAt" DESC;

-- Examine chunk details
SELECT id, document_id, LEFT(text, 100) as text_preview, 
       LENGTH(text) as char_count, chunk_index
FROM neo4j_chunks
WHERE document_id = 'your-document-uuid'
ORDER BY chunk_index;
```

---

### **Phase 5: Named Entity Recognition (NER)**

**Purpose**: Extract entities (people, organizations, locations, dates) from each chunk

**Scripts Involved**:
- Primary: `entity_extraction.py`
- Models: `models_init.py` (HuggingFace NER pipeline)

**Trigger Mechanism**:
- Automatically triggered after chunking completion
- Part of `main_pipeline.process_single_document()` flow

**Process**:
1. **HuggingFace NER**: Extract standard entities (PERSON, ORG, LOC, MISC)
2. **Date Extraction**: Use regex + dateparser for temporal entities
3. **Contact Extraction**: Extract phone numbers and email addresses
4. **Entity Mentions**: Create `neo4j_entity_mentions` entries for each entity
5. **Confidence Scoring**: Track extraction confidence levels

**Entity Types Extracted**:
- PERSON: Names of individuals
- ORGANIZATION: Company names, institutions
- LOCATION: Geographic locations
- DATE: Temporal references
- PHONE: Phone numbers
- EMAIL: Email addresses
- MISC: Other relevant entities

**Status Changes**:
- `neo4j_documents.processingStatus`: `'pending_canonicalization'`
- Multiple `neo4j_entity_mentions` entries created

**Verification**:
```sql
-- Check NER completion
SELECT d.name, d."processingStatus", COUNT(em.id) as entity_count,
       COUNT(DISTINCT em.entity_type) as unique_types
FROM neo4j_documents d
LEFT JOIN neo4j_chunks c ON d.id = c.document_id
LEFT JOIN neo4j_entity_mentions em ON c.id = em.chunk_id
WHERE d."processingStatus" = 'pending_canonicalization'
GROUP BY d.id, d.name, d."processingStatus";

-- View extracted entities by type
SELECT entity_type, COUNT(*) as count, 
       ARRAY_AGG(DISTINCT entity_value) as sample_values
FROM neo4j_entity_mentions
WHERE chunk_id IN (
    SELECT id FROM neo4j_chunks WHERE document_id = 'your-document-uuid'
)
GROUP BY entity_type;
```

---

### **Phase 6: Entity Resolution (Canonicalization)**

**Purpose**: Group similar entity mentions and create canonical entities

**Scripts Involved**:
- Primary: `entity_resolution.py`
- LLM Processing: For intelligent entity grouping

**Trigger Mechanism**:
- Automatically triggered after NER completion
- Part of `main_pipeline.process_single_document()` flow

**Process**:
1. **Entity Clustering**: Group similar mentions using LLM analysis
2. **Canonical Entity Creation**: Create `neo4j_canonical_entities` entries
3. **Mention Linking**: Link entity mentions to canonical entities
4. **Confidence Scoring**: Track resolution confidence levels
5. **Cross-Document Linking**: Link entities across documents (future enhancement)

**Resolution Strategies**:
- String similarity matching
- LLM-based semantic grouping
- Context-aware disambiguation
- Confidence thresholding

**Status Changes**:
- `neo4j_documents.processingStatus`: `'pending_relationships'`
- `neo4j_canonical_entities` entries created
- Links between mentions and canonical entities established

**Verification**:
```sql
-- Check canonicalization completion
SELECT d.name, d."processingStatus", 
       COUNT(DISTINCT ce.id) as canonical_entities,
       COUNT(em.id) as entity_mentions
FROM neo4j_documents d
LEFT JOIN neo4j_chunks c ON d.id = c.document_id
LEFT JOIN neo4j_entity_mentions em ON c.id = em.chunk_id
LEFT JOIN neo4j_canonical_entities ce ON em.canonical_entity_id = ce.id
WHERE d."processingStatus" = 'pending_relationships'
GROUP BY d.id, d.name, d."processingStatus";

-- View canonical entities with their mentions
SELECT ce.canonical_value, ce.entity_type, 
       COUNT(em.id) as mention_count,
       ARRAY_AGG(DISTINCT em.entity_value) as variations
FROM neo4j_canonical_entities ce
LEFT JOIN neo4j_entity_mentions em ON ce.id = em.canonical_entity_id
GROUP BY ce.id, ce.canonical_value, ce.entity_type;
```

---

### **Phase 7: Relationship Building**

**Purpose**: Create graph relationships between all entities in the document

**Scripts Involved**:
- Primary: `relationship_builder.py`
- Database: `supabase_utils.py`

**Trigger Mechanism**:
- Automatically triggered after entity canonicalization
- Part of `main_pipeline.process_single_document()` flow

**Process**:
1. **Document-Project Relationships**: `(Document)-[:BELONGS_TO]->(Project)`
2. **Document-Chunk Relationships**: `(Chunk)-[:BELONGS_TO]->(Document)`
3. **Chunk-Entity Relationships**: `(Chunk)-[:CONTAINS_MENTION]->(EntityMention)`
4. **Entity-Canonical Relationships**: `(EntityMention)-[:MEMBER_OF_CLUSTER]->(CanonicalEntity)`
5. **Chunk Sequence Relationships**: `(Chunk)-[:NEXT_CHUNK/PREVIOUS_CHUNK]->(Chunk)`
6. **Cross-Document Relationships**: For shared canonical entities

**Relationship Types**:
- **BELONGS_TO**: Hierarchical ownership
- **CONTAINS_MENTION**: Entity occurrence in text
- **MEMBER_OF_CLUSTER**: Entity resolution grouping
- **NEXT_CHUNK/PREVIOUS_CHUNK**: Document sequence
- **REFERENCES**: Cross-document entity connections

**Storage**:
- All relationships staged in `neo4j_relationships_staging` table
- Ready for Neo4j import or direct querying

**Status Changes**:
- `neo4j_documents.processingStatus`: `'complete'`
- Multiple `neo4j_relationships_staging` entries created

**Verification**:
```sql
-- Check relationship building completion
SELECT d.name, d."processingStatus", COUNT(rs.id) as relationship_count
FROM neo4j_documents d
LEFT JOIN neo4j_relationships_staging rs ON (
    rs.start_node_uuid = d.id OR rs.end_node_uuid = d.id
)
WHERE d."processingStatus" = 'complete'
GROUP BY d.id, d.name, d."processingStatus";

-- View relationship types
SELECT relationship_type, COUNT(*) as count
FROM neo4j_relationships_staging rs
JOIN neo4j_documents d ON (rs.start_node_uuid = d.id OR rs.end_node_uuid = d.id)
WHERE d.id = 'your-document-uuid'
GROUP BY relationship_type;
```

---

### **Phase 8: Processing Completion**

**Purpose**: Mark document as fully processed and update all status fields

**Scripts Involved**:
- Primary: `main_pipeline.py`
- Database: Automatic triggers

**Trigger Mechanism**:
- Automatically triggered after relationship building
- Database triggers handle queue status updates

**Process**:
1. Update `source_documents.initial_processing_status` to `'completed'`
2. Database trigger updates `document_processing_queue.status` to `'completed'`
3. Set completion timestamps
4. Log final processing metrics

**Final Status Changes**:
- `source_documents.initial_processing_status`: `'completed'`
- `neo4j_documents.processingStatus`: `'complete'`
- `document_processing_queue.status`: `'completed'`
- `document_processing_queue.completed_at`: Set to current timestamp

**Verification**:
```sql
-- Check completion status
SELECT sd.original_file_name, sd.initial_processing_status,
       nd."processingStatus", q.status, q.completed_at
FROM source_documents sd
JOIN neo4j_documents nd ON sd.document_uuid = nd.id
JOIN document_processing_queue q ON sd.document_uuid = q.source_document_uuid
WHERE sd.initial_processing_status = 'completed'
ORDER BY q.completed_at DESC;

-- Processing pipeline summary
SELECT 
    COUNT(*) as total_documents,
    COUNT(CASE WHEN initial_processing_status = 'completed' THEN 1 END) as completed,
    COUNT(CASE WHEN initial_processing_status LIKE '%pending%' THEN 1 END) as pending,
    COUNT(CASE WHEN initial_processing_status LIKE '%error%' THEN 1 END) as errors
FROM source_documents;
```

---

## Queue Processing & Worker Management

### **Queue Processor Operation**

**Script**: `queue_processor.py`

**Key Features**:
- **Batch Processing**: Claims up to 5 documents at once
- **Safe Concurrency**: Uses `FOR UPDATE SKIP LOCKED` for safe multi-worker operation
- **Automatic Retries**: Up to 3 attempts per document
- **Stalled Detection**: Identifies documents stuck in processing
- **Processor Identification**: Unique processor IDs for tracking

**Manual Operation**:
```bash
# Single run with debug logging
python queue_processor.py --single-run --log-level DEBUG

# Continuous processing
python queue_processor.py --batch-size 10 --max-processing-time 120

# Check for stalled documents
python queue_processor.py --check-stalled
```

**Configuration**:
- `batch_size`: Number of documents to process simultaneously (default: 5)
- `max_processing_time_minutes`: Timeout for processing (default: 60)
- Processor ID: Automatically generated from hostname + UUID

---

## Error Handling & Recovery

### **Common Error States**

1. **`extraction_failed`**: OCR/text extraction failed
2. **`extraction_unsupported`**: File type not supported
3. **`processing_error`**: General processing error
4. **Queue status `'failed'`**: Queue processing failed with retry exhaustion

### **Error Investigation**:
```sql
-- Check error documents
SELECT sd.original_file_name, sd.initial_processing_status, sd.error_message,
       q.status, q.last_error, q.retry_count
FROM source_documents sd
LEFT JOIN document_processing_queue q ON sd.document_uuid = q.source_document_uuid
WHERE sd.initial_processing_status LIKE '%error%' OR q.status = 'failed'
ORDER BY sd.intake_timestamp DESC;

-- Retry failed documents
UPDATE document_processing_queue 
SET status = 'pending', retry_count = 0, last_error = NULL 
WHERE status = 'failed' AND retry_count < 3;
```

### **Recovery Procedures**:

1. **Reset Failed Queue Items**:
```sql
UPDATE document_processing_queue 
SET status = 'pending', retry_count = 0, last_error = NULL, processing_started_at = NULL
WHERE status = 'failed';
```

2. **Reset Stalled Documents**:
```sql
UPDATE document_processing_queue 
SET status = 'pending', processing_started_at = NULL
WHERE status = 'processing' 
AND processing_started_at < NOW() - INTERVAL '2 hours';
```

3. **Reprocess from Specific Phase**:
```sql
-- Reset to specific processing phase
UPDATE source_documents 
SET initial_processing_status = 'ocr_complete_pending_doc_node'
WHERE id = your_document_id;
```

---

## Monitoring & Verification Tools

### **Live Monitor Usage**:
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python monitoring/live_monitor.py --refresh 2 --max-docs 20
```

### **Processing Statistics Queries**:
```sql
-- Overall pipeline health
SELECT 
    initial_processing_status as status,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
FROM source_documents 
GROUP BY initial_processing_status
ORDER BY count DESC;

-- OCR method effectiveness
SELECT 
    ocr_metadata_json->0->>'method' as method,
    COUNT(*) as count,
    AVG((ocr_metadata_json->0->>'processing_time_seconds')::NUMERIC) as avg_time
FROM source_documents 
WHERE ocr_metadata_json IS NOT NULL
GROUP BY method;

-- Queue processing performance
SELECT 
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as processed,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration
FROM document_processing_queue 
WHERE status = 'completed' AND started_at IS NOT NULL
GROUP BY hour 
ORDER BY hour DESC;
```

This comprehensive flow documentation provides complete visibility into the document processing pipeline, enabling effective monitoring, debugging, and optimization of the system.