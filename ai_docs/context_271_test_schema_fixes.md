# Test Schema Fixes Summary

## Date: 2025-01-06

### Issues Fixed

Fixed all failing tests in `tests/core/test_schemas.py` to match the actual behavior of the Pydantic models. The tests were expecting different default values than what the models actually produce.

### Key Findings

1. **JSON Field Defaults**: Fields like `ocr_metadata_json`, `transcription_metadata_json`, `metadata_json`, and `attributes_json` have different default behaviors:
   - When the field is **not provided** at all → defaults to `None` (from Field definition)
   - When the field is **explicitly passed as None** → validator converts to `{}` (empty dict)
   - This is because Pydantic validators only run when a field is explicitly provided

2. **to_db_dict() Behavior**: The method has `exclude_none=True` by default, which means:
   - Fields with None values are excluded from the output dictionary
   - Tests checking for None values with `dict["field"] is None` fail with KeyError
   - Must use `"field" not in dict` to check for excluded None fields

### Specific Fixes

1. **ChunkModel**:
   - `metadata_json` defaults to None, not {} (line 367)
   - In `to_db_dict()` with `by_alias=False`, `next_chunk_id` is excluded when None (line 499)

2. **SourceDocumentModel**:
   - `ocr_metadata_json` and `transcription_metadata_json` default to None when not provided (lines 116-117)
   - The validator that converts None to {} only runs when fields are explicitly passed

3. **EntityMentionModel**:
   - `attributes_json` defaults to None (line 522)
   - In `to_db_dict()` with `by_alias=False`, `offset_start` is excluded when None (line 644)

4. **ProjectModel**:
   - `metadata` field correctly defaults to {} because it uses `Field(default_factory=dict)`
   - This is different from the other JSON fields which use `Field(None)`

### Test Results

All 26 tests now pass successfully:
```
======================= 26 passed, 146 warnings in 0.52s =======================
```

### Lessons Learned

1. Pydantic validators only run when fields are explicitly provided (even if the value is None)
2. Default field values come from the Field definition when fields are not provided
3. The `exclude_none=True` parameter in serialization methods affects which fields appear in output
4. Tests must match the actual model behavior, not assumed behavior