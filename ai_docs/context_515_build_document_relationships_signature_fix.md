# Context 515: Fix build_document_relationships Function Signature Mismatch

## Issue Identified
The `resolve_document_entities` function in `scripts/pdf_tasks.py` had a critical bug where it was calling `build_document_relationships` with only one argument (document_uuid) when using cached canonical entities, but the function requires 6 arguments.

## Function Signature
```python
def build_document_relationships(self, document_uuid: str, document_data: Dict[str, Any],
                               project_uuid: str, chunks: List[Dict[str, Any]],
                               entity_mentions: List[Dict[str, Any]],
                               canonical_entities: List[Dict[str, Any]]) -> Dict[str, Any]:
```

## The Problem
In the cached path (lines 1783-1794), when canonical entities were found in Redis cache, the code would:
1. Return early with cached entities
2. Call `build_document_relationships.apply_async(args=[document_uuid])` with only document_uuid
3. This caused a TypeError due to missing required arguments

## The Solution
Modified the cached path to:
1. Retrieve all required data before calling build_document_relationships:
   - `project_uuid` from Redis metadata
   - `document_metadata` from Redis metadata
   - `chunks` from Redis cache
   - `entity_mentions_list` from Redis cache or database fallback
2. Only trigger relationship building if all required data is available
3. Pass all 6 required arguments to the function

## Key Changes
- Added data retrieval logic in the cached path (lines 1788-1832)
- Added validation to ensure all required data exists before triggering next stage
- Added logging for missing data scenarios
- Maintained backward compatibility with existing cache structure

## Impact
This fix ensures that the pipeline can properly proceed from entity resolution to relationship building when using Redis acceleration and cached canonical entities. Without this fix, the pipeline would fail with a TypeError when cached entities were used.

## Testing Recommendations
1. Test with Redis acceleration enabled
2. Process a document twice to ensure cache is populated
3. Verify that the second run properly triggers relationship building
4. Check logs for proper parameter passing

## Related Files
- `scripts/pdf_tasks.py` - Contains both resolve_document_entities and build_document_relationships functions
- `scripts/cache.py` - Redis caching implementation
- `scripts/graph_service.py` - Relationship extraction logic