# Context 264: Fixing Table Mappings Issue

## Date: May 31, 2025
## Issue: Table mappings are inverted

## Problem Identified

The `enhanced_column_mappings.py` has the TABLE_MAPPINGS backwards:

```python
TABLE_MAPPINGS = {
    # Pipeline expects -> RDS has
    "source_documents": "documents",  # WRONG!
    ...
}
```

This is mapping FROM the RDS table names TO simplified names, but the code expects the opposite.

## What the Code Does

1. `insert_record("documents", data)` is called
2. `map_table_name("documents")` looks up "documents" in TABLE_MAPPINGS
3. It doesn't find "documents" (because the mapping has "source_documents" as the key)
4. It returns "documents" unchanged
5. SQL tries to insert into "documents" table which doesn't exist

## Solution

The TABLE_MAPPINGS should be:
```python
TABLE_MAPPINGS = {
    # Simplified name -> Actual RDS table
    "documents": "source_documents",
    "chunks": "document_chunks",
    "entities": "entity_mentions",
    ...
}
```

## Implementation

We need to invert the TABLE_MAPPINGS dictionary to fix this issue.