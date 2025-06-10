# DEPRECATION NOTICE

## Date: January 10, 2025

This directory (`scripts/core/`) contains deprecated modules that are being phased out.

### Current Status:

#### Still in Use (Do Not Delete Yet):
- `processing_models.py` - Pipeline data transfer models (used by entity_service.py)
- `task_models.py` - Celery task models (imported by __init__.py)
- `__init__.py` - Provides backward compatibility imports

#### Recently Moved:
- `json_serializer.py` → `scripts/utils/json_serializer.py`
- `conformance_engine.py` → `scripts/validation/conformance_engine.py`
- `conformance_validator.py` → `scripts/validation/conformance_validator.py`

#### Deleted (No Longer Needed):
- `model_factory.py` - Functionality moved to scripts/models.py
- `model_migration.py` - No longer needed
- `error_handler.py` - Not referenced anywhere
- `pdf_validator.py` - Not referenced anywhere

### Migration Plan:

1. **processing_models.py** - These models serve a different purpose than database models (they're for pipeline data transfer). Consider moving to `scripts/processing_models.py` in the future.

2. **task_models.py** - These are Celery-specific models. Consider moving to `scripts/task_models.py` in the future.

3. **__init__.py** - Once all imports are updated, this file can be reduced to a simple stub or removed entirely.

### For AI Coding Agents:

**DO NOT** import from `scripts.core.*` for new code. Instead use:
- Database models: `from scripts.models import ...`
- JSON serializer: `from scripts.utils.json_serializer import ...`
- Conformance: `from scripts.validation.conformance_validator import ...`
- Processing models: Still in `scripts.core.processing_models` (for now)

See context_487, context_488, and context_489 for the consolidation history.