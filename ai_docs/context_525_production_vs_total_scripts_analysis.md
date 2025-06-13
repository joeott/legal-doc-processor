# Production Scripts vs Total Scripts Analysis

## Summary Statistics
- **Total Python scripts**: 71 scripts
- **Scripts loaded during production batch run**: 11 core scripts
- **Potential utilization rate**: ~15.5% (11/71)

## Scripts Imported/Used During Production Batch Run

Based on the batch run log, these scripts were directly loaded:

1. **scripts.config** - Environment and configuration management
2. **scripts.intake_service** - Document discovery and intake
3. **scripts.validation** (3 modules):
   - ocr_validator - OCR validation
   - entity_validator - Entity extraction validation  
   - pipeline_validator - End-to-end pipeline validation
4. **scripts.status_manager** - Processing status tracking
5. **scripts.audit_logger** - Audit logging
6. **scripts.cache** - Redis caching layer
7. **scripts.db** - Database operations
8. **scripts.batch_tasks** - Batch processing tasks
9. **scripts.production_processor** - Main production orchestrator
10. **scripts.logging_config** - Logging configuration

## Complete Script Inventory by Category

### 1. Core Processing Scripts (17 scripts)
**Purpose**: Main pipeline execution and task processing

- `pdf_tasks.py` - Core pipeline tasks (6 stages) ✓ Used via batch_tasks
- `batch_tasks.py` - Batch processing with priority queues ✓ Used
- `batch_processor.py` - Batch orchestration ✓ Used via production_processor
- `batch_recovery.py` - Batch failure recovery
- `celery_app.py` - Celery configuration ✓ Used implicitly
- `production_processor.py` - Production orchestrator ✓ Used
- `ocr_extraction.py` - PDF text extraction
- `textract_utils.py` - AWS Textract integration
- `chunking_utils.py` - Text chunking
- `entity_service.py` - Entity extraction
- `graph_service.py` - Relationship extraction
- `intake_service.py` - Document intake ✓ Used
- `s3_storage.py` - S3 operations
- `start_worker.py` - Worker startup
- `cache_warmer.py` - Cache pre-warming
- `batch_metrics.py` - Batch metrics collection
- `rds_utils.py` - RDS utilities

### 2. Data Layer Scripts (4 scripts)
**Purpose**: Database and caching operations

- `db.py` - Database manager ✓ Used
- `cache.py` - Redis cache manager ✓ Used
- `models.py` - Pydantic data models
- `migrate_redis_databases.py` - Redis migration utility

### 3. Infrastructure Scripts (7 scripts)
**Purpose**: Configuration and logging

- `config.py` - Configuration management ✓ Used
- `logging_config.py` - Logging setup ✓ Used
- `audit_logger.py` - Audit logging ✓ Used
- `status_manager.py` - Status tracking ✓ Used
- `setup_cloudwatch_alarms.py` - CloudWatch setup
- `core_enhancements_immediate.py` - Enhancement scripts
- `__init__.py` files (multiple)

### 4. Validation Scripts (7 scripts)
**Purpose**: Data validation and conformance

- `validation/ocr_validator.py` ✓ Used
- `validation/entity_validator.py` ✓ Used
- `validation/pipeline_validator.py` ✓ Used
- `validation/conformance_validator.py`
- `validation/conformance_engine.py`
- `validation/flexible_validator.py`
- `validation/pre_processor.py`

### 5. CLI Tools (4 scripts)
**Purpose**: Command-line interfaces

- `cli/monitor.py` - Pipeline monitoring
- `cli/import.py` - Document import
- `cli/admin.py` - Administrative tasks
- `cli/enhanced_monitor.py` - Enhanced monitoring

### 6. Monitoring Scripts (4 scripts)
**Purpose**: System monitoring and health checks

- `monitoring/health_monitor.py`
- `monitoring/monitor_full_pipeline.py`
- `monitoring/monitor_redis_acceleration.py`
- `monitoring/process_with_redis_monitoring.py`

### 7. Utility Scripts (11 scripts in utilities/)
**Purpose**: Diagnostic and maintenance utilities

- `utilities/check_all_redis_keys.py`
- `utilities/check_batch_details.py`
- `utilities/check_batch_simple.py`
- `utilities/check_batch_status.py`
- `utilities/check_ocr_cache.py`
- `utilities/check_pipeline_status.py`
- `utilities/check_project_schema.py`
- `utilities/check_redis_info.py`
- `utilities/check_task_error.py`
- `utilities/clear_rds_test_data.py`
- `utilities/clear_redis_cache.py`

### 8. Helper/Utils Scripts (7 scripts in utils/)
**Purpose**: Shared utilities and helpers

- `utils/error_handler.py`
- `utils/error_types.py`
- `utils/json_serializer.py`
- `utils/param_validator.py`
- `utils/pdf_handler.py`
- `utils/s3_streaming.py`
- `utils/schema_inspector.py`
- `utils/schema_reference.py`

### 9. Service Scripts (3 scripts)
**Purpose**: Business logic services

- `services/document_categorization.py`
- `services/project_association.py`
- `services/semantic_naming.py`

### 10. Legacy/Core Scripts (3 scripts)
**Purpose**: Legacy models (being phased out)

- `core/processing_models.py`
- `core/task_models.py`
- `database/__init__.py`

## Dependency Analysis

### Primary Production Dependencies
The production batch run shows a clear dependency chain:

1. **production_processor.py** imports:
   - intake_service
   - batch_processor
   - status_manager
   - audit_logger
   - validation modules
   - db
   - logging_config

2. **batch_processor.py** imports:
   - cache
   - logging_config
   - db
   - celery_app (implicitly)

3. **batch_tasks.py** imports:
   - celery_app
   - pdf_tasks
   - cache
   - config
   - cache_warmer

### Scripts NOT Used in Production Batch

Based on the analysis, these scripts appear to be auxiliary or unused:

1. **Monitoring tools** (4 scripts) - Separate monitoring utilities
2. **CLI tools** (4 scripts) - Command-line interfaces  
3. **Utility scripts** (11 scripts) - Diagnostic/maintenance tools
4. **Service scripts** (3 scripts) - May be unused business logic
5. **Legacy core scripts** (3 scripts) - Being phased out
6. **Migration scripts** (1 script) - One-time use
7. **Setup scripts** (1 script) - One-time CloudWatch setup

## Recommendations

### 1. Scripts That Could Be Removed/Archived
- `core/` directory (3 scripts) - Legacy models being phased out
- `services/` directory (3 scripts) - Appear unused in production
- `migrate_redis_databases.py` - One-time migration script
- `setup_cloudwatch_alarms.py` - One-time setup script
- `core_enhancements_immediate.py` - Temporary enhancement script

### 2. Scripts to Keep But Separate
- `utilities/` directory (11 scripts) - Move to a separate diagnostics package
- `cli/` tools (4 scripts) - Keep for operational tasks but separate from core
- `monitoring/` scripts (4 scripts) - Keep for debugging but separate

### 3. Core Production Scripts
The essential production scripts are:
- All scripts in the production dependency chain (~20 scripts)
- Core processing tasks (pdf_tasks, batch_tasks, etc.)
- Data layer (db, cache, models)
- Infrastructure (config, logging, audit)

### 4. Optimization Opportunities
- Consolidate validation modules (7 scripts → 2-3)
- Merge utils helpers where appropriate
- Create clear separation between production and diagnostic code

## Conclusion

The production system uses approximately 20-25 core scripts out of 71 total, suggesting significant opportunity for code organization. The remaining scripts serve diagnostic, CLI, and monitoring purposes that could be separated into distinct packages to clarify the production codebase.