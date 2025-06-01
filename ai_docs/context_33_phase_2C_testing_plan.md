# Phase 2C Testing Plan: queue_processor.py

## Overview
Phase 2C focuses on comprehensive testing of the `queue_processor.py` module, which manages the document processing queue with batch processing, retry logic, and stalled document detection. This module is critical for reliable, scalable document processing.

## Module Analysis

### Key Components in queue_processor.py
1. **QueueProcessor Class**:
   - `__init__`: Initializes processor with batch size, timeout, and unique processor ID
   - `claim_pending_documents`: Claims pending documents from queue with optimistic locking
   - `_process_claimed_documents`: Prepares claimed documents for processing
   - `mark_queue_item_failed`: Marks queue items as failed with error handling
   - `check_for_stalled_documents`: Detects and resets/fails stalled documents
   - `process_queue`: Main processing loop with batch handling

2. **Dependencies**:
   - SupabaseManager for database operations
   - main_pipeline.process_single_document for actual processing
   - S3FileManager for optional S3 integration
   - Configuration from config.py

3. **Key Features**:
   - Batch processing with configurable size
   - Retry logic with max attempts (default 3)
   - Stalled document detection and recovery
   - S3 file download support
   - Unique processor ID for distributed processing
   - Graceful shutdown on KeyboardInterrupt

## Testing Strategy

### Test Categories
1. **Queue Management Tests** (8 tests)
   - Document claiming with optimistic locking
   - Batch size enforcement
   - Priority and order handling
   - Concurrent processor safety

2. **Error Handling Tests** (5 tests)
   - Failed document marking
   - Retry count management
   - Error message truncation
   - Database error recovery

3. **Stalled Document Tests** (4 tests)
   - Stalled document detection
   - Reset vs fail logic based on retry count
   - Processor metadata handling
   - Timeout calculations

4. **Processing Flow Tests** (4 tests)
   - Complete processing workflow
   - S3 download integration
   - Single run vs continuous mode
   - Max documents limit

5. **Edge Cases & Integration** (4 tests)
   - Empty queue handling
   - Keyboard interrupt handling
   - Database trigger interactions
   - Cleanup operations

**Total Target: 25 tests** (exceeding the 15 test minimum)

## Detailed Test Plan

### 1. Queue Management Tests (test_queue_management)

#### Test 1.1: test_claim_pending_documents_success
- **Purpose**: Verify successful claiming of pending documents
- **Setup**: Mock DB with 10 pending documents
- **Verify**: Correct number claimed, status updated to 'processing'

#### Test 1.2: test_claim_respects_batch_size
- **Purpose**: Ensure batch size limit is enforced
- **Setup**: Mock DB with 20 pending docs, batch_size=5
- **Verify**: Only 5 documents claimed

#### Test 1.3: test_claim_respects_priority_order
- **Purpose**: Verify priority and creation order
- **Setup**: Documents with different priorities
- **Verify**: Claimed in correct order

#### Test 1.4: test_claim_skips_high_retry_count
- **Purpose**: Skip documents with retry_count >= 3
- **Setup**: Mix of documents with various retry counts
- **Verify**: High retry documents not claimed

#### Test 1.5: test_concurrent_claim_safety
- **Purpose**: Test optimistic locking prevents double claiming
- **Setup**: Simulate concurrent update failure
- **Verify**: Document skipped, no error raised

#### Test 1.6: test_process_claimed_documents_with_s3
- **Purpose**: Test S3 download integration
- **Setup**: Mock S3 manager and file operations
- **Verify**: Files downloaded, paths updated

#### Test 1.7: test_process_claimed_missing_source_doc
- **Purpose**: Handle missing source document
- **Setup**: Claimed doc with invalid source_document_id
- **Verify**: Queue item marked failed

#### Test 1.8: test_process_claimed_s3_download_failure
- **Purpose**: Handle S3 download errors
- **Setup**: Mock S3 download to raise exception
- **Verify**: Queue item marked failed, error logged

### 2. Error Handling Tests (test_error_handling)

#### Test 2.1: test_mark_queue_item_failed_basic
- **Purpose**: Verify basic failure marking
- **Setup**: Valid queue item
- **Verify**: Status='failed', error message saved

#### Test 2.2: test_mark_failed_with_source_doc_update
- **Purpose**: Test source document status update
- **Setup**: Queue item with source_doc_sql_id
- **Verify**: Both queue and source doc updated

#### Test 2.3: test_mark_failed_error_message_truncation
- **Purpose**: Ensure long errors are truncated
- **Setup**: 3000+ character error message
- **Verify**: Truncated to 2000 chars

#### Test 2.4: test_mark_failed_database_error_recovery
- **Purpose**: Handle DB errors during failure marking
- **Setup**: Mock DB to raise exception
- **Verify**: Exception logged, no crash

#### Test 2.5: test_project_creation_failure
- **Purpose**: Handle project creation errors
- **Setup**: Mock get_or_create_project to fail
- **Verify**: Empty list returned, error logged

### 3. Stalled Document Tests (test_stalled_documents)

#### Test 3.1: test_detect_stalled_documents
- **Purpose**: Identify stalled documents correctly
- **Setup**: Docs with old started_at timestamps
- **Verify**: Correct documents identified

#### Test 3.2: test_reset_stalled_under_max_retries
- **Purpose**: Reset stalled docs with retries left
- **Setup**: Stalled doc with retry_count=1
- **Verify**: Status='pending', metadata cleared

#### Test 3.3: test_fail_stalled_at_max_retries
- **Purpose**: Fail stalled docs at max retries
- **Setup**: Stalled doc with retry_count=3
- **Verify**: Status='failed', error message set

#### Test 3.4: test_stalled_processor_metadata_handling
- **Purpose**: Extract processor info from metadata
- **Setup**: Various metadata formats
- **Verify**: Processor ID correctly extracted

### 4. Processing Flow Tests (test_processing_flow)

#### Test 4.1: test_complete_processing_workflow
- **Purpose**: End-to-end processing success
- **Setup**: Mock all dependencies for success
- **Verify**: Document processed, no errors

#### Test 4.2: test_single_run_mode
- **Purpose**: Verify single batch processing
- **Setup**: Queue with multiple batches, single_run=True
- **Verify**: Process one batch then exit

#### Test 4.3: test_max_documents_limit
- **Purpose**: Respect max documents limit
- **Setup**: Queue with 10 docs, max_documents=3
- **Verify**: Only 3 documents processed

#### Test 4.4: test_continuous_mode_empty_queue
- **Purpose**: Handle empty queue in continuous mode
- **Setup**: Empty queue, mock sleep
- **Verify**: Sleep called, continue loop

### 5. Edge Cases & Integration Tests (test_edge_cases)

#### Test 5.1: test_keyboard_interrupt_handling
- **Purpose**: Graceful shutdown on interrupt
- **Setup**: Raise KeyboardInterrupt during processing
- **Verify**: Proper cleanup, log message

#### Test 5.2: test_s3_file_cleanup
- **Purpose**: Verify temp file cleanup
- **Setup**: Mock S3 file operations
- **Verify**: Temp files removed after processing

#### Test 5.3: test_database_trigger_integration
- **Purpose**: Verify trigger-based status updates
- **Setup**: Mock process_single_document success
- **Verify**: No manual queue update needed

#### Test 5.4: test_command_line_argument_parsing
- **Purpose**: Test CLI argument handling
- **Setup**: Mock argparse with various args
- **Verify**: Correct configuration applied

## Implementation Guidelines

### Mock Strategy
```python
# Key mocks needed:
- SupabaseManager (client, methods)
- S3FileManager (download_file)
- process_single_document
- datetime.now() for time-based tests
- os.path.exists, os.remove for file ops
- socket.gethostname, uuid.uuid4
```

### Test Fixtures
```python
@pytest.fixture
def mock_queue_processor():
    """Create QueueProcessor with all dependencies mocked"""
    with patch('queue_processor.SupabaseManager') as mock_db:
        with patch('queue_processor.S3FileManager') as mock_s3:
            with patch('queue_processor.process_single_document') as mock_process:
                processor = QueueProcessor(batch_size=5)
                yield processor, mock_db, mock_s3, mock_process

@pytest.fixture
def sample_queue_items():
    """Generate sample queue items for testing"""
    return [
        {
            'id': i,
            'source_document_id': 100 + i,
            'source_document_uuid': f'uuid-{i}',
            'status': 'pending',
            'retry_count': 0,
            'priority': i % 3,
            'created_at': '2024-01-01T00:00:00'
        }
        for i in range(1, 11)
    ]
```

### Common Test Patterns
1. **Time-based testing**: Mock datetime.now() for consistent timestamps
2. **Database responses**: Use Supabase response format with .data attribute
3. **Error simulation**: Test both exceptions and empty responses
4. **Cleanup verification**: Check file removal and resource cleanup

## Success Criteria
- All 25 tests implemented and passing
- 100% code coverage for queue_processor.py
- Proper mocking without external dependencies
- Clear test documentation and assertions
- Edge cases and error scenarios covered

## Timeline
- Test implementation: 2-3 hours
- Debugging and refinement: 1 hour
- Documentation: 30 minutes
- Total estimated: 3.5-4 hours

## Next Steps After Phase 2C
1. Integration testing with main_pipeline.py
2. Performance testing with large queues
3. Stress testing for concurrent processors
4. End-to-end system testing with all components