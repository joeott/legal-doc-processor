# Context 204: Production Verification Guide

## Overview

This guide provides a comprehensive approach to deploying, operating, and verifying the document processing pipeline in production. It ensures reliable processing of 450+ documents with full visibility and quality control.

## Prerequisites

- [ ] Supabase instance with new schema deployed
- [ ] Redis Cloud connection configured
- [ ] AWS credentials for S3 and Textract
- [ ] OpenAI API key configured
- [ ] Celery workers deployed
- [ ] Monitoring stack (Grafana/Prometheus) ready

## 1. Pre-Production Verification

### 1.1 Environment Validation

```bash
# Verify all services are accessible
python scripts/cli/admin.py verify-services

# Expected output:
# ✓ Supabase: Connected (https://xxx.supabase.co)
# ✓ Redis: Connected (redis-xxx.c1.us-east-1-2.ec2.cloud.redislabs.com:11111)
# ✓ S3: Accessible (samu-docs-private-upload)
# ✓ Textract: Region verified (us-east-1)
# ✓ OpenAI: API key valid
# ✓ Celery: 4 workers online
```

### 1.2 Schema Verification

```bash
# Verify Supabase schema
python scripts/cli/admin.py verify-schema --check-indexes

# Run test document through pipeline
python scripts/cli/admin.py test-pipeline --document tests/fixtures/sample.pdf
```

## 2. Production Import Process

### 2.1 Create Import Session

```bash
# Initialize import session for batch processing
python scripts/cli/import.py create-session \
    --project-uuid "your-project-uuid" \
    --session-name "Paul Michael Acuity Import" \
    --manifest-file "paul_michael_acuity_manifest.json"

# Output:
# Import session created: session_uuid=abc-123-def
# Total files to process: 127
# Estimated processing time: 2.5 hours
```

### 2.2 Upload Documents

```bash
# Upload documents with progress tracking
python scripts/cli/import.py upload-batch \
    --session-uuid "abc-123-def" \
    --source-dir "input/Paul, Michael (Acuity)" \
    --parallel 4

# Real-time output:
# Uploading: 32/127 [██████░░░░] 25.2% | 3.2 MB/s | ETA: 5:23
# ✓ Discovery/correspondence_2024.pdf uploaded
# ✓ Client Docs/contract_draft_v3.docx uploaded
# ⚠ Dropbox files/~$temp.docx skipped (temporary file)
```

### 2.3 Start Processing Pipeline

```bash
# Trigger processing for all uploaded documents
python scripts/cli/import.py start-processing \
    --session-uuid "abc-123-def" \
    --priority 8 \
    --batch-size 10

# Monitor in real-time
python scripts/cli/monitor.py session \
    --session-uuid "abc-123-def" \
    --refresh 5
```

## 3. Real-Time Monitoring

### 3.1 Pipeline Dashboard

```bash
# Launch monitoring dashboard
python scripts/cli/monitor.py dashboard \
    --project-uuid "your-project-uuid"

# Display shows:
┌─────────────────────────────────────────────────────────────┐
│ Pipeline Status - Paul Michael Acuity                      │
├─────────────────────────────────────────────────────────────┤
│ Stage          │ Pending │ Processing │ Complete │ Failed │
├────────────────┼─────────┼────────────┼──────────┼────────┤
│ OCR            │    12   │     4      │   111    │   0    │
│ Chunking       │    16   │     2      │   109    │   0    │
│ Entity Extract │    18   │     8      │   101    │   0    │
│ Resolution     │    26   │     4      │    97    │   0    │
│ Relationships  │    30   │     2      │    95    │   0    │
└────────────────┴─────────┴────────────┴──────────┴────────┘

Processing Rate: 42 docs/hour | Avg OCR Time: 8.3s
Active Workers: 4/4 | Queue Depth: 58 | ETA: 1:23:45
```

### 3.2 Error Monitoring

```bash
# Monitor errors in real-time
python scripts/cli/monitor.py errors \
    --session-uuid "abc-123-def" \
    --tail

# Output:
[2025-01-29 10:23:45] ERROR: Document correspondence_old.pdf
  Stage: OCR
  Error: TextractThrottlingException - Rate exceeded
  Retry: 2/3 in 300s

[2025-01-29 10:25:12] ERROR: Document meeting_notes.docx
  Stage: Entity Extraction
  Error: OpenAI API timeout after 30s
  Retry: 1/3 in 60s
```

## 4. Quality Control Verification

### 4.1 Entity Resolution Verification

```bash
# Check entity resolution quality
python scripts/cli/admin.py verify-entities \
    --project-uuid "your-project-uuid" \
    --min-confidence 0.8

# Output:
Entity Type    | Total | Unique | Avg Confidence | Verified
───────────────┼───────┼────────┼───────────────┼──────────
PERSON         |  523  |   67   |    0.89       |   12
ORGANIZATION   |  412  |   45   |    0.92       |    8
LOCATION       |  234  |   28   |    0.87       |    5
DATE           |  789  |  156   |    0.95       |    0

Potential Issues:
- "Paul Michael" resolved to 3 different entities
- "Acuity" has 5 variations needing review
- 23 entities below confidence threshold
```

### 4.2 Relationship Validation

```bash
# Validate extracted relationships
python scripts/cli/admin.py validate-relationships \
    --project-uuid "your-project-uuid" \
    --check-consistency

# Output:
Relationship Type      | Count | Valid | Warnings
──────────────────────┼───────┼───────┼──────────
PARTY_TO_CONTRACT     |  45   |  45   |    0
REPRESENTS            |  67   |  65   |    2
LOCATED_AT           |  123  | 120   |    3
REFERENCES_CASE      |  89   |  89   |    0

Warnings:
- Circular relationship: ORG_123 -> REPRESENTS -> PERSON_45 -> REPRESENTS -> ORG_123
- Missing entity: REL_234 references non-existent PERSON_99
```

## 5. Performance Verification

### 5.1 Processing Metrics

```bash
# Generate performance report
python scripts/cli/admin.py performance-report \
    --session-uuid "abc-123-def" \
    --output-format markdown

# Key Metrics:
- Total Processing Time: 2:34:12
- Average Document Time: 72.3 seconds
- OCR Stage: 31.2s avg (8.1s - 89.3s)
- Chunking Stage: 4.5s avg
- Entity Extraction: 28.4s avg
- Resolution: 5.2s avg
- Relationships: 3.0s avg

- Cache Hit Rate: 23.4%
- Retry Rate: 3.2%
- Failure Rate: 0.0%
```

### 5.2 Resource Utilization

```bash
# Check resource usage
python scripts/cli/monitor.py resources

# Output:
Resource       | Current | Peak  | Limit
───────────────┼─────────┼───────┼────────
Redis Memory   | 234 MB  | 412MB | 1 GB
Redis Conn     | 23      | 67    | 200
Celery Queue   | 45      | 234   | 1000
S3 Bandwidth   | 12 MB/s | 45MB/s| 100MB/s
API Calls/min  | 234     | 456   | 600
```

## 6. Production Checkpoints

### 6.1 Pre-Processing Checklist

- [ ] All source documents accessible
- [ ] Sufficient API credits (OpenAI, Textract)
- [ ] Redis cache cleared or warmed
- [ ] Celery workers healthy
- [ ] Database connections < 50% limit
- [ ] S3 bucket has sufficient space
- [ ] Monitoring alerts configured

### 6.2 During Processing

Every 30 minutes:
- [ ] Check error rate < 5%
- [ ] Verify processing rate > 30 docs/hour
- [ ] Monitor API rate limits
- [ ] Check worker memory usage
- [ ] Verify no queue backup > 100 docs

### 6.3 Post-Processing Verification

- [ ] All documents in 'completed' state
- [ ] No unresolved errors
- [ ] Entity resolution > 85% confidence
- [ ] All relationships validated
- [ ] Export ready for Neo4j
- [ ] Backup created

## 7. Error Recovery Procedures

### 7.1 Bulk Retry Failed Documents

```bash
# Identify and retry failed documents
python scripts/cli/admin.py retry-failed \
    --session-uuid "abc-123-def" \
    --error-type "rate_limit" \
    --delay 300

# Manual retry with different settings
python scripts/cli/admin.py reprocess-document \
    --document-uuid "failed-doc-uuid" \
    --start-stage "entity_extraction" \
    --force
```

### 7.2 Handle Specific Error Types

```bash
# OCR failures (usually Textract limits)
python scripts/cli/admin.py handle-ocr-errors \
    --fallback-to-local \
    --batch-size 5

# Entity extraction failures
python scripts/cli/admin.py handle-entity-errors \
    --reduce-chunk-size \
    --model "gpt-3.5-turbo"
```

## 8. Data Export and Verification

### 8.1 Prepare for Neo4j Import

```bash
# Generate Neo4j import files
python scripts/cli/admin.py export-to-neo4j \
    --project-uuid "your-project-uuid" \
    --output-dir "exports/neo4j" \
    --format "csv"

# Verify export integrity
python scripts/cli/admin.py verify-export \
    --export-dir "exports/neo4j" \
    --check-relationships
```

### 8.2 Create Production Report

```bash
# Generate comprehensive processing report
python scripts/cli/admin.py generate-report \
    --session-uuid "abc-123-def" \
    --include-metrics \
    --include-entities \
    --include-errors \
    --format "pdf" \
    --output "reports/paul_michael_acuity_processing_report.pdf"
```

## 9. Production Deployment Commands

### 9.1 Start Production Processing

```bash
# Full production run
./scripts/production_run.sh \
    --manifest "paul_michael_acuity_manifest.json" \
    --project-uuid "your-project-uuid" \
    --workers 4 \
    --monitor
```

### 9.2 Stop/Pause Processing

```bash
# Graceful pause
python scripts/cli/admin.py pause-processing \
    --session-uuid "abc-123-def" \
    --complete-current

# Emergency stop
python scripts/cli/admin.py emergency-stop \
    --session-uuid "abc-123-def" \
    --reason "API rate limit exceeded"
```

## 10. Success Criteria

Production run is considered successful when:

1. **Completion Rate**: > 99% of documents fully processed
2. **Error Rate**: < 1% require manual intervention  
3. **Performance**: Average processing time < 90s per document
4. **Quality**: 
   - Entity confidence > 0.85 average
   - Relationship validation > 95%
   - OCR accuracy spot checks > 98%
5. **Reliability**: No system crashes or data loss
6. **Visibility**: All metrics captured and accessible

## Continuous Monitoring

Set up these alerts for production:

```yaml
alerts:
  - name: high_error_rate
    condition: error_rate > 5%
    window: 5m
    severity: warning
    
  - name: processing_stalled
    condition: completed_count unchanged
    window: 15m
    severity: critical
    
  - name: api_limit_approaching
    condition: api_calls > 500/min
    window: 1m
    severity: warning
    
  - name: queue_backup
    condition: queue_depth > 200
    window: 5m
    severity: warning
```

## Conclusion

This guide ensures reliable, verifiable production processing. Each checkpoint provides confidence that the system is operating correctly. The monitoring tools give real-time visibility into processing state, enabling quick intervention when needed.

Remember: **Visibility is key** - if you can't see it, you can't verify it.