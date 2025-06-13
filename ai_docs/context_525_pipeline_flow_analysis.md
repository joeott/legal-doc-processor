# Pipeline Flow Analysis - Complete Mapping

## Overview
The pipeline in `/opt/legal-doc-processor/scripts/pdf_tasks.py` consists of 6 stages that are properly connected via `apply_async` calls.

## Pipeline Flow Map

### Stage 1: OCR (extract_text_from_document)
- **Function**: `extract_text_from_document` (line 995)
- **Queue**: `ocr`
- **Triggers**: `continue_pipeline_after_ocr.apply_async()` at multiple points:
  - Line 1051: When using cached OCR result
  - Line 1151: When using cached text from Textract
  - Line 1259: After successful OCR extraction
  - Line 2699: After Textract job completion

### Transition Function: continue_pipeline_after_ocr
- **Function**: `continue_pipeline_after_ocr` (line 2753)
- **Queue**: `default`
- **Purpose**: Bridge between OCR and chunking stages
- **Triggers**: `chunk_document_text.apply_async()` at line 2803

### Stage 2: Chunking (chunk_document_text)
- **Function**: `chunk_document_text` (line 1302)
- **Queue**: `text`
- **Triggers**: `extract_entities_from_chunks.apply_async()` at:
  - Line 1333: When using cached chunks
  - Line 1575: After successful chunking

### Stage 3: Entity Extraction (extract_entities_from_chunks)
- **Function**: `extract_entities_from_chunks` (line 1613)
- **Queue**: `entity`
- **Triggers**: `resolve_document_entities.apply_async()` at line 1786

### Stage 4: Entity Resolution (resolve_document_entities)
- **Function**: `resolve_document_entities` (line 1804)
- **Queue**: `entity`
- **Triggers**: `build_document_relationships.apply_async()` at:
  - Line 1879: When using cached canonical entities
  - Line 2394: After successful entity resolution

### Stage 5: Relationship Building (build_document_relationships)
- **Function**: `build_document_relationships` (line 2426)
- **Queue**: `graph`
- **Triggers**: `finalize_document_pipeline.apply_async()` at:
  - Line 2456: When using cached relationships
  - Line 2505: After successful relationship building

### Stage 6: Finalization (finalize_document_pipeline)
- **Function**: `finalize_document_pipeline` (line 2829)
- **Queue**: `cleanup`
- **Purpose**: Updates final state, cleans up metadata, marks document as completed

## Key Findings

### ✅ All Stages Are Connected
1. Every stage properly triggers the next stage via `apply_async`
2. The pipeline flow is complete from Stage 1 through Stage 6
3. Both cached and non-cached paths trigger the next stage

### Pipeline Execution Flow
```
extract_text_from_document
    ↓ (via continue_pipeline_after_ocr)
chunk_document_text
    ↓
extract_entities_from_chunks
    ↓
resolve_document_entities
    ↓
build_document_relationships
    ↓
finalize_document_pipeline
```

### Queue Distribution
- **ocr**: Stage 1 (OCR extraction)
- **default**: Pipeline continuation
- **text**: Stage 2 (Chunking)
- **entity**: Stages 3-4 (Entity extraction & resolution)
- **graph**: Stage 5 (Relationship building)
- **cleanup**: Stage 6 (Finalization)

### Redis Acceleration
Each stage checks Redis cache before processing:
- If cached results exist, they use them and still trigger the next stage
- This ensures the pipeline continues even when using cached data

## Conclusion
The pipeline is properly connected. All 6 stages are being called in sequence. Both Stage 5 (relationship building) and Stage 6 (finalization) are correctly triggered by their preceding stages.