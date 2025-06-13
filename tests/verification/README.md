# Production Verification Protocol

This directory contains the comprehensive verification test suite implementing the 50+ checkpoint protocol from context_399 for testing the entire document processing pipeline.

## Overview

The verification protocol validates all aspects of the legal document processing system:
- Environment configuration
- Document discovery and intake
- Batch processing capabilities
- Real-time status tracking
- Validation frameworks
- Audit logging
- Production processing
- Performance metrics
- Quality thresholds
- System integration

## Quick Start

### Run Full Verification
```bash
# Run all verification tests
python run_verification.py

# Run with minimal output
python run_verification.py --quiet

# Run essential tests only (quick check)
python run_verification.py --quick
```

### Run Individual Checks
```bash
# Check environment setup
python verification_helper.py env

# Test document discovery
python verification_helper.py discovery

# Check worker health
python verification_helper.py workers

# Run all individual checks
python verification_helper.py all
```

### Using Pytest (Recommended for CI/CD)
```bash
# Run all verification tests with pytest
pytest tests/verification/test_production_verification.py -v

# Run specific phase
pytest tests/verification/test_production_verification.py::TestPreFlight -v

# Run specific test
pytest tests/verification/test_production_verification.py -k "ENV-001" -v

# Generate HTML report
pytest tests/verification/test_production_verification.py --html=verification_report.html
```

## Test Structure

### Phase 1: Pre-Flight Checks (ENV-001 to ENV-005)
- Environment variables verification
- Redis connection testing
- Database connectivity
- S3 bucket access
- Input document availability

### Phase 2: Document Discovery (DISC-001, DISC-002, VAL-001)
- Document discovery functionality
- Deduplication verification
- Integrity validation

### Phase 3: Batch Processing (BATCH-001, BATCH-002)
- Batch creation with strategies
- Manifest generation

### Phase 4: Status Tracking (STATUS-001, STATUS-002, DASH-001)
- Document status tracking
- Batch progress monitoring
- Dashboard data aggregation

### Phase 5: Validation Framework (OCR-001, ENTITY-001)
- OCR quality validation
- Entity extraction validation

### Phase 6: Audit Logging (LOG-001, LOG-002)
- Logging functionality
- Directory structure verification

### Phase 7: Production Processing (PROD-001 to PROD-004)
- Small batch processing
- Campaign monitoring
- Enhanced dashboard
- Full production test

### Phase 8: Performance (PERF-001, PERF-002)
- Throughput measurement
- Error rate calculation

### Phase 9: Quality (QUAL-001, QUAL-002)
- OCR quality validation
- Data consistency checks

### Phase 10: Integration (E2E-001, SYS-001)
- End-to-end pipeline validation
- Worker health verification

## Success Criteria

The system is considered "Production Ready" when:
- All environment checks pass (100%)
- Document discovery finds and validates files
- Batch processing creates appropriate batches
- Status tracking works via Redis
- Validation framework operates correctly
- Audit logging creates proper log structure
- Production processing handles real documents
- Performance meets targets (10+ docs/hour, <5% error rate)
- Quality metrics meet thresholds (OCR >95%, Consistency >85%)
- End-to-end pipeline validation passes

## Output and Reports

### Console Output
The verification runner provides real-time feedback:
```
================================================================
Phase: Pre-Flight Environment Checks
================================================================
  ✅ ENV-001: Passed
  ✅ ENV-002: Passed
  ✅ ENV-003: Passed
  ✅ ENV-004: Passed
  ✅ ENV-005: Passed

Phase Summary: 5/5 passed (2.3s)
```

### JSON Report
Detailed reports are saved to `/opt/legal-doc-processor/monitoring/reports/`:
```json
{
  "timestamp": "2025-06-04T12:00:00",
  "total_duration_minutes": 30.5,
  "total_tests": 50,
  "passed": 48,
  "failed": 2,
  "success_rate": 96.0,
  "system_ready": true,
  "phases": [...]
}
```

## Troubleshooting

### Common Issues

1. **Missing Environment Variables**
   ```bash
   # Load environment
   source /opt/legal-doc-processor/load_env.sh
   ```

2. **Redis Connection Failed**
   ```bash
   # Check Redis
   redis-cli ping
   # Start if needed
   sudo service redis-server start
   ```

3. **No Workers Active**
   ```bash
   # Start workers
   celery -A scripts.celery_app worker --loglevel=info &
   ```

4. **S3 Access Denied**
   ```bash
   # Verify credentials
   aws sts get-caller-identity
   ```

## Development

### Adding New Tests

1. Add test method to appropriate class in `test_production_verification.py`
2. Follow naming convention: `test_CATEGORY_NNN_description`
3. Use `VerificationResult` for consistent reporting
4. Document expected outcomes

### Test Categories
- ENV: Environment checks
- DISC: Document discovery
- VAL: Validation
- BATCH: Batch processing
- STATUS: Status tracking
- DASH: Dashboard
- OCR: OCR validation
- ENTITY: Entity validation
- LOG: Logging
- PROD: Production processing
- PERF: Performance
- QUAL: Quality
- E2E: End-to-end
- SYS: System integration

## Integration with CI/CD

### GitHub Actions Example
```yaml
- name: Run Verification Tests
  run: |
    python run_verification.py --quiet
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
    AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

### Jenkins Pipeline
```groovy
stage('Verification') {
    steps {
        sh 'python run_verification.py'
        publishHTML([
            reportDir: 'monitoring/reports',
            reportFiles: 'verification_report_*.json',
            reportName: 'Verification Report'
        ])
    }
}
```

## Maintenance

- Review and update tests when adding new features
- Monitor test execution times and optimize slow tests
- Archive old verification reports monthly
- Update success criteria based on production metrics