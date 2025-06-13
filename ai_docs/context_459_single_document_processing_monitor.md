# Context 459: Single Document Processing Monitor

## Date: June 09, 2025

## Executive Summary

This document provides detailed monitoring of a single document processed through the legal document pipeline, tracking each stage and the scripts/functions used.

## Document Details

- **File**: Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf
- **Processing Start**: 2025-06-09T01:44:59.420180
- **Processing End**: 2025-06-09T01:44:59.679686

## Processing Stages


### Project Creation - STARTED

- **Time**: 2025-06-09T01:44:59.420197
- **Script**: `scripts/db.py`
- **Function**: `DatabaseManager.execute`

### Project Creation - COMPLETED

- **Time**: 2025-06-09T01:44:59.457796
- **Script**: `scripts/db.py`
- **Function**: `DatabaseManager.execute`
- **Details**:
```json
{
  "project_id": 24,
  "project_uuid": "491dbe3e-9340-47d6-a868-a436e17f2473"
}
```

### Document Processing - STARTED

- **Time**: 2025-06-09T01:44:59.458220
- **Script**: `scripts/intake_service.py`
- **Function**: `create_document_with_validation`
- **Details**:
```json
{
  "filename": "Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf",
  "document_uuid": "4457a843-7b78-49ce-a51c-09d16c88edc0"
}
```

### S3 Upload - STARTED

- **Time**: 2025-06-09T01:44:59.458478
- **Script**: `scripts/s3_storage.py`
- **Function**: `upload_document_with_uuid_naming`

### S3 Upload - COMPLETED

- **Time**: 2025-06-09T01:44:59.678798
- **Script**: `scripts/s3_storage.py`
- **Function**: `upload_document_with_uuid_naming`
- **Details**:
```json
{
  "s3_key": "documents/4457a843-7b78-49ce-a51c-09d16c88edc0.pdf",
  "s3_bucket": "samu-docs-private-upload",
  "file_size": 149104
}
```

### Database Record Creation - STARTED

- **Time**: 2025-06-09T01:44:59.679305
- **Script**: `scripts/intake_service.py`
- **Function**: `create_document_with_validation`

### Document Processing - FAILED

- **Time**: 2025-06-09T01:44:59.679435
- **Script**: `ERROR`
- **Function**: `TypeError`
- **Details**:
```json
{
  "error": "create_document_with_validation() got an unexpected keyword argument 'document_data'"
}
```

## Pipeline Flow Summary

Based on the monitoring, here's the order of script execution:

1. **scripts/db.py**
   - DatabaseManager.execute (Project Creation)
   - DatabaseManager.execute (Project Creation)
2. **scripts/intake_service.py**
   - create_document_with_validation (Document Processing)
   - create_document_with_validation (Database Record Creation)
3. **scripts/s3_storage.py**
   - upload_document_with_uuid_naming (S3 Upload)
   - upload_document_with_uuid_naming (S3 Upload)
4. **ERROR**
   - TypeError (Document Processing)
