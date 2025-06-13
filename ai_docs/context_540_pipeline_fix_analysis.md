# Context 540: Pipeline Fix Analysis - Stage 5 & 6 Issues

**Date**: 2025-06-13 16:30 UTC  
**Branch**: fix/pipeline-langchain-optimizations  
**Purpose**: Document the pipeline issues and fixes needed

## Critical Findings

### 1. Pipeline Stages ARE Connected
All 6 stages exist and are properly chained via `apply_async` calls:
1. `extract_text_from_document` → 
2. `chunk_document_text` → 
3. `extract_entities_from_chunks` → 
4. `resolve_document_entities` → 
5. `build_document_relationships` → 
6. `finalize_document_pipeline`

### 2. Stage 5 (Relationship Building) is FAILING
**Error**: `build_document_relationships() missing 5 required positional arguments`

**Function expects**:
```python
def build_document_relationships(self, 
    document_uuid: str,
    document_data: Dict[str, Any],
    project_uuid: str, 
    chunks: List[Dict[str, Any]],
    entity_mentions: List[Dict[str, Any]],     # MISSING!
    canonical_entities: List[Dict[str, Any]]
) -> Dict[str, Any]:
```

**But it's being called with only 5 args**:
```python
build_document_relationships.apply_async(
    args=[
        document_uuid,
        document_metadata,      # This is document_data
        project_uuid,
        chunks,
        canonical_entities      # Missing entity_mentions!
    ]
)
```

### 3. Stage 6 (Finalization) Never Runs
Since Stage 5 fails, Stage 6 is never triggered. The database shows:
- 0 finalization tasks
- Only 1 relationship_building task (failed)

### 4. Database Schema Insights

**Task Types in Database**:
```sql
chunking              | 532 tasks
entity_extraction     | 100 tasks
entity_resolution     |  99 tasks
ocr                   | 470 tasks
relationship_building |   1 task (failed)
finalization          |   0 tasks
```

## Root Cause

The `resolve_document_entities` function (Stage 4) is not passing `entity_mentions` to Stage 5. It only passes:
1. document_uuid
2. document_metadata
3. project_uuid
4. chunks
5. canonical_entities

But Stage 5 needs:
1. document_uuid
2. document_data
3. project_uuid
4. chunks
5. **entity_mentions** ← MISSING
6. canonical_entities

## Fix Required

### Option 1: Fix the Caller (Recommended)
Update `resolve_document_entities` to pass entity_mentions:

```python
# In resolve_document_entities, around line where it calls build_document_relationships
build_document_relationships.apply_async(
    args=[
        document_uuid,
        document_metadata,
        project_uuid,
        chunks,
        entity_mentions,  # ADD THIS
        resolution_result['canonical_entities']
    ]
)
```

### Option 2: Fix the Function Signature
Remove entity_mentions parameter if not needed:

```python
def build_document_relationships(self, 
    document_uuid: str,
    document_data: Dict[str, Any],
    project_uuid: str, 
    chunks: List[Dict[str, Any]],
    canonical_entities: List[Dict[str, Any]]  # Remove entity_mentions
) -> Dict[str, Any]:
```

## Impact Analysis

1. **Why only 1 failed task?** 
   - The first document that reached Stage 4 tried Stage 5 and failed
   - Subsequent documents might have hit circuit breakers or error handling that prevented retry

2. **Why different task counts?**
   - OCR: 470 (all attempts)
   - Chunking: 532 (includes retries)
   - Entity tasks: ~100 (only successful OCR/chunks proceed)
   - Relationship: 1 (first attempt failed, no retries)

## Implementation Plan

1. **Immediate Fix**: Add entity_mentions to the apply_async call
2. **Test**: Run single document through pipeline
3. **Verify**: Check all 6 stages complete
4. **Monitor**: Ensure finalization tasks appear in database