# Context 263: Schema Test Findings and Resolution Plan

## Date: May 31, 2025
## Issue: Schema Alignment Test Results

## Test Results Summary

### What We Found

1. **Database Schema Mismatch**
   - Code expects table: `documents`
   - Actual table name: `source_documents`
   - This confirms the mapping layer issue identified in previous contexts

2. **JSON Serialization Error**
   ```
   psycopg2.ProgrammingError: can't adapt type 'dict'
   ```
   - PostgreSQL cannot directly handle Python dictionaries
   - Need JSON serialization for `metadata` and `processing_metadata` fields

3. **Test Results**
   - ✅ Pydantic Document Validation: PASSED
   - ❌ Document Database Insertion: FAILED (dict adaptation)
   - ❌ Chunk Operations: FAILED (parent document creation failed)
   - ❌ Entity Operations: FAILED (missing required field)
   - ✅ Status Enum Mapping: PASSED
   - ✅ Metadata JSON Serialization: PASSED

## Root Cause Analysis

### 1. Table Name Mapping
The RDS schema uses full descriptive names:
- `source_documents` (not `documents`)
- `document_chunks` (not `chunks`)
- `entity_mentions` (not `entities`)
- `canonical_entities` (not `entities_canonical`)
- `relationship_staging` (not `relationships`)

### 2. JSON Field Handling
The `metadata` and `processing_metadata` fields are JSONB in PostgreSQL but the code is passing raw Python dictionaries without proper serialization.

### 3. Field Mapping Issues
The test revealed that the mapping layer in `enhanced_column_mappings.py` is not being properly applied during database operations.

## Resolution Plan

### Step 1: Fix JSON Serialization
The issue is in `scripts/rds_utils.py` where dictionaries need to be converted to JSON:

```python
import json
from decimal import Decimal

def serialize_for_postgres(value):
    """Convert Python types to PostgreSQL-compatible formats."""
    if isinstance(value, dict):
        return json.dumps(value)
    elif isinstance(value, Decimal):
        return float(value)
    elif isinstance(value, (list, tuple)):
        return json.dumps(list(value))
    return value
```

### Step 2: Verify Table Mapping
The `enhanced_column_mappings.py` has the correct mappings:
```python
TABLE_MAPPINGS = {
    'documents': 'source_documents',
    'chunks': 'document_chunks',
    'entities': 'entity_mentions',
    ...
}
```

But these mappings are not being used in the direct SQL queries in the test.

### Step 3: Fix Direct SQL Queries
The test uses direct SQL with hardcoded table names:
```sql
DELETE FROM documents WHERE file_name LIKE :pattern
```

Should use the mapped table name:
```sql
DELETE FROM source_documents WHERE file_name LIKE :pattern
```

## Implementation Steps

1. **Fix RDS Utils JSON Handling**
   - Add JSON serialization for dict/list fields
   - Handle None values properly
   - Ensure all JSONB fields are serialized

2. **Update Test Scripts**
   - Use correct table names in direct SQL
   - Or better: use the DatabaseManager methods that handle mapping

3. **Verify Mapping Layer**
   - Ensure all database operations go through the mapping layer
   - Check that `_map_to_simplified_schema` is called for all operations

4. **Run Tests Again**
   - Schema alignment should pass
   - Document processing should work
   - Celery tasks should complete

## Expected Outcome

After fixes:
- All schema alignment tests should pass
- Documents should insert successfully
- JSON metadata should be properly stored
- Field mappings should work transparently

## Next Steps

1. Apply the JSON serialization fix
2. Update test scripts with correct table names
3. Run schema alignment tests
4. Run document processing tests
5. Submit test document through Celery
6. Monitor for any remaining issues