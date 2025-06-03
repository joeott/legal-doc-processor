# API Mismatches Found and Correct Usage

## Date: 2025-06-03

### Overview
Found several API mismatches in the codebase where code is calling methods that don't exist or using incorrect method names.

### 1. S3StorageManager Methods

**Incorrect Usage:**
```python
s3_storage.upload_document(...)  # This method doesn't exist
s3_storage.upload_file(...)      # This method doesn't exist
```

**Correct Usage:**
```python
# From scripts/s3_storage.py
s3_storage = S3StorageManager()
result = s3_storage.upload_document_with_uuid_naming(
    local_file_path="/path/to/file.pdf",
    document_uuid="uuid-string",
    original_filename="original_name.pdf"
)
```

**Available Methods:**
- `upload_document_with_uuid_naming(local_file_path, document_uuid, original_filename)`
- `get_s3_document_location(s3_key, s3_bucket=None, version_id=None)`
- `check_s3_object_exists(s3_key, s3_bucket=None)`

### 2. RedisManager Methods

**Incorrect Usage:**
```python
redis_manager.set(key, value)              # Doesn't exist
redis_manager.get(key)                     # Doesn't exist
redis_manager.cache_ocr_result(...)        # Doesn't exist
redis_manager.get_cached_ocr_result(...)   # Doesn't exist
```

**Correct Usage:**
```python
# From scripts/cache.py
redis_manager = get_redis_manager()

# Setting values
redis_manager.set_cached(key, value, ttl=3600)

# Getting values
value = redis_manager.get_cached(key)

# For dictionaries specifically
redis_manager.store_dict(key, dict_value, ttl=3600)
dict_value = redis_manager.get_dict(key)

# For OCR results (compatibility methods)
redis_manager.cache_ocr_result(key, ocr_data, ttl=3600)
ocr_result = redis_manager.get_cached_ocr_result(key)
```

**Available Methods:**
- `set_cached(key, value, ttl=None)`
- `get_cached(key)`
- `delete(key)`
- `exists(key)`
- `store_dict(key, value, ttl=None)` - Compatibility wrapper
- `get_dict(key)` - Compatibility wrapper
- `cache_ocr_result(key, ocr_data, ttl=None)` - Compatibility wrapper
- `get_cached_ocr_result(key)` - Compatibility wrapper

### 3. EntityService Methods

**Incorrect Usage:**
```python
from scripts.entity_service import EntityExtractionService  # Class doesn't exist
service = EntityExtractionService()
```

**Correct Usage:**
```python
from scripts.entity_service import EntityService
from scripts.db import DatabaseManager

db = DatabaseManager()
service = EntityService(db)

# Extract entities
result = service.extract_entities_from_chunk(
    chunk_text="text to analyze",
    chunk_uuid=uuid.UUID(...),
    document_uuid="document-uuid-string"
)

# Access results
entities = result.entity_mentions  # List of EntityMentionModel instances
```

### 4. Database/SQLAlchemy Usage

**Incorrect Usage:**
```python
session.execute("SELECT version()")  # Raw SQL string
```

**Correct Usage:**
```python
from sqlalchemy import text
session.execute(text("SELECT version()"))
```

### 5. TextractProcessor Methods

**Note:** The `get_cached_ocr_result` method DOES exist in TextractProcessor class:
```python
# From scripts/textract_utils.py
textract_processor = TextractProcessor(db_manager)
cached_result = textract_processor.get_cached_ocr_result(document_uuid)
# Returns: Optional[Tuple[str, Dict[str, Any]]]
```

### 6. Missing Imports

Several modules are missing or need to be created:
- `scripts.entity_extraction_fixes` - Referenced but doesn't exist
- `ConformanceError` - Should be imported from `scripts.core.conformance_validator`

### Recommendations

1. **Update all S3 upload calls** to use `upload_document_with_uuid_naming`
2. **Update all Redis calls** to use `set_cached`/`get_cached` or the compatibility wrappers
3. **Fix EntityService imports** and instantiation with DatabaseManager
4. **Add missing imports** for ConformanceError and create entity_extraction_fixes if needed
5. **Wrap all raw SQL** in `text()` calls for SQLAlchemy 2.0 compatibility