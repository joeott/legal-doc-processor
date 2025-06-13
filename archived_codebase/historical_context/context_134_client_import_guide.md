# Client File Import Guide

This guide provides step-by-step instructions for importing complete client files into the document processing system. The system is designed to handle legal documents worth millions of dollars with complete tracking, verification, and cost monitoring.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Pre-Import Preparation](#pre-import-preparation)
3. [Step 1: Clear Test Data](#step-1-clear-test-data)
4. [Step 2: Analyze Client Files](#step-2-analyze-client-files)
5. [Step 3: Start Background Services](#step-3-start-background-services)
6. [Step 4: Import Documents](#step-4-import-documents)
7. [Step 5: Monitor Progress](#step-5-monitor-progress)
8. [Step 6: Verify Import](#step-6-verify-import)
9. [Cost Analysis](#cost-analysis)
10. [Troubleshooting](#troubleshooting)

## Prerequisites

Before starting the import process, ensure you have:

1. **Environment Variables Set**:
   ```bash
   # Required
   export SUPABASE_URL="your_supabase_url"
   export SUPABASE_KEY="your_supabase_anon_key"
   export SUPABASE_SERVICE_ROLE_KEY="your_service_role_key"
   export AWS_ACCESS_KEY_ID="your_aws_key"
   export AWS_SECRET_ACCESS_KEY="your_aws_secret"
   export S3_PRIMARY_DOCUMENT_BUCKET="your_s3_bucket"
   export OPENAI_API_KEY="your_openai_key"
   
   # Redis configuration
   export REDIS_HOST="localhost"  # or your Redis Cloud host
   export REDIS_PORT="6379"
   export REDIS_PASSWORD="your_redis_password"  # if using Redis Cloud
   ```

2. **Dependencies Installed**:
   ```bash
   pip install -r requirements.txt
   pip install python-magic  # For file type detection
   ```

3. **Database Migrations Applied**:
   - Ensure migrations 00015 and 00016 are applied in Supabase for vector embeddings

4. **Services Running**:
   - Redis server (local or cloud)
   - Supabase project accessible
   - AWS credentials valid

## Pre-Import Preparation

### Directory Structure
Your client files should be organized in a logical directory structure:
```
/path/to/client/files/
├── folder_a_pleadings/
├── folder_b_medical_records/
├── folder_c_discovery/
├── folder_d_correspondence/
└── folder_e_exhibits/
```

### File Naming Best Practices
- Use descriptive filenames
- Avoid special characters (except - and _)
- Keep filenames under 255 characters
- Maintain consistent naming conventions

## Step 1: Clear Test Data

**⚠️ WARNING**: This will permanently delete all data in the system. Only proceed if you're sure!

```bash
# Option 1: Clear all data (requires double confirmation)
python scripts/cleanup_database.py --all

# Option 2: Clear specific project data
python scripts/cleanup_database.py --project PROJECT_ID
```

The script will:
1. Ask for confirmation (type the case name)
2. Ask for second confirmation (type 'DELETE')
3. Remove all data in proper order respecting foreign keys
4. Show deletion counts for each table

## Step 2: Analyze Client Files

Analyze your client files to understand what will be imported:

```bash
# Basic analysis
python scripts/analyze_client_files.py /path/to/client/files \
    --case-name "Paul, Michael (Acuity)" \
    --output import_manifest.json
```

This will:
- Scan all files in the directory
- Detect file types and calculate sizes
- Identify duplicates by content hash
- Estimate processing costs
- Generate an import manifest

Review the output carefully:
```
FILE ANALYSIS SUMMARY - Paul, Michael (Acuity)
============================================================
Total files: 497
Unique files: 485
Duplicates: 12
Total size: 2.34 GB
Errors encountered: 0

Files by type:
  application/pdf: 245
  application/vnd.openxmlformats-officedocument.wordprocessingml.document: 125
  image/jpeg: 87
  text/plain: 40

Estimated costs:
  Textract OCR: $184.50
  OpenAI extraction: $45.20
  OpenAI embeddings: $0.89
  S3 uploads: $0.02
  Total processing: $230.61
  Monthly storage: $0.05
```

## Step 3: Start Background Services

### Start Celery Workers
```bash
# Terminal 1: Start Celery workers
cd /path/to/project
export PYTHONPATH=$PWD:$PYTHONPATH
celery -A scripts.celery_app worker --loglevel=info --concurrency=4 \
    --queues=default,ocr,text,entity,graph,embeddings
```

### Start Flower Monitor (Optional)
```bash
# Terminal 2: Start Flower dashboard
celery -A scripts.celery_app flower
# Access at http://localhost:5555
```

## Step 4: Import Documents

### Dry Run First
Always do a dry run to verify configuration:
```bash
python scripts/import_client_files.py import_manifest.json \
    --dry-run \
    --workers 4 \
    --batch-size 50
```

### Full Import
```bash
# Start the import
python scripts/import_client_files.py import_manifest.json \
    --workers 4 \
    --batch-size 50 \
    --export import_results.json
```

Import parameters:
- `--workers`: Number of concurrent upload threads (default: 4)
- `--batch-size`: Documents per batch (default: 50)
- `--project-id`: Use existing project ID (optional)
- `--skip-processed`: Skip already processed files (default: true)

The import will:
1. Create/use a project for the case
2. Register all files in the tracking database
3. Process files by category in order (pleadings → medical → discovery → etc.)
4. Upload to S3 with proper folder structure
5. Create database entries
6. Submit to Celery for processing
7. Track costs in real-time
8. Retry failed documents automatically

## Step 5: Monitor Progress

### Option 1: Live Dashboard
In a new terminal:
```bash
# Get the session ID from import output
python scripts/import_dashboard.py SESSION_ID --refresh 2
```

Dashboard features:
- Real-time progress tracking
- Cost breakdown by service
- Currently processing documents
- Recent errors
- Tab navigation (TAB key)
- Scroll support (↑↓ keys)

### Option 2: Flower Web UI
Navigate to http://localhost:5555 to see:
- Active tasks
- Task history
- Worker status
- Queue lengths

### Option 3: Enhanced Pipeline Monitor
```bash
python scripts/enhanced_pipeline_monitor.py --refresh-interval 5
```

## Step 6: Verify Import

After import completes, verify everything worked:

### Basic Verification
```bash
python scripts/verify_import.py SESSION_ID --output verification_report.json
```

### Deep Verification
```bash
python scripts/verify_import.py SESSION_ID --deep --output verification_report.json
```

The verification checks:
1. Import completeness (>95% success rate expected)
2. Duplicate detection
3. File integrity
4. Database entries exist
5. S3 uploads completed
6. Processing status
7. Error pattern analysis
8. S3 accessibility (deep check)
9. Processing outputs (chunks, entities, relationships)

Review the verification summary:
```
VERIFICATION SUMMARY
============================================================
Checks performed: 9
  PASS: 6
  WARN: 2
  INFO: 1

Issues found: 2
  MEDIUM: 2

Overall Status: WARN

RECOMMENDATIONS
============================================================
⚡ MEDIUM PRIORITY: 12 documents are duplicates
   Action: Review duplicate files and consider deduplication

⚡ MEDIUM PRIORITY: 3 documents missing S3 keys
   Action: Check S3 permissions and re-upload missing files
```

## Cost Analysis

### During Import
The dashboard shows real-time costs:
- Textract OCR charges
- OpenAI API usage
- S3 storage costs
- Running total

### Post-Import Analysis
```bash
# Extract cost report from import results
python -c "
import json
with open('import_results.json') as f:
    data = json.load(f)
    costs = data['summary']['session']['cost_breakdown']
    total = data['summary']['session']['total_cost']
    print('Cost Breakdown:')
    for service, cost in costs.items():
        print(f'  {service}: ${cost:.2f}')
    print(f'Total: ${total:.2f}')
"
```

### Cost Optimization Tips
1. **Batch Processing**: Larger batches reduce API overhead
2. **Deduplication**: Remove duplicates before import
3. **File Filtering**: Exclude non-relevant files (videos, etc.)
4. **Off-Peak Processing**: Run during AWS off-peak hours

## Troubleshooting

### Common Issues

#### 1. Import Failures
```bash
# Check specific failed documents
python -c "
import json
with open('import_results.json') as f:
    data = json.load(f)
    for doc in data['documents']:
        if doc['status'] == 'failed':
            print(f\"{doc['file_path']}: {doc['error_message']}\")
"
```

#### 2. Stuck Processing
```bash
# Check Celery task status
celery -A scripts.celery_app inspect active

# Debug specific document
python scripts/debug_celery_document.py --file "document.pdf"
```

#### 3. S3 Upload Issues
- Verify AWS credentials: `aws s3 ls`
- Check bucket permissions
- Ensure bucket region matches configuration

#### 4. Database Connection Issues
```bash
# Test database connection
python scripts/health_check.py
```

### Recovery Procedures

#### Retry Failed Documents
The import process automatically retries failed documents up to 3 times.

#### Resume Interrupted Import
```bash
# Import will skip already processed files
python scripts/import_client_files.py import_manifest.json \
    --skip-processed
```

#### Manual Document Processing
```bash
# Process single document manually
python scripts/test_single_document.py /path/to/document.pdf
```

## Best Practices

1. **Always Do a Dry Run First**
   - Validates configuration
   - Estimates costs
   - Identifies potential issues

2. **Monitor During Import**
   - Use the dashboard to catch issues early
   - Watch for error patterns
   - Monitor costs in real-time

3. **Verify After Import**
   - Run verification immediately
   - Address high-priority issues first
   - Keep verification reports for audit trail

4. **Document Everything**
   - Save all manifests and reports
   - Note any manual interventions
   - Track total costs for billing

5. **Process in Batches**
   - For very large imports (>10,000 files), process in batches
   - Allows for incremental verification
   - Easier error recovery

## Example Complete Workflow

```bash
# 1. Prepare environment
export PYTHONPATH=/path/to/project:$PYTHONPATH
source .env  # Load environment variables

# 2. Clear test data (if needed)
python scripts/cleanup_database.py --all

# 3. Analyze files
python scripts/analyze_client_files.py /Volumes/ExtDrive/ClientFiles \
    --case-name "Smith v. Jones" \
    --output smith_jones_manifest.json

# 4. Start workers
celery -A scripts.celery_app worker --loglevel=info --concurrency=4 \
    --queues=default,ocr,text,entity,graph,embeddings &

# 5. Start Flower (in new terminal)
celery -A scripts.celery_app flower &

# 6. Dry run
python scripts/import_client_files.py smith_jones_manifest.json --dry-run

# 7. Full import (in new terminal for dashboard)
python scripts/import_client_files.py smith_jones_manifest.json \
    --workers 6 --batch-size 100 --export smith_jones_import.json &

# 8. Monitor (in new terminal)
python scripts/import_dashboard.py 1  # Use actual session ID

# 9. Wait for completion, then verify
python scripts/verify_import.py 1 --deep --output smith_jones_verification.json

# 10. Review results
cat smith_jones_verification.json | jq '.overall_status'
```

## Support

For issues or questions:
1. Check the verification report for specific errors
2. Review Celery/Flower logs for processing errors
3. Consult the troubleshooting section
4. Check system logs in `logs/` directory

Remember: This system handles critical legal documents. Always verify imports and maintain proper backups!