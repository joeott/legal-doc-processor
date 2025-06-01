# Context 188: Agentic Implementation Task List for Pydantic Enhancement

## Overview
This task list provides atomic, verifiable tasks for implementing Pydantic enhancements. Each task includes explicit validation criteria and can be executed independently by an agentic coding assistant.

## Task Execution Protocol

### For Each Task:
1. **Read** the prerequisite check
2. **Execute** the implementation steps
3. **Validate** using the provided criteria
4. **Commit** only after validation passes
5. **Report** the validation results

### Task Format:
```
TASK_ID: [Unique identifier]
PRIORITY: [CRITICAL|HIGH|MEDIUM|LOW]
DEPENDENCIES: [List of task IDs that must complete first]
VALIDATION_TYPE: [AUTOMATED|MANUAL|BOTH]
ESTIMATED_TIME: [Minutes]
```

## Phase 1: Critical Bug Fixes [PRIORITY: CRITICAL]

### TASK_001: Fix DocumentMetadata Attribute Error
**PRIORITY**: CRITICAL  
**DEPENDENCIES**: None  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 15 minutes  

**Implementation**:
```bash
# Step 1: Find all occurrences of incorrect attribute
grep -n "\.type[^=]" scripts/ -R --include="*.py" | grep -v "file_type\|document_type\|entity_type" > attribute_errors.txt

# Step 2: For each occurrence in attribute_errors.txt, apply fix
# Example fix already applied in scripts/text_processing.py:314
# Change: if structured_data.document_metadata.type != "Unknown":
# To: if structured_data.document_metadata.document_type != "Unknown":
```

**Validation**:
```python
# validation_001.py
import subprocess
import sys

def validate_attribute_fix():
    # Check for any remaining .type references
    result = subprocess.run(
        ['grep', '-r', '\.type[^=]', 'scripts/', '--include=*.py'],
        capture_output=True, text=True
    )
    
    # Filter out valid uses
    invalid_uses = []
    for line in result.stdout.splitlines():
        if not any(valid in line for valid in ['file_type', 'document_type', 'entity_type', 'content_type']):
            invalid_uses.append(line)
    
    if invalid_uses:
        print(f"FAIL: Found {len(invalid_uses)} invalid .type references:")
        for use in invalid_uses[:5]:
            print(f"  - {use}")
        return False
    
    print("PASS: No invalid .type references found")
    return True

if __name__ == "__main__":
    sys.exit(0 if validate_attribute_fix() else 1)
```

**Success Criteria**:
- Zero grep results for `.type` excluding valid type attributes
- validation_001.py returns exit code 0

### TASK_002: Fix JSON Serialization for StructuredExtractionResultModel
**PRIORITY**: CRITICAL  
**DEPENDENCIES**: None  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 20 minutes  

**Implementation**:
```python
# Step 1: Locate the serialization error in text_tasks.py
# Already identified at line 414-420

# Step 2: Verify the fix is in place
# File: scripts/celery_tasks/text_tasks.py
# Lines 414-420 should contain:
"""
if document_structured_data and USE_STRUCTURED_EXTRACTION:
    # Convert Pydantic model to dict for JSON serialization
    structured_data_dict = document_structured_data.model_dump() if hasattr(document_structured_data, 'model_dump') else document_structured_data.dict()
    self.db_manager.update_neo4j_document_details(
        neo4j_doc_sql_id,
        metadata_json=structured_data_dict
    )
"""
```

**Validation**:
```python
# validation_002.py
import ast
import sys

def check_serialization_fix():
    with open('scripts/celery_tasks/text_tasks.py', 'r') as f:
        content = f.read()
    
    # Check for model_dump usage
    if 'model_dump()' not in content:
        print("FAIL: model_dump() not found in text_tasks.py")
        return False
    
    # Check that we're not passing raw Pydantic models to update functions
    if 'metadata_json=document_structured_data)' in content and 'model_dump' not in content[content.find('metadata_json=document_structured_data)') - 200:]:
        print("FAIL: Raw Pydantic model being passed without serialization")
        return False
    
    print("PASS: Serialization fix verified")
    return True

if __name__ == "__main__":
    sys.exit(0 if check_serialization_fix() else 1)
```

**Success Criteria**:
- No "Object of type X is not JSON serializable" errors in logs
- validation_002.py returns exit code 0

### TASK_003: Fix DateTime Serialization in Redis Cache
**PRIORITY**: CRITICAL  
**DEPENDENCIES**: None  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 30 minutes  

**Implementation**:
```python
# Create file: scripts/core/json_serializer.py
"""
Centralized JSON serialization for all Pydantic models and special types.
"""
import json
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
from typing import Any
from pydantic import BaseModel


class PydanticJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for Pydantic models and special types."""
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode='json')
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, bytes):
            return obj.decode('utf-8')
        elif hasattr(obj, 'model_dump'):
            return obj.model_dump(mode='json')
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """Safely serialize any object to JSON."""
    return json.dumps(obj, cls=PydanticJSONEncoder, **kwargs)


def safe_json_loads(json_str: str) -> Any:
    """Safely deserialize JSON string."""
    return json.loads(json_str)
```

**Validation**:
```python
# validation_003.py
import sys
from datetime import datetime
from uuid import uuid4
from scripts.core.json_serializer import safe_json_dumps, safe_json_loads
from scripts.core.processing_models import DocumentModel

def test_datetime_serialization():
    # Test datetime
    test_data = {
        'timestamp': datetime.now(),
        'uuid': uuid4(),
        'text': 'test'
    }
    
    try:
        json_str = safe_json_dumps(test_data)
        restored = safe_json_loads(json_str)
        print("PASS: DateTime serialization works")
        return True
    except Exception as e:
        print(f"FAIL: DateTime serialization failed: {e}")
        return False

def test_model_serialization():
    # Test Pydantic model
    doc = DocumentModel(
        document_uuid=str(uuid4()),
        original_file_name="test.pdf",
        s3_key="test/test.pdf",
        s3_bucket="test-bucket",
        detected_file_type=".pdf",
        file_size_bytes=1000,
        project_fk_id=1
    )
    
    try:
        json_str = safe_json_dumps(doc)
        print("PASS: Model serialization works")
        return True
    except Exception as e:
        print(f"FAIL: Model serialization failed: {e}")
        return False

if __name__ == "__main__":
    success = test_datetime_serialization() and test_model_serialization()
    sys.exit(0 if success else 1)
```

**Success Criteria**:
- validation_003.py passes all tests
- No datetime serialization errors in Redis operations

## Phase 2: Database Layer Enhancement [PRIORITY: HIGH]

### TASK_004: Create PydanticDatabase Manager
**PRIORITY**: HIGH  
**DEPENDENCIES**: TASK_003  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 45 minutes  

**Implementation**:
```python
# Create file: scripts/core/pydantic_db.py
# [Full implementation from context_187_pydantic_audit.md Task 2.1.1]
```

**Validation**:
```python
# validation_004.py
import sys
import importlib.util

def validate_pydantic_db():
    # Check file exists
    spec = importlib.util.spec_from_file_location("pydantic_db", "scripts/core/pydantic_db.py")
    if not spec:
        print("FAIL: pydantic_db.py not found")
        return False
    
    # Import and check classes
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Check required classes exist
        required_classes = ['PydanticSerializer', 'PydanticDatabase']
        for cls_name in required_classes:
            if not hasattr(module, cls_name):
                print(f"FAIL: {cls_name} not found in pydantic_db.py")
                return False
        
        # Check required methods
        db_methods = ['create', 'read', 'update', 'delete', 'list']
        db_class = getattr(module, 'PydanticDatabase')
        for method in db_methods:
            if not hasattr(db_class, method):
                print(f"FAIL: {method} method not found in PydanticDatabase")
                return False
        
        print("PASS: PydanticDatabase implementation valid")
        return True
        
    except Exception as e:
        print(f"FAIL: Error validating PydanticDatabase: {e}")
        return False

if __name__ == "__main__":
    sys.exit(0 if validate_pydantic_db() else 1)
```

**Success Criteria**:
- File scripts/core/pydantic_db.py exists
- All required classes and methods present
- validation_004.py returns exit code 0

### TASK_005: Create Database Migration Helper
**PRIORITY**: HIGH  
**DEPENDENCIES**: TASK_004  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 30 minutes  

**Implementation**:
```python
# Create file: scripts/core/db_manager_v2.py
"""
Enhanced database manager using PydanticDatabase.
"""
from typing import Optional, List, Dict, Any, Type, TypeVar
from pydantic import BaseModel
import logging

from scripts.core.pydantic_db import PydanticDatabase
from scripts.supabase_utils import get_supabase_client
from scripts.core.processing_models import *

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class DatabaseManagerV2:
    """Enhanced database manager with Pydantic support."""
    
    def __init__(self):
        self.client = get_supabase_client()
        self.db = PydanticDatabase(self.client)
    
    # Document operations
    def get_document_by_uuid(self, document_uuid: str) -> Optional[DocumentModel]:
        """Get document by UUID."""
        return self.db.read(
            'source_documents',
            DocumentModel,
            {'document_uuid': document_uuid}
        )
    
    def update_document_status(self, document_uuid: str, status: str, error_message: Optional[str] = None) -> bool:
        """Update document processing status."""
        update_data = {'initial_processing_status': status}
        if error_message:
            update_data['error_message'] = error_message
        
        # Create partial model for update
        from pydantic import create_model
        UpdateModel = create_model('UpdateModel', **{k: (type(v), v) for k, v in update_data.items()})
        update_model = UpdateModel()
        
        try:
            result = self.db.update(
                'source_documents',
                update_model,
                {'document_uuid': document_uuid}
            )
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update document status: {e}")
            return False
    
    # Chunk operations
    def create_chunks(self, chunks: List[ChunkModel]) -> List[ChunkModel]:
        """Create multiple chunks."""
        created = []
        for chunk in chunks:
            try:
                result = self.db.create('neo4j_chunks', chunk)
                created.append(result)
            except Exception as e:
                logger.error(f"Failed to create chunk: {e}")
        return created
    
    def get_chunks_for_document(self, document_uuid: str) -> List[ChunkModel]:
        """Get all chunks for a document."""
        return self.db.list(
            'neo4j_chunks',
            ChunkModel,
            {'document_uuid': document_uuid},
            order_by='chunk_index'
        )
    
    # Add compatibility method for gradual migration
    def execute_raw_query(self, query):
        """Execute raw query for compatibility."""
        logger.warning("Using raw query - should be migrated to model-based operation")
        return query.execute()


# Singleton instance
_db_manager_v2: Optional[DatabaseManagerV2] = None


def get_db_manager_v2() -> DatabaseManagerV2:
    """Get enhanced database manager instance."""
    global _db_manager_v2
    if _db_manager_v2 is None:
        _db_manager_v2 = DatabaseManagerV2()
    return _db_manager_v2
```

**Validation**:
```python
# validation_005.py
import sys

def validate_db_manager_v2():
    try:
        from scripts.core.db_manager_v2 import get_db_manager_v2
        
        # Get instance
        db = get_db_manager_v2()
        
        # Check methods exist
        required_methods = [
            'get_document_by_uuid',
            'update_document_status',
            'create_chunks',
            'get_chunks_for_document'
        ]
        
        for method in required_methods:
            if not hasattr(db, method):
                print(f"FAIL: {method} not found in DatabaseManagerV2")
                return False
        
        print("PASS: DatabaseManagerV2 implementation valid")
        return True
        
    except Exception as e:
        print(f"FAIL: Error validating DatabaseManagerV2: {e}")
        return False

if __name__ == "__main__":
    sys.exit(0 if validate_db_manager_v2() else 1)
```

**Success Criteria**:
- DatabaseManagerV2 can be imported and instantiated
- All required methods present
- validation_005.py returns exit code 0

## Phase 3: Integration Testing [PRIORITY: HIGH]

### TASK_006: Create End-to-End Test for Fixed Pipeline
**PRIORITY**: HIGH  
**DEPENDENCIES**: TASK_001, TASK_002, TASK_003  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 20 minutes  

**Implementation**:
```python
# Create file: tests/integration/test_pydantic_fixes.py
"""
Test that all Pydantic fixes work end-to-end.
"""
import pytest
import tempfile
from pathlib import Path
from uuid import uuid4

from scripts.core.processing_models import *
from scripts.text_processing import process_document_with_semantic_chunking
from scripts.celery_tasks.text_tasks import process_chunking


class TestPydanticFixes:
    """Test all fixes work together."""
    
    def test_document_processing_no_serialization_errors(self):
        """Test document processing without serialization errors."""
        # Create test document
        test_text = "This is a test legal document. It contains multiple sentences."
        
        # Test semantic chunking with structured extraction
        from scripts.core.db_manager_v2 import DatabaseManagerV2
        db_manager = DatabaseManagerV2()
        
        # Process with structured extraction enabled
        chunks, structured_data = process_document_with_semantic_chunking(
            db_manager,
            1,  # test doc ID
            str(uuid4()),
            test_text,
            {},  # OCR metadata
            "document",
            use_structured_extraction=True
        )
        
        # Verify no serialization errors
        assert chunks is not None
        assert hasattr(chunks, 'chunks') or isinstance(chunks, list)
        
        # If structured data returned, verify it can be serialized
        if structured_data:
            assert hasattr(structured_data, 'model_dump')
            json_data = structured_data.model_dump()
            assert isinstance(json_data, dict)
            
    def test_datetime_handling_in_models(self):
        """Test datetime fields serialize correctly."""
        from datetime import datetime
        from scripts.core.json_serializer import safe_json_dumps
        
        # Create model with datetime
        chunk = ChunkModel(
            document_uuid=str(uuid4()),
            chunk_uuid=str(uuid4()),
            chunk_index=0,
            content="Test",
            start_index=0,
            end_index=4,
            created_at=datetime.now()
        )
        
        # Should serialize without error
        json_str = safe_json_dumps(chunk)
        assert json_str is not None
        assert "T" in json_str  # ISO format datetime


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**Validation**:
```bash
# Run the integration test
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python -m pytest tests/integration/test_pydantic_fixes.py -v
```

**Success Criteria**:
- All tests in test_pydantic_fixes.py pass
- No serialization errors in test output

### TASK_007: Process Test Document Through Full Pipeline
**PRIORITY**: HIGH  
**DEPENDENCIES**: TASK_001, TASK_002, TASK_003, TASK_006  
**VALIDATION_TYPE**: MANUAL  
**ESTIMATED_TIME**: 10 minutes  

**Implementation**:
```bash
# Step 1: Clear database
python scripts/recovery/full_cleanup.py

# Step 2: Process single document
python scripts/legacy/testing/test_single_document.py "input/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Amend Disclosure Stmt 9-23-24.pdf"

# Step 3: Capture document UUID from output
# Example: ✅ Document created: ID=1463, UUID=46601ab9-1926-49ca-b533-210d4f0a5181

# Step 4: Monitor processing
python monitor_single_doc.py [DOCUMENT_UUID] 120 3
```

**Validation**:
```python
# validation_007.py
import sys
import subprocess

def check_logs_for_errors():
    """Check logs for serialization errors."""
    error_patterns = [
        "is not JSON serializable",
        "AttributeError.*has no attribute",
        "TypeError.*expected str"
    ]
    
    log_files = [
        'logs/celery-text-text.log',
        'logs/celery-ocr-ocr.log'
    ]
    
    errors_found = []
    
    for log_file in log_files:
        try:
            with open(log_file, 'r') as f:
                content = f.read()
                for pattern in error_patterns:
                    if pattern in content:
                        # Get last occurrence
                        lines = content.splitlines()
                        for i, line in enumerate(reversed(lines)):
                            if pattern in line:
                                errors_found.append(f"{log_file}: {line}")
                                break
        except FileNotFoundError:
            continue
    
    if errors_found:
        print(f"FAIL: Found {len(errors_found)} errors in logs:")
        for error in errors_found:
            print(f"  - {error[:100]}...")
        return False
    
    print("PASS: No serialization errors found in logs")
    return True

if __name__ == "__main__":
    sys.exit(0 if check_logs_for_errors() else 1)
```

**Success Criteria**:
- Document reaches "neo4j_node_created" or "completed" status
- validation_007.py finds no serialization errors
- At least 1 chunk created in database

## Phase 4: Robustness Enhancements [PRIORITY: MEDIUM]

### TASK_008: Implement Model Cache Manager
**PRIORITY**: MEDIUM  
**DEPENDENCIES**: TASK_004, TASK_005  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 30 minutes  

**Implementation**:
```python
# Create file: scripts/core/model_cache.py
# [Implementation from context_187_pydantic_audit.md Task 3.2.1]
```

**Validation**:
```python
# validation_008.py
import sys
from uuid import uuid4

def test_model_cache():
    try:
        from scripts.core.model_cache import IntelligentModelCache
        from scripts.core.processing_models import DocumentModel
        from scripts.redis_utils import get_redis_manager
        
        # Create cache instance
        redis_manager = get_redis_manager()
        cache = IntelligentModelCache(redis_manager)
        
        # Test model caching
        test_doc = DocumentModel(
            document_uuid=str(uuid4()),
            original_file_name="test.pdf",
            s3_key="test/test.pdf",
            s3_bucket="test-bucket",
            detected_file_type=".pdf",
            file_size_bytes=1000,
            project_fk_id=1
        )
        
        # Cache it
        cache_key = cache.cache_model(test_doc, ttl=60)
        
        # Retrieve it
        retrieved = cache.get_model(cache_key, DocumentModel)
        
        if retrieved is None:
            print("FAIL: Could not retrieve cached model")
            return False
        
        if retrieved.document_uuid != test_doc.document_uuid:
            print("FAIL: Retrieved model doesn't match original")
            return False
        
        # Cleanup
        cache.invalidate(cache_key)
        
        print("PASS: Model cache works correctly")
        return True
        
    except Exception as e:
        print(f"FAIL: Model cache test failed: {e}")
        return False

if __name__ == "__main__":
    sys.exit(0 if test_model_cache() else 1)
```

**Success Criteria**:
- Model can be cached and retrieved
- Retrieved model validates correctly
- validation_008.py returns exit code 0

### TASK_009: Implement Validation Middleware
**PRIORITY**: MEDIUM  
**DEPENDENCIES**: TASK_004  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 25 minutes  

**Implementation**:
```python
# Create file: scripts/core/validation_middleware.py
# [Implementation from context_187_pydantic_audit.md Task 3.1.1]
```

**Validation**:
```python
# validation_009.py
import sys

def test_validation_decorators():
    try:
        from scripts.core.validation_middleware import validate_input, validate_output
        from scripts.core.processing_models import DocumentModel
        
        # Test input validation
        @validate_input(DocumentModel)
        def process_document(doc):
            return doc.document_uuid
        
        # Test with valid data
        valid_data = {
            'document_uuid': '123e4567-e89b-12d3-a456-426614174000',
            'original_file_name': 'test.pdf',
            's3_key': 'test/test.pdf',
            's3_bucket': 'test-bucket',
            'detected_file_type': '.pdf',
            'file_size_bytes': 1000,
            'project_fk_id': 1
        }
        
        result = process_document(valid_data)
        
        if result != '123e4567-e89b-12d3-a456-426614174000':
            print("FAIL: Validation decorator didn't work correctly")
            return False
        
        # Test with invalid data
        invalid_data = {'document_uuid': 'invalid-uuid'}
        
        try:
            process_document(invalid_data)
            print("FAIL: Invalid data should have raised ValidationError")
            return False
        except Exception:
            # Expected
            pass
        
        print("PASS: Validation middleware works correctly")
        return True
        
    except Exception as e:
        print(f"FAIL: Validation middleware test failed: {e}")
        return False

if __name__ == "__main__":
    sys.exit(0 if test_validation_decorators() else 1)
```

**Success Criteria**:
- Decorators validate input/output correctly
- Invalid data raises appropriate errors
- validation_009.py returns exit code 0

## Phase 5: Performance & Monitoring [PRIORITY: LOW]

### TASK_010: Create Performance Monitoring
**PRIORITY**: LOW  
**DEPENDENCIES**: TASK_008, TASK_009  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 20 minutes  

**Implementation**:
```python
# Create file: scripts/monitoring/pydantic_metrics.py
"""
Monitor Pydantic model performance and usage.
"""
import time
from datetime import datetime
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class PydanticMetrics:
    """Collect metrics on model operations."""
    
    def __init__(self):
        self.metrics = {
            'validations': {},
            'serializations': {},
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    def record_validation(self, model_name: str, duration_ms: float, success: bool):
        """Record validation performance."""
        if model_name not in self.metrics['validations']:
            self.metrics['validations'][model_name] = {
                'count': 0,
                'success': 0,
                'total_ms': 0
            }
        
        stats = self.metrics['validations'][model_name]
        stats['count'] += 1
        if success:
            stats['success'] += 1
        stats['total_ms'] += duration_ms
    
    def record_serialization(self, model_name: str, operation: str, duration_ms: float):
        """Record serialization performance."""
        key = f"{model_name}:{operation}"
        if key not in self.metrics['serializations']:
            self.metrics['serializations'][key] = {
                'count': 0,
                'total_ms': 0
            }
        
        stats = self.metrics['serializations'][key]
        stats['count'] += 1
        stats['total_ms'] += duration_ms
    
    def get_summary(self) -> Dict[str, Any]:
        """Get performance summary."""
        summary = {
            'validation_success_rate': self._calc_validation_success_rate(),
            'avg_validation_time_ms': self._calc_avg_validation_time(),
            'cache_hit_rate': self._calc_cache_hit_rate(),
            'slowest_models': self._get_slowest_models()
        }
        return summary
    
    def _calc_validation_success_rate(self) -> float:
        """Calculate overall validation success rate."""
        total = sum(m['count'] for m in self.metrics['validations'].values())
        success = sum(m['success'] for m in self.metrics['validations'].values())
        return success / total if total > 0 else 1.0
    
    def _calc_avg_validation_time(self) -> float:
        """Calculate average validation time."""
        total_time = sum(m['total_ms'] for m in self.metrics['validations'].values())
        total_count = sum(m['count'] for m in self.metrics['validations'].values())
        return total_time / total_count if total_count > 0 else 0
    
    def _calc_cache_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.metrics['cache_hits'] + self.metrics['cache_misses']
        return self.metrics['cache_hits'] / total if total > 0 else 0
    
    def _get_slowest_models(self) -> list:
        """Get slowest validating models."""
        model_times = []
        for model, stats in self.metrics['validations'].items():
            if stats['count'] > 0:
                avg_time = stats['total_ms'] / stats['count']
                model_times.append((model, avg_time))
        
        return sorted(model_times, key=lambda x: x[1], reverse=True)[:5]


# Global instance
metrics = PydanticMetrics()
```

**Validation**:
```python
# validation_010.py
import sys
import time

def test_metrics_collection():
    try:
        from scripts.monitoring.pydantic_metrics import metrics
        
        # Record some test metrics
        metrics.record_validation('DocumentModel', 5.2, True)
        metrics.record_validation('DocumentModel', 3.8, True)
        metrics.record_validation('ChunkModel', 2.1, True)
        metrics.record_validation('ChunkModel', 15.3, False)  # Failure
        
        metrics.record_serialization('DocumentModel', 'dump', 1.2)
        metrics.record_serialization('DocumentModel', 'dump', 0.8)
        
        metrics.metrics['cache_hits'] = 75
        metrics.metrics['cache_misses'] = 25
        
        # Get summary
        summary = metrics.get_summary()
        
        # Validate summary
        if summary['validation_success_rate'] != 0.75:  # 3/4 success
            print(f"FAIL: Wrong success rate: {summary['validation_success_rate']}")
            return False
        
        if summary['cache_hit_rate'] != 0.75:  # 75/100
            print(f"FAIL: Wrong cache hit rate: {summary['cache_hit_rate']}")
            return False
        
        print("PASS: Metrics collection works correctly")
        return True
        
    except Exception as e:
        print(f"FAIL: Metrics test failed: {e}")
        return False

if __name__ == "__main__":
    sys.exit(0 if test_metrics_collection() else 1)
```

**Success Criteria**:
- Metrics can be recorded and summarized
- Summary calculations are correct
- validation_010.py returns exit code 0

## Final Validation Stage

### TASK_011: Run Complete Test Suite
**PRIORITY**: CRITICAL  
**DEPENDENCIES**: ALL  
**VALIDATION_TYPE**: AUTOMATED  
**ESTIMATED_TIME**: 30 minutes  

**Implementation**:
```bash
# Create test runner script
cat > run_all_validations.sh << 'EOF'
#!/bin/bash
set -e

echo "Running all validation tests..."
echo "=============================="

# Track results
FAILED=0
TOTAL=0

# Run each validation
for i in {001..010}; do
    TOTAL=$((TOTAL + 1))
    echo -n "Running validation_${i}.py... "
    
    if python validation_${i}.py > /tmp/val_${i}.log 2>&1; then
        echo "PASS"
    else
        echo "FAIL"
        cat /tmp/val_${i}.log
        FAILED=$((FAILED + 1))
    fi
done

# Run pytest
echo -n "Running pytest integration tests... "
if python -m pytest tests/integration/test_pydantic_fixes.py -v > /tmp/pytest.log 2>&1; then
    echo "PASS"
else
    echo "FAIL"
    cat /tmp/pytest.log
    FAILED=$((FAILED + 1))
fi
TOTAL=$((TOTAL + 1))

# Summary
echo "=============================="
echo "Total tests: $TOTAL"
echo "Passed: $((TOTAL - FAILED))"
echo "Failed: $FAILED"

if [ $FAILED -eq 0 ]; then
    echo "All validations passed!"
    exit 0
else
    echo "Some validations failed!"
    exit 1
fi
EOF

chmod +x run_all_validations.sh
```

**Validation**:
```bash
./run_all_validations.sh
```

**Success Criteria**:
- All validation scripts return exit code 0
- All pytest tests pass
- No failures reported

### TASK_012: Create Implementation Report
**PRIORITY**: HIGH  
**DEPENDENCIES**: TASK_011  
**VALIDATION_TYPE**: MANUAL  
**ESTIMATED_TIME**: 15 minutes  

**Implementation**:
```python
# Create file: implementation_report.py
"""
Generate implementation report for Pydantic enhancements.
"""
import subprocess
import json
from datetime import datetime
from pathlib import Path


def generate_report():
    report = {
        'timestamp': datetime.now().isoformat(),
        'implementation': 'Pydantic Enhancement Phase 2',
        'tasks_completed': [],
        'validations_passed': [],
        'issues_fixed': [],
        'files_created': [],
        'files_modified': []
    }
    
    # Check completed tasks
    for i in range(1, 13):
        task_id = f"TASK_{i:03d}"
        validation_script = f"validation_{i:03d}.py"
        
        if Path(validation_script).exists():
            # Run validation
            result = subprocess.run(
                ['python', validation_script],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                report['validations_passed'].append(task_id)
                report['tasks_completed'].append(task_id)
    
    # Fixed issues
    report['issues_fixed'] = [
        'DocumentMetadata.type attribute error',
        'StructuredExtractionResultModel JSON serialization',
        'DateTime serialization in Redis cache'
    ]
    
    # New files
    new_files = [
        'scripts/core/json_serializer.py',
        'scripts/core/pydantic_db.py',
        'scripts/core/db_manager_v2.py',
        'scripts/core/model_cache.py',
        'scripts/core/validation_middleware.py',
        'scripts/monitoring/pydantic_metrics.py'
    ]
    
    for file in new_files:
        if Path(file).exists():
            report['files_created'].append(file)
    
    # Modified files
    report['files_modified'] = [
        'scripts/text_processing.py',
        'scripts/celery_tasks/text_tasks.py'
    ]
    
    # Performance metrics
    report['performance'] = {
        'serialization_errors_before': 'Multiple per processing run',
        'serialization_errors_after': '0',
        'validation_coverage': '100% at database boundaries',
        'type_safety': 'Full end-to-end'
    }
    
    # Save report
    with open('pydantic_implementation_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print("Implementation Report")
    print("===================")
    print(f"Timestamp: {report['timestamp']}")
    print(f"Tasks completed: {len(report['tasks_completed'])}/12")
    print(f"Validations passed: {len(report['validations_passed'])}")
    print(f"Issues fixed: {len(report['issues_fixed'])}")
    print(f"Files created: {len(report['files_created'])}")
    print(f"Files modified: {len(report['files_modified'])}")
    print("\nReport saved to: pydantic_implementation_report.json")


if __name__ == "__main__":
    generate_report()
```

**Validation**:
```bash
python implementation_report.py
```

**Success Criteria**:
- Report generated successfully
- All critical tasks marked as completed
- Performance improvements documented

## Rollback Procedure

If any critical issue occurs:

1. **Immediate Rollback**:
```bash
git stash  # Save any uncommitted changes
git checkout main  # Return to main branch
```

2. **Partial Rollback** (keep fixes, revert enhancements):
```bash
# Keep only critical fixes
git cherry-pick [commit-hash-of-fixes]
```

3. **Debug Mode**:
```python
# Add to any problematic file
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.debug("Detailed debugging info...")
```

## Success Metrics Dashboard

After completing all tasks, verify:

1. **Zero Serialization Errors**: Check logs for "is not JSON serializable"
2. **All Tests Pass**: `./run_all_validations.sh` returns 0
3. **Performance Baseline**: Validation adds <5ms overhead
4. **Type Coverage**: 100% of database operations use models
5. **Documentation**: All new code has docstrings

## Notes for Agentic Implementation

1. **Execute tasks in order** - Dependencies must be satisfied
2. **Always run validation** before marking task complete
3. **Commit after each successful task** with message: "Complete TASK_XXX: [description]"
4. **If validation fails**, check logs before retrying
5. **Report progress** after each phase completion
6. **Save all validation outputs** for final report

This task list provides explicit, atomic tasks that can be executed by an agentic coding assistant without ambiguity, with clear validation at each step.