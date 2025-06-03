# Context 214: Document Import System Design

**Date**: 2025-01-29
**Type**: System Architecture Documentation
**Status**: DOCUMENTED

## Overview

This document describes how the document import system is designed to handle document intake and processing in the legal document pipeline.

## Document Import System Design

The system uses a **manifest-based import process** with the following key components:

### 1. Primary Import Method: Manifest Files

Documents are imported using JSON manifest files that describe:
- Case metadata (name, base path, creation time)
- File listings with metadata (path, size, type, hash)
- Import configuration (batch size, processing order)

### 2. Import Commands via CLI

The system provides two main import methods through `scripts/cli/import.py`:

```bash
# Import from a manifest file
python -m scripts.cli.import from-manifest manifest.json --project-uuid <uuid>

# Import from a directory (auto-generates manifest)
python -m scripts.cli.import from-directory /path/to/docs --project-uuid <uuid> --recursive
```

### 3. Document Flow

1. **Local Files** → Stored in `/input/` directory structure
2. **Manifest Creation** → JSON file listing all documents with metadata
3. **Import Session** → Created in database to track progress
4. **S3 Upload** → Documents uploaded with UUID naming
5. **Celery Processing** → Tasks submitted for pipeline processing

### 4. Processing Example: Wombat Document

To process the Wombat Answer and Counterclaim document:

```bash
# Option 1: Import single file from directory
python -m scripts.cli.import from-directory "/Users/josephott/Documents/phase_1_2_3_process_v5/input/Paul, Michael (Acuity)" \
  --project-uuid <project-uuid> \
  --file-types pdf

# Option 2: Create manifest first, then import
# The manifest would include the file path relative to base directory
```

### 5. Key Design Features

- **Type Safety**: Uses Pydantic models for validation
- **Batch Processing**: Handles large imports in configurable batches
- **Progress Tracking**: Import sessions track success/failure rates
- **Cost Estimation**: Estimates processing costs before import
- **S3 Integration**: Automatically uploads to S3 with proper naming

### 6. Directory Structure

The `/input/` directory contains client files organized by:
```
input/
└── Paul, Michael (Acuity)/
    ├── Client Docs/
    │   ├── Discovery/
    │   ├── Dropbox files/
    │   └── [other subdirectories]
    └── [individual case documents]
```

### 7. Import Validation

Before import, the system validates:
- File existence and accessibility
- Duplicate file detection (via hash)
- Large file warnings (>100MB)
- Supported file types
- Project UUID existence

### 8. Database Integration

Import sessions are tracked in the `import_sessions` table with:
- Session name and status
- Total/processed/failed file counts
- Start and completion timestamps
- Manifest path reference

Each imported document creates entries in:
- `source_documents` table (with S3 keys and metadata)
- Links to `import_sessions` for tracking
- Celery task IDs for processing status

## Implementation Notes

The system is designed to handle bulk imports from client file directories, with manifest files serving as the primary mechanism for organizing and tracking document sets. This approach provides:

1. **Auditability**: Complete record of what was imported
2. **Reprocessing**: Ability to retry failed imports
3. **Cost Control**: Preview costs before processing
4. **Flexibility**: Import entire directories or specific manifests

## Related Contexts

- Context 213: Production Deployment Checklist
- Context 203: Supabase Schema Design
- Context 204: Production Verification Guide