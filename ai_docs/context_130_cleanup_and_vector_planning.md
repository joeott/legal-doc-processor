# Context 130: Database Cleanup Implementation & Vector Embeddings Planning

## Part 1: Database Cleanup Implementation Complete

### Summary
Successfully implemented comprehensive database cleanup and project installation functionality to support iterative processing of legal case documents. This allows complete data erasure and fresh installation of individual projects.

### Key Implementations

#### 1. Database Cleanup Functions (supabase_utils.py)
Added two new methods to SupabaseManager class:

```python
def cleanup_all_data(self, confirm: bool = False) -> Dict[str, int]:
    """Complete cleanup of all data in the database"""
    
def cleanup_project_data(self, project_id: str) -> Dict[str, int]:
    """Clean up all data for a specific project"""
```

**Key Features:**
- Respects foreign key constraints with correct deletion order
- Uses service role key for RLS-protected tables (neo4j_relationships_staging)
- Batch deletion for large tables (>1000 rows)
- Redis cache clearing integration
- Returns deletion counts by table

**Deletion Order (Child → Parent):**
1. neo4j_relationships_staging
2. neo4j_entity_mentions
3. neo4j_chunks
4. neo4j_canonical_entities
5. document_processing_history
6. document_processing_queue
7. textract_jobs
8. neo4j_documents
9. source_documents
10. projects

#### 2. Interactive Cleanup Script (cleanup_database.py)
**Features:**
- `--stats`: Show current database statistics
- `--all`: Delete all data (requires double confirmation)
- `--project <uuid>`: Delete specific project data
- `--force`: Skip confirmations (dangerous)
- Creates timestamped backup info files
- Two-step confirmation with "YES" requirement

#### 3. Project Installation Script (install_project.py)
**Features:**
- Batch document processing by project/case
- Automatic project creation/retrieval
- Duplicate detection and skipping
- Real-time progress monitoring
- Comprehensive JSON reporting
- Support for all document types (PDF, DOCX, TXT, audio)

**Usage:**
```bash
python install_project.py --name "Case Name" --dir /path/to/docs [--id custom-id] [--timeout 3600] [--no-monitor]
```

#### 4. Documentation (DATABASE_MANAGEMENT_GUIDE.md)
- Safety warnings and best practices
- Step-by-step workflows
- Example directory structures
- Troubleshooting guide
- Python API usage examples

## Part 2: Vector Embeddings Planning

### Overview
Implement vector embeddings for semantic understanding and similarity search across document chunks using OpenAI's text-embedding-3-large model (3072 dimensions).

### Architecture Design

#### 1. Database Schema
```sql
-- New table for storing chunk embeddings
CREATE TABLE chunk_embeddings (
    id SERIAL PRIMARY KEY,
    chunk_id UUID NOT NULL REFERENCES neo4j_chunks(chunkId),
    embedding vector(3072) NOT NULL,  -- Using pgvector extension
    model_name VARCHAR(100) DEFAULT 'text-embedding-3-large',
    model_version VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processing_version INTEGER DEFAULT 1,
    
    -- Indexes for performance
    CONSTRAINT chunk_embeddings_chunk_id_version_key UNIQUE(chunk_id, processing_version)
);

-- Enable vector similarity search
CREATE INDEX chunk_embeddings_embedding_idx ON chunk_embeddings 
USING ivfflat (embedding vector_cosine_ops);

-- Performance indexes
CREATE INDEX idx_chunk_embeddings_chunk_id ON chunk_embeddings(chunk_id);
CREATE INDEX idx_chunk_embeddings_created_at ON chunk_embeddings(created_at);
```

#### 2. Celery Task Structure

##### New Task: generate_chunk_embeddings
```python
# scripts/celery_tasks/embedding_tasks.py

@app.task(bind=True, base=EmbeddingTask, max_retries=3)
def generate_chunk_embeddings(self, chunk_uuids: List[str], 
                            document_uuid: str, 
                            processing_version: int = 1) -> Dict[str, Any]:
    """
    Generate embeddings for document chunks using OpenAI text-embedding-3-large.
    
    This task should be chained after process_chunking in the pipeline:
    process_chunking → generate_chunk_embeddings → extract_entities
    """
```

##### Integration Points:
1. **After Chunking**: Chain immediately after chunk creation
2. **Parallel Processing**: Can run alongside entity extraction
3. **Caching Strategy**: Store in Redis with vector-specific keys

#### 3. Redis Vector Integration

##### Caching Strategy:
```python
# Cache individual chunk embeddings
chunk_embedding_key = f"emb:chunk:{chunk_uuid}:v{version}"

# Cache document-level aggregated embedding (mean pooling)
doc_embedding_key = f"emb:doc:{document_uuid}:v{version}"

# Use Redis vector similarity features for fast retrieval
# Store as packed numpy arrays for efficiency
```

##### Redis Vector Features to Utilize:
1. **Vector Similarity Search**: Find similar chunks across documents
2. **Nearest Neighbor Queries**: For entity resolution assistance
3. **Clustered Caching**: Group similar embeddings for batch operations

#### 4. Implementation Strategy

##### Phase 1: Basic Embedding Generation
```python
def generate_embeddings_for_chunks(chunks: List[Dict], model="text-embedding-3-large"):
    """
    Generate embeddings using OpenAI API with batching for efficiency.
    
    Optimizations:
    - Batch API calls (up to 100 chunks per request)
    - Retry logic for transient failures
    - Progress tracking via Redis
    """
```

##### Phase 2: Storage and Retrieval
```python
def store_chunk_embedding(chunk_id: str, embedding: np.ndarray, 
                         model_info: Dict, db_manager: SupabaseManager):
    """
    Store embedding in Supabase with proper indexing.
    Also cache in Redis for fast access.
    """
```

##### Phase 3: Similarity Operations
```python
def find_similar_chunks(query_embedding: np.ndarray, 
                       top_k: int = 10, 
                       threshold: float = 0.8):
    """
    Find semantically similar chunks using cosine similarity.
    Useful for deduplication and context retrieval.
    """
```

### Downstream Process Integration

#### 1. Entity Resolution Enhancement
**Current Process**: String matching and fuzzy matching
**Enhancement with Vectors**:
- Calculate semantic similarity between entity mentions
- Use embeddings to identify conceptually similar entities
- Improve cross-document entity linking

```python
def enhanced_entity_resolution(mention: str, mention_embedding: np.ndarray,
                             canonical_entities: List[Dict]) -> str:
    """
    Combine string similarity with semantic similarity.
    Weight: 70% semantic, 30% string matching.
    """
```

#### 2. Relationship Extraction Context
**Current Process**: Rule-based extraction from entity co-occurrence
**Enhancement with Vectors**:
- Use chunk embeddings to understand semantic context
- Identify implicit relationships through similarity
- Cluster related chunks for better context understanding

#### 3. Semantic Search Capabilities
**New Capability**: Enable semantic search across all documents
- Find similar passages across cases
- Identify related legal concepts
- Support precedent research

### Technical Considerations

#### 1. Performance Optimization
- **Batch Processing**: Process 50-100 chunks per API call
- **Async Operations**: Use asyncio for concurrent API calls
- **Caching**: Aggressive Redis caching with 24-hour TTL
- **Compression**: Store compressed embeddings in Supabase

#### 2. Cost Management
- **API Costs**: ~$0.13 per 1M tokens for text-embedding-3-large
- **Estimation**: ~1-2K tokens per chunk = ~$0.00013-0.00026 per chunk
- **Optimization**: Cache aggressively, batch efficiently

#### 3. Error Handling
- **Rate Limiting**: Exponential backoff for OpenAI API
- **Partial Failures**: Process chunks individually on batch failure
- **Versioning**: Support re-embedding with new models

### Implementation Priorities

#### Priority 1: Core Embedding Pipeline
1. Create Celery task for embedding generation
2. Implement Supabase storage with pgvector
3. Add Redis caching layer
4. Chain into existing pipeline after chunking

#### Priority 2: Entity Resolution Enhancement
1. Modify entity resolution to use semantic similarity
2. Create hybrid scoring function
3. Test improvement in entity matching accuracy

#### Priority 3: Advanced Features
1. Semantic search API endpoints
2. Similarity-based deduplication
3. Cross-document relationship discovery
4. Cluster analysis for topic modeling

### Success Metrics
1. **Embedding Coverage**: 100% of chunks have embeddings
2. **Processing Speed**: <2 seconds per document (excluding API calls)
3. **Cache Hit Rate**: >80% for frequently accessed documents
4. **Entity Resolution**: >20% improvement in cross-document matching
5. **Storage Efficiency**: <100KB per document (compressed embeddings)

### Risk Mitigation
1. **API Failures**: Implement robust retry with circuit breaker
2. **Cost Overruns**: Set daily/monthly limits, monitor usage
3. **Storage Growth**: Implement embedding expiration for old versions
4. **Performance**: Use connection pooling, batch operations

### Next Steps
1. Install pgvector extension in Supabase
2. Create chunk_embeddings table
3. Implement embedding_tasks.py
4. Update text_tasks.py to chain embedding generation
5. Enhance entity_resolution.py with semantic similarity
6. Add monitoring and metrics collection

## Conclusion

The database cleanup functionality provides a solid foundation for iterative project processing, while the vector embeddings plan will significantly enhance the semantic understanding and cross-document analysis capabilities of the system. The combination of proper data management and semantic embeddings will enable more sophisticated legal document analysis and knowledge extraction.