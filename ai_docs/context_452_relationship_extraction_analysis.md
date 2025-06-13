# Context 451: Relationship Extraction/Building Analysis

## Date: June 8, 2025

## Overview

This document analyzes the relationship extraction and building functionality in the legal document processing pipeline, including the current implementation, issues, and the complete pipeline flow.

## Pipeline Flow

The document processing pipeline follows this sequence:

1. **OCR Processing** → `continue_pipeline_after_ocr`
2. **Text Chunking** → `chunk_document_text` → triggers `extract_entities_from_chunks`
3. **Entity Extraction** → `extract_entities_from_chunks` → triggers `resolve_entities`
4. **Entity Resolution** → `resolve_entities` → triggers relationship building
5. **Relationship Building** → Uses `GraphService.stage_structural_relationships`
6. **Pipeline Finalization** → `finalize_document_pipeline`

## Key Components

### 1. GraphService (`scripts/graph_service.py`)

The `GraphService` class handles relationship building:

```python
class GraphService:
    def stage_structural_relationships(
        self,
        document_data: Dict[str, Any],
        project_uuid: str,
        chunks_data: List[Dict[str, Any]],
        entity_mentions_data: List[Dict[str, Any]],
        canonical_entities_data: List[Dict[str, Any]],
        document_uuid: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
```

**Current Implementation:**
- Only creates relationships between canonical entities (due to FK constraints)
- Creates CO_OCCURS relationships for entities in the same document
- Returns a dictionary with status and staged relationships

### 2. Relationship Staging Table Schema

From `archived_codebase/phase3/database/create_conformant_schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS relationship_staging (
    id SERIAL PRIMARY KEY,
    source_entity_uuid UUID REFERENCES canonical_entities(canonical_entity_uuid),
    target_entity_uuid UUID REFERENCES canonical_entities(canonical_entity_uuid),
    relationship_type TEXT NOT NULL,
    confidence_score FLOAT DEFAULT 0.0,
    source_chunk_uuid UUID REFERENCES document_chunks(chunk_uuid),
    evidence_text TEXT,
    properties JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**Key Constraints:**
- Both source and target must be canonical entities
- Cannot create relationships with chunks, documents, or entity mentions directly

### 3. Models

The pipeline uses two relationship models:

1. **RelationshipStagingMinimal** (`scripts/models.py`):
   - Database model for persistence
   - Fields: source_entity_uuid, target_entity_uuid, relationship_type, etc.

2. **StagedRelationship** (`scripts/core/processing_models.py`):
   - Processing model for pipeline operations
   - Fields: from_node_id, to_node_id, relationship_type, properties, etc.

### 4. Task Chaining

The pipeline automatically chains tasks using Celery's `apply_async`:

```python
# In chunk_document_text:
extract_entities_from_chunks.apply_async(
    args=[document_uuid, serialized_chunks]
)

# In extract_entities_from_chunks:
resolve_entities.apply_async(
    args=[document_uuid, all_entities_list]
)

# In resolve_entities:
# Triggers relationship building inline (not shown in search results)

# After relationship building:
finalize_document_pipeline.apply_async(
    args=[document_uuid, len(chunks), len(canonical_entities), result.total_relationships]
)
```

## Current Issues and Limitations

### 1. Limited Relationship Types

Currently only creates structural CO_OCCURS relationships:
- Entities that appear in the same document
- No semantic relationships (e.g., "represents", "filed_by", "party_to")
- No relationships based on context or meaning

### 2. Foreign Key Constraints

The relationship_staging table only allows relationships between canonical entities:
- Cannot create document-to-entity relationships
- Cannot create chunk-to-entity relationships
- Cannot create entity-mention-to-canonical relationships

### 3. Missing Relationship Extraction

The current implementation doesn't extract relationships from text:
- No LLM-based relationship extraction
- No pattern-based relationship detection
- Only creates generic CO_OCCURS relationships

### 4. Limited Context in Relationship Building

The `stage_structural_relationships` method doesn't use:
- Text content from chunks
- Entity context or attributes
- Document metadata for relationship inference

## Recommended Enhancements

### 1. Add Semantic Relationship Extraction

Implement LLM-based relationship extraction in entity extraction phase:

```python
def extract_relationships_from_chunk(chunk_text: str, entities: List[Dict]) -> List[Dict]:
    """Extract semantic relationships between entities in a chunk"""
    prompt = f"""
    Given this text and entities, identify relationships:
    
    Text: {chunk_text}
    Entities: {entities}
    
    Extract relationships like:
    - Person X represents Organization Y
    - Organization A filed document against Organization B
    - Person X is party to case Y
    """
    # Call LLM to extract relationships
```

### 2. Expand Relationship Types

Define domain-specific relationship types:
- REPRESENTS (lawyer-client)
- FILED_BY (document-party)
- PARTY_TO (person/org-case)
- JUDGE_IN (person-case)
- CITED_IN (case-case)

### 3. Add Evidence Tracking

Store evidence for each relationship:
- Source chunk UUID
- Evidence text snippet
- Confidence score from LLM

### 4. Enable Cross-Document Relationships

Look for relationships across documents in same project:
- Same entities appearing in multiple documents
- Timeline-based relationships
- Reference relationships

## Testing Relationship Extraction

To verify relationship building is working:

```bash
# Check if relationships are being created
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -c "
SELECT COUNT(*) as relationship_count,
       relationship_type,
       AVG(confidence_score) as avg_confidence
FROM relationship_staging
GROUP BY relationship_type;"

# Check relationships for specific document
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -c "
SELECT rs.*, 
       ce1.canonical_name as source_entity,
       ce2.canonical_name as target_entity
FROM relationship_staging rs
JOIN canonical_entities ce1 ON rs.source_entity_uuid = ce1.canonical_entity_uuid
JOIN canonical_entities ce2 ON rs.target_entity_uuid = ce2.canonical_entity_uuid
WHERE ce1.canonical_entity_uuid IN (
    SELECT DISTINCT canonical_entity_uuid 
    FROM entity_mentions 
    WHERE document_uuid = '<document_uuid>'
);"
```

## Conclusion

The relationship building functionality is currently limited to structural CO_OCCURS relationships between canonical entities. While the pipeline successfully chains from entity resolution to relationship building, it doesn't extract meaningful semantic relationships from the document text. The framework is in place but needs enhancement to provide value for legal document analysis.