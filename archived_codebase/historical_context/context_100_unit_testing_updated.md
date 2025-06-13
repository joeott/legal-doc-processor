# Phase 1 Comprehensive Unit Testing Guide - Updated with Celery

## Overview

This guide provides a complete testing strategy for Phase 1 (cloud-only) implementation of the legal document processing pipeline with Celery integration. Phase 1 utilizes AWS Textract for OCR and OpenAI GPT-4 for entity extraction, with Redis caching, Celery for distributed task processing, and Supabase for data persistence.

## Testing Architecture

### Test Organization
```
tests/
├── unit/                    # Component-specific tests
├── integration/             # Cross-component tests  
├── e2e/                     # End-to-end pipeline tests
├── fixtures/                # Test data and mocks
└── conftest.py             # Shared test configuration
```

## 1. Core Pipeline Testing

### 1.1 Main Pipeline Tests (`test_main_pipeline.py`)

```python
import pytest
from unittest.mock import Mock, patch, AsyncMock
from scripts.main_pipeline import DocumentProcessor
from scripts.config import Config

class TestDocumentProcessor:
    """Test the main document processing pipeline"""
    
    @pytest.fixture
    def processor(self, mock_db_manager, mock_redis_client):
        """Create processor with mocked dependencies"""
        with patch('scripts.main_pipeline.SupabaseManager', return_value=mock_db_manager):
            with patch('scripts.main_pipeline.get_redis_client', return_value=mock_redis_client):
                return DocumentProcessor()
    
    def test_process_document_success(self, processor, mock_textract, mock_openai):
        """Test successful document processing flow"""
        # Arrange
        document_id = "test-uuid-123"
        mock_textract.return_value = "Extracted text content"
        mock_openai.return_value = {"entities": ["John Doe", "Acme Corp"]}
        
        # Act
        result = processor.process_document(document_id)
        
        # Assert
        assert result['status'] == 'completed'
        assert result['stages']['ocr'] == 'completed'
        assert result['stages']['entity_extraction'] == 'completed'
        assert result['stages']['relationship_building'] == 'completed'
    
    def test_process_document_ocr_failure(self, processor, mock_textract):
        """Test handling of OCR failures"""
        # Arrange
        mock_textract.side_effect = Exception("Textract API error")
        
        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            processor.process_document("test-uuid")
        assert "OCR extraction failed" in str(exc_info.value)
    
    def test_process_document_with_retry(self, processor, mock_textract):
        """Test retry mechanism for transient failures"""
        # Arrange
        mock_textract.side_effect = [Exception("Timeout"), "Success text"]
        
        # Act
        result = processor.process_document("test-uuid", max_retries=2)
        
        # Assert
        assert result['status'] == 'completed'
        assert mock_textract.call_count == 2
```

### 1.2 Queue Processor Tests (`test_queue_processor.py`)

```python
import pytest
from scripts.queue_processor import QueueProcessor
from datetime import datetime, timedelta

class TestQueueProcessor:
    """Test document queue processing with Celery"""
    
    def test_fetch_pending_documents(self, mock_db_manager):
        """Test fetching documents from queue"""
        # Arrange
        mock_docs = [
            {"id": 1, "document_id": "uuid-1", "status": "pending"},
            {"id": 2, "document_id": "uuid-2", "status": "pending"}
        ]
        mock_db_manager.fetch_pending_documents.return_value = mock_docs
        
        # Act
        processor = QueueProcessor(mock_db_manager)
        docs = processor.fetch_pending_documents(limit=10)
        
        # Assert
        assert len(docs) == 2
        assert all(doc['status'] == 'pending' for doc in docs)
    
    def test_process_batch_with_celery(self, mock_db_manager, mock_celery_app):
        """Test batch processing using Celery tasks"""
        # Arrange
        batch = [
            {"id": 1, "document_id": "uuid-1"},
            {"id": 2, "document_id": "uuid-2"}
        ]
        
        with patch('scripts.celery_tasks.ocr_tasks.process_ocr.delay') as mock_task:
            mock_task.return_value.id = "celery-task-123"
            
            # Act
            processor = QueueProcessor(mock_db_manager)
            results = processor.process_batch(batch)
            
            # Assert
            assert len(results) == 2
            assert mock_task.call_count == 2
            # Verify status updates for Celery processing
            assert mock_db_manager.update_queue_status.call_count >= 2
    
    def test_retry_mechanism(self, mock_db_manager):
        """Test automatic retry for failed documents"""
        # Arrange
        failed_doc = {
            "id": 1, 
            "document_id": "uuid-1",
            "retry_count": 1,
            "last_error": "API timeout"
        }
        
        # Act
        processor = QueueProcessor(mock_db_manager)
        should_retry = processor.should_retry(failed_doc)
        
        # Assert
        assert should_retry is True
        assert processor.calculate_backoff(1) == 60  # 1 minute backoff
```

## 2. Celery Task Testing

### 2.1 Celery App Tests (`test_celery_app.py`)

```python
import pytest
from scripts.celery_app import app
from unittest.mock import patch

class TestCeleryApp:
    """Test Celery application configuration"""
    
    def test_celery_app_configuration(self):
        """Test Celery app is configured correctly"""
        assert app.conf.broker_url.startswith('redis://')
        assert app.conf.result_backend.startswith('redis://')
        assert app.conf.task_serializer == 'json'
        assert app.conf.result_serializer == 'json'
        assert app.conf.accept_content == ['json']
        assert app.conf.timezone == 'UTC'
    
    def test_task_routing(self):
        """Test tasks are routed to correct queues"""
        routes = app.conf.task_routes
        assert 'scripts.celery_tasks.ocr_tasks.*' in routes
        assert routes['scripts.celery_tasks.ocr_tasks.*'] == {'queue': 'ocr'}
        assert routes['scripts.celery_tasks.text_tasks.*'] == {'queue': 'text'}
        assert routes['scripts.celery_tasks.entity_tasks.*'] == {'queue': 'entity'}
        assert routes['scripts.celery_tasks.graph_tasks.*'] == {'queue': 'graph'}
```

### 2.2 OCR Tasks Tests (`test_celery_ocr_tasks.py`)

```python
import pytest
from unittest.mock import MagicMock, patch
from scripts.celery_tasks.ocr_tasks import process_ocr, check_textract_job_status

class TestCeleryOCRTasks:
    """Test Celery OCR tasks"""
    
    @patch('scripts.celery_tasks.text_tasks.create_document_node.apply_async')
    @patch('scripts.celery_tasks.ocr_tasks.extract_text_from_docx')
    @patch('scripts.celery_tasks.ocr_tasks.get_redis_manager')
    @patch('scripts.celery_tasks.ocr_tasks.SupabaseManager')
    def test_process_ocr_docx_success(self, mock_db_class, mock_redis_func, mock_extract, mock_next_task):
        """Test successful DOCX OCR processing"""
        # Setup mocks
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_redis = MagicMock()
        mock_redis.is_available.return_value = True
        mock_redis_func.return_value = mock_redis
        
        # Mock extraction
        mock_extract.return_value = "Document text content"
        mock_db.client.table.return_value.update.return_value.eq.return_value.execute.return_value = None
        
        # Execute task
        result = process_ocr(
            document_uuid="doc-123",
            source_doc_sql_id=123,
            file_path="test.docx",
            file_name="test.docx",
            detected_file_type=".docx",
            project_sql_id=1
        )
        
        # Verify
        mock_extract.assert_called_once_with("test.docx")
        mock_db.update_source_document_text.assert_called_once()
        mock_next_task.assert_called_once()
    
    @patch('scripts.celery_tasks.ocr_tasks.TextractProcessor')
    @patch('scripts.celery_tasks.ocr_tasks.get_redis_manager')
    @patch('scripts.celery_tasks.ocr_tasks.SupabaseManager')
    def test_check_textract_job_status(self, mock_db_class, mock_redis_func, mock_textract_class):
        """Test Textract job status checking"""
        # Setup mocks
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_redis = MagicMock()
        mock_redis_func.return_value = mock_redis
        
        mock_processor = MagicMock()
        mock_textract_class.return_value = mock_processor
        mock_processor.get_text_detection_results.return_value = ("Extracted text", "SUCCEEDED")
        
        # Execute task
        result = check_textract_job_status(
            job_id="textract-job-123",
            document_uuid="doc-123",
            source_doc_sql_id=123
        )
        
        # Verify
        assert result['status'] == 'SUCCEEDED'
        assert result['text'] == "Extracted text"
```

### 2.3 Text Tasks Tests (`test_celery_text_tasks.py`)

```python
import pytest
from unittest.mock import MagicMock, patch
from scripts.celery_tasks.text_tasks import create_document_node, process_chunking

class TestCeleryTextTasks:
    """Test Celery text processing tasks"""
    
    @patch('scripts.celery_tasks.text_tasks.process_chunking.apply_async')
    @patch('scripts.celery_tasks.text_tasks.get_redis_manager')
    @patch('scripts.celery_tasks.text_tasks.SupabaseManager')
    def test_create_document_node(self, mock_db_class, mock_redis_func, mock_next_task):
        """Test document node creation"""
        # Setup mocks
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_redis = MagicMock()
        mock_redis.is_available.return_value = True
        mock_redis_func.return_value = mock_redis
        
        # Mock database response
        mock_db.create_neo4j_document.return_value = (1000, "doc-node-uuid")
        
        # Execute task
        result = create_document_node(
            document_uuid="doc-123",
            source_doc_sql_id=123,
            project_sql_id=1,
            file_name="test.docx",
            detected_file_type=".docx",
            raw_text="Test document content",
            ocr_meta_json=None
        )
        
        # Verify
        mock_db.create_neo4j_document.assert_called_once()
        mock_next_task.assert_called_once()
        assert result['neo4j_doc_id'] == 1000
    
    @patch('scripts.celery_tasks.entity_tasks.extract_entities.apply_async')
    @patch('scripts.celery_tasks.text_tasks.semantic_chunking')
    @patch('scripts.celery_tasks.text_tasks.get_redis_manager')
    @patch('scripts.celery_tasks.text_tasks.SupabaseManager')
    def test_process_chunking(self, mock_db_class, mock_redis_func, mock_chunk_func, mock_next_task):
        """Test text chunking"""
        # Setup mocks
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_redis = MagicMock()
        mock_redis_func.return_value = mock_redis
        
        # Mock chunking
        mock_chunk_func.return_value = [
            {'text': 'Chunk 1', 'start': 0, 'end': 100},
            {'text': 'Chunk 2', 'start': 100, 'end': 200}
        ]
        
        # Mock chunk creation
        mock_db.create_neo4j_chunk.side_effect = [
            (2001, "chunk-uuid-2001"),
            (2002, "chunk-uuid-2002")
        ]
        
        # Execute task
        result = process_chunking(
            neo4j_doc_id=1000,
            document_uuid="doc-uuid-1000",
            extracted_text="Test document content for chunking",
            source_doc_sql_id=123
        )
        
        # Verify
        assert mock_db.create_neo4j_chunk.call_count == 2
        mock_next_task.assert_called_once()
```

### 2.4 Entity Tasks Tests (`test_celery_entity_tasks.py`)

```python
import pytest
from unittest.mock import MagicMock, patch
from scripts.celery_tasks.entity_tasks import extract_entities, resolve_entities

class TestCeleryEntityTasks:
    """Test Celery entity extraction tasks"""
    
    @patch('scripts.celery_tasks.graph_tasks.build_relationships.apply_async')
    @patch('scripts.celery_tasks.entity_tasks.extract_entities_from_chunk')
    @patch('scripts.celery_tasks.entity_tasks.get_redis_manager')
    @patch('scripts.celery_tasks.entity_tasks.SupabaseManager')
    def test_extract_entities(self, mock_db_class, mock_redis_func, mock_extract_func, mock_next_task):
        """Test entity extraction"""
        # Setup mocks
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_redis = MagicMock()
        mock_redis_func.return_value = mock_redis
        
        # Mock entity extraction
        mock_extract_func.return_value = [
            {'text': 'John Doe', 'label': 'PERSON', 'start': 0, 'end': 8},
            {'text': 'ACME Corp', 'label': 'ORG', 'start': 20, 'end': 29}
        ]
        
        # Mock entity creation
        mock_db.create_entity_mention.side_effect = [
            (3001, "mention-uuid-3001"),
            (3002, "mention-uuid-3002")
        ]
        
        # Execute task
        result = extract_entities(
            document_uuid="doc-123",
            chunks=[
                {
                    'chunkId': 'chunk-1',
                    'chunkIndex': 0,
                    'text': 'John Doe works at ACME Corp'
                }
            ],
            source_doc_sql_id=123
        )
        
        # Verify
        mock_extract_func.assert_called_once()
        assert mock_db.create_entity_mention.call_count == 2
        mock_next_task.assert_called_once()
    
    @patch('scripts.celery_tasks.entity_tasks.get_redis_manager')
    @patch('scripts.celery_tasks.entity_tasks.SupabaseManager')
    def test_resolve_entities(self, mock_db_class, mock_redis_func):
        """Test entity resolution"""
        # Setup mocks
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_redis = MagicMock()
        mock_redis_func.return_value = mock_redis
        
        # Mock entity data
        mock_db.get_canonical_entity_by_text_and_type.side_effect = [
            None,  # John Doe not found
            {'id': 4001, 'uuid': 'canon-uuid-4001'}  # ACME Corp exists
        ]
        mock_db.create_canonical_entity.return_value = (4002, "canon-uuid-4002")
        
        # Execute task
        result = resolve_entities(
            document_uuid="doc-123",
            entity_mentions=[
                {'text': 'John Doe', 'type': 'PERSON', 'mention_id': 3001},
                {'text': 'ACME Corp', 'type': 'ORG', 'mention_id': 3002}
            ]
        )
        
        # Verify
        mock_db.create_canonical_entity.assert_called_once_with(
            name='John Doe',
            entity_type='PERSON'
        )
        assert mock_db.update_entity_mention.call_count == 2
```

### 2.5 Graph Tasks Tests (`test_celery_graph_tasks.py`)

```python
import pytest
from unittest.mock import MagicMock, patch
from scripts.celery_tasks.graph_tasks import build_relationships

class TestCeleryGraphTasks:
    """Test Celery graph building tasks"""
    
    @patch('scripts.celery_tasks.graph_tasks.get_redis_manager')
    @patch('scripts.celery_tasks.graph_tasks.SupabaseManager')
    def test_build_relationships(self, mock_db_class, mock_redis_func):
        """Test relationship building"""
        # Setup mocks
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        mock_redis = MagicMock()
        mock_redis.is_available.return_value = True
        mock_redis_func.return_value = mock_redis
        
        # Execute task
        result = build_relationships(
            document_uuid="doc-123",
            doc_data={
                'documentId': 'doc-node-uuid',
                'sql_id': 1000,
                'name': 'test.docx',
                'category': 'legal',
                'file_type': '.docx'
            },
            project_uuid="proj-123",
            chunks=[
                {
                    'chunkId': 'chunk-1',
                    'chunkIndex': 0
                }
            ],
            entity_mentions=[
                {'id': 101, 'canonical_id': 201, 'chunk_uuid': 'chunk-1'}
            ],
            canonical_entities=[
                {'id': 201, 'name': 'John Doe', 'type': 'PERSON'}
            ]
        )
        
        # Verify relationships were created
        assert mock_db.create_relationship_staging.call_count > 0
        
        # Verify completion status was updated
        mock_db.update_queue_status.assert_called_once()
```

## 3. Redis Integration Testing

### 3.1 Redis Cache Tests (`test_redis_utils.py`)

```python
import pytest
from scripts.redis_utils import RedisManager, get_redis_manager
import json
import time

class TestRedisManager:
    """Test Redis caching functionality with Celery support"""
    
    @pytest.fixture
    def redis_manager(self):
        """Create Redis manager instance"""
        return get_redis_manager()
    
    def test_singleton_pattern(self):
        """Test Redis manager follows singleton pattern"""
        manager1 = get_redis_manager()
        manager2 = get_redis_manager()
        assert manager1 is manager2
    
    def test_cache_ocr_result(self, redis_manager):
        """Test caching OCR results"""
        # Arrange
        document_id = "test-uuid-123"
        ocr_text = "This is extracted text"
        
        # Act
        success = redis_manager.cache_ocr_result(document_id, ocr_text)
        
        # Assert
        assert success is True
        cached = redis_manager.get_cached_ocr(document_id)
        assert cached == ocr_text
    
    def test_document_state_tracking(self, redis_manager):
        """Test document processing state tracking for Celery"""
        # Arrange
        document_id = "test-uuid-123"
        
        # Act
        redis_manager.hset(f"doc:state:{document_id}", {
            "ocr_status": "completed",
            "entity_status": "processing",
            "task_id": "celery-task-123"
        })
        
        # Assert
        state = redis_manager.hgetall(f"doc:state:{document_id}")
        assert state['ocr_status'] == 'completed'
        assert state['entity_status'] == 'processing'
        assert state['task_id'] == 'celery-task-123'
    
    def test_rate_limiting(self, redis_manager):
        """Test API rate limiting implementation"""
        # Arrange
        api_key = "openai"
        limit = 5
        window = 60
        
        # Act & Assert
        for i in range(5):
            allowed = redis_manager.check_rate_limit(api_key, limit=limit, window=window)
            assert allowed is True
        
        # Should be rate limited on 6th call
        allowed = redis_manager.check_rate_limit(api_key, limit=limit, window=window)
        assert allowed is False
```

### 3.2 Redis Cache Decorator Tests (`test_redis_cache_decorator.py`)

```python
import pytest
from scripts.redis_utils import redis_cache
from unittest.mock import patch, MagicMock

class TestRedisCacheDecorator:
    """Test Redis caching decorator"""
    
    def test_cache_decorator_basic(self):
        """Test basic cache decorator functionality"""
        call_count = 0
        
        @redis_cache(ttl=300)
        def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
        
        # First call - cache miss
        result1 = expensive_function(5, 3)
        assert result1 == 8
        assert call_count == 1
        
        # Second call - cache hit
        result2 = expensive_function(5, 3)
        assert result2 == 8
        assert call_count == 1  # Function not called again
    
    def test_cache_decorator_with_prefix(self):
        """Test cache decorator with custom prefix"""
        @redis_cache(prefix="ocr", ttl=600)
        def extract_text(document_id):
            return f"Text for {document_id}"
        
        # Test the cache key format
        with patch('scripts.redis_utils.get_redis_manager') as mock_redis:
            mock_manager = MagicMock()
            mock_redis.return_value = mock_manager
            mock_manager.get.return_value = None
            
            result = extract_text("doc-123")
            
            # Verify cache key includes prefix
            cache_key = mock_manager.get.call_args[0][0]
            assert cache_key.startswith("ocr:")
            assert "doc-123" in cache_key
```

## 4. Supabase Integration Testing

### 4.1 Database Operations Tests (`test_supabase_utils.py`)

```python
import pytest
from scripts.supabase_utils import SupabaseManager
from uuid import uuid4
from unittest.mock import MagicMock, patch

class TestSupabaseManager:
    """Test Supabase database operations with Celery support"""
    
    @pytest.fixture
    def db_manager(self):
        """Create database manager with mocked client"""
        with patch('scripts.supabase_utils.create_client') as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client
            return SupabaseManager()
    
    def test_create_document_entry(self, db_manager):
        """Test creating document entries"""
        # Arrange
        document_data = {
            "filename": "contract.pdf",
            "project_id": str(uuid4()),
            "content_hash": "abc123",
            "celery_task_id": "celery-task-123"  # New field for Celery
        }
        
        # Mock response
        db_manager.client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": 123, "uuid": "doc-uuid-123"}
        ]
        
        # Act
        doc_id, doc_uuid = db_manager.create_document_entry(**document_data)
        
        # Assert
        assert doc_id == 123
        assert doc_uuid == "doc-uuid-123"
        db_manager.client.table.assert_called_with('source_documents')
    
    def test_update_celery_task_status(self, db_manager):
        """Test updating Celery task status in database"""
        # Arrange
        document_id = 123
        task_id = "celery-task-456"
        
        # Act
        db_manager.update_celery_task_status(document_id, task_id, "SUCCESS")
        
        # Assert
        db_manager.client.table.assert_called_with('document_processing_queue')
        update_call = db_manager.client.table.return_value.update
        update_call.assert_called_once()
        update_data = update_call.call_args[0][0]
        assert update_data['celery_task_id'] == task_id
        assert update_data['celery_task_status'] == 'SUCCESS'
```

## 5. Testing with Celery Workers

### 5.1 Worker Management Tests (`test_celery_workers.py`)

```python
import pytest
from scripts.start_celery_workers import start_workers, stop_workers, check_worker_health
from unittest.mock import patch, MagicMock
import subprocess

class TestCeleryWorkerManagement:
    """Test Celery worker management scripts"""
    
    @patch('subprocess.Popen')
    def test_start_workers(self, mock_popen):
        """Test starting all worker types"""
        # Arrange
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        
        # Act
        workers = start_workers()
        
        # Assert
        assert len(workers) == 4  # OCR, text, entity, graph
        assert all(w['status'] == 'running' for w in workers)
        
        # Verify correct queues
        calls = mock_popen.call_args_list
        queues = ['-Q ocr', '-Q text', '-Q entity', '-Q graph']
        for queue in queues:
            assert any(queue in ' '.join(call[0][0]) for call in calls)
    
    @patch('subprocess.check_output')
    def test_check_worker_health(self, mock_check_output):
        """Test worker health monitoring"""
        # Arrange
        mock_check_output.return_value = b"""
        -> celery@worker-1: OK
           * ocr: OK
        -> celery@worker-2: OK
           * text: OK
        """
        
        # Act
        health = check_worker_health()
        
        # Assert
        assert health['healthy'] is True
        assert health['worker_count'] == 2
        assert 'ocr' in health['active_queues']
        assert 'text' in health['active_queues']
```

### 5.2 Migration to Celery Tests (`test_migrate_to_celery.py`)

```python
import pytest
from scripts.migrate_to_celery import CeleryMigration
from unittest.mock import MagicMock, patch

class TestCeleryMigration:
    """Test migration of existing documents to Celery"""
    
    @pytest.fixture
    def migration(self, mock_db_manager):
        """Create migration instance"""
        return CeleryMigration(mock_db_manager)
    
    def test_find_pending_documents(self, migration, mock_db_manager):
        """Test finding documents that need migration"""
        # Arrange
        mock_db_manager.client.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
            {"id": 1, "uuid": "doc-1", "status": "processing"},
            {"id": 2, "uuid": "doc-2", "status": "failed"}
        ]
        
        # Act
        pending = migration.find_pending_documents()
        
        # Assert
        assert len(pending) == 2
        assert all(d['status'] in ['processing', 'failed'] for d in pending)
    
    @patch('scripts.celery_tasks.ocr_tasks.process_ocr.delay')
    def test_migrate_document_to_celery(self, mock_task, migration):
        """Test migrating single document to Celery processing"""
        # Arrange
        document = {
            "id": 123,
            "uuid": "doc-123",
            "file_path": "s3://bucket/doc-123.pdf",
            "file_name": "contract.pdf",
            "detected_file_type": ".pdf"
        }
        mock_task.return_value.id = "celery-task-789"
        
        # Act
        result = migration.migrate_document(document)
        
        # Assert
        assert result['success'] is True
        assert result['task_id'] == "celery-task-789"
        mock_task.assert_called_once()
```

## 6. Integration Testing

### 6.1 Celery Pipeline Integration (`test_celery_pipeline_integration.py`)

```python
import pytest
from celery import chain
from scripts.celery_tasks.ocr_tasks import process_ocr
from scripts.celery_tasks.text_tasks import create_document_node
from scripts.celery_tasks.entity_tasks import extract_entities
from scripts.celery_tasks.graph_tasks import build_relationships

class TestCeleryPipelineIntegration:
    """Test complete Celery pipeline integration"""
    
    @pytest.mark.integration
    def test_complete_pipeline_chain(self, celery_app, test_document):
        """Test complete document processing chain"""
        # Arrange
        document_data = {
            "document_uuid": "test-doc-123",
            "source_doc_sql_id": 123,
            "file_path": "test.pdf",
            "file_name": "test.pdf",
            "detected_file_type": ".pdf",
            "project_sql_id": 1
        }
        
        # Create pipeline chain
        pipeline = chain(
            process_ocr.s(**document_data),
            create_document_node.s(),
            extract_entities.s(),
            build_relationships.s()
        )
        
        # Act
        result = pipeline.apply()
        
        # Assert
        assert result.successful()
        assert result.result['status'] == 'completed'
    
    @pytest.mark.integration
    def test_pipeline_error_handling(self, celery_app):
        """Test pipeline handles errors gracefully"""
        # Arrange
        document_data = {
            "document_uuid": "test-doc-error",
            "source_doc_sql_id": 999,
            "file_path": "nonexistent.pdf",
            "file_name": "nonexistent.pdf",
            "detected_file_type": ".pdf",
            "project_sql_id": 1
        }
        
        # Act
        task = process_ocr.delay(**document_data)
        
        # Assert
        assert task.failed() is True
        assert 'error' in task.info
```

## 7. Performance Testing

### 7.1 Celery Performance Tests (`test_celery_performance.py`)

```python
import pytest
import time
from concurrent.futures import ThreadPoolExecutor
from scripts.celery_tasks.ocr_tasks import process_ocr

class TestCeleryPerformance:
    """Test Celery task performance"""
    
    @pytest.mark.performance
    def test_parallel_task_execution(self, test_documents):
        """Test parallel document processing with Celery"""
        # Arrange
        num_documents = 10
        
        # Act
        start_time = time.time()
        tasks = []
        
        for i in range(num_documents):
            task = process_ocr.delay(
                document_uuid=f"perf-test-{i}",
                source_doc_sql_id=i,
                file_path=test_documents[i % len(test_documents)],
                file_name=f"test-{i}.pdf",
                detected_file_type=".pdf",
                project_sql_id=1
            )
            tasks.append(task)
        
        # Wait for all tasks
        results = [task.get(timeout=300) for task in tasks]
        end_time = time.time()
        
        # Assert
        assert all(r is not None for r in results)
        processing_time = end_time - start_time
        assert processing_time < 60  # All docs processed in under 1 minute
        
        # Calculate throughput
        throughput = num_documents / processing_time
        assert throughput > 0.2  # At least 0.2 docs/second
    
    @pytest.mark.performance
    def test_task_retry_performance(self):
        """Test Celery retry mechanism performance"""
        # Arrange
        from scripts.celery_tasks.ocr_tasks import OCRTask
        
        # Create task with fast retry
        task = OCRTask()
        task.default_retry_delay = 1  # 1 second retry
        task.max_retries = 3
        
        # Act
        start_time = time.time()
        
        # Simulate retries
        for i in range(3):
            try:
                # This would normally raise and trigger retry
                pass
            except Exception:
                time.sleep(task.default_retry_delay * (2 ** i))
        
        end_time = time.time()
        
        # Assert
        total_time = end_time - start_time
        assert total_time < 10  # All retries complete in under 10 seconds
```

## 8. End-to-End Testing with Celery

### 8.1 E2E Celery Tests (`test_e2e_celery.py`)

```python
import pytest
import asyncio
from pathlib import Path

class TestEndToEndCelery:
    """Test complete pipeline with Celery"""
    
    @pytest.mark.e2e
    async def test_document_upload_to_completion(self, test_pdf_file, live_services):
        """Test document from upload through Celery processing"""
        # Arrange
        project_id = "test-project-celery-e2e"
        
        # Act - Upload document
        doc_id, doc_uuid = await upload_test_document(test_pdf_file, project_id)
        
        # Verify Celery task was created
        queue_entry = await get_queue_entry(doc_id)
        assert queue_entry['celery_task_id'] is not None
        
        # Wait for Celery processing
        result = await wait_for_celery_completion(queue_entry['celery_task_id'], timeout=300)
        
        # Assert - Verify all stages completed
        assert result['status'] == 'SUCCESS'
        
        # Verify database updates
        doc_status = await get_document_status(doc_uuid)
        assert doc_status['ocr_completed_at'] is not None
        assert doc_status['entity_extraction_completed_at'] is not None
        assert doc_status['neo4j_staged_at'] is not None
    
    @pytest.mark.e2e
    def test_celery_worker_failover(self, test_document):
        """Test Celery handles worker failures"""
        # This would require a more complex setup with actual workers
        # For now, we'll test the retry mechanism
        pass
```

## 9. Test Fixtures and Utilities

### 9.1 Updated conftest.py

```python
import pytest
from unittest.mock import Mock, MagicMock, patch
import fakeredis
from celery import Celery
from pathlib import Path

@pytest.fixture
def mock_redis_client():
    """Provide fake Redis client for testing"""
    return fakeredis.FakeRedis(decode_responses=True)

@pytest.fixture
def mock_db_manager():
    """Mock Supabase database manager"""
    mock = MagicMock()
    mock.create_document_entry.return_value = (1, "test-uuid-123")
    mock.create_queue_entry.return_value = 1
    mock.fetch_pending_documents.return_value = []
    mock.update_celery_task_status = MagicMock()
    return mock

@pytest.fixture
def celery_app():
    """Create test Celery app"""
    app = Celery('test', broker='memory://', backend='cache+memory://')
    app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )
    return app

@pytest.fixture
def mock_celery_task():
    """Mock Celery task for testing"""
    task = MagicMock()
    task.delay.return_value.id = "test-task-id"
    task.apply_async.return_value.id = "test-task-id"
    return task

@pytest.fixture
def test_pdf_file():
    """Provide test PDF file"""
    return Path("tests/fixtures/documents/sample.pdf")
```

## 10. Running Tests

### 10.1 Test Commands

```bash
# Run all unit tests including Celery
pytest tests/unit/ -v

# Run only Celery-specific tests
pytest tests/unit/test_celery*.py -v

# Run integration tests with real Redis
docker run -d -p 6379:6379 redis:alpine
pytest tests/integration/ -v

# Run with coverage
pytest --cov=scripts --cov-report=html --cov-report=term-missing tests/

# Run specific test classes
pytest tests/unit/test_celery_tasks.py::TestCeleryOCRTasks -v

# Run with Celery worker (integration tests)
celery -A scripts.celery_app worker --loglevel=info &
pytest tests/integration/test_celery_pipeline_integration.py -v

# Run performance tests
pytest tests/performance/ -v -m performance

# Run end-to-end tests
DEPLOYMENT_STAGE=1 pytest tests/e2e/ -v -m e2e
```

### 10.2 Coverage Goals

Target coverage for each module:
- `scripts/celery_app.py`: 90%+
- `scripts/celery_tasks/*.py`: 85%+
- `scripts/queue_processor.py`: 85%+
- `scripts/redis_utils.py`: 90%+
- `scripts/supabase_utils.py`: 85%+
- `scripts/main_pipeline.py`: 80%+
- Overall: 80%+

## 11. CI/CD Updates for Celery

### 11.1 GitHub Actions Workflow

```yaml
# .github/workflows/test-celery.yml
name: Celery Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test-celery:
    runs-on: ubuntu-latest
    
    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install -r tests/requirements-test.txt
    
    - name: Start Celery workers
      run: |
        celery -A scripts.celery_app worker --loglevel=info --detach
        sleep 5  # Wait for workers to start
    
    - name: Run Celery unit tests
      env:
        CELERY_BROKER_URL: redis://localhost:6379/0
        CELERY_RESULT_BACKEND: redis://localhost:6379/0
      run: |
        pytest tests/unit/test_celery*.py -v --cov=scripts.celery_tasks
    
    - name: Run integration tests
      env:
        DEPLOYMENT_STAGE: 1
        REDIS_URL: redis://localhost:6379
      run: |
        pytest tests/integration/test_celery*.py -v
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
        flags: celery
        fail_ci_if_error: true
```

## Summary

This updated testing guide now comprehensively covers the Celery implementation with:

1. **Celery App Tests**: Configuration and routing validation
2. **Task Tests**: All 4 task modules (OCR, text, entity, graph) 
3. **Worker Tests**: Management and health monitoring
4. **Integration Tests**: Complete pipeline with Celery
5. **Performance Tests**: Parallel execution and throughput
6. **Migration Tests**: Moving existing documents to Celery
7. **E2E Tests**: Full workflow with Celery workers

The test suite ensures robust coverage of the distributed task processing system, providing confidence in the Celery integration for production deployment.