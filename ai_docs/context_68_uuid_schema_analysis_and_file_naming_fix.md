# Context 68: UUID Schema Analysis and File Naming Fix

## Date: 2025-05-23

## Overview
This document provides a comprehensive analysis of the UUID implementation across all Supabase tables in the legal document processing pipeline, along with documentation of the file naming fix implemented to ensure proper UUID-based file storage.

## UUID Schema Complexity Analysis

### 1. Projects Table
- **id** (integer): Primary key, auto-increment
- **projectId** (varchar): UUID stored as string - this is the main project identifier
- **supabaseProjectId** (varchar): Optional Supabase-specific project ID

**Analysis**: The projects table uses a dual-ID system where `id` is for internal SQL relations and `projectId` is the UUID for cross-system references.

### 2. Source Documents Table
- **id** (integer): Primary key, auto-increment
- **project_fk_id** (integer): Foreign key to projects.id
- **project_uuid** (varchar): Foreign key to projects.projectId
- **document_uuid** (varchar): UNIQUE, auto-generated UUID for the document

**Analysis**: Source documents maintain both SQL ID references and UUID references to projects, creating redundancy but ensuring compatibility with both reference systems.

### 3. Document Processing Queue
- **id** (integer): Primary key
- **document_id** (integer): Nullable reference to a document (unclear which table)
- **source_document_id** (integer): Nullable reference to source_documents.id
- **document_uuid** (varchar): Nullable UUID reference (purpose unclear)
- **source_document_uuid** (varchar): UNIQUE reference to source_documents.document_uuid

**Analysis**: The queue table has significant redundancy and confusion:
- Both `document_id` and `source_document_id` exist but seem to serve similar purposes
- Both `document_uuid` and `source_document_uuid` exist, creating ambiguity
- Many references are nullable, leading to the errors we encountered

### 4. Neo4j Documents Table
- **id** (integer): Primary key
- **documentId** (varchar): UUID for Neo4j node identification
- **source_document_fk_id** (integer): FK to source_documents.id
- **project_id** (integer): FK to projects.id
- **supabaseDocumentId** (varchar): Legacy field
- **project_uuid** (varchar): FK to projects.projectId
- **source_document_uuid** (varchar): FK to source_documents.document_uuid

**Analysis**: This table maintains THREE different document ID systems:
1. SQL integer IDs
2. Its own `documentId` UUID for Neo4j
3. References to source document UUIDs

### 5. Neo4j Chunks Table
- **id** (integer): Primary key
- **chunkId** (varchar): UUID for Neo4j node
- **document_id** (integer): FK to neo4j_documents.id
- **supabaseChunkId** (varchar): Legacy field
- **document_uuid** (varchar): FK to neo4j_documents.documentId

**Analysis**: Chunks reference documents by both integer ID and UUID, but the UUID references neo4j_documents.documentId, not source_documents.document_uuid.

### 6. Neo4j Entity Mentions Table
- **id** (integer): Primary key
- **entityMentionId** (varchar): UUID for Neo4j node
- **chunk_fk_id** (integer): FK to neo4j_chunks.id
- **chunk_uuid** (varchar): FK to neo4j_chunks.chunkId

**Analysis**: Similar dual-reference pattern.

### 7. Neo4j Canonical Entities Table
- **id** (integer): Primary key
- **canonicalEntityId** (varchar): UUID for Neo4j node
- **documentId** (integer): FK to neo4j_documents.id
- **clusterId** (varchar): Cluster identifier
- **document_uuid** (varchar): FK to neo4j_documents.documentId

**Analysis**: References documents but uses neo4j_documents UUIDs, not source UUIDs.

### 8. Neo4j Relationships Staging Table
- **fromNodeId** (varchar): UUID of source node
- **toNodeId** (varchar): UUID of target node
- No explicit UUID columns, but uses UUID values for node references

## UUID Implementation Issues

### 1. **Redundant ID Systems**
- Every table maintains both integer IDs and UUID strings
- Creates confusion about which to use for references
- Leads to nullable fields and lookup failures

### 2. **Inconsistent Naming**
- `projectId` vs `project_uuid`
- `documentId` vs `document_uuid` vs `source_document_uuid`
- CamelCase vs snake_case UUID field names

### 3. **Multiple UUID Hierarchies**
- Source documents have their own UUIDs
- Neo4j documents create new UUIDs rather than reusing source UUIDs
- This means a single document has at least 2 different UUIDs in the system

### 4. **Nullable UUID References**
- Queue table has nullable UUID fields, causing lookup failures
- Requires fallback logic to handle missing IDs

### 5. **Foreign Key Confusion**
- Some FKs reference integer IDs, others reference UUIDs
- neo4j_chunks.document_uuid references neo4j_documents.documentId, not source_documents.document_uuid

## File Naming Fix Implementation

### Problem Statement
Files uploaded to Supabase Storage were stored with timestamp-based names (e.g., `1747966420130-m9gegr9fdp.pdf`) but the system expected UUID-based naming for consistency and traceability.

### Root Cause
1. Files were uploaded to Supabase Storage with original naming
2. The path was stored as `s3://uploads/[timestamp-random].pdf` 
3. This was not a real S3 path but a Supabase Storage path formatted to look like S3
4. The OCR pipeline (Textract) requires real AWS S3 access

### Solution Implemented

#### 1. **UUID Detection Logic** (queue_processor.py lines 140-157)
```python
if USE_UUID_FILE_NAMING and source_doc_details.get('document_uuid'):
    doc_uuid = source_doc_details['document_uuid']
    if doc_uuid not in original_path:
        # File needs UUID renaming
        migration_result = self.migrate_existing_file_to_s3(source_doc_id, original_path)
```

#### 2. **Supabase Storage to S3 Migration** (queue_processor.py lines 199-223)
```python
if file_path.startswith('s3://uploads/'):
    # This is a Supabase Storage path formatted as S3
    file_key = file_path.replace('s3://', '')  # uploads/filename.pdf
    
    # Generate Supabase Storage URL
    storage_url = generate_document_url(file_key, use_signed_url=True)
    
    # Download from Supabase Storage
    response = requests.get(storage_url)
    
    # Upload to S3 with UUID naming
    result = s3_manager.upload_document_with_uuid_naming(
        temp_path, document_uuid, original_filename
    )
```

#### 3. **UUID-Based S3 Key Format**
Files are now stored in S3 as: `documents/[document_uuid].[extension]`
Example: `documents/4eda0aa3-1088-40a7-afe0-276abf521e76.pdf`

### Benefits of the Fix
1. **Consistent Naming**: All files in S3 use document UUIDs
2. **Direct Traceability**: File name directly maps to document record
3. **AWS Textract Compatibility**: Real S3 paths work with Textract
4. **Automatic Migration**: Handles existing files transparently

## Recommendations for UUID Schema Improvement

### 1. **Eliminate Redundancy**
- Choose either integer IDs or UUIDs, not both
- If both are needed, clearly document primary vs secondary

### 2. **Consistent Naming Convention**
- Use snake_case for all UUID fields: `document_uuid`, `project_uuid`, etc.
- Avoid mixing `Id` and `uuid` suffixes

### 3. **Single Document UUID**
- Source document UUID should flow through entire pipeline
- Neo4j documents should reference source UUID, not create new ones

### 4. **Non-Nullable Critical Fields**
- Make UUID fields non-nullable where they're essential
- Queue table should require either document_id OR document_uuid, not allow both null

### 5. **Clear Foreign Key Relationships**
- Document which UUID references which table
- Consider using database comments to clarify relationships

### 6. **Simplify Queue Table**
- Remove either `document_id`/`document_uuid` or `source_document_id`/`source_document_uuid`
- One set of references is sufficient

## Current State After Fixes

1. **Queue Processor**: Now handles UUID lookup when ID is missing
2. **File Migration**: Automatically migrates Supabase Storage files to S3 with UUID naming
3. **Error Handling**: Gracefully handles missing IDs with fallback to UUID lookup
4. **Schema Compatibility**: Works with existing complex schema while planning improvements

The system now functions despite the UUID complexity, but significant simplification would improve maintainability and reduce errors.