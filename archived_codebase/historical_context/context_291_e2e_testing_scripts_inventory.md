# Complete E2E Testing Scripts Inventory

## Date: 2025-06-01
## Purpose: Comprehensive inventory of scripts for E2E testing execution
## Status: SCRIPT INVENTORY COMPLETE

## Overview

This document provides a complete inventory of all scripts required for end-to-end testing of the legal document processing pipeline. Each script is documented with its purpose, dependencies, and logging patterns to ensure successful test execution.

## 1. Primary CLI Scripts

### 1.1 Document Import Script
**Location**: `/opt/legal-doc-processor/scripts/cli/import.py`
- **Purpose**: Import documents from directory or manifest with type-safe validation
- **Dependencies**:
  - `DatabaseManager` - PostgreSQL operations
  - `S3StorageManager` - Document upload to S3
  - `get_redis_manager()` - Cache management
  - Pydantic models - Data validation
- **Logging Pattern**:
  ```python
  logger = logging.getLogger(__name__)
  # Logs: Document validation, upload progress, error details
  ```
- **Key Functions**:
  - `import_documents()` - Main import function
  - `validate_manifest()` - Manifest structure validation
  - `estimate_costs()` - Processing cost estimation

### 1.2 Pipeline Monitor Script
**Location**: `/opt/legal-doc-processor/scripts/cli/monitor.py`
- **Purpose**: Real-time pipeline monitoring dashboard
- **Dependencies**:
  - `DatabaseManager` - Database queries
  - Redis client - Cache status
  - Celery app - Worker monitoring
  - Rich console - UI rendering
- **Logging Pattern**:
  ```python
  logging.basicConfig(level=logging.INFO)
  # Rich console for visual output
  ```
- **Key Commands**:
  - `live` - Real-time dashboard
  - `health` - System health check
  - `doc-status <uuid>` - Specific document status
  - `workers` - Worker status

## 2. Core Processing Scripts

### 2.1 PDF Processing Tasks
**Location**: `/opt/legal-doc-processor/scripts/pdf_tasks.py`
- **Purpose**: Celery tasks for document processing pipeline
- **Dependencies**:
  - `celery_app` - Task queue
  - `DatabaseManager` - Data persistence
  - `EntityService` - Entity extraction
  - `GraphService` - Relationship building
  - `extract_text_from_pdf` - OCR functionality
- **Logging Pattern**:
  ```python
  @log_task_execution  # Decorator for enhanced logging
  logger.info("="*60)
  logger.info(f"🚀 TASK START: {task_name}")
  logger.info(f"📄 Document: {doc_uuid}")
  ```
- **Key Tasks**:
  - `extract_text_from_document` - OCR initiation
  - `poll_textract_job` - Async OCR polling
  - `chunk_document_text` - Text chunking
  - `extract_entities_from_chunks` - Entity extraction
  - `resolve_document_entities` - Entity resolution
  - `build_document_relationships` - Graph building

### 2.2 Celery Application
**Location**: `/opt/legal-doc-processor/scripts/celery_app.py`
- **Purpose**: Celery configuration and initialization
- **Dependencies**:
  - Redis (broker and backend)
  - SSL certificates for Redis Cloud
  - Environment configuration
- **Logging Pattern**:
  ```python
  # Uses Celery's built-in logging
  app.conf.worker_log_format = '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
  ```

## 3. Database Management Scripts

### 3.1 Database Manager
**Location**: `/opt/legal-doc-processor/scripts/db.py`
- **Purpose**: Unified database operations with Pydantic integration
- **Dependencies**:
  - SQLAlchemy 2.0
  - Pydantic models from `core/`
  - Model factory for conditional loading
  - Enhanced column mappings
- **Logging Pattern**:
  ```python
  logger = logging.getLogger(__name__)
  logger.warning("Skipping conformance validation due to SKIP_CONFORMANCE_CHECK=true")
  ```

### 3.2 Database State Checker
**Location**: `/opt/legal-doc-processor/scripts/check_database_state.py`
- **Purpose**: Check database connectivity and document status
- **Dependencies**:
  - SQLAlchemy
  - Database configuration
- **Logging Pattern**:
  ```python
  print(f"✅ Connected to database")
  print(f"⚠️  Warning: {warning}")
  print(f"❌ Failed: {error}")
  ```

### 3.3 RDS Connection Verifier
**Location**: `/opt/legal-doc-processor/scripts/check_rds_connection.py`
- **Purpose**: Verify RDS database connectivity
- **Dependencies**:
  - psycopg2 or SQLAlchemy
  - Environment variables
- **Logging Pattern**:
  ```python
  print(f"Testing connection to: {database_url}")
  print("✅ Connection successful!")
  ```

## 4. Monitoring and Verification Scripts

### 4.1 Pipeline Progress Monitor
**Location**: `/opt/legal-doc-processor/scripts/monitor_pipeline_progress.py`
- **Purpose**: Track document processing progress
- **Dependencies**:
  - RDS utilities
  - Cache manager
  - Processing models
- **Logging Pattern**:
  ```python
  logger.info(f"Monitoring document: {document_uuid}")
  logger.info(f"Stage: {stage} - Status: {status}")
  ```

### 4.2 Log Monitor
**Location**: `/opt/legal-doc-processor/scripts/monitor_logs.py`
- **Purpose**: Real-time log monitoring
- **Dependencies**:
  - Log file access
  - Pattern matching utilities
- **Logging Pattern**:
  ```python
  # Reads from log files, doesn't generate logs
  tail -f /opt/legal-doc-processor/monitoring/logs/*.log
  ```

### 4.3 Pipeline Conformance Verifier
**Location**: `/opt/legal-doc-processor/scripts/verify_pipeline_conformance.py`
- **Purpose**: Verify schema conformance
- **Dependencies**:
  - SQLAlchemy inspector
  - Pydantic models
  - Conformance engine
- **Logging Pattern**:
  ```python
  print(f"Checking conformance for table: {table_name}")
  print(f"✅ Conformance check passed")
  ```

## 5. Testing Scripts

### 5.1 Single Document E2E Test
**Location**: `/opt/legal-doc-processor/scripts/test_e2e_single_doc.py`
- **Purpose**: Test complete pipeline with one document
- **Dependencies**:
  - All processing modules
  - Test document in S3/local
- **Logging Pattern**:
  ```python
  logging.basicConfig(level=logging.INFO)
  logger.info(f"Starting E2E test for document: {doc_uuid}")
  ```

### 5.2 Minimal Models E2E Test
**Location**: `/opt/legal-doc-processor/scripts/tests/test_e2e_minimal.py`
- **Purpose**: Test with minimal models enabled
- **Dependencies**:
  - Minimal model definitions
  - Environment variables (USE_MINIMAL_MODELS=true)
- **Logging Pattern**:
  ```python
  print(f"Testing with minimal models...")
  print(f"✅ Test passed: {test_name}")
  ```

### 5.3 Load Testing Script
**Location**: `/opt/legal-doc-processor/scripts/tests/test_load_async.py`
- **Purpose**: Test concurrent document processing
- **Dependencies**:
  - Async task submission
  - Multiple test documents
- **Logging Pattern**:
  ```python
  logger.info(f"Submitting {count} documents for processing")
  logger.info(f"Document {i}/{count}: {task_id}")
  ```

## 6. Utility Scripts

### 6.1 Cache Cleaner
**Location**: `/opt/legal-doc-processor/scripts/clear_doc_cache.py`
- **Purpose**: Clear Redis cache for documents
- **Dependencies**:
  - Redis client
  - Cache key patterns
- **Logging Pattern**:
  ```python
  print(f"Clearing cache for document: {doc_uuid}")
  print(f"Deleted {count} keys")
  ```

### 6.2 Logging Configuration
**Location**: `/opt/legal-doc-processor/scripts/logging_config.py`
- **Purpose**: Centralized logging setup
- **Dependencies**:
  - Python logging module
  - CloudWatch handler (optional)
- **Logging Pattern**:
  ```python
  # Configures logging for other modules
  handlers:
    - RotatingFileHandler (daily, 30-day retention)
    - StreamHandler (console output)
    - CloudWatchHandler (if configured)
  ```

### 6.3 Configuration Module
**Location**: `/opt/legal-doc-processor/scripts/config.py`
- **Purpose**: Environment configuration management
- **Dependencies**:
  - python-dotenv
  - Environment variables
- **Logging Pattern**:
  ```python
  logger.warning("CONFORMANCE VALIDATION BYPASSED - FOR TESTING ONLY")
  logger.info(f"Deployment Stage: {DEPLOYMENT_STAGE}")
  ```

## 7. Support Scripts

### 7.1 Entity Service
**Location**: `/opt/legal-doc-processor/scripts/entity_service.py`
- **Purpose**: Entity extraction and resolution
- **Dependencies**:
  - OpenAI API
  - spaCy (optional)
  - Database manager
- **Logging Pattern**:
  ```python
  logger.info(f"Extracting entities from {len(chunks)} chunks")
  logger.debug(f"Found entity: {entity_text} ({entity_type})")
  ```

### 7.2 Graph Service
**Location**: `/opt/legal-doc-processor/scripts/graph_service.py`
- **Purpose**: Build entity relationships
- **Dependencies**:
  - Entity data
  - Graph algorithms
- **Logging Pattern**:
  ```python
  logger.info(f"Building relationships for document {doc_uuid}")
  logger.info(f"Created {count} relationships")
  ```

### 7.3 S3 Storage Manager
**Location**: `/opt/legal-doc-processor/scripts/s3_storage.py`
- **Purpose**: S3 document operations
- **Dependencies**:
  - boto3
  - AWS credentials
- **Logging Pattern**:
  ```python
  logger.info(f"Uploading {file_name} to S3")
  logger.error(f"S3 upload failed: {error}")
  ```

## Test Execution Sequence

To execute a complete E2E test, use these scripts in order:

1. **Preparation**:
   ```bash
   python scripts/check_rds_connection.py  # Verify database
   python scripts/check_database_state.py  # Check initial state
   ```

2. **Start Monitoring**:
   ```bash
   python scripts/cli/monitor.py live  # In separate terminal
   ```

3. **Import Documents**:
   ```bash
   python scripts/cli/import.py --directory /opt/legal-doc-processor/document_intake/
   ```

4. **Track Progress**:
   ```bash
   python scripts/monitor_pipeline_progress.py --document-uuid <uuid>
   ```

5. **Verify Results**:
   ```bash
   python scripts/check_database_state.py  # Final state
   python scripts/verify_pipeline_conformance.py  # Data quality
   ```

## Common Logging Patterns Summary

1. **Standard Python Logging**:
   - Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
   - Levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

2. **Enhanced Task Logging** (pdf_tasks.py):
   - Visual separators and emojis
   - Task timing and performance metrics
   - Structured error reporting

3. **Console Output** (monitoring/verification):
   - Status indicators: ✅ ❌ ⚠️ 
   - Progress bars for batch operations
   - Rich formatting for dashboards

4. **Structured Logging** (production):
   - JSON format for machine parsing
   - Contextual information (doc_uuid, task_id)
   - Performance metrics included

## Dependencies Summary

### Python Packages
- SQLAlchemy >= 2.0
- Pydantic >= 2.0
- Celery >= 5.0
- Redis >= 4.0
- boto3 (AWS SDK)
- Rich (console UI)
- python-dotenv

### External Services
- PostgreSQL (RDS)
- Redis (Redis Cloud)
- AWS S3
- AWS Textract
- OpenAI API

### Environment Variables
- DATABASE_URL
- REDIS_HOST/PORT/PASSWORD
- AWS_ACCESS_KEY_ID/SECRET
- OPENAI_API_KEY
- USE_MINIMAL_MODELS
- SKIP_CONFORMANCE_CHECK

This comprehensive inventory ensures all necessary scripts are identified and understood for successful E2E testing execution.