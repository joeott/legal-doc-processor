# Context 444: Entity Extraction Fix - Model Switch to gpt-4o-mini

## Date: June 8, 2025

## Issue Summary

Entity extraction was failing with empty responses when using the `o4-mini-2025-04-16` model. The user identified that this is likely a reasoning/thinking model that takes longer to respond or has different response characteristics, causing issues with the worker processing.

## Root Cause

The `o4-mini-2025-04-16` model appears to be a thinking/reasoning model that:
1. Returns empty responses despite HTTP 200 OK status
2. May have longer processing times that interfere with worker timeouts
3. Has different response format or structure than standard models

## Solution Implemented

### 1. Model Switch
Changed from `o4-mini-2025-04-16` to `gpt-4o-mini-2024-07-18` in `.env`:
```
OPENAI_MODEL=gpt-4o-mini-2024-07-18
```

### 2. Code Cleanup
Removed o4-mini specific parameter handling from `entity_service.py`:
- Removed conditional logic for `max_completion_tokens` vs `max_tokens`
- Removed temperature parameter exclusion for o4-mini models
- Simplified to use standard parameters for all models

### 3. API Key Configuration
Updated `config.py` to support both environment variable names:
```python
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")
```

### 4. OpenAI Library Update
Upgraded OpenAI library from 1.6.1 to 1.84.0 to fix initialization issues.

## Test Results

Successfully extracted entities with gpt-4o-mini:
```
INFO:__main__:Result status: success
INFO:__main__:Total entities: 5
INFO:__main__:Entity types found: ['ORG', 'DATE']
INFO:__main__:
Extracted entities:
INFO:__main__:  - DATE: 10/21/24 (confidence: 1.0)
INFO:__main__:  - ORG: UNITED STATES DISTRICT COURT (confidence: 1.0)
INFO:__main__:  - ORG: EASTERN DISTRICT OF MISSOURI (confidence: 1.0)
INFO:__main__:  - ORG: Acuity, A Mutual Insurance Company (confidence: 1.0)
INFO:__main__:  - ORG: Lora Property Investments, LLC (confidence: 1.0)
```

## Key Learnings

1. **Model Selection**: Not all OpenAI models are suitable for real-time entity extraction. Reasoning models like o4-mini may have different response characteristics.
2. **Standard Models**: Stick with proven models like `gpt-4o-mini-2024-07-18` for production entity extraction.
3. **API Compatibility**: Keep OpenAI library updated to avoid initialization issues.

## Next Steps

1. Entity extraction is now working with `gpt-4o-mini-2024-07-18`
2. Celery workers can process entity extraction tasks successfully
3. Pipeline should continue through to entity resolution and relationship building

## Configuration Reference

For entity extraction to work properly:
- Use `OPENAI_MODEL=gpt-4o-mini-2024-07-18`
- Ensure `OPEN_API_KEY` or `OPENAI_API_KEY` is set
- Keep OpenAI library at version 1.84.0 or later