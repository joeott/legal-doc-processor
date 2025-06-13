# Context 536: Phased Deployment Architecture

**Date**: 2025-06-13 14:30 UTC  
**Branch**: fix/pipeline-langchain-optimizations  
**Purpose**: Define comprehensive phased deployment plan with verification gates

## Deployment Overview

This document outlines a 6-week phased deployment plan to transform our document processing system into a virtual knowledge graph architecture. Each phase includes specific tasks, verification criteria, and rollback procedures.

## Phase 0: Pre-deployment Preparation (Week 0)
**Status**: PENDING | **Priority**: HIGH | **Risk**: LOW

### Objectives
- Environment setup and dependency installation
- Baseline metrics collection
- Team training and documentation

### Tasks
```yaml
infrastructure:
  - task: "Upgrade Redis to support vector search"
    verification: "redis-cli INFO modules | grep search"
    owner: "DevOps"
    
  - task: "Configure Redis memory and vector index"
    config:
      maxmemory: 8gb
      maxmemory-policy: allkeys-lru
      vector-index-memory: 2gb
    verification: "redis-cli CONFIG GET maxmemory"
    
  - task: "Install LangChain dependencies"
    commands: |
      pip install langchain==0.3.0
      pip install langchain-redis==0.1.0
      pip install sentence-transformers==3.0.0
    verification: "pip list | grep langchain"

baseline_metrics:
  - task: "Measure current pipeline performance"
    metrics:
      - entity_resolution_accuracy
      - processing_time_per_document
      - infrastructure_costs
      - error_rates_by_stage
    output: "baseline_metrics_week0.json"
    
  - task: "Document current entity count and relationships"
    query: |
      SELECT COUNT(DISTINCT canonical_id) as entities,
             COUNT(*) as relationships
      FROM canonical_entities, relationship_staging
    output: "baseline_data_week0.json"

team_preparation:
  - task: "Create technical documentation"
    deliverables:
      - architecture_diagram.png
      - virtual_graph_concepts.md
      - troubleshooting_guide.md
      
  - task: "Conduct team training session"
    topics:
      - Virtual knowledge graph concepts
      - LangChain fundamentals
      - Monitoring and debugging
```

### Verification Gate
- [ ] All dependencies installed successfully
- [ ] Redis vector search operational
- [ ] Baseline metrics collected
- [ ] Team training completed
- [ ] Rollback plan documented

---

## Phase 1: Fix Pipeline Completion (Week 1)
**Status**: PENDING | **Priority**: HIGH | **Risk**: MEDIUM

### Objectives
- Ensure all 6 pipeline stages execute
- Remove deprecated code
- Establish monitoring for all stages

### Tasks
```python
pipeline_fixes:
  - task: "Audit pdf_tasks.py for missing stages"
    code_review:
      file: "scripts/pdf_tasks.py"
      verify_functions:
        - extract_text_from_document
        - chunk_document_text
        - extract_entities_from_chunks
        - resolve_document_entities
        - build_document_relationships  # Currently missing?
        - finalize_document_processing   # Currently missing?
        
  - task: "Implement missing pipeline stages"
    implementation: |
      @app.task(bind=True, base=PDFTask)
      def build_document_relationships(self, document_uuid: str) -> Dict:
          """Extract relationships between resolved entities"""
          # Implementation
          
      @app.task(bind=True, base=PDFTask)
      def finalize_document_processing(self, document_uuid: str) -> Dict:
          """Finalize processing and update status"""
          # Implementation
          
  - task: "Update process_pdf_document to include all stages"
    verification: "grep -c 'build_document_relationships' scripts/pdf_tasks.py"

cleanup:
  - task: "Remove batch_processor.py"
    commands: |
      git rm scripts/batch_processor.py
      grep -r "batch_processor" scripts/  # Verify no remaining imports
      
  - task: "Update production_processor.py imports"
    changes:
      from: "from scripts.batch_processor import BatchProcessor"
      to: "from scripts.batch_tasks import submit_batch"

monitoring:
  - task: "Add stage completion metrics"
    metrics:
      - pipeline_stage_completion_rate
      - stage_transition_time
      - stage_error_rate
    dashboard: "grafana/pipeline_health.json"
```

### Test Plan
```bash
# Test batch of 10 documents
python test_deployment/test_phase1_pipeline.py \
  --documents 10 \
  --verify-all-stages \
  --output phase1_test_results.json
```

### Verification Gate
- [ ] All 6 stages executing successfully
- [ ] 100% pipeline completion rate on test batch
- [ ] Deprecated code removed
- [ ] Monitoring dashboards active
- [ ] No regression in processing time

### Rollback Plan
```bash
# If pipeline breaks:
git revert --no-commit HEAD~3..HEAD
celery -A scripts.celery_app control shutdown
# Restart with previous version
```

---

## Phase 2: Semantic Cache Implementation (Week 2)
**Status**: PENDING | **Priority**: HIGH | **Risk**: MEDIUM

### Objectives
- Deploy Redis vector-based semantic cache
- Integrate with entity resolution pipeline
- Achieve >50% cache hit rate

### Tasks
```python
semantic_cache:
  - task: "Implement SemanticEntityCache class"
    file: "scripts/langchain_cache.py"
    components:
      - VectorEmbeddingGenerator
      - RedisSimilaritySearch  
      - CacheInvalidationHandler
      
  - task: "Create vector index in Redis"
    index_config:
      name: "idx:entities"
      algorithm: "FLAT"
      distance_metric: "COSINE"
      vector_dimensions: 1536
      
  - task: "Integrate cache with entity_service.py"
    integration_points:
      - before: "Check cache before LLM call"
      - after: "Update cache after resolution"
      - invalidate: "Handle entity merges"

cache_warming:
  - task: "Pre-populate cache with existing entities"
    script: "scripts/deployment/warm_semantic_cache.py"
    strategy:
      - Load all canonical_entities
      - Generate embeddings in batches of 100
      - Store with 7-day TTL
      
  - task: "Implement cache metrics"
    metrics:
      - cache_hit_rate
      - cache_miss_rate
      - similarity_score_distribution
      - cache_memory_usage

configuration:
  - task: "Add cache configuration"
    env_vars:
      LANGCHAIN_CACHE_ENABLED: "true"
      LANGCHAIN_SIMILARITY_THRESHOLD: "0.85"
      LANGCHAIN_EMBEDDING_MODEL: "text-embedding-3-small"
      LANGCHAIN_BATCH_SIZE: "100"
```

### Progressive Rollout
```yaml
week_2_day_1:
  - Enable for 10% of documents
  - Monitor cache performance
  
week_2_day_3:
  - Increase to 50% if metrics good
  - Tune similarity threshold
  
week_2_day_5:
  - Full rollout if hit rate >50%
  - Enable cache warming
```

### Verification Gate
- [ ] Cache hit rate >50% achieved
- [ ] No increase in error rates
- [ ] Embedding generation <100ms
- [ ] Cache memory usage within limits
- [ ] Invalidation working correctly

---

## Phase 3: Multi-Step Entity Resolution (Week 3)
**Status**: PENDING | **Priority**: MEDIUM | **Risk**: HIGH

### Objectives
- Deploy multi-step resolution pipeline
- Implement confidence scoring
- Enable cross-document linking

### Tasks
```python
multi_step_resolution:
  - task: "Implement MultiStepEntityResolver"
    stages:
      1: "Semantic cache lookup (85% threshold)"
      2: "Fuzzy match existing (80% threshold)"
      3: "LLM resolution with context"
      4: "Cross-document validation"
      5: "Confidence scoring"
      
  - task: "Create confidence scoring system"
    algorithm: |
      def calculate_confidence(resolution_path):
          weights = {
              "cache_hit": 1.0,
              "fuzzy_match": 0.85,
              "llm_high_confidence": 0.95,
              "llm_low_confidence": 0.75
          }
          # Weighted scoring with agreement bonus
          
  - task: "Implement cache invalidation strategy"
    operations:
      - merge_entities(id1, id2)
      - update_entity_name(id, new_name)
      - link_mention_to_entity(mention_id, entity_id)
      - recompute_embeddings(entity_id)

llm_configuration:
  - task: "Configure LLM parameters"
    configs:
      entity_resolution:
        model: "gpt-4o-mini"
        temperature: 0.1
        timeout: 30
        max_retries: 3
        
      confidence_scoring:
        model: "gpt-4o-mini"
        temperature: 0.0
        timeout: 15

cross_document:
  - task: "Enable cross-document entity linking"
    implementation:
      - Build document co-occurrence matrix
      - Weight entities by document relevance
      - Merge similar entities across documents
```

### A/B Testing Plan
```yaml
control_group:
  size: 20%
  pipeline: "existing_fuzzy_match_only"
  
treatment_group:
  size: 80%
  pipeline: "multi_step_with_llm"
  
metrics:
  - resolution_accuracy
  - processing_time
  - cost_per_entity
  - user_satisfaction
```

### Verification Gate
- [ ] 95%+ entity resolution accuracy
- [ ] Average confidence score >0.85
- [ ] Cross-document linking functional
- [ ] A/B test shows improvement
- [ ] LLM costs within budget

---

## Phase 4: Enhanced Relationship Extraction (Week 4)
**Status**: PENDING | **Priority**: MEDIUM | **Risk**: MEDIUM

### Objectives
- Deploy LangGraph-based extraction
- Implement few-shot learning
- Add relationship validation

### Tasks
```python
relationship_extraction:
  - task: "Implement RelationshipExtractionGraph"
    nodes:
      - load_entities
      - generate_candidates
      - validate_relationships
      - score_confidence
      - store_results
      
  - task: "Create few-shot example bank"
    examples: "config/few_shot_relationships.yaml"
    categories:
      - employment_relationships
      - ownership_relationships
      - contractual_relationships
      - family_relationships
      
  - task: "Implement relationship validation"
    rules:
      - entity_type_compatibility
      - relationship_cardinality
      - temporal_consistency
      - legal_validity

prompt_engineering:
  - task: "Create prompt template system"
    templates:
      - entity_resolution_prompt.txt
      - relationship_extraction_prompt.txt
      - confidence_scoring_prompt.txt
    versioning: "git-tracked with A/B testing"
    
  - task: "Implement prompt injection protection"
    measures:
      - Input sanitization
      - Output format validation
      - Token limit enforcement
```

### Quality Assurance
```python
# Automated testing
def test_relationship_extraction():
    test_documents = load_test_set("legal_relationships_gold_standard.json")
    
    for doc in test_documents:
        extracted = extract_relationships(doc.text)
        
        # Verify precision and recall
        assert precision(extracted, doc.gold_relationships) > 0.90
        assert recall(extracted, doc.gold_relationships) > 0.85
```

### Verification Gate
- [ ] Relationship extraction accuracy >90%
- [ ] All relationship types covered
- [ ] Validation rules enforced
- [ ] Few-shot learning improving results
- [ ] Performance within SLA

---

## Phase 5: Codebase Consolidation (Week 5)
**Status**: PENDING | **Priority**: LOW | **Risk**: LOW

### Objectives
- Reduce codebase to ~35 production scripts
- Separate non-production tools
- Update documentation

### Tasks
```bash
consolidation:
  - task: "Archive deprecated scripts"
    script: |
      # Create backup
      tar -czf deprecated_backup_$(date +%Y%m%d).tar.gz \
        scripts/batch_processor.py \
        scripts/core/ \
        scripts/utils/neo4j_utils.py
      
      # Remove files
      git rm -r scripts/core/
      git rm scripts/batch_processor.py
      
  - task: "Consolidate validation modules"
    from:
      - validation/ocr_validator.py
      - validation/entity_validator.py
      - validation/pipeline_validator.py
    to: "validation/unified_validator.py"
    
  - task: "Create separate repositories"
    repos:
      - name: "legal-doc-cli"
        contents: "scripts/cli/*"
        
      - name: "legal-doc-monitoring"  
        contents: "scripts/monitoring/*"
        
      - name: "legal-doc-utilities"
        contents: "scripts/utilities/*"

documentation:
  - task: "Update all documentation"
    docs:
      - README.md
      - CLAUDE.md
      - API_REFERENCE.md
      - DEPLOYMENT.md
```

### Verification Gate
- [ ] Script count reduced to <40
- [ ] All tests passing
- [ ] Documentation updated
- [ ] Team trained on new structure
- [ ] CI/CD pipelines updated

---

## Phase 6: Validation & Rollout (Week 6)
**Status**: PENDING | **Priority**: HIGH | **Risk**: LOW

### Objectives
- Complete end-to-end validation
- Performance benchmarking
- Full production rollout

### Tasks
```yaml
validation:
  - task: "Run complete test suite"
    tests:
      - unit_tests: "100% pass rate"
      - integration_tests: "100% pass rate"
      - e2e_tests: "95%+ pass rate"
      - load_tests: "Meet SLA targets"
      
  - task: "Benchmark against baseline"
    comparisons:
      - processing_time: "<30s per document"
      - accuracy: ">95% entity resolution"
      - cost: "<$0.10 per document"
      - cache_hit_rate: ">70%"

production_rollout:
  - task: "Deploy to production"
    strategy: "Blue-green deployment"
    steps:
      1: "Deploy to green environment"
      2: "Run smoke tests"
      3: "Route 10% traffic"
      4: "Monitor for 24 hours"
      5: "Full traffic cutover"
      
  - task: "Configure monitoring alerts"
    alerts:
      - cache_hit_rate < 60%
      - error_rate > 5%
      - p95_latency > 2s
      - memory_usage > 80%
```

### Success Celebration
```yaml
achievements:
  - "Virtual knowledge graph operational"
  - "70%+ cache hit rate achieved"
  - "95%+ entity resolution accuracy"
  - "50% reduction in codebase size"
  - "2x performance improvement"
  
team_celebration:
  - "Deploy success announcement"
  - "Lessons learned session"
  - "Team recognition"
```

## Risk Management

### Risk Matrix
| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Redis memory overflow | Medium | High | Memory limits, monitoring |
| LLM API failures | Low | High | Retry logic, fallbacks |
| Cache invalidation bugs | Medium | Medium | Extensive testing |
| Performance regression | Low | Medium | A/B testing, gradual rollout |

### Rollback Procedures
Each phase includes specific rollback steps:
1. Feature flags for instant disable
2. Database migration rollbacks
3. Git revert procedures
4. Cache clearing scripts
5. Worker restart procedures

## Resource Requirements

### Infrastructure
- Redis: 8GB RAM upgrade
- Celery Workers: +4 instances for LLM tasks
- Monitoring: Grafana + Prometheus setup

### Team
- 2 Backend Engineers (full-time)
- 1 DevOps Engineer (50%)
- 1 Data Scientist (for prompt engineering)
- 1 QA Engineer (for validation)

### Budget
- Infrastructure: $2,000/month increase
- LLM API costs: $3,000/month estimate
- Total 6-week project cost: ~$15,000

## Success Metrics Dashboard

### Real-time Metrics
```yaml
dashboard_url: "https://grafana.legal-doc.internal/virtual-graph"

panels:
  - title: "Cache Performance"
    metrics: ["hit_rate", "miss_rate", "latency_p95"]
    
  - title: "Entity Resolution"
    metrics: ["accuracy", "confidence_distribution", "cross_doc_links"]
    
  - title: "Pipeline Health"
    metrics: ["stage_completion", "error_rates", "processing_time"]
    
  - title: "Cost Tracking"
    metrics: ["llm_tokens_used", "cost_per_document", "daily_spend"]
```

## Conclusion

This phased deployment plan transforms our document processing system into a sophisticated virtual knowledge graph without requiring a traditional graph database. By leveraging semantic caching, multi-step resolution, and intelligent relationship extraction, we achieve graph-like capabilities with better performance and flexibility.

The 6-week timeline allows for careful validation at each phase with clear rollback procedures, ensuring a safe and successful deployment.