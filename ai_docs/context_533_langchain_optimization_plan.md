# Context 533: LangChain Optimization Implementation Plan

**Date**: 2025-06-13 13:00 UTC  
**Branch**: fix/pipeline-langchain-optimizations  
**Issue**: #4  
**Purpose**: Document detailed implementation plan for LangChain-based optimizations

## Overview

This context documents the comprehensive plan to implement LangChain optimizations based on the reference implementation analysis. The plan addresses both immediate pipeline fixes and advanced entity resolution capabilities.

## Reference Implementation Analysis

### Key Patterns from `/opt/legal-doc-processor/resources/langchain/`

1. **Semantic Caching Architecture**
   - Uses embeddings for similarity-based lookups (not exact match)
   - MongoDB/Redis backends with vector search
   - Configurable similarity thresholds (default 0.85)
   - Session-based isolation for multi-tenancy

2. **Multi-Step Processing**
   - Always validate before execution
   - Retry with error context
   - Confidence scoring at each step
   - Few-shot learning for better accuracy

3. **Cross-Document Patterns**
   - Semantic XML markup preserves structure
   - Multi-vector retrieval (summaries + raw data)
   - Batch processing for efficiency
   - Knowledge graph integration

## Implementation Phases

### Phase 1: Pipeline Completion (Week 1)

**Objective**: Fix the incomplete pipeline that stops at stage 4/6

1. **Audit `pdf_tasks.py`**
   ```python
   # Verify process_pdf_document includes:
   def process_pdf_document(document_uuid, s3_url, project_uuid=None):
       # Stage 1: OCR
       text = extract_text_from_document(document_uuid, s3_url)
       
       # Stage 2: Chunking
       chunks = chunk_document_text(document_uuid, text)
       
       # Stage 3: Entity Extraction
       entities = extract_entities_from_chunks(document_uuid, chunks)
       
       # Stage 4: Entity Resolution
       resolved = resolve_document_entities(document_uuid, entities)
       
       # Stage 5: Relationship Building (MISSING?)
       relationships = build_document_relationships(document_uuid, resolved)
       
       # Stage 6: Finalization (MISSING?)
       finalize_document_processing(document_uuid)
   ```

2. **Remove Deprecated Code**
   - Delete `batch_processor.py`
   - Update imports in `production_processor.py`
   - Clean up test scripts from root

3. **Test Full Pipeline**
   - Run batch of 10 documents
   - Verify all 6 stages complete
   - Monitor database for all task types

### Phase 2: Semantic Cache Implementation (Week 2)

**Objective**: Implement Redis-backed semantic cache for entity resolution

1. **Core Cache Class**
   ```python
   # scripts/langchain_cache.py
   from langchain.cache import BaseCache
   from langchain.embeddings import OpenAIEmbeddings
   import numpy as np
   
   class SemanticEntityCache(BaseCache):
       def __init__(self, redis_manager, embedding_model, similarity_threshold=0.85):
           self.redis = redis_manager
           self.embeddings = embedding_model
           self.threshold = similarity_threshold
           
       async def lookup(self, entity_text: str) -> Optional[Dict]:
           # Generate embedding
           embedding = await self.embeddings.aembed_query(entity_text)
           
           # Search similar embeddings in Redis
           similar = await self._vector_search(embedding)
           
           if similar and similar['score'] > self.threshold:
               return similar['entity']
           return None
           
       async def update(self, entity_text: str, resolved_entity: Dict):
           # Generate and store embedding
           embedding = await self.embeddings.aembed_query(entity_text)
           
           # Store in Redis with vector index
           await self._store_with_vector(entity_text, resolved_entity, embedding)
   ```

2. **Redis Vector Search Setup**
   ```python
   # Add to scripts/cache.py
   def create_vector_index(self):
       """Create Redis vector similarity index"""
       try:
           self.client.ft('idx:entities').create_index([
               VectorField('embedding', 
                          'FLAT', 
                          {'TYPE': 'FLOAT32', 'DIM': 1536, 'DISTANCE_METRIC': 'COSINE'})
           ])
       except ResponseError:
           # Index already exists
           pass
   ```

3. **Integration Points**
   - Update `entity_service.py` to use semantic cache
   - Add cache warming from existing canonical entities
   - Implement batch lookup for efficiency

### Phase 3: Multi-Step Entity Resolution (Week 3)

**Objective**: Implement intelligent multi-step entity resolution

1. **Resolution Pipeline**
   ```python
   # scripts/entity_resolver_v2.py
   class MultiStepEntityResolver:
       def __init__(self, semantic_cache, llm, fuzzy_matcher):
           self.cache = semantic_cache
           self.llm = llm
           self.fuzzy = fuzzy_matcher
           
       async def resolve_entity(self, mention: EntityMention, context: DocumentContext):
           # Step 1: Semantic cache lookup
           cached = await self.cache.lookup(mention.text)
           if cached and cached.confidence > 0.9:
               return cached
               
           # Step 2: Fuzzy match existing entities
           candidates = await self.fuzzy.find_similar(
               mention.text, 
               threshold=0.8,
               limit=5
           )
           
           # Step 3: LLM resolution with context
           if candidates:
               resolved = await self._llm_resolve_with_candidates(
                   mention, context, candidates
               )
           else:
               resolved = await self._llm_resolve_new_entity(
                   mention, context
               )
               
           # Step 4: Validate resolution
           validated = await self._validate_resolution(resolved)
           
           # Step 5: Update cache
           await self.cache.update(mention.text, validated)
           
           return validated
   ```

2. **Cross-Document Linking**
   ```python
   async def link_across_documents(self, entity: CanonicalEntity):
       # Find all mentions across documents
       mentions = await self.find_entity_mentions(entity.canonical_id)
       
       # Build cross-document context
       xdoc_context = await self.build_cross_doc_context(mentions)
       
       # Re-resolve with full context
       enhanced = await self.enhance_entity_with_context(entity, xdoc_context)
       
       return enhanced
   ```

### Phase 4: Enhanced Relationship Extraction (Week 4)

**Objective**: Implement LangChain-based relationship extraction

1. **LangGraph Workflow**
   ```python
   # scripts/relationship_extractor_v2.py
   from langchain.graphs import StateGraph
   
   class RelationshipExtractionGraph:
       def __init__(self):
           self.graph = StateGraph(RelationshipState)
           
           # Define workflow
           self.graph.add_node("load_entities", self.load_entities)
           self.graph.add_node("generate_candidates", self.generate_candidates)
           self.graph.add_node("validate", self.validate_relationships)
           self.graph.add_node("score", self.score_confidence)
           self.graph.add_node("store", self.store_relationships)
           
           # Define edges
           self.graph.add_edge("load_entities", "generate_candidates")
           self.graph.add_edge("generate_candidates", "validate")
           self.graph.add_edge("validate", "score")
           self.graph.add_edge("score", "store")
           
       async def extract_relationships(self, document_uuid: str):
           initial_state = RelationshipState(document_uuid=document_uuid)
           result = await self.graph.arun(initial_state)
           return result.relationships
   ```

2. **Few-Shot Learning Setup**
   ```python
   # Load examples from training data
   few_shot_examples = [
       {
           "entities": ["John Smith", "ABC Corporation"],
           "context": "John Smith serves as CEO of ABC Corporation",
           "relationship": {
               "type": "EMPLOYMENT",
               "source": "John Smith",
               "target": "ABC Corporation", 
               "role": "CEO",
               "confidence": 0.95
           }
       },
       # More examples...
   ]
   ```

### Phase 5: Codebase Consolidation (Week 5)

**Objective**: Clean up codebase to ~35 production scripts

1. **Remove Deprecated (17 files)**
   ```bash
   # Create archive before deletion
   tar -czf deprecated_scripts_backup.tar.gz \
       scripts/batch_processor.py \
       scripts/core/ \
       scripts/utils/neo4j_utils.py \
       scripts/utils/supabase_utils.py \
       migrate_redis_databases.py \
       core_enhancements_immediate.py
       
   # Remove files
   rm -rf scripts/core/
   rm scripts/batch_processor.py
   # ... etc
   ```

2. **Consolidate Validation (7→3 files)**
   ```python
   # scripts/validation/unified_validator.py
   class UnifiedValidator:
       """Combines OCR, Entity, and Pipeline validation"""
       
       def __init__(self):
           self.ocr = OCRValidationRules()
           self.entity = EntityValidationRules()
           self.pipeline = PipelineValidationRules()
           
       async def validate_document(self, document_uuid: str):
           results = ValidationResults()
           
           # Run all validations
           results.ocr = await self.ocr.validate(document_uuid)
           results.entity = await self.entity.validate(document_uuid)
           results.pipeline = await self.pipeline.validate(document_uuid)
           
           return results
   ```

3. **Repository Separation**
   ```bash
   # Create new repositories
   - legal-doc-cli (4 scripts)
   - legal-doc-monitoring (4 scripts)  
   - legal-doc-utilities (11 scripts)
   ```

## Success Metrics

### Performance Targets
- **Cache Hit Rate**: >70% for repeated entities
- **Resolution Speed**: 2x faster with cache
- **Accuracy**: >95% entity resolution accuracy
- **Pipeline Completion**: 100% documents complete all stages

### Code Quality Targets
- **Script Count**: Reduce from 71 to ~35
- **Test Coverage**: >80% for core modules
- **Documentation**: All new code documented

## Configuration Updates

### New Environment Variables
```bash
# LangChain Configuration
LANGCHAIN_CACHE_ENABLED=true
LANGCHAIN_SIMILARITY_THRESHOLD=0.85
LANGCHAIN_EMBEDDING_MODEL=text-embedding-3-small
LANGCHAIN_EMBEDDING_DIMENSION=1536
LANGCHAIN_CACHE_TTL=604800  # 7 days
LANGCHAIN_BATCH_SIZE=100
LANGCHAIN_MAX_RETRIES=3

# Redis Vector Search
REDIS_VECTOR_INDEX=idx:entities
REDIS_VECTOR_DIMENSION=1536
REDIS_VECTOR_METRIC=COSINE
```

### Dependencies to Add
```txt
# requirements.txt additions
langchain==0.3.0
langchain-community==0.3.0
langchain-openai==0.2.0
langchain-redis==0.1.0
sentence-transformers==3.0.0
redis[hiredis]>=5.0.0
numpy>=1.24.0
scikit-learn>=1.3.0
```

## Risk Mitigation

1. **Backward Compatibility**
   - Keep old entity resolution as fallback
   - Gradual rollout with feature flags
   - Comprehensive testing before cutover

2. **Performance Concerns**
   - Monitor embedding generation costs
   - Implement request batching
   - Use smaller embedding models if needed

3. **Data Migration**
   - Script to generate embeddings for existing entities
   - Parallel processing for large datasets
   - Progress tracking and resumability

## Next Steps

1. Create detailed technical design doc
2. Set up development environment with LangChain
3. Implement Phase 1 (pipeline fix) immediately
4. Begin Phase 2 (semantic cache) in parallel
5. Schedule weekly progress reviews

This implementation will transform our entity resolution from simple string matching to intelligent, context-aware resolution with cross-document understanding.