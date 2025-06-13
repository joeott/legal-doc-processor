"""
Comprehensive test suite for batch processing functionality.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from uuid import uuid4

from scripts.batch_tasks import (
    BatchTask, process_batch_high, process_batch_normal, process_batch_low,
    aggregate_batch_results, get_batch_status, submit_batch
)
from scripts.batch_recovery import (
    BatchRecoveryManager, recover_failed_batch, recover_single_document,
    analyze_batch_failures, ErrorCategory, RetryStrategy
)
from scripts.batch_metrics import (
    BatchMetricsCollector, record_batch_metric, collect_system_metrics
)
from scripts.cache_warmer import CacheWarmer, warm_batch_cache


class TestBatchTasks:
    """Test batch processing tasks."""
    
    @pytest.fixture
    def batch_task(self):
        """Create a BatchTask instance."""
        task = BatchTask()
        task.db_manager = Mock()
        task.request = Mock(id='test-task-id')
        return task
    
    @pytest.fixture
    def sample_batch_manifest(self):
        """Create a sample batch manifest."""
        return {
            'batch_id': str(uuid4()),
            'documents': [
                {'document_uuid': str(uuid4()), 'file_path': f'/path/doc{i}.pdf'}
                for i in range(5)
            ],
            'project_uuid': str(uuid4()),
            'options': {'warm_cache': True}
        }
    
    def test_batch_task_progress_update(self, batch_task):
        """Test batch progress update."""
        with patch('scripts.batch_tasks.get_redis_manager') as mock_redis:
            mock_manager = Mock()
            mock_redis.return_value = mock_manager
            
            batch_id = 'test-batch'
            update = {'status': 'processing', 'completed': 5}
            
            batch_task.update_batch_progress(batch_id, update)
            
            # Verify Redis operations
            mock_manager.get_dict.assert_called_once()
            mock_manager.store_dict.assert_called_once()
            
            # Check that timestamp was added
            stored_data = mock_manager.store_dict.call_args[0][1]
            assert 'last_updated' in stored_data
            assert stored_data['status'] == 'processing'
            assert stored_data['completed'] == 5
    
    def test_track_document_in_batch(self, batch_task):
        """Test document tracking in batch."""
        with patch('scripts.batch_tasks.get_redis_manager') as mock_redis:
            mock_manager = Mock()
            mock_redis.return_value = mock_manager
            
            batch_id = 'test-batch'
            doc_uuid = str(uuid4())
            status = 'completed'
            
            batch_task.track_document_in_batch(batch_id, doc_uuid, status)
            
            # Verify document tracking
            expected_key = f"batch:document:{batch_id}:{doc_uuid}"
            mock_manager.store_dict.assert_called_once()
            stored_data = mock_manager.store_dict.call_args[0][1]
            assert stored_data['status'] == status
            assert 'updated_at' in stored_data
    
    @patch('scripts.batch_tasks.warm_cache_before_batch')
    @patch('scripts.batch_tasks.process_pdf_document')
    @patch('scripts.batch_tasks.chord')
    def test_process_batch_high_priority(self, mock_chord, mock_process_pdf, 
                                       mock_warm_cache, sample_batch_manifest):
        """Test high priority batch processing."""
        # Setup mocks
        mock_warm_cache.return_value = {'status': 'completed'}
        mock_process_pdf.signature.return_value = Mock()
        mock_chord_result = Mock(id='chord-id')
        mock_chord.return_value.return_value = mock_chord_result
        
        # Create task instance
        task = process_batch_high
        task_instance = Mock()
        task_instance.update_batch_progress = Mock()
        
        # Process batch
        with patch.object(task, 'run', task._run):
            result = task.run(sample_batch_manifest, _self=task_instance)
        
        # Verify results
        assert result['status'] == 'submitted'
        assert result['priority'] == 'high'
        assert result['document_count'] == 5
        assert result['chord_id'] == 'chord-id'
        
        # Verify cache warming was called
        mock_warm_cache.assert_called_once()
        
        # Verify task signatures were created with high priority
        assert mock_process_pdf.signature.call_count == 5
        for call in mock_process_pdf.signature.call_args_list:
            assert call[1]['priority'] == 9
    
    def test_aggregate_batch_results(self, batch_task):
        """Test batch result aggregation."""
        results = [
            {'status': 'completed', 'document_uuid': 'doc1'},
            {'status': 'completed', 'document_uuid': 'doc2'},
            {'status': 'failed', 'document_uuid': 'doc3', 'error': 'Test error'},
            {'status': 'completed', 'document_uuid': 'doc4'},
        ]
        
        with patch.object(batch_task, 'update_batch_progress'):
            result = aggregate_batch_results.run(
                results, 'test-batch', 'normal', _self=batch_task
            )
        
        assert result['completed'] == 3
        assert result['failed'] == 1
        assert result['success_rate'] == 75.0
        assert len(result['errors']) == 1
        assert result['errors'][0]['error'] == 'Test error'
    
    def test_get_batch_status(self, batch_task):
        """Test batch status retrieval."""
        with patch('scripts.batch_tasks.get_redis_manager') as mock_redis:
            mock_manager = Mock()
            mock_redis.return_value = mock_manager
            
            # Setup batch data
            batch_data = {
                'batch_id': 'test-batch',
                'status': 'processing',
                'total': 10,
                'completed': 6,
                'failed': 1,
                'started_at': datetime.utcnow().isoformat()
            }
            mock_manager.get_dict.return_value = batch_data
            
            result = get_batch_status.run('test-batch', _self=batch_task)
            
            assert result['status'] == 'processing'
            assert result['progress_percentage'] == 70.0
            assert result['success_rate'] == 60.0
            assert 'estimated_time_remaining' in result
    
    def test_submit_batch_routing(self):
        """Test batch submission with priority routing."""
        documents = [{'document_uuid': str(uuid4()), 'file_path': '/path/doc.pdf'}]
        project_uuid = str(uuid4())
        
        # Test high priority routing
        with patch('scripts.batch_tasks.process_batch_high.apply_async') as mock_high:
            mock_high.return_value = Mock(id='task-id-high')
            result = submit_batch(documents, project_uuid, priority='high')
            
            assert result['priority'] == 'high'
            assert result['task_id'] == 'task-id-high'
            mock_high.assert_called_once()
        
        # Test normal priority routing
        with patch('scripts.batch_tasks.process_batch_normal.apply_async') as mock_normal:
            mock_normal.return_value = Mock(id='task-id-normal')
            result = submit_batch(documents, project_uuid, priority='normal')
            
            assert result['priority'] == 'normal'
            assert result['task_id'] == 'task-id-normal'
            mock_normal.assert_called_once()


class TestBatchRecovery:
    """Test batch recovery functionality."""
    
    @pytest.fixture
    def recovery_manager(self):
        """Create a BatchRecoveryManager instance."""
        manager = BatchRecoveryManager()
        manager.db_manager = Mock()
        manager.redis_manager = Mock()
        return manager
    
    def test_error_categorization(self, recovery_manager):
        """Test error categorization logic."""
        # Test transient errors
        assert recovery_manager.categorize_error("ConnectionError: timeout") == ErrorCategory.TRANSIENT
        assert recovery_manager.categorize_error("NetworkError") == ErrorCategory.TRANSIENT
        
        # Test resource errors
        assert recovery_manager.categorize_error("MemoryError") == ErrorCategory.RESOURCE
        assert recovery_manager.categorize_error("OutOfMemory") == ErrorCategory.RESOURCE
        
        # Test rate limit errors
        assert recovery_manager.categorize_error("RateLimitExceeded") == ErrorCategory.RATE_LIMIT
        assert recovery_manager.categorize_error("429 Too Many Requests") == ErrorCategory.RATE_LIMIT
        
        # Test configuration errors
        assert recovery_manager.categorize_error("InvalidCredentials") == ErrorCategory.CONFIGURATION
        assert recovery_manager.categorize_error("MissingAPIKey") == ErrorCategory.CONFIGURATION
        
        # Test data errors
        assert recovery_manager.categorize_error("CorruptFile") == ErrorCategory.DATA
        assert recovery_manager.categorize_error("InvalidFormat") == ErrorCategory.DATA
        
        # Test unknown errors
        assert recovery_manager.categorize_error("Unknown error") == ErrorCategory.PERMANENT
    
    def test_retry_strategy_determination(self, recovery_manager):
        """Test retry strategy determination."""
        # Transient errors - immediate retry for first attempts
        strategy, delay = recovery_manager.determine_retry_strategy(ErrorCategory.TRANSIENT, 1)
        assert strategy == RetryStrategy.IMMEDIATE
        assert delay == 0
        
        # Transient errors - exponential backoff for later attempts
        strategy, delay = recovery_manager.determine_retry_strategy(ErrorCategory.TRANSIENT, 4)
        assert strategy == RetryStrategy.EXPONENTIAL
        assert delay == 4  # 2^(4-2)
        
        # Resource errors - linear backoff
        strategy, delay = recovery_manager.determine_retry_strategy(ErrorCategory.RESOURCE, 2)
        assert strategy == RetryStrategy.LINEAR
        assert delay == 180  # 3 minutes
        
        # Rate limit errors - exponential with cap
        strategy, delay = recovery_manager.determine_retry_strategy(ErrorCategory.RATE_LIMIT, 3)
        assert strategy == RetryStrategy.EXPONENTIAL
        assert delay <= 3600  # Max 1 hour
        
        # Data errors - manual intervention
        strategy, delay = recovery_manager.determine_retry_strategy(ErrorCategory.DATA, 1)
        assert strategy == RetryStrategy.MANUAL
        assert delay == 0
    
    @patch('scripts.batch_recovery.get_redis_manager')
    def test_get_failed_documents(self, mock_redis, recovery_manager):
        """Test retrieval of failed documents."""
        mock_client = Mock()
        mock_redis.return_value.get_client.return_value = mock_client
        
        # Setup mock data
        failed_keys = [
            'batch:document:test-batch:doc1',
            'batch:document:test-batch:doc2'
        ]
        mock_client.scan_iter.return_value = failed_keys
        
        mock_redis.return_value.get_dict.side_effect = [
            {'status': 'failed'},  # doc1
            {'status': 'completed'},  # doc2 (not failed)
            {'error_message': 'Test error', 'retry_count': 2},  # doc1 error
            None  # doc2 error (not found)
        ]
        
        result = recovery_manager.get_failed_documents('test-batch')
        
        assert len(result) == 1
        assert result[0]['document_uuid'] == 'doc1'
        assert result[0]['error'] == 'Test error'
        assert result[0]['retry_count'] == 2
    
    @patch('scripts.batch_recovery.recover_single_document')
    @patch('scripts.batch_recovery.aggregate_recovery_results')
    @patch('scripts.batch_recovery.chord')
    def test_recover_failed_batch(self, mock_chord, mock_aggregate, 
                                mock_recover_single, recovery_manager):
        """Test batch recovery process."""
        # Setup mocks
        recovery_manager.get_failed_documents = Mock(return_value=[
            {
                'document_uuid': 'doc1',
                'error': 'ConnectionError',
                'error_type': 'ConnectionError',
                'retry_count': 1
            },
            {
                'document_uuid': 'doc2',
                'error': 'CorruptFile',
                'error_type': 'DataError',
                'retry_count': 1
            }
        ])
        
        mock_chord_result = Mock(id='recovery-chord-id')
        mock_chord.return_value.return_value = mock_chord_result
        
        # Test recovery with retry_all=False (should skip data error)
        with patch('scripts.batch_recovery.get_redis_manager'):
            result = recover_failed_batch.run(
                'test-batch', 
                {'max_retries': 3, 'retry_all': False},
                _self=recovery_manager
            )
        
        assert result['status'] == 'submitted'
        assert result['documents_to_retry'] == 1  # Only transient error
        assert result['skipped_documents'] == 1  # Data error skipped
    
    def test_analyze_batch_failures(self, recovery_manager):
        """Test batch failure analysis."""
        recovery_manager.get_failed_documents = Mock(return_value=[
            {'error': 'ConnectionError', 'error_type': 'ConnectionError', 'stage': 'ocr'},
            {'error': 'ConnectionError', 'error_type': 'ConnectionError', 'stage': 'ocr'},
            {'error': 'RateLimitExceeded', 'error_type': 'RateLimitError', 'stage': 'entity'},
            {'error': 'MemoryError', 'error_type': 'MemoryError', 'stage': 'chunking'},
        ])
        
        result = analyze_batch_failures.run('test-batch', _self=recovery_manager)
        
        assert result['total_failures'] == 4
        assert result['failure_analysis']['by_category'][ErrorCategory.TRANSIENT.value] == 2
        assert result['failure_analysis']['by_category'][ErrorCategory.RATE_LIMIT.value] == 1
        assert result['failure_analysis']['by_category'][ErrorCategory.RESOURCE.value] == 1
        assert result['failure_analysis']['by_stage']['ocr'] == 2
        assert result['recoverable_count'] == 3  # All except resource error
        assert len(result['recommendations']) > 0


class TestBatchMetrics:
    """Test batch metrics collection."""
    
    @pytest.fixture
    def metrics_collector(self):
        """Create a BatchMetricsCollector instance."""
        with patch('scripts.batch_metrics.get_redis_manager'):
            return BatchMetricsCollector()
    
    def test_record_batch_start(self, metrics_collector):
        """Test batch start metric recording."""
        batch_id = 'test-batch'
        priority = 'high'
        doc_count = 10
        
        with patch.object(metrics_collector.redis_manager, 'get_client') as mock_client:
            metrics_collector.record_batch_start(batch_id, priority, doc_count)
            
            # Verify sorted set operation
            mock_client.return_value.zadd.assert_called_once()
            mock_client.return_value.expire.assert_called_once()
            
            # Verify batch details storage
            metrics_collector.redis_manager.store_dict.assert_called_once()
            stored_data = metrics_collector.redis_manager.store_dict.call_args[0][1]
            assert stored_data['priority'] == priority
            assert stored_data['document_count'] == doc_count
            assert stored_data['status'] == 'started'
    
    def test_record_batch_complete(self, metrics_collector):
        """Test batch completion metric recording."""
        batch_id = 'test-batch'
        completed = 8
        failed = 2
        duration = 120.5
        
        # Setup existing batch data
        metrics_collector.redis_manager.get_dict.return_value = {
            'start_time': 1234567890,
            'priority': 'normal',
            'document_count': 10
        }
        
        with patch.object(metrics_collector.redis_manager, 'get_client') as mock_client:
            metrics_collector.record_batch_complete(batch_id, completed, failed, duration)
            
            # Verify metrics recorded
            mock_client.return_value.zadd.assert_called_once()
            
            # Verify batch details updated
            assert metrics_collector.redis_manager.store_dict.call_count == 1
            updated_data = metrics_collector.redis_manager.store_dict.call_args[0][1]
            assert updated_data['completed'] == completed
            assert updated_data['failed'] == failed
            assert updated_data['success_rate'] == 80.0
            assert updated_data['throughput_per_minute'] == 5.0  # 10 docs / 2 minutes
    
    def test_get_batch_metrics(self, metrics_collector):
        """Test batch metrics aggregation."""
        start_time = datetime.utcnow()
        end_time = datetime.utcnow()
        
        # Mock metric collection
        with patch.object(metrics_collector, '_collect_metrics') as mock_collect:
            mock_collect.side_effect = [
                # Batch starts
                [
                    {'priority': 'high', 'document_count': 10},
                    {'priority': 'normal', 'document_count': 20},
                    {'priority': 'high', 'document_count': 5}
                ],
                # Batch completes
                [
                    {'batch_id': 'b1', 'completed': 8, 'failed': 2, 'duration_seconds': 100},
                    {'batch_id': 'b2', 'completed': 18, 'failed': 2, 'duration_seconds': 200}
                ]
            ]
            
            # Mock batch details
            metrics_collector.redis_manager.get_dict.side_effect = [
                {'priority': 'high'},
                {'priority': 'normal'}
            ]
            
            result = metrics_collector.get_batch_metrics(start_time, end_time)
            
            assert result['summary']['total_batches'] == 3
            assert result['summary']['total_documents'] == 35
            assert result['summary']['total_completed'] == 26
            assert result['summary']['total_failed'] == 4
            assert result['by_priority']['high']['count'] == 2
            assert result['by_priority']['normal']['count'] == 1
    
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('socket.gethostname')
    def test_collect_system_metrics(self, mock_hostname, mock_memory, mock_cpu):
        """Test system metrics collection."""
        mock_hostname.return_value = 'test-worker'
        mock_cpu.return_value = 45.5
        mock_memory.return_value = Mock(used=1024*1024*1024)  # 1GB
        
        with patch('scripts.batch_metrics.get_metrics_collector') as mock_get_collector:
            mock_collector = Mock()
            mock_get_collector.return_value = mock_collector
            
            result = collect_system_metrics()
            
            assert result['hostname'] == 'test-worker'
            assert result['cpu_percent'] == 45.5
            assert result['memory_mb'] == 1024.0
            
            # Verify metrics recorded
            mock_collector.record_resource_usage.assert_called_once_with(
                worker_id='test-worker',
                cpu_percent=45.5,
                memory_mb=1024.0,
                active_tasks=0  # Mocked as 0
            )


class TestCacheWarmer:
    """Test cache warming functionality."""
    
    @pytest.fixture
    def cache_warmer(self):
        """Create a CacheWarmer instance."""
        with patch('scripts.cache_warmer.get_redis_manager'):
            with patch('scripts.cache_warmer.DatabaseManager'):
                return CacheWarmer()
    
    def test_analyze_batch_access_patterns(self, cache_warmer):
        """Test access pattern analysis."""
        batch_manifest = {
            'project_uuid': 'proj-123',
            'documents': [
                {'document_uuid': 'doc-1', 'file_path': '/path/1.pdf'},
                {'document_uuid': 'doc-2', 'file_path': '/path/2.pdf'}
            ],
            'options': {'entity_resolution': True}
        }
        
        patterns = cache_warmer.analyze_batch_access_patterns(batch_manifest)
        
        assert 'proj-123' in patterns['projects']
        assert 'doc-1' in patterns['documents']
        assert 'doc-2' in patterns['documents']
        assert patterns['entities'] == 'frequent'
        assert patterns['canonical_entities'] == 'frequent'
    
    def test_estimate_cache_size(self, cache_warmer):
        """Test cache size estimation."""
        patterns = {
            'projects': {'proj1', 'proj2'},
            'documents': {'doc1', 'doc2', 'doc3'},
            'chunks': {'doc1', 'doc2', 'doc3'},
            'entities': 'frequent'
        }
        
        estimates = cache_warmer.estimate_cache_size(patterns)
        
        assert estimates['projects'] == 2 * 1024  # 2KB
        assert estimates['documents'] == 3 * 2048  # 6KB
        assert estimates['chunks'] == 3 * 20 * 512  # ~30KB for chunks
        assert estimates['entities'] == 1000 * 256  # 256KB for top entities
        assert estimates['total_mb'] > 0
    
    @patch('scripts.cache_warmer.warm_batch_cache')
    def test_warm_cache_integration(self, mock_warm_task):
        """Test cache warming integration."""
        from scripts.cache_warmer import warm_cache_before_batch
        
        batch_manifest = {'batch_id': 'test-batch'}
        mock_task_result = Mock()
        mock_task_result.get.return_value = {'status': 'completed'}
        mock_warm_task.apply_async.return_value = mock_task_result
        
        # Test synchronous warming
        result = warm_cache_before_batch(batch_manifest, wait=True)
        assert result['status'] == 'completed'
        mock_task_result.get.assert_called_once_with(timeout=60)
        
        # Test asynchronous warming
        result = warm_cache_before_batch(batch_manifest, wait=False)
        assert result is None
        mock_warm_task.apply_async.call_count == 2


class TestBatchProcessingIntegration:
    """Integration tests for batch processing."""
    
    @patch('scripts.batch_tasks.process_pdf_document')
    @patch('scripts.batch_tasks.warm_cache_before_batch')
    @patch('scripts.batch_metrics.record_batch_metric')
    def test_end_to_end_batch_processing(self, mock_metric, mock_warm, mock_process):
        """Test end-to-end batch processing flow."""
        # Setup mocks
        mock_warm.return_value = {'status': 'completed'}
        mock_process.signature.return_value = Mock()
        
        # Submit batch
        documents = [
            {'document_uuid': f'doc-{i}', 'file_path': f'/path/doc{i}.pdf'}
            for i in range(3)
        ]
        
        with patch('scripts.batch_tasks.chord') as mock_chord:
            mock_chord_result = Mock(id='chord-123')
            mock_chord.return_value.return_value = mock_chord_result
            
            result = submit_batch(
                documents=documents,
                project_uuid='proj-123',
                priority='normal',
                options={'warm_cache': True}
            )
            
            assert result['document_count'] == 3
            assert result['priority'] == 'normal'
            assert 'batch_id' in result
            assert 'task_id' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])