# Context 275: Jules' Tests Analysis Summary

## Overview

Jules added comprehensive test suites:
- `tests/core/test_schemas.py` - Pydantic model validation tests
- `tests/core/test_processing_models.py` - Import/processing model tests  
- `tests/test_db.py` - Database layer tests
- `tests/test_pdf_tasks.py` - PDF processing task tests

## Key Findings

### 1. Test-Code Misalignment

The tests were written with assumptions that don't match the actual code:

1. **Parameter Order Mismatch**:
   - Test calls: `PydanticSerializer.deserialize(model_class, data)`
   - Actual signature: `deserialize(data, model_class, table_name=None)`

2. **Field Name Confusion**:
   - Tests use camelCase aliases (`scriptRunCount`)
   - Models only allow snake_case access (`script_run_count`)

3. **UUID Generation Assumptions**:
   - Tests expect automatic UUID generation
   - Models only generate when `field=None` is explicitly passed

4. **Timestamp Expectations**:
   - Tests expect auto-populated timestamps
   - Models leave timestamps as None (database responsibility)

### 2. What This Reveals

1. **Tests Were Written Against Different API**: The tests assume a different interface than what exists, suggesting they were written speculatively or against an earlier version.

2. **Models Are Correct**: The Pydantic models follow proper patterns:
   - Optional fields with defaults
   - Validators for data transformation
   - Clear separation of concerns

3. **Tests Need Fixing**: Since Pydantic models are truth, tests must be updated to match actual behavior.

## Action Plan

### Phase 1: Fix Test-Code Alignment
1. Update test method calls to match actual signatures
2. Use snake_case field names in tests
3. Fix UUID generation expectations
4. Remove timestamp auto-generation assumptions

### Phase 2: Identify Schema Requirements
1. Run corrected tests against RDS
2. Document exact schema mismatches
3. Generate SQL migrations

### Phase 3: Apply Schema Changes
1. Modify RDS schema to match Pydantic models
2. Remove column mapping layer
3. Re-enable conformance validation

## Current State

- **Models**: Correct and should not be changed
- **Tests**: Need updates to match actual model behavior
- **Database**: Partially aligned, needs further updates
- **Pipeline**: Blocked by Celery task discovery issue

## Recommendation

1. **Don't Run Tests Yet**: They will fail due to API mismatches
2. **Fix Tests First**: Update to match actual code interfaces
3. **Then Validate Schema**: Use corrected tests to find RDS issues
4. **Apply Changes**: Make RDS conform to Pydantic models

## Key Principle

**Pydantic models are the source of truth**. Everything else (tests, database, scripts) must conform to them, not the other way around.