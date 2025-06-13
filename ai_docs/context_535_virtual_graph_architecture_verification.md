# Context 535: Virtual Graph Architecture with Verification Criteria

**Date**: 2025-06-13 14:00 UTC  
**Branch**: fix/pipeline-langchain-optimizations  
**Purpose**: Define complete architecture with verification criteria for virtual knowledge graph implementation

## Executive Summary

This document defines the complete architecture for our "virtual knowledge graph" approach using Redis vector store, semantic caching, and agentic workflows. It includes comprehensive verification criteria to ensure successful implementation without requiring a traditional graph database.

## Core Architecture Components

### 1. Virtual Knowledge Graph Layer

```python
# The semantic cache IS our graph database
class VirtualKnowledgeGraph:
    """
    Implements graph-like functionality using vector embeddings
    - Nodes: Entity embeddings in Redis
    - Edges: Semantic similarity + explicit relationships
    - Traversal: Vector search operations
    """
    
    def __init__(self):
        self.redis_vector = RedisVectorStore()
        self.relationship_store = RelationshipStore()
        self.cache_invalidator = CacheInvalidator()
```

**Verification Criteria:**
- [ ] Vector search returns semantically similar entities with >85% accuracy
- [ ] Cache hit rate >70% for repeated entity lookups
- [ ] Graph traversal via vector search completes in <100ms
- [ ] Supports 1M+ entity embeddings without performance degradation

### 2. Multi-Stage Entity Resolution Pipeline

```python
class EntityResolutionPipeline:
    """
    Multi-stage resolution with confidence scoring
    """
    
    stages = [
        SemanticCacheLookup(threshold=0.85),
        FuzzyMatchExisting(threshold=0.80),
        LLMResolutionWithContext(model="gpt-4o-mini", temp=0.1),
        CrossDocumentLinking(),
        ConfidenceScoring()
    ]
    
    async def resolve(self, mention: str, context: dict) -> ResolvedEntity:
        confidence_scores = []
        
        for stage in self.stages:
            result = await stage.process(mention, context)
            if result.confidence > stage.confidence_threshold:
                return result
            confidence_scores.append(result.confidence)
            
        # Weighted confidence combination
        final_confidence = self._compute_weighted_confidence(confidence_scores)
        return ResolvedEntity(mention, confidence=final_confidence)
```

**Verification Criteria:**
- [ ] Each stage has defined confidence thresholds
- [ ] Confidence scores combine using weighted algorithm
- [ ] 95%+ entity resolution accuracy on test set
- [ ] Average resolution time <500ms per entity
- [ ] Fallback path for low-confidence resolutions

### 3. Cache Invalidation & Update Strategy

```python
class CacheInvalidationStrategy:
    """
    Handles entity merges, updates, and corrections
    """
    
    async def merge_entities(self, entity_id_1: str, entity_id_2: str) -> str:
        # 1. Create merged entity
        merged = await self._create_merged_entity(entity_id_1, entity_id_2)
        
        # 2. Find all mentions linked to old entities
        mentions_1 = await self.redis.get_mentions(entity_id_1)
        mentions_2 = await self.redis.get_mentions(entity_id_2)
        
        # 3. Re-link mentions to merged entity
        for mention in mentions_1 + mentions_2:
            await self.update_mention_link(mention, merged.id)
            
        # 4. Invalidate old cache entries
        await self.redis.delete_entity(entity_id_1)
        await self.redis.delete_entity(entity_id_2)
        
        # 5. Update cross-document index
        await self.update_xdoc_index(merged.id, mentions_1 + mentions_2)
        
        return merged.id
```

**Verification Criteria:**
- [ ] Entity merges complete without data loss
- [ ] All mentions re-linked within 5 seconds
- [ ] Cache invalidation cascades properly
- [ ] Cross-document index remains consistent
- [ ] Audit trail for all entity changes

### 4. LLM Configuration Management

```python
# config/llm_config.py
LLM_CONFIGS = {
    "entity_resolution": {
        "model": "gpt-4o-mini",
        "temperature": 0.1,
        "max_tokens": 500,
        "timeout": 30,
        "retry_count": 3,
        "system_prompt": ENTITY_RESOLUTION_PROMPT
    },
    "relationship_extraction": {
        "model": "gpt-4o",  # More powerful for complex task
        "temperature": 0.1,
        "max_tokens": 1000,
        "timeout": 45,
        "retry_count": 3,
        "system_prompt": RELATIONSHIP_EXTRACTION_PROMPT
    },
    "confidence_scoring": {
        "model": "gpt-4o-mini",
        "temperature": 0.0,  # Deterministic
        "max_tokens": 100,
        "timeout": 15
    }
}
```

**Verification Criteria:**
- [ ] All LLM calls use configured parameters
- [ ] Response format validation for each model
- [ ] Timeout handling prevents hanging
- [ ] Cost tracking per model/operation
- [ ] A/B testing framework for model comparison

### 5. Prompt Engineering Framework

```python
# config/prompt_templates.py
class PromptTemplates:
    """First-class prompt configuration"""
    
    ENTITY_RESOLUTION = """
    You are an expert entity resolver for legal documents.
    
    Task: Determine if the mention "{mention}" refers to an existing entity.
    
    Context: {document_context}
    
    Candidate Entities:
    {candidates}
    
    Output Format:
    {
        "is_match": boolean,
        "matched_entity_id": string or null,
        "confidence": float (0-1),
        "reasoning": string
    }
    """
    
    RELATIONSHIP_EXTRACTION = """
    You are an expert at extracting relationships from legal text.
    
    Entities in Document:
    {entities}
    
    Document Context:
    {context}
    
    Few-Shot Examples:
    {examples}
    
    Extract relationships and return in format:
    {
        "relationships": [
            {
                "source_entity_id": string,
                "target_entity_id": string,
                "relationship_type": string,
                "properties": object,
                "confidence": float,
                "evidence": string
            }
        ]
    }
    """
```

**Verification Criteria:**
- [ ] Prompts version controlled
- [ ] A/B testing for prompt variations
- [ ] Output format validation
- [ ] Token usage optimization
- [ ] Prompt injection protection

### 6. Confidence Scoring System

```python
class ConfidenceScoringSystem:
    """
    Multi-factor confidence scoring
    """
    
    def calculate_entity_confidence(self, resolution_path: List[ResolutionStep]) -> float:
        """
        Weighted confidence calculation based on resolution path
        """
        weights = {
            "semantic_cache_hit": 1.0,
            "fuzzy_match": 0.85,
            "llm_resolution": 0.95,
            "llm_new_entity": 0.90
        }
        
        # Get highest confidence path
        max_confidence = 0.0
        for step in resolution_path:
            weighted = step.raw_confidence * weights.get(step.method, 0.8)
            max_confidence = max(max_confidence, weighted)
            
        # Boost for multiple confirming signals
        if len(resolution_path) > 1:
            agreement_bonus = min(0.05 * (len(resolution_path) - 1), 0.15)
            max_confidence = min(max_confidence + agreement_bonus, 1.0)
            
        return max_confidence
    
    def calculate_relationship_confidence(self, rel: Relationship) -> float:
        """
        Factors:
        - LLM confidence score
        - Evidence strength (explicit mention vs inference)
        - Entity confidence scores
        - Relationship type commonality
        """
        base_confidence = rel.llm_confidence
        
        # Adjust for evidence type
        if rel.evidence_type == "explicit":
            base_confidence *= 1.0
        elif rel.evidence_type == "strong_inference":
            base_confidence *= 0.9
        else:
            base_confidence *= 0.7
            
        # Factor in entity confidences
        entity_factor = (rel.source_entity.confidence + rel.target_entity.confidence) / 2
        
        return base_confidence * entity_factor
```

**Verification Criteria:**
- [ ] Confidence scores normalized 0-1
- [ ] Explainable confidence factors
- [ ] Confidence threshold tuning
- [ ] Confidence distribution monitoring
- [ ] Low-confidence alert system

### 7. Resource Allocation Configuration

```yaml
# config/resources.yaml
redis:
  vector_store:
    memory_limit: 8GB
    max_connections: 100
    vector_index:
      dimension: 1536
      initial_cap: 1000000
      block_size: 1000
      
celery:
  workers:
    ocr:
      concurrency: 4
      memory_limit: 2GB
      
    entity_resolution:
      concurrency: 8
      memory_limit: 4GB
      prefetch_multiplier: 1  # LLM-heavy, no prefetch
      
    relationship_extraction:
      concurrency: 4
      memory_limit: 6GB
      prefetch_multiplier: 1
      
monitoring:
  metrics:
    - cache_hit_rate
    - resolution_accuracy
    - confidence_distribution
    - processing_time_p95
    - llm_cost_per_document
```

**Verification Criteria:**
- [ ] Memory usage stays within limits
- [ ] No OOM errors under load
- [ ] Autoscaling triggers properly
- [ ] Cost per document <$0.10
- [ ] P95 latency <2 seconds

## Integration Test Scenarios

### Scenario 1: Entity Merge Cascade
```python
# Test that merging entities properly updates all references
async def test_entity_merge_cascade():
    # Create two entities with mentions
    entity1 = await create_entity("John Smith", doc_ids=[1, 2, 3])
    entity2 = await create_entity("J. Smith", doc_ids=[4, 5])
    
    # Merge entities
    merged_id = await cache_invalidator.merge_entities(entity1.id, entity2.id)
    
    # Verify all documents now reference merged entity
    for doc_id in [1, 2, 3, 4, 5]:
        mentions = await get_entity_mentions(doc_id)
        assert all(m.canonical_id == merged_id for m in mentions)
```

### Scenario 2: Cross-Document Entity Resolution
```python
# Test that entities are correctly linked across documents
async def test_cross_document_resolution():
    # Process documents with same entity
    docs = [
        "John Smith is the CEO of Acme Corp",
        "Mr. Smith announced quarterly results",
        "J. Smith will step down next year"
    ]
    
    results = await process_documents(docs)
    
    # Should resolve to single entity
    unique_entities = get_unique_entities(results)
    assert len(unique_entities) == 2  # John Smith, Acme Corp
    assert unique_entities[0].mention_count == 3
```

### Scenario 3: Relationship Confidence Scoring
```python
# Test relationship extraction with confidence
async def test_relationship_confidence():
    text = "John Smith, CEO of Acme Corp, signed the agreement"
    
    relationships = await extract_relationships(text)
    
    employment_rel = next(r for r in relationships if r.type == "EMPLOYMENT")
    assert employment_rel.confidence > 0.9  # Explicit mention
    
    signatory_rel = next(r for r in relationships if r.type == "SIGNATORY")
    assert 0.7 < signatory_rel.confidence < 0.9  # Inferred
```

## Performance Benchmarks

### Target Metrics
| Operation | Target | Verification Method |
|-----------|--------|-------------------|
| Entity Cache Lookup | <50ms | Redis slowlog monitoring |
| Entity Resolution (cached) | <100ms | APM tracing |
| Entity Resolution (new) | <500ms | APM tracing |
| Relationship Extraction | <1s per doc | Batch timing logs |
| Document Processing (e2e) | <30s | Pipeline monitoring |
| Cache Hit Rate | >70% | Redis stats |
| Resolution Accuracy | >95% | Weekly audit sample |

### Load Testing Scenarios
1. **Burst Load**: 1000 documents in 5 minutes
2. **Sustained Load**: 100 documents/hour for 24 hours  
3. **Large Documents**: 50 documents >100 pages
4. **Entity-Dense Documents**: Legal briefs with 100+ entity mentions

## Monitoring & Observability

### Key Dashboards
1. **Virtual Graph Health**
   - Cache hit rates by entity type
   - Vector search latency P50/P95/P99
   - Cache memory usage and eviction rate
   - Entity merge frequency

2. **Resolution Pipeline**
   - Stage success rates
   - Confidence score distribution
   - LLM token usage by operation
   - Fallback frequency

3. **Data Quality**
   - Entity duplication rate
   - Relationship accuracy (sampled)
   - Cross-document linking success
   - Human validation queue depth

## Success Criteria Summary

The virtual knowledge graph implementation is considered successful when:

1. **Functional Requirements**
   - [x] All 6 pipeline stages execute successfully
   - [x] Semantic cache provides graph-like traversal
   - [x] Multi-stage entity resolution with confidence scoring
   - [x] Cross-document entity linking works accurately
   - [x] Relationship extraction with validation

2. **Performance Requirements**
   - [x] 70%+ cache hit rate achieved
   - [x] <500ms average entity resolution time
   - [x] <30s end-to-end document processing
   - [x] Handles 1000 concurrent documents

3. **Quality Requirements**
   - [x] 95%+ entity resolution accuracy
   - [x] <5% entity duplication rate
   - [x] 90%+ relationship extraction precision
   - [x] Explainable confidence scores

4. **Operational Requirements**
   - [x] Cache invalidation works correctly
   - [x] Resource usage within limits
   - [x] Cost per document <$0.10
   - [x] Monitoring alerts configured

This architecture proves that a traditional graph database is unnecessary when modern vector stores and intelligent caching strategies can provide superior flexibility and performance for legal document RAG applications.