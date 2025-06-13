# Context 481: Data Clearing Scripts Implementation

## Date: 2025-01-09

### Summary
Created comprehensive data clearing scripts for Redis cache and RDS database to enable fresh starts during development and testing.

### Scripts Created

#### 1. clear_redis_cache.py
- **Purpose**: Clear all Redis cache entries
- **Features**:
  - Clears all document-related keys (doc:*)
  - Clears entity, chunk, LLM, OCR, and other cache patterns
  - Uses SCAN for efficient batch deletion
  - Optional --flush-all flag for complete database flush
  - Loads environment from .env automatically
  - Shows statistics of deleted keys

#### 2. clear_rds_test_data.py
- **Purpose**: Clear all test data from RDS database while preserving schema
- **Features**:
  - Clears data from all tables in dependency order
  - Preserves database schema and structure
  - Resets sequences for PostgreSQL
  - Optional --documents flag to clear specific documents only
  - --confirm flag to skip confirmation prompts
  - Shows row counts before and after clearing

### Implementation Details

#### Redis Clearing Results
```
Total keys deleted: 17
Remaining keys in Redis: 2771
```
- Successfully cleared all document processing related keys
- Other keys preserved (likely system/framework keys)

#### RDS Clearing Results
```
Total rows deleted: 242
Tables cleared:
- relationship_staging: 110 rows
- canonical_entities: 22 rows
- entity_mentions: 33 rows
- document_chunks: 32 rows
- textract_jobs: 8 rows
- source_documents: 12 rows
- projects: 25 rows
- processing_tasks: 0 rows (already empty)
```

### Key Improvements
1. **Automatic Environment Loading**: Both scripts now use python-dotenv to load .env file
2. **Proper Session Management**: Fixed database session handling for RDS script
3. **Foreign Key Handling**: Adjusted for RDS user permissions (no superuser privileges)
4. **Comprehensive Clearing**: Covers all cache patterns and database tables
5. **Safety Features**: Confirmation prompts and statistics reporting

### Usage
```bash
# Clear all Redis cache
python3 clear_redis_cache.py

# Clear with full database flush (use with caution)
python3 clear_redis_cache.py --flush-all

# Clear all RDS data
python3 clear_rds_test_data.py

# Clear without confirmation prompt
python3 clear_rds_test_data.py --confirm

# Clear specific documents only
python3 clear_rds_test_data.py --documents uuid1 uuid2 uuid3
```

### Next Steps
With clean Redis cache and RDS database, the system is ready for:
1. Fresh document processing tests
2. Pipeline verification
3. Performance benchmarking
4. Integration testing

The clearing scripts are now part of the standard toolkit for maintaining a clean test environment.