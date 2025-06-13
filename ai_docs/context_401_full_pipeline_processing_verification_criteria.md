# Context 401: Full Pipeline Processing Verification Criteria and Metrics Collection

**Date**: June 5, 2025  
**Purpose**: Comprehensive verification criteria for processing all 463 documents in `/opt/legal-doc-processor/input_docs` through the complete pipeline with stage-by-stage verification and performance metrics collection.

## Executive Summary

This document defines the verification criteria, metrics collection framework, and task list for processing the entire document corpus through all pipeline stages. Each document will be tracked through:
1. Document Intake & S3 Upload
2. OCR Processing (Textract)
3. Text Chunking
4. Entity Extraction
5. Entity Resolution
6. Relationship Building

Performance metrics will be collected at each stage to establish baseline processing times and identify bottlenecks.

## Verification Criteria

### 1. Document Intake Verification

**Criteria ID**: INTAKE-001  
**Description**: Verify all documents are successfully discovered, validated, and uploaded to S3

**Success Metrics**:
- 100% of documents discovered (463 expected)
- 100% pass integrity validation
- 100% successfully uploaded to S3
- S3 URLs generated and stored

**Verification Steps**:
```python
# 1. Count discovered documents
discovered = intake_service.discover_documents('/opt/legal-doc-processor/input_docs')
assert len(discovered) == 463

# 2. Validate each document
validation_results = {}
for doc in discovered:
    validation = intake_service.validate_document_integrity(doc.local_path)
    validation_results[doc.filename] = validation.is_valid

# 3. Upload to S3 and verify
upload_results = {}
for doc in discovered:
    s3_location = intake_service.upload_to_s3_with_metadata(doc.local_path, doc.to_dict())
    upload_results[doc.filename] = s3_location is not None
```

**Metrics to Collect**:
- Discovery time (total)
- Validation time per document
- Upload time per document
- File size distribution
- Document type distribution

### 2. OCR Processing Verification

**Criteria ID**: OCR-001  
**Description**: Verify Textract processing completes for all documents

**Success Metrics**:
- 95%+ documents successfully OCR'd
- Average confidence score > 85%
- Text extraction not empty
- Job IDs persisted in database

**Verification Steps**:
```python
# For each document
ocr_results = {}
for doc_uuid in document_uuids:
    # Submit to Textract
    result = extract_text_from_document.delay(doc_uuid, s3_url)
    
    # Poll for completion
    while True:
        status = check_textract_job_status(doc_uuid)
        if status in ['SUCCEEDED', 'FAILED']:
            break
        time.sleep(5)
    
    # Verify results
    text = get_cached_ocr_result(doc_uuid)
    ocr_results[doc_uuid] = {
        'status': status,
        'has_text': bool(text and len(text) > 0),
        'text_length': len(text) if text else 0,
        'confidence': get_ocr_confidence(doc_uuid)
    }
```

**Metrics to Collect**:
- OCR submission time
- Textract processing time (async)
- Text extraction success rate
- Average confidence scores
- Text length distribution
- Retry count per document

### 3. Text Chunking Verification

**Criteria ID**: CHUNK-001  
**Description**: Verify text is properly chunked with appropriate overlap

**Success Metrics**:
- 100% of OCR'd documents have chunks created
- Average chunks per document: 5-50 (depending on size)
- Chunk overlap maintained (200 chars)
- Chunks stored in database

**Verification Steps**:
```python
chunking_results = {}
for doc_uuid in successful_ocr_docs:
    # Get text
    text = get_cached_ocr_result(doc_uuid)
    
    # Create chunks
    chunks = chunk_document_text.delay(doc_uuid, text)
    
    # Verify chunks
    stored_chunks = db.query(ChunkModel).filter_by(document_uuid=doc_uuid).all()
    chunking_results[doc_uuid] = {
        'chunk_count': len(stored_chunks),
        'avg_chunk_size': sum(len(c.chunk_text) for c in stored_chunks) / len(stored_chunks),
        'has_overlap': verify_chunk_overlap(stored_chunks)
    }
```

**Metrics to Collect**:
- Chunking time per document
- Number of chunks per document
- Average chunk size
- Chunk size distribution
- Memory usage during chunking

### 4. Entity Extraction Verification

**Criteria ID**: ENTITY-001  
**Description**: Verify entities are extracted from all chunks

**Success Metrics**:
- 90%+ chunks have entities extracted
- Average entities per chunk: 5-20
- Entity types properly distributed
- Confidence scores recorded

**Verification Steps**:
```python
entity_results = {}
for doc_uuid in chunked_docs:
    chunks = get_document_chunks(doc_uuid)
    
    # Extract entities
    extraction_result = extract_entities_from_chunks.delay(doc_uuid, chunks)
    
    # Verify entities
    entities = db.query(EntityMentionModel).filter_by(document_uuid=doc_uuid).all()
    
    entity_results[doc_uuid] = {
        'total_entities': len(entities),
        'entities_per_chunk': len(entities) / len(chunks),
        'entity_types': count_entity_types(entities),
        'avg_confidence': calculate_avg_confidence(entities)
    }
```

**Metrics to Collect**:
- Entity extraction time per chunk
- OpenAI API call time
- Number of entities per document
- Entity type distribution
- Confidence score distribution
- API token usage

### 5. Entity Resolution Verification

**Criteria ID**: RESOLVE-001  
**Description**: Verify entities are resolved to canonical entities

**Success Metrics**:
- 85%+ entities resolved
- Duplicate entities merged
- Canonical entities created
- Resolution confidence tracked

**Verification Steps**:
```python
resolution_results = {}
for doc_uuid in entity_extracted_docs:
    # Resolve entities
    result = resolve_entities_for_document.delay(doc_uuid)
    
    # Verify resolution
    mentions = db.query(EntityMentionModel).filter_by(document_uuid=doc_uuid).all()
    canonical = db.query(CanonicalEntityModel).join(
        EntityMentionModel
    ).filter(EntityMentionModel.document_uuid == doc_uuid).distinct().all()
    
    resolution_results[doc_uuid] = {
        'total_mentions': len(mentions),
        'canonical_entities': len(canonical),
        'resolution_ratio': len(canonical) / len(mentions),
        'resolved_mentions': count_resolved_mentions(mentions)
    }
```

**Metrics to Collect**:
- Resolution time per document
- Resolution ratio (canonical/mentions)
- Cluster sizes
- Resolution confidence distribution
- Memory usage during resolution

### 6. Relationship Building Verification

**Criteria ID**: RELATION-001  
**Description**: Verify relationships are built between entities

**Success Metrics**:
- Relationships created for 80%+ documents
- Average relationships per document: 10-50
- Relationship types properly distributed
- Confidence scores recorded

**Verification Steps**:
```python
relationship_results = {}
for doc_uuid in resolved_docs:
    # Build relationships
    result = build_document_relationships.delay(doc_uuid)
    
    # Verify relationships
    relationships = db.query(RelationshipStagingModel).filter_by(
        document_uuid=doc_uuid
    ).all()
    
    relationship_results[doc_uuid] = {
        'total_relationships': len(relationships),
        'relationship_types': count_relationship_types(relationships),
        'avg_confidence': calculate_avg_confidence(relationships),
        'entities_connected': count_unique_entities_in_relationships(relationships)
    }
```

**Metrics to Collect**:
- Relationship extraction time
- Number of relationships per document
- Relationship type distribution
- Confidence score distribution
- Graph connectivity metrics

## Performance Metrics Framework

### Time Tracking Structure
```python
@dataclass
class StageMetrics:
    stage_name: str
    document_uuid: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    status: str = "in_progress"
    error_message: Optional[str] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Metrics Collection Points
1. **Per-Document Metrics**
   - Total processing time (intake to relationships)
   - Time spent in each stage
   - Queue wait times
   - Retry attempts
   - Error occurrences

2. **Per-Stage Metrics**
   - Average processing time
   - Success rate
   - Error rate
   - Throughput (docs/hour)
   - Resource utilization

3. **System-Wide Metrics**
   - Total throughput
   - Concurrent processing capacity
   - API usage (OpenAI, Textract)
   - Database query performance
   - Redis cache hit rates

## Task List for Full Processing

### Phase 1: Environment Preparation
- [ ] **PREP-001**: Start Celery workers with all queues
  ```bash
  celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup --concurrency=4
  ```

- [ ] **PREP-002**: Clear any existing processing state
  ```python
  # Clear Redis state for clean run
  redis_manager.clear_pattern("doc:state:*")
  redis_manager.clear_pattern("doc:ocr:*")
  ```

- [ ] **PREP-003**: Initialize metrics collection
  ```python
  metrics_collector = MetricsCollector()
  campaign_id = f"full_processing_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
  ```

### Phase 2: Batch Creation and Submission
- [ ] **BATCH-001**: Create processing batches
  ```python
  # Discover documents
  documents = intake_service.discover_documents('/opt/legal-doc-processor/input_docs')
  
  # Create batches (25 docs per batch for optimal performance)
  batches = intake_service.create_processing_batches(
      [doc.to_dict() for doc in documents],
      batch_strategy='balanced'
  )
  ```

- [ ] **BATCH-002**: Submit batches for processing
  ```python
  batch_jobs = []
  for batch in batches:
      manifest = batch_processor.create_batch_manifest(batch['documents'], batch)
      job = batch_processor.submit_batch_for_processing(manifest)
      batch_jobs.append(job)
      metrics_collector.record_batch_submission(job)
  ```

### Phase 3: Real-Time Monitoring
- [ ] **MONITOR-001**: Track processing progress
  ```python
  while processing_active:
      for batch_job in batch_jobs:
          progress = batch_processor.monitor_batch_progress(batch_job.batch_id)
          metrics_collector.update_batch_progress(batch_job.batch_id, progress)
      
      # Update dashboard
      dashboard = status_manager.get_live_processing_dashboard()
      display_progress(dashboard)
      
      time.sleep(30)  # Check every 30 seconds
  ```

- [ ] **MONITOR-002**: Collect stage transition metrics
  ```python
  # Monitor Redis for stage transitions
  for doc_uuid in all_document_uuids:
      state = redis_manager.get_cached(f"doc:state:{doc_uuid}")
      if state and state.get('stage') != last_known_stage[doc_uuid]:
          metrics_collector.record_stage_transition(
              doc_uuid,
              last_known_stage[doc_uuid],
              state.get('stage'),
              timestamp=datetime.now()
          )
  ```

### Phase 4: Verification at Each Stage
- [ ] **VERIFY-001**: Verify intake completion
  ```python
  intake_complete = verify_all_documents_in_s3(document_uuids)
  metrics_collector.record_stage_completion('intake', intake_complete)
  ```

- [ ] **VERIFY-002**: Verify OCR completion
  ```python
  ocr_complete = verify_all_documents_have_text(document_uuids)
  metrics_collector.record_stage_completion('ocr', ocr_complete)
  ```

- [ ] **VERIFY-003**: Verify chunking completion
  ```python
  chunking_complete = verify_all_documents_have_chunks(document_uuids)
  metrics_collector.record_stage_completion('chunking', chunking_complete)
  ```

- [ ] **VERIFY-004**: Verify entity extraction
  ```python
  entity_complete = verify_all_documents_have_entities(document_uuids)
  metrics_collector.record_stage_completion('entity_extraction', entity_complete)
  ```

- [ ] **VERIFY-005**: Verify entity resolution
  ```python
  resolution_complete = verify_all_documents_have_canonical_entities(document_uuids)
  metrics_collector.record_stage_completion('entity_resolution', resolution_complete)
  ```

- [ ] **VERIFY-006**: Verify relationship building
  ```python
  relationship_complete = verify_all_documents_have_relationships(document_uuids)
  metrics_collector.record_stage_completion('relationship_building', relationship_complete)
  ```

### Phase 5: Metrics Analysis and Reporting
- [ ] **REPORT-001**: Generate processing summary
  ```python
  summary = metrics_collector.generate_summary()
  print(f"Total Documents: {summary['total_documents']}")
  print(f"Successfully Processed: {summary['successful']}")
  print(f"Failed: {summary['failed']}")
  print(f"Total Time: {summary['total_duration_hours']:.2f} hours")
  print(f"Average Time per Document: {summary['avg_time_per_doc_minutes']:.2f} minutes")
  ```

- [ ] **REPORT-002**: Generate stage-wise metrics
  ```python
  stage_metrics = metrics_collector.get_stage_metrics()
  for stage in ['intake', 'ocr', 'chunking', 'entity_extraction', 'entity_resolution', 'relationships']:
      metrics = stage_metrics[stage]
      print(f"\n{stage.upper()}:")
      print(f"  Average Time: {metrics['avg_time_seconds']:.2f}s")
      print(f"  Success Rate: {metrics['success_rate']:.1f}%")
      print(f"  Throughput: {metrics['docs_per_hour']:.1f} docs/hour")
  ```

- [ ] **REPORT-003**: Identify bottlenecks
  ```python
  bottlenecks = metrics_collector.identify_bottlenecks()
  print("\nBottleneck Analysis:")
  for bottleneck in bottlenecks:
      print(f"  {bottleneck['stage']}: {bottleneck['issue']}")
      print(f"    Impact: {bottleneck['impact']}")
      print(f"    Recommendation: {bottleneck['recommendation']}")
  ```

- [ ] **REPORT-004**: Generate detailed CSV report
  ```python
  # Export detailed metrics for each document
  metrics_collector.export_to_csv(f"{campaign_id}_detailed_metrics.csv")
  
  # Export stage transition timeline
  metrics_collector.export_timeline(f"{campaign_id}_timeline.csv")
  ```

## Expected Outcomes

### Performance Baselines
Based on system configuration and Stage 1 deployment:

1. **Document Intake**: 1-2 seconds per document
2. **OCR (Textract)**: 30-60 seconds per document (async)
3. **Text Chunking**: 2-5 seconds per document
4. **Entity Extraction**: 10-30 seconds per document (OpenAI API)
5. **Entity Resolution**: 5-10 seconds per document
6. **Relationship Building**: 5-15 seconds per document

**Total Pipeline Time**: 60-120 seconds per document (with parallelization)

### Success Criteria
- **Overall Success Rate**: > 95%
- **OCR Success Rate**: > 98%
- **Entity Extraction Coverage**: > 90%
- **Throughput**: > 30 documents/hour (with 4 workers)
- **Error Rate**: < 5%
- **Retry Rate**: < 10%

### Failure Handling
- Documents failing at any stage should be logged with detailed error information
- Retry logic should handle transient failures
- Failed documents should be quarantined for manual review
- Partial processing should be resumable

## Monitoring Commands

### Real-Time Monitoring
```bash
# Watch processing progress
python scripts/cli/monitor.py live

# Check specific document
python scripts/cli/monitor.py doc-status <document_uuid>

# View worker status
python scripts/cli/monitor.py workers
```

### Batch Status
```bash
# Check batch progress
python scripts/production_processor.py monitor <campaign_id>

# Generate report
python scripts/production_processor.py report <campaign_id>
```

## Troubleshooting Guide

### Common Issues and Solutions

1. **Slow OCR Processing**
   - Check Textract job queue
   - Verify AWS credentials and region
   - Monitor API throttling

2. **Entity Extraction Timeouts**
   - Check OpenAI API status
   - Verify API key and rate limits
   - Reduce chunk sizes if needed

3. **Memory Issues**
   - Monitor worker memory usage
   - Reduce batch sizes
   - Increase worker count instead of concurrency

4. **Database Bottlenecks**
   - Check connection pool usage
   - Monitor slow queries
   - Verify RDS instance performance

## Conclusion

This verification criterion provides a comprehensive framework for processing all 463 documents through the complete pipeline while collecting detailed metrics at each stage. The metrics collected will establish performance baselines, identify bottlenecks, and verify the production readiness of the system.

The task list ensures systematic execution with proper monitoring and verification at each stage, while the metrics framework provides the data needed for optimization and capacity planning.