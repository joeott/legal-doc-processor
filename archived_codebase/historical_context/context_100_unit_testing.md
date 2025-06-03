# Phase 1 Comprehensive Unit Testing Guide

## Overview

This guide provides a complete testing strategy for Phase 1 (cloud-only) implementation of the legal document processing pipeline. Phase 1 utilizes AWS Textract for OCR and OpenAI GPT-4 for entity extraction, with Redis caching and Supabase for data persistence.

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
    """Test document queue processing"""
    
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
    
    def test_process_batch(self, mock_db_manager, mock_pipeline):
        """Test batch processing of documents"""
        # Arrange
        batch = [
            {"id": 1, "document_id": "uuid-1"},
            {"id": 2, "document_id": "uuid-2"}
        ]
        
        # Act
        processor = QueueProcessor(mock_db_manager)
        results = processor.process_batch(batch)
        
        # Assert
        assert len(results) == 2
        assert mock_db_manager.update_queue_status.call_count == 4  # 2 processing + 2 completed
    
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

## 2. Redis Integration Testing

### 2.1 Redis Cache Tests (`test_redis_utils.py`)

```python
import pytest
from scripts.redis_utils import RedisManager
import json

class TestRedisManager:
    """Test Redis caching functionality"""
    
    @pytest.fixture
    def redis_manager(self, mock_redis_client):
        """Create Redis manager with mock client"""
        return RedisManager(mock_redis_client)
    
    def test_cache_ocr_result(self, redis_manager):
        """Test caching OCR results"""
        # Arrange
        document_id = "test-uuid-123"
        ocr_text = "This is extracted text"
        
        # Act
        redis_manager.cache_ocr_result(document_id, ocr_text)
        
        # Assert
        expected_key = f"ocr:result:{document_id}"
        redis_manager.client.setex.assert_called_once_with(
            expected_key, 
            3600,  # 1 hour TTL
            json.dumps({"text": ocr_text, "timestamp": pytest.approx(time.time())})
        )
    
    def test_get_cached_ocr(self, redis_manager):
        """Test retrieving cached OCR results"""
        # Arrange
        document_id = "test-uuid-123"
        cached_data = json.dumps({"text": "Cached text", "timestamp": time.time()})
        redis_manager.client.get.return_value = cached_data
        
        # Act
        result = redis_manager.get_cached_ocr(document_id)
        
        # Assert
        assert result == "Cached text"
        redis_manager.client.get.assert_called_with(f"ocr:result:{document_id}")
    
    def test_rate_limiting(self, redis_manager):
        """Test API rate limiting implementation"""
        # Arrange
        api_key = "openai"
        
        # Act
        for i in range(5):
            allowed = redis_manager.check_rate_limit(api_key, limit=5, window=60)
            assert allowed is True
        
        # Should be rate limited on 6th call
        allowed = redis_manager.check_rate_limit(api_key, limit=5, window=60)
        
        # Assert
        assert allowed is False
```

### 2.2 MCP Redis Pipeline Tests (`test_mcp_redis_pipeline.py`)

```python
import pytest
from resources.mcp_redis_pipeline.src.tools import cache_document_text, get_pipeline_metrics

class TestMCPRedisIntegration:
    """Test MCP Redis server integration"""
    
    def test_cache_document_via_mcp(self, mcp_redis_client):
        """Test document caching through MCP interface"""
        # Arrange
        document_id = "test-uuid-123"
        text_content = "Legal document content"
        
        # Act
        result = cache_document_text(document_id, text_content, ttl=7200)
        
        # Assert
        assert result['success'] is True
        assert result['cached_key'] == f"document:text:{document_id}"
    
    def test_get_pipeline_metrics(self, mcp_redis_client):
        """Test retrieving pipeline metrics via MCP"""
        # Act
        metrics = get_pipeline_metrics(time_range="1h")
        
        # Assert
        assert 'documents_processed' in metrics
        assert 'average_processing_time' in metrics
        assert 'cache_hit_rate' in metrics
        assert metrics['cache_hit_rate'] >= 0.0
```

## 3. Supabase Integration Testing

### 3.1 Database Operations Tests (`test_supabase_utils.py`)

```python
import pytest
from scripts.supabase_utils import SupabaseManager
from uuid import uuid4

class TestSupabaseManager:
    """Test Supabase database operations"""
    
    def test_create_document_entry(self, mock_supabase_client):
        """Test creating document entries"""
        # Arrange
        manager = SupabaseManager()
        document_data = {
            "filename": "contract.pdf",
            "project_id": str(uuid4()),
            "content_hash": "abc123"
        }
        
        # Act
        doc_id, doc_uuid = manager.create_document_entry(**document_data)
        
        # Assert
        assert isinstance(doc_id, int)
        assert isinstance(doc_uuid, str)
        mock_supabase_client.table.assert_called_with('source_documents')
    
    def test_create_queue_entry(self, mock_supabase_client):
        """Test queue entry creation with triggers"""
        # Arrange
        manager = SupabaseManager()
        document_id = "test-uuid-123"
        
        # Act
        queue_id = manager.create_queue_entry(document_id)
        
        # Assert
        assert isinstance(queue_id, int)
        # Verify trigger creates notification
        mock_supabase_client.table('notifications').select.assert_called()
    
    def test_update_processing_status(self, mock_supabase_client):
        """Test status updates with history tracking"""
        # Arrange
        manager = SupabaseManager()
        queue_id = 123
        
        # Act
        manager.update_queue_status(queue_id, 'processing')
        manager.update_queue_status(queue_id, 'completed')
        
        # Assert
        assert mock_supabase_client.table('document_processing_queue').update.call_count == 2
        # Verify history is tracked
        assert mock_supabase_client.table('document_processing_history').insert.called
```

### 3.2 MCP Supabase Tests (`test_mcp_supabase.py`)

```python
import pytest
from unittest.mock import patch

class TestMCPSupabaseIntegration:
    """Test MCP Supabase server integration"""
    
    def test_execute_migration(self, mcp_supabase_client):
        """Test database migration execution"""
        # Arrange
        migration_sql = """
        CREATE TABLE test_table (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL
        );
        """
        
        # Act
        result = mcp_supabase_client.apply_migration(
            name="create_test_table",
            query=migration_sql
        )
        
        # Assert
        assert result['success'] is True
        assert 'migration_id' in result
    
    def test_list_tables(self, mcp_supabase_client):
        """Test listing database tables"""
        # Act
        tables = mcp_supabase_client.list_tables(schemas=['public'])
        
        # Assert
        expected_tables = [
            'source_documents',
            'document_processing_queue',
            'neo4j_canonical_entities',
            'textract_jobs'
        ]
        for table in expected_tables:
            assert any(t['name'] == table for t in tables)
```

## 4. AWS Integration Testing

### 4.1 Textract Tests (`test_textract_utils.py`)

```python
import pytest
from scripts.textract_utils import TextractManager
from botocore.exceptions import ClientError

class TestTextractManager:
    """Test AWS Textract integration"""
    
    @pytest.fixture
    def textract_manager(self, mock_textract_client, mock_s3_client):
        """Create Textract manager with mocked AWS clients"""
        with patch('boto3.client') as mock_boto:
            mock_boto.side_effect = lambda service: {
                'textract': mock_textract_client,
                's3': mock_s3_client
            }.get(service)
            return TextractManager()
    
    def test_start_document_analysis(self, textract_manager):
        """Test starting async Textract job"""
        # Arrange
        s3_uri = "s3://bucket/document-uuid-123.pdf"
        mock_response = {"JobId": "textract-job-123"}
        textract_manager.textract_client.start_document_analysis.return_value = mock_response
        
        # Act
        job_id = textract_manager.start_document_analysis(s3_uri)
        
        # Assert
        assert job_id == "textract-job-123"
        textract_manager.textract_client.start_document_analysis.assert_called_once()
    
    def test_poll_job_completion(self, textract_manager):
        """Test polling for job completion"""
        # Arrange
        job_id = "textract-job-123"
        responses = [
            {"JobStatus": "IN_PROGRESS"},
            {"JobStatus": "IN_PROGRESS"},
            {"JobStatus": "SUCCEEDED", "Blocks": [{"Text": "Extracted text"}]}
        ]
        textract_manager.textract_client.get_document_analysis.side_effect = responses
        
        # Act
        result = textract_manager.wait_for_completion(job_id, max_wait=30)
        
        # Assert
        assert result['status'] == 'SUCCEEDED'
        assert textract_manager.textract_client.get_document_analysis.call_count == 3
    
    def test_handle_textract_failure(self, textract_manager):
        """Test handling Textract job failures"""
        # Arrange
        job_id = "textract-job-123"
        textract_manager.textract_client.get_document_analysis.return_value = {
            "JobStatus": "FAILED",
            "StatusMessage": "Invalid PDF format"
        }
        
        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            textract_manager.wait_for_completion(job_id)
        assert "Textract job failed" in str(exc_info.value)
```

### 4.2 S3 Storage Tests (`test_s3_storage.py`)

```python
import pytest
from scripts.s3_storage import S3Manager
import io

class TestS3Manager:
    """Test S3 document storage"""
    
    def test_upload_document(self, mock_s3_client):
        """Test document upload with UUID naming"""
        # Arrange
        manager = S3Manager()
        document_id = "test-uuid-123"
        file_content = b"PDF content here"
        
        # Act
        s3_key = manager.upload_document(document_id, file_content, "pdf")
        
        # Assert
        assert s3_key == f"documents/{document_id}.pdf"
        mock_s3_client.put_object.assert_called_once()
        
    def test_generate_signed_url(self, mock_s3_client):
        """Test signed URL generation"""
        # Arrange
        manager = S3Manager()
        s3_key = "documents/test-uuid-123.pdf"
        mock_s3_client.generate_presigned_url.return_value = "https://signed-url"
        
        # Act
        url = manager.get_signed_url(s3_key, expiration=3600)
        
        # Assert
        assert url == "https://signed-url"
        mock_s3_client.generate_presigned_url.assert_called_with(
            'get_object',
            Params={'Bucket': manager.bucket_name, 'Key': s3_key},
            ExpiresIn=3600
        )
    
    def test_handle_large_files(self, mock_s3_client):
        """Test multipart upload for large files"""
        # Arrange
        manager = S3Manager()
        large_file = io.BytesIO(b"x" * (10 * 1024 * 1024))  # 10MB
        
        # Act
        result = manager.upload_large_document("test-uuid", large_file, "pdf")
        
        # Assert
        mock_s3_client.create_multipart_upload.assert_called_once()
        assert result['multipart'] is True
```

## 5. Frontend Testing

### 5.1 Frontend Upload Tests (`test_frontend_upload.js`)

```javascript
// tests/frontend/test_upload.js
import { uploadDocument } from '../../frontend/public/upload.js';

describe('Document Upload', () => {
    let mockSupabaseClient;
    
    beforeEach(() => {
        mockSupabaseClient = {
            storage: {
                from: jest.fn().mockReturnThis(),
                upload: jest.fn()
            },
            from: jest.fn().mockReturnThis(),
            insert: jest.fn()
        };
    });
    
    test('successful document upload', async () => {
        // Arrange
        const file = new File(['test content'], 'test.pdf', { type: 'application/pdf' });
        const projectId = 'test-project-123';
        mockSupabaseClient.storage.upload.mockResolvedValue({ data: { path: 'test.pdf' } });
        mockSupabaseClient.insert.mockResolvedValue({ data: { id: 123 } });
        
        // Act
        const result = await uploadDocument(file, projectId, mockSupabaseClient);
        
        // Assert
        expect(result.success).toBe(true);
        expect(result.documentId).toBe(123);
        expect(mockSupabaseClient.storage.upload).toHaveBeenCalledWith(
            expect.stringMatching(/^[0-9a-f-]+\.pdf$/),
            file
        );
    });
    
    test('handle upload failure', async () => {
        // Arrange
        const file = new File(['test'], 'test.pdf');
        mockSupabaseClient.storage.upload.mockRejectedValue(new Error('Network error'));
        
        // Act & Assert
        await expect(uploadDocument(file, 'project-123', mockSupabaseClient))
            .rejects.toThrow('Upload failed');
    });
    
    test('validate file size limit', () => {
        // Arrange
        const largeFile = new File(['x'.repeat(26 * 1024 * 1024)], 'large.pdf');
        
        // Act & Assert
        expect(() => validateFileSize(largeFile)).toThrow('File size exceeds 25MB limit');
    });
});
```

### 5.2 API Endpoint Tests (`test_api_endpoints.ts`)

```typescript
// tests/frontend/test_api_endpoints.ts
import { createDocumentEntry } from '../../frontend/api/create-document-entry';
import { createMocks } from 'node-mocks-http';

describe('API Endpoints', () => {
    test('create document entry endpoint', async () => {
        // Arrange
        const { req, res } = createMocks({
            method: 'POST',
            headers: {
                'authorization': 'Bearer test-key'
            },
            body: {
                filename: 'contract.pdf',
                projectId: 'project-123',
                userId: 'user-456'
            }
        });
        
        // Act
        await createDocumentEntry(req, res);
        
        // Assert
        expect(res._getStatusCode()).toBe(200);
        const data = JSON.parse(res._getData());
        expect(data).toHaveProperty('documentId');
        expect(data).toHaveProperty('documentUuid');
    });
    
    test('handle missing authorization', async () => {
        // Arrange
        const { req, res } = createMocks({
            method: 'POST',
            body: { filename: 'test.pdf' }
        });
        
        // Act
        await createDocumentEntry(req, res);
        
        // Assert
        expect(res._getStatusCode()).toBe(401);
        expect(JSON.parse(res._getData())).toEqual({
            error: 'Unauthorized'
        });
    });
});
```

## 6. Monitoring Testing

### 6.1 Live Monitor Tests (`test_live_monitor.py`)

```python
import pytest
from monitoring.live_monitor import PipelineMonitor
from unittest.mock import MagicMock

class TestPipelineMonitor:
    """Test pipeline monitoring functionality"""
    
    def test_fetch_processing_metrics(self, mock_db_connection):
        """Test fetching real-time metrics"""
        # Arrange
        monitor = PipelineMonitor(mock_db_connection)
        mock_db_connection.execute.return_value = [
            {"status": "processing", "count": 5},
            {"status": "completed", "count": 150},
            {"status": "failed", "count": 3}
        ]
        
        # Act
        metrics = monitor.get_current_metrics()
        
        # Assert
        assert metrics['processing'] == 5
        assert metrics['completed'] == 150
        assert metrics['failed'] == 3
        assert metrics['success_rate'] == pytest.approx(98.0, 0.1)
    
    def test_detect_stuck_documents(self, mock_db_connection):
        """Test detection of stuck documents"""
        # Arrange
        monitor = PipelineMonitor(mock_db_connection)
        mock_db_connection.execute.return_value = [
            {
                "document_id": "stuck-uuid-123",
                "processing_time_minutes": 15,
                "current_stage": "ocr_extraction"
            }
        ]
        
        # Act
        stuck_docs = monitor.find_stuck_documents(threshold_minutes=10)
        
        # Assert
        assert len(stuck_docs) == 1
        assert stuck_docs[0]['document_id'] == "stuck-uuid-123"
        assert stuck_docs[0]['processing_time_minutes'] == 15
```

### 6.2 Pipeline Analysis Tests (`test_pipeline_analysis.py`)

```python
import pytest
from monitoring.pipeline_analysis import PipelineAnalyzer

class TestPipelineAnalyzer:
    """Test pipeline performance analysis"""
    
    def test_calculate_stage_metrics(self, mock_db_connection):
        """Test stage-wise performance metrics"""
        # Arrange
        analyzer = PipelineAnalyzer(mock_db_connection)
        mock_db_connection.execute.return_value = [
            {"stage": "ocr", "avg_time": 45.2, "success_rate": 0.95},
            {"stage": "entity_extraction", "avg_time": 12.8, "success_rate": 0.98},
            {"stage": "relationship_building", "avg_time": 5.3, "success_rate": 0.99}
        ]
        
        # Act
        metrics = analyzer.get_stage_metrics()
        
        # Assert
        assert metrics['ocr']['avg_time'] == 45.2
        assert metrics['entity_extraction']['success_rate'] == 0.98
        assert sum(m['avg_time'] for m in metrics.values()) < 300  # Under 5 min total
    
    def test_identify_bottlenecks(self, analyzer):
        """Test bottleneck identification"""
        # Arrange
        stage_metrics = {
            "ocr": {"avg_time": 180, "success_rate": 0.85},
            "entity_extraction": {"avg_time": 30, "success_rate": 0.95}
        }
        
        # Act
        bottlenecks = analyzer.identify_bottlenecks(stage_metrics)
        
        # Assert
        assert "ocr" in bottlenecks
        assert bottlenecks["ocr"]["reason"] == "High processing time"
```

## 7. End-to-End Testing

### 7.1 Complete Pipeline Test (`test_e2e_pipeline.py`)

```python
import pytest
import asyncio
from pathlib import Path

class TestEndToEndPipeline:
    """Test complete document processing pipeline"""
    
    @pytest.mark.e2e
    async def test_complete_document_flow(self, test_pdf_file, live_services):
        """Test document from upload to knowledge graph"""
        # Arrange
        project_id = "test-project-e2e"
        
        # Act - Upload document
        doc_id, doc_uuid = await upload_test_document(test_pdf_file, project_id)
        
        # Wait for processing (with timeout)
        result = await wait_for_processing(doc_uuid, timeout=300)
        
        # Assert - Verify all stages completed
        assert result['status'] == 'completed'
        
        # Verify OCR results
        ocr_text = await get_document_text(doc_uuid)
        assert len(ocr_text) > 100
        
        # Verify entity extraction
        entities = await get_extracted_entities(doc_uuid)
        assert len(entities) > 0
        
        # Verify relationships
        relationships = await get_relationships(doc_uuid)
        assert len(relationships) > 0
        
        # Verify Neo4j staging
        neo4j_ready = await check_neo4j_staging(doc_uuid)
        assert neo4j_ready is True
    
    @pytest.mark.e2e
    def test_error_recovery_flow(self, corrupted_pdf):
        """Test pipeline error handling and recovery"""
        # Arrange
        project_id = "test-project-errors"
        
        # Act - Upload corrupted document
        doc_id, doc_uuid = upload_test_document(corrupted_pdf, project_id)
        
        # Wait for processing attempt
        result = wait_for_processing(doc_uuid, timeout=120)
        
        # Assert - Verify proper error handling
        assert result['status'] == 'failed'
        assert result['error_message'] is not None
        assert result['retry_count'] == 3  # Max retries attempted
        
        # Verify document marked as failed in queue
        queue_status = get_queue_status(doc_uuid)
        assert queue_status == 'failed'
```

## 8. Performance Testing

### 8.1 Load Testing (`test_performance.py`)

```python
import pytest
import concurrent.futures
import time

class TestPerformance:
    """Test pipeline performance under load"""
    
    def test_concurrent_document_processing(self, test_documents):
        """Test processing multiple documents concurrently"""
        # Arrange
        num_documents = 10
        
        # Act
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(num_documents):
                future = executor.submit(process_document, test_documents[i])
                futures.append(future)
            
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        end_time = time.time()
        
        # Assert
        assert all(r['status'] == 'completed' for r in results)
        assert (end_time - start_time) < 300  # All docs in under 5 minutes
        
    def test_cache_performance(self, redis_manager):
        """Test Redis cache hit rates"""
        # Arrange
        test_data = {"key": f"test-{i}", "value": f"data-{i}"} for i in range(100)
        
        # Act - Populate cache
        for item in test_data:
            redis_manager.set(item['key'], item['value'])
        
        # Measure hit rate
        hits = 0
        for _ in range(1000):
            key = f"test-{random.randint(0, 99)}"
            if redis_manager.get(key):
                hits += 1
        
        # Assert
        hit_rate = hits / 1000
        assert hit_rate > 0.95  # 95% cache hit rate
```

## 9. Security Testing

### 9.1 Authentication Tests (`test_security.py`)

```python
import pytest
from scripts.supabase_utils import SupabaseManager

class TestSecurity:
    """Test security measures"""
    
    def test_api_key_validation(self):
        """Test API key validation"""
        # Arrange
        invalid_key = "invalid-key-123"
        
        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            manager = SupabaseManager(api_key=invalid_key)
        assert "Invalid API key" in str(exc_info.value)
    
    def test_sql_injection_prevention(self, db_manager):
        """Test SQL injection prevention"""
        # Arrange
        malicious_input = "'; DROP TABLE source_documents; --"
        
        # Act
        result = db_manager.search_documents(query=malicious_input)
        
        # Assert
        # Should safely escape the input
        assert result is not None
        # Verify table still exists
        assert db_manager.table_exists('source_documents') is True
    
    def test_file_upload_validation(self):
        """Test file upload security"""
        # Arrange
        malicious_filename = "../../../etc/passwd"
        
        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            validate_upload_filename(malicious_filename)
        assert "Invalid filename" in str(exc_info.value)
```

## 10. Test Utilities

### 10.1 Test Fixtures (`conftest.py`)

```python
import pytest
from unittest.mock import Mock, MagicMock
import fakeredis
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
    return mock

@pytest.fixture
def mock_textract_client():
    """Mock AWS Textract client"""
    mock = MagicMock()
    mock.start_document_analysis.return_value = {"JobId": "test-job-123"}
    mock.get_document_analysis.return_value = {
        "JobStatus": "SUCCEEDED",
        "Blocks": [{"BlockType": "LINE", "Text": "Test text"}]
    }
    return mock

@pytest.fixture
def test_pdf_file():
    """Provide test PDF file"""
    return Path("tests/fixtures/documents/sample.pdf")

@pytest.fixture
def mock_openai():
    """Mock OpenAI API responses"""
    with patch('openai.ChatCompletion.create') as mock:
        mock.return_value = {
            "choices": [{
                "message": {
                    "content": '{"entities": ["John Doe", "Acme Corp"]}'
                }
            }]
        }
        yield mock
```

### 10.2 Test Helpers (`test_helpers.py`)

```python
import time
import json
from typing import Dict, Any

def wait_for_processing(document_uuid: str, timeout: int = 300) -> Dict[str, Any]:
    """Wait for document processing to complete"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        status = get_processing_status(document_uuid)
        if status['status'] in ['completed', 'failed']:
            return status
        time.sleep(5)
    raise TimeoutError(f"Processing timeout for document {document_uuid}")

def create_test_document(filename: str = "test.pdf") -> Dict[str, Any]:
    """Create a test document entry"""
    return {
        "filename": filename,
        "project_id": "test-project",
        "file_type": "pdf",
        "file_size": 1024,
        "content_hash": "test-hash-123"
    }

def assert_valid_uuid(value: str) -> None:
    """Assert that a value is a valid UUID"""
    import uuid
    try:
        uuid.UUID(value)
    except ValueError:
        pytest.fail(f"Invalid UUID: {value}")
```

## 11. Running Tests

### 11.1 Test Commands

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run integration tests
pytest tests/integration/ -v

# Run end-to-end tests (requires live services)
pytest tests/e2e/ -v -m e2e

# Run with coverage
pytest --cov=scripts --cov-report=html tests/

# Run specific test file
pytest tests/unit/test_main_pipeline.py -v

# Run tests matching pattern
pytest -k "test_ocr" -v

# Run with Redis mock
pytest --redis-mock tests/

# Run with live services (CI/CD)
DEPLOYMENT_STAGE=1 pytest tests/ --live-services
```

### 11.2 Test Configuration

```python
# pytest.ini
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --strict-markers --tb=short"
markers = [
    "e2e: End-to-end tests requiring live services",
    "slow: Tests that take more than 30 seconds",
    "redis: Tests requiring Redis",
    "aws: Tests requiring AWS services"
]

# Coverage configuration
[coverage:run]
source = ["scripts", "frontend", "monitoring"]
omit = ["*/tests/*", "*/conftest.py"]

[coverage:report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError"
]
```

## 12. CI/CD Integration

### 12.1 GitHub Actions Test Workflow

```yaml
# .github/workflows/test-phase1.yml
name: Phase 1 Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
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
    
    - name: Run unit tests
      env:
        DEPLOYMENT_STAGE: 1
        REDIS_URL: redis://localhost:6379
      run: |
        pytest tests/unit/ -v --cov=scripts --cov-report=xml
    
    - name: Run integration tests
      env:
        DEPLOYMENT_STAGE: 1
        SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
        SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
      run: |
        pytest tests/integration/ -v
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
        fail_ci_if_error: true
```

## 13. Celery Task Testing

### 13.1 Document Tasks Tests (`test_celery_document_tasks.py`)

```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from scripts.celery_tasks.document_tasks import (
    process_document_task, 
    process_document_batch_task,
    retry_failed_document_task
)
from celery import Task
from celery.exceptions import Retry

class TestDocumentTasks:
    """Test Celery document processing tasks"""
    
    @pytest.fixture
    def mock_task(self):
        """Create mock Celery task"""
        task = Mock(spec=Task)
        task.request.id = 'test-task-id'
        task.request.retries = 0
        task.max_retries = 3
        task.retry = Mock(side_effect=Retry)
        return task
    
    def test_process_document_task_success(self, mock_task, mock_db_manager):
        """Test successful document processing task"""
        # Arrange
        document_id = "test-uuid-123"
        with patch('scripts.celery_tasks.document_tasks.DocumentProcessor') as mock_processor:
            processor_instance = mock_processor.return_value
            processor_instance.process_document.return_value = {
                'status': 'completed',
                'stages': {'ocr': 'completed', 'entity_extraction': 'completed'}
            }
            
            # Act
            result = process_document_task(document_id)
            
            # Assert
            assert result['status'] == 'completed'
            processor_instance.process_document.assert_called_once_with(document_id)
    
    def test_process_document_task_retry(self, mock_task, mock_db_manager):
        """Test task retry on transient failure"""
        # Arrange
        document_id = "test-uuid-123"
        process_document_task.bind = Mock(return_value=mock_task)
        
        with patch('scripts.celery_tasks.document_tasks.DocumentProcessor') as mock_processor:
            processor_instance = mock_processor.return_value
            processor_instance.process_document.side_effect = Exception("API timeout")
            
            # Act & Assert
            with pytest.raises(Retry):
                process_document_task(document_id)
            
            mock_task.retry.assert_called_once()
    
    def test_process_document_batch_task(self, mock_db_manager):
        """Test batch document processing"""
        # Arrange
        document_ids = ["uuid-1", "uuid-2", "uuid-3"]
        
        with patch('scripts.celery_tasks.document_tasks.group') as mock_group:
            # Act
            result = process_document_batch_task(document_ids)
            
            # Assert
            mock_group.assert_called_once()
            # Verify individual tasks were created
            assert mock_group.call_args[0][0].__len__() == 3
    
    def test_retry_failed_document_task(self, mock_db_manager):
        """Test retrying failed documents"""
        # Arrange
        document_id = "failed-uuid-123"
        mock_db_manager.get_document_status.return_value = {
            'status': 'failed',
            'retry_count': 2,
            'last_error': 'OCR extraction failed'
        }
        
        with patch('scripts.celery_tasks.document_tasks.process_document_task.delay') as mock_delay:
            # Act
            result = retry_failed_document_task(document_id)
            
            # Assert
            mock_delay.assert_called_once_with(document_id)
            mock_db_manager.update_queue_status.assert_called_with(
                document_id, 'pending', retry_count=3
            )
```

### 13.2 OCR Tasks Tests (`test_celery_ocr_tasks.py`)

```python
import pytest
from scripts.celery_tasks.ocr_tasks import (
    extract_text_task,
    start_textract_job_task,
    check_textract_job_task
)

class TestOCRTasks:
    """Test Celery OCR extraction tasks"""
    
    def test_extract_text_task_with_cache(self, mock_redis_client):
        """Test OCR extraction with Redis caching"""
        # Arrange
        document_id = "test-uuid-123"
        s3_uri = "s3://bucket/test-uuid-123.pdf"
        
        # Mock cache miss then successful extraction
        mock_redis_client.get.return_value = None
        
        with patch('scripts.celery_tasks.ocr_tasks.TextractManager') as mock_textract:
            mock_textract.return_value.extract_text.return_value = "Extracted text"
            
            # Act
            result = extract_text_task(document_id, s3_uri)
            
            # Assert
            assert result['text'] == "Extracted text"
            assert result['cached'] is False
            # Verify result was cached
            mock_redis_client.setex.assert_called_once()
    
    def test_extract_text_task_cache_hit(self, mock_redis_client):
        """Test OCR extraction with cache hit"""
        # Arrange
        document_id = "test-uuid-123"
        cached_text = json.dumps({"text": "Cached text", "timestamp": time.time()})
        mock_redis_client.get.return_value = cached_text
        
        # Act
        result = extract_text_task(document_id, "s3://bucket/test.pdf")
        
        # Assert
        assert result['text'] == "Cached text"
        assert result['cached'] is True
    
    def test_start_textract_job_task(self):
        """Test starting async Textract job"""
        # Arrange
        s3_uri = "s3://bucket/large-document.pdf"
        
        with patch('scripts.celery_tasks.ocr_tasks.TextractManager') as mock_textract:
            mock_textract.return_value.start_document_analysis.return_value = "job-123"
            
            # Act
            job_id = start_textract_job_task(s3_uri)
            
            # Assert
            assert job_id == "job-123"
    
    def test_check_textract_job_task_in_progress(self, mock_task):
        """Test checking Textract job status - still processing"""
        # Arrange
        job_id = "job-123"
        check_textract_job_task.bind = Mock(return_value=mock_task)
        
        with patch('scripts.celery_tasks.ocr_tasks.TextractManager') as mock_textract:
            mock_textract.return_value.get_job_status.return_value = {
                'JobStatus': 'IN_PROGRESS'
            }
            
            # Act & Assert
            with pytest.raises(Retry):
                check_textract_job_task(job_id)
            
            # Verify task will retry with countdown
            mock_task.retry.assert_called_with(countdown=30)
```

### 13.3 Entity Tasks Tests (`test_celery_entity_tasks.py`)

```python
import pytest
from scripts.celery_tasks.entity_tasks import (
    extract_entities_task,
    resolve_entities_task,
    build_relationships_task
)

class TestEntityTasks:
    """Test Celery entity processing tasks"""
    
    def test_extract_entities_task(self, mock_openai):
        """Test entity extraction task"""
        # Arrange
        chunk_id = "chunk-uuid-123"
        text = "John Doe from Acme Corp signed the contract"
        
        mock_openai.return_value = {
            "entities": [
                {"text": "John Doe", "type": "PERSON"},
                {"text": "Acme Corp", "type": "ORGANIZATION"}
            ]
        }
        
        # Act
        result = extract_entities_task(chunk_id, text)
        
        # Assert
        assert len(result['entities']) == 2
        assert result['entities'][0]['type'] == 'PERSON'
        assert result['chunk_id'] == chunk_id
    
    def test_resolve_entities_task(self, mock_db_manager):
        """Test entity resolution task"""
        # Arrange
        entity_mentions = [
            {"id": 1, "text": "John Doe", "type": "PERSON"},
            {"id": 2, "text": "J. Doe", "type": "PERSON"},
            {"id": 3, "text": "Acme Corporation", "type": "ORGANIZATION"}
        ]
        
        with patch('scripts.celery_tasks.entity_tasks.EntityResolver') as mock_resolver:
            resolver_instance = mock_resolver.return_value
            resolver_instance.resolve_entities.return_value = {
                1: "canonical-person-1",
                2: "canonical-person-1",  # Same as 1
                3: "canonical-org-1"
            }
            
            # Act
            result = resolve_entities_task(entity_mentions)
            
            # Assert
            assert len(result) == 3
            assert result[1] == result[2]  # Same canonical entity
            assert result[3] != result[1]
    
    def test_build_relationships_task(self, mock_db_manager):
        """Test relationship building task"""
        # Arrange
        document_id = "doc-uuid-123"
        
        with patch('scripts.celery_tasks.entity_tasks.RelationshipBuilder') as mock_builder:
            builder_instance = mock_builder.return_value
            builder_instance.build_relationships.return_value = [
                {
                    'source': 'entity-1',
                    'target': 'entity-2',
                    'type': 'MENTIONED_WITH',
                    'properties': {'confidence': 0.95}
                }
            ]
            
            # Act
            result = build_relationships_task(document_id)
            
            # Assert
            assert len(result) == 1
            assert result[0]['type'] == 'MENTIONED_WITH'
```

### 13.4 Pipeline Tasks Tests (`test_celery_pipeline_tasks.py`)

```python
import pytest
from scripts.celery_tasks.pipeline_tasks import (
    orchestrate_document_pipeline,
    process_queue_batch_task,
    monitor_pipeline_health_task
)

class TestPipelineTasks:
    """Test Celery pipeline orchestration tasks"""
    
    def test_orchestrate_document_pipeline(self):
        """Test complete pipeline orchestration"""
        # Arrange
        document_id = "test-uuid-123"
        
        with patch('scripts.celery_tasks.pipeline_tasks.chain') as mock_chain:
            # Act
            orchestrate_document_pipeline(document_id)
            
            # Assert
            mock_chain.assert_called_once()
            # Verify pipeline stages are chained correctly
            chain_args = mock_chain.call_args[0]
            assert len(chain_args) >= 4  # OCR, entity extraction, resolution, relationships
    
    def test_process_queue_batch_task(self, mock_db_manager):
        """Test queue batch processing"""
        # Arrange
        mock_db_manager.fetch_pending_documents.return_value = [
            {"id": 1, "document_id": "uuid-1"},
            {"id": 2, "document_id": "uuid-2"}
        ]
        
        with patch('scripts.celery_tasks.pipeline_tasks.group') as mock_group:
            # Act
            result = process_queue_batch_task(batch_size=10)
            
            # Assert
            mock_group.assert_called_once()
            assert result['processed'] == 2
            assert result['status'] == 'success'
    
    def test_monitor_pipeline_health_task(self, mock_redis_client, mock_db_manager):
        """Test pipeline health monitoring"""
        # Arrange
        mock_db_manager.get_pipeline_metrics.return_value = {
            'documents_processing': 5,
            'documents_completed': 100,
            'documents_failed': 2,
            'avg_processing_time': 120
        }
        
        # Act
        health = monitor_pipeline_health_task()
        
        # Assert
        assert health['status'] == 'healthy'
        assert health['metrics']['success_rate'] > 0.95
        assert 'alerts' in health
```

## 14. Celery Worker Testing

### 14.1 Worker Management Tests (`test_celery_worker.py`)

```python
import pytest
from celery import Celery
from celery.worker import WorkController
from scripts.celery_app import create_celery_app

class TestCeleryWorker:
    """Test Celery worker functionality"""
    
    @pytest.fixture
    def celery_app(self):
        """Create test Celery app"""
        app = create_celery_app(testing=True)
        app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
            broker_url='memory://',
            result_backend='cache+memory://'
        )
        return app
    
    def test_worker_initialization(self, celery_app):
        """Test worker starts with correct configuration"""
        # Arrange
        worker = celery_app.Worker()
        
        # Act
        config = worker.app.conf
        
        # Assert
        assert config.task_routes is not None
        assert 'scripts.celery_tasks.document_tasks.*' in config.task_routes
        assert config.task_default_queue == 'default'
    
    def test_worker_queue_routing(self, celery_app):
        """Test tasks are routed to correct queues"""
        # Arrange
        from scripts.celery_tasks import document_tasks, ocr_tasks
        
        # Act
        doc_route = celery_app.amqp.router.route(
            document_tasks.process_document_task.name
        )
        ocr_route = celery_app.amqp.router.route(
            ocr_tasks.extract_text_task.name
        )
        
        # Assert
        assert doc_route['queue'] == 'documents'
        assert ocr_route['queue'] == 'ocr'
    
    def test_worker_concurrency_settings(self, celery_app):
        """Test worker concurrency configuration"""
        # Act
        worker = celery_app.Worker(
            concurrency=4,
            pool='prefork'
        )
        
        # Assert
        assert worker.concurrency == 4
        assert worker.pool_cls.__name__ == 'Pool'
```

### 14.2 Worker Script Tests (`test_manage_workers.py`)

```python
import pytest
from unittest.mock import patch, MagicMock
import subprocess
from scripts.manage_workers import WorkerManager

class TestWorkerManager:
    """Test worker management script"""
    
    @pytest.fixture
    def worker_manager(self):
        """Create worker manager instance"""
        return WorkerManager()
    
    def test_start_workers(self, worker_manager):
        """Test starting all worker types"""
        # Arrange
        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process
            
            # Act
            worker_manager.start_all_workers()
            
            # Assert
            assert mock_popen.call_count == 4  # 4 worker types
            # Verify each worker started with correct queue
            calls = mock_popen.call_args_list
            assert any('-Q documents' in ' '.join(call[0][0]) for call in calls)
            assert any('-Q ocr' in ' '.join(call[0][0]) for call in calls)
    
    def test_stop_workers(self, worker_manager):
        """Test stopping workers gracefully"""
        # Arrange
        mock_processes = {
            'documents': MagicMock(pid=1001),
            'ocr': MagicMock(pid=1002)
        }
        worker_manager.processes = mock_processes
        
        # Act
        worker_manager.stop_all_workers()
        
        # Assert
        for process in mock_processes.values():
            process.terminate.assert_called_once()
    
    def test_monitor_worker_health(self, worker_manager):
        """Test worker health monitoring"""
        # Arrange
        with patch.object(worker_manager, 'get_worker_stats') as mock_stats:
            mock_stats.return_value = {
                'documents': {'active': 2, 'processed': 100},
                'ocr': {'active': 1, 'processed': 50}
            }
            
            # Act
            health = worker_manager.check_health()
            
            # Assert
            assert health['healthy'] is True
            assert health['workers']['documents']['active'] == 2
```

## 15. Queue Processor with Celery Tests

### 15.1 Celery Queue Integration Tests (`test_queue_processor_celery.py`)

```python
import pytest
from scripts.queue_processor import QueueProcessor
from unittest.mock import patch, Mock

class TestQueueProcessorCelery:
    """Test queue processor with Celery integration"""
    
    def test_process_with_celery_tasks(self, mock_db_manager):
        """Test queue processing using Celery tasks"""
        # Arrange
        processor = QueueProcessor(mock_db_manager, use_celery=True)
        pending_docs = [
            {"id": 1, "document_id": "uuid-1"},
            {"id": 2, "document_id": "uuid-2"}
        ]
        mock_db_manager.fetch_pending_documents.return_value = pending_docs
        
        with patch('scripts.celery_tasks.pipeline_tasks.process_queue_batch_task.delay') as mock_task:
            # Act
            processor.process_batch()
            
            # Assert
            mock_task.assert_called_once()
            # Verify documents were marked as queued
            assert mock_db_manager.update_queue_status.call_count == 2
    
    def test_celery_task_monitoring(self, mock_db_manager):
        """Test monitoring Celery task status"""
        # Arrange
        processor = QueueProcessor(mock_db_manager, use_celery=True)
        task_id = "celery-task-123"
        
        with patch('scripts.queue_processor.AsyncResult') as mock_result:
            mock_result.return_value.state = 'SUCCESS'
            mock_result.return_value.result = {'status': 'completed'}
            
            # Act
            status = processor.check_task_status(task_id)
            
            # Assert
            assert status['state'] == 'SUCCESS'
            assert status['result']['status'] == 'completed'
```

## 16. Migration Script Testing

### 16.1 Redis Migration Tests (`test_migrate_to_optimized_redis.py`)

```python
import pytest
from scripts.migrate_to_optimized_redis import RedisMigration

class TestRedisMigration:
    """Test Redis optimization migration"""
    
    def test_migrate_cache_keys(self, mock_redis_client):
        """Test migrating cache keys to optimized structure"""
        # Arrange
        migration = RedisMigration(mock_redis_client)
        old_keys = [
            "ocr:result:doc-123",
            "entity:cache:doc-456",
            "pipeline:metrics:2024-01-01"
        ]
        mock_redis_client.scan_iter.return_value = old_keys
        
        # Act
        result = migration.migrate_keys()
        
        # Assert
        assert result['migrated'] == 3
        assert result['errors'] == 0
        # Verify new keys were created
        assert mock_redis_client.rename.call_count == 3
    
    def test_optimize_data_structures(self, mock_redis_client):
        """Test optimizing Redis data structures"""
        # Arrange
        migration = RedisMigration(mock_redis_client)
        
        # Act
        migration.optimize_structures()
        
        # Assert
        # Verify hash fields were created for metrics
        mock_redis_client.hset.assert_called()
        # Verify sorted sets for time-series data
        mock_redis_client.zadd.assert_called()
```

### 16.2 Database Migration Tests (`test_apply_migration.py`)

```python
import pytest
from scripts.apply_migration import MigrationRunner

class TestMigrationRunner:
    """Test database migration execution"""
    
    def test_apply_migration_success(self, mock_db_connection):
        """Test successful migration application"""
        # Arrange
        runner = MigrationRunner(mock_db_connection)
        migration_sql = "ALTER TABLE documents ADD COLUMN celery_task_id TEXT;"
        
        # Act
        result = runner.apply_migration('add_celery_task_id', migration_sql)
        
        # Assert
        assert result['success'] is True
        mock_db_connection.execute.assert_called_with(migration_sql)
        # Verify migration was recorded
        assert runner.is_migration_applied('add_celery_task_id')
    
    def test_migration_rollback(self, mock_db_connection):
        """Test migration rollback on failure"""
        # Arrange
        runner = MigrationRunner(mock_db_connection)
        mock_db_connection.execute.side_effect = Exception("Syntax error")
        
        # Act
        result = runner.apply_migration('bad_migration', 'INVALID SQL')
        
        # Assert
        assert result['success'] is False
        assert 'error' in result
        # Verify transaction was rolled back
        mock_db_connection.rollback.assert_called_once()
```

## 17. Coverage and Test Execution

### 17.1 Coverage Configuration Updates

```ini
# Updated pytest.ini for Celery testing
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --strict-markers --tb=short"
markers = [
    "e2e: End-to-end tests requiring live services",
    "slow: Tests that take more than 30 seconds",
    "redis: Tests requiring Redis",
    "aws: Tests requiring AWS services",
    "celery: Tests requiring Celery workers",
    "integration: Integration tests"
]

# Updated coverage configuration
[coverage:run]
source = ["scripts", "frontend", "monitoring"]
omit = [
    "*/tests/*", 
    "*/conftest.py",
    "*/migrations/*",
    "*/__pycache__/*"
]

[coverage:report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if TYPE_CHECKING:"
]
precision = 2
skip_covered = False
show_missing = True

[coverage:html]
directory = htmlcov
```

### 17.2 Test Execution Commands

```bash
# Run all tests including new Celery tests
pytest tests/ -v --cov=scripts --cov-report=term-missing --cov-report=html

# Run only Celery-related tests
pytest tests/ -v -m celery

# Run Celery tests with real broker (requires Redis)
CELERY_BROKER_URL=redis://localhost:6379 pytest tests/ -v -m "celery and integration"

# Run with parallel execution
pytest tests/ -v -n auto --cov=scripts

# Generate detailed coverage report
pytest tests/ --cov=scripts --cov=monitoring --cov-report=term-missing:skip-covered --cov-report=html --cov-fail-under=80
```

## Summary

This comprehensive testing guide now covers all critical components including the new Celery implementation:

1. **Unit Tests**: Individual component testing with mocks
2. **Integration Tests**: Cross-component interaction testing  
3. **E2E Tests**: Complete pipeline validation
4. **Performance Tests**: Load and efficiency testing
5. **Security Tests**: Authentication and validation testing
6. **Celery Task Tests**: All 4 task module testing
7. **Celery Worker Tests**: Worker management and health monitoring
8. **Queue Processor Tests**: Celery integration with queue processing
9. **Migration Tests**: Redis optimization and database migration testing

Key testing principles:
- Mock external services (AWS, OpenAI, Supabase, Celery)
- Test error scenarios and recovery
- Validate UUID consistency
- Ensure <5 minute processing time
- Maintain >95% cache hit rate
- Cover all pipeline stages including Celery tasks
- Test worker management and health monitoring
- Validate task routing and queue processing

The enhanced test suite ensures complete coverage of Phase 1 implementation with Celery integration, providing a robust foundation for reliable document processing.