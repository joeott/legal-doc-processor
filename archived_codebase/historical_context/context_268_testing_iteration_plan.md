# Context 268: Testing Iteration Plan - Path to Document Processing

## Date: May 31, 2025
## Objective: Process a document from /opt/legal-doc-processor/input_docs completely through without errors

## Current State Analysis

### ✅ Completed:
1. Environment setup (Python, dependencies, Supervisor)
2. Database connectivity (RDS direct access)
3. Celery workers running (5 workers: ocr, text, entity, graph, default)
4. Schema mapping layer (table names, column names)
5. Database inserts working (records being created)

### 🔄 Current Issue:
- Reverse mapping for deserialization
- Database returns RDS column names, Pydantic expects model field names
- Example: `original_filename` (RDS) → `original_file_name` (Pydantic)

## Strategic Plan

### Phase 1: Fix Reverse Mapping (Immediate)
1. **Implement reverse column mapping function**
   - Create mapping from RDS columns back to Pydantic fields
   - Integrate into deserialization process
   - Test with schema alignment tests

2. **Fix entity model validation issues**
   - EntityMentionModel requires `chunk_fk_id`
   - May need to adjust model or provide defaults

### Phase 2: Complete Schema Tests (30 min)
1. Run schema alignment tests to completion
2. Verify all CRUD operations work
3. Document any remaining mapping issues

### Phase 3: Document Processing Test (1-2 hours)
1. **Check input_docs directory**
   - List available test documents
   - Select appropriate PDF for testing

2. **Submit document through pipeline**
   - Use CLI import tool or direct submission
   - Monitor each stage (OCR → Text → Entity → Graph)
   - Track with live monitor

3. **Debug any failures**
   - Check logs for each stage
   - Fix mapping/serialization issues
   - Retry failed stages

### Phase 4: End-to-End Validation (30 min)
1. Verify all stages completed
2. Check database for:
   - Document record
   - Chunks created
   - Entities extracted
   - Relationships built
3. Run comprehensive test suite

## Implementation Approach

### Reverse Mapping Solution
```python
def create_reverse_mappings():
    """Create reverse mappings from RDS columns to Pydantic fields"""
    reverse_mappings = {}
    for table, mappings in COLUMN_MAPPINGS.items():
        reverse_mappings[table] = {v: k for k, v in mappings.items() if v not in ['metadata', 'processing_metadata', 'ocr_metadata_json']}
    return reverse_mappings

def reverse_map_columns(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Map RDS column names back to Pydantic field names"""
    reverse_mappings = create_reverse_mappings()
    table_mappings = reverse_mappings.get(table, {})
    
    result = {}
    for key, value in data.items():
        pydantic_key = table_mappings.get(key, key)
        result[pydantic_key] = value
    
    # Handle special metadata fields
    # Unpack from ocr_metadata_json back to individual fields
    return result
```

## Success Criteria

1. **Schema Tests**: All 6 tests pass
2. **Document Import**: Document successfully imported from input_docs
3. **Pipeline Completion**: All stages (OCR, Text, Entity, Graph) complete
4. **Data Verification**: All expected data in database
5. **No Errors**: Clean execution without exceptions

## Risk Mitigation

1. **Mapping Issues**: Keep detailed log of all mapping fixes
2. **OCR Failures**: Have fallback options (local OCR, skip OCR)
3. **Memory Issues**: Monitor system resources during processing
4. **Timeout Issues**: Adjust Celery timeouts if needed

## Debugging Strategy

1. **Enable verbose logging**
2. **Test incrementally** (one stage at a time)
3. **Use monitoring tools** throughout
4. **Document all fixes** in ai_docs
5. **Create minimal test cases** for issues

## Expected Timeline

- Phase 1: 15-30 minutes (reverse mapping)
- Phase 2: 30 minutes (complete schema tests)
- Phase 3: 1-2 hours (document processing)
- Phase 4: 30 minutes (validation)
- **Total**: 2-3 hours to full document processing

## Next Immediate Action

Implement the reverse mapping functionality in the db.py or serialization layer to fix the current deserialization issue.