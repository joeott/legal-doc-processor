# Context 273: Test Analysis - Pydantic Models as Truth

## Test Results Summary

Out of 26 tests:
- **Passed**: 7 tests (27%)
- **Failed**: 19 tests (73%)

## Key Findings

### 1. UUID Generation Issues

The tests expect automatic UUID generation, but the models have UUIDs as optional fields:

**Test Expectation**:
```python
project = ProjectModel(name="Test Project")
assert isinstance(project.project_id, uuid.UUID)  # Expects auto-generation
```

**Model Reality**:
```python
project_id: Optional[uuid.UUID] = Field(None, alias="projectId")
```

**Solution**: The validator `ensure_project_id` exists but returns None if v is None. This should return `uuid.uuid4()` when None.

### 2. Timestamp Auto-Generation

Tests expect `created_at` and `updated_at` to be auto-populated, but models have them as optional:

**Test Expectation**:
```python
doc = SourceDocumentModel(...)
assert doc.created_at is not None  # Expects auto-generation
```

**Model Reality**:
```python
created_at: Optional[datetime] = Field(None, alias="createdAt")
```

**Solution**: Timestamps should be handled by the database or set during model creation.

### 3. Field Name Mismatches

Tests use camelCase while models use snake_case with aliases:

**Test**:
```python
assert project.scriptRunCount == 0  # camelCase
```

**Model**:
```python
script_run_count: Optional[int] = Field(0, alias="scriptRunCount")
```

**Solution**: Tests should use the primary field name (snake_case), not the alias.

### 4. Enum Validation

Tests expect strict enum validation but models may accept strings:

**Test**:
```python
doc = SourceDocumentModel(processing_status="invalid_status")  # Should raise error
```

**Solution**: Models correctly use Enum types, tests need to verify this properly.

## Action Items

### 1. Fix Pydantic Models (Source of Truth)

Since Pydantic models are the truth, we need to fix their validators:

1. **ProjectModel.ensure_project_id**: Should generate UUID when None
2. **SourceDocumentModel**: Add validator for document_uuid generation
3. **ChunkModel**: Add validator for chunk_id generation
4. **EntityMentionModel**: Add validator for entity_mention_uuid generation

### 2. Update Tests to Match Model Reality

1. Use snake_case field names, not camelCase aliases
2. Don't expect auto-generation of timestamps (database responsibility)
3. Properly test enum validation
4. Test actual model behavior, not assumed behavior

### 3. Database Schema Must Match

The RDS schema must have:
1. UUID columns that accept UUID type
2. Timestamp columns with DEFAULT CURRENT_TIMESTAMP
3. Enum columns that match Pydantic enum values
4. All required fields marked as NOT NULL

## Current Model Truth

Based on the actual Pydantic models:

1. **UUIDs**: Optional fields with validators that should (but don't always) generate them
2. **Timestamps**: Optional fields, expected to be set by database
3. **Field Names**: Snake_case with camelCase aliases for compatibility
4. **Enums**: Properly defined with string values
5. **Defaults**: Specified in Field() definitions

## Next Steps

1. **Fix Model Validators**: Update UUID generation validators to actually generate UUIDs
2. **Update Tests**: Make tests match actual model behavior
3. **Verify Database Schema**: Ensure RDS tables match Pydantic field requirements
4. **Remove Column Mappings**: Once schema aligns, remove mapping layer

## Test Categories

### Working Tests (7)
- Basic model creation with proper data
- JSON metadata parsing
- Field validation for constraints
- Serialization to dict

### Failing Tests (19)
- UUID auto-generation expectations
- Timestamp auto-generation expectations
- Field name confusion (camelCase vs snake_case)
- Incorrect assumptions about model behavior

## Conclusion

The tests reveal a mismatch between expected and actual model behavior. Since Pydantic models are the source of truth, we need to:
1. Fix the models where they have incomplete validators
2. Update tests to match actual model behavior
3. Ensure database schema supports model requirements