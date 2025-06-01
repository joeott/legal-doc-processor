# Context 177: Chunking Strategy Implementation Plan - Next Steps

## Date: 2025-05-28

## Executive Summary

After reviewing the recent chunking analysis and current implementation, the system is **already using the correct approach** - plain text semantic chunking for Textract output. The perceived issues may stem from other pipeline stages or error handling. This document outlines a comprehensive plan to verify, optimize, and enhance the chunking system.

## Current State Assessment

### What's Working Correctly
1. **Plain Text Chunker Implementation**: `scripts/plain_text_chunker.py` properly handles Textract output
2. **Semantic Boundary Detection**: Recognizes legal document structure (sections, headings, page breaks)
3. **Integration**: `text_processing.py` correctly uses the plain text chunker
4. **Fallback Logic**: Has character-based splitting when semantic chunking fails

### Potential Issue Sources
1. **Database Storage**: How chunks are persisted to Supabase
2. **Entity Extraction**: Verbose prompts causing confusion in OpenAI logs
3. **Error Propagation**: Failures in chunking not properly handled downstream
4. **Validation**: Missing validation between chunking and entity extraction

## Proposed Implementation Plan

### Phase 1: Verification and Diagnostics (Immediate)

#### 1.1 Add Comprehensive Logging
```python
# In text_processing.py, enhance logging around chunking:
logger.info(f"Document {document_id}: Starting chunking with {len(cleaned_text)} characters")
logger.info(f"Document {document_id}: Created {len(semantic_chunks)} semantic chunks")
for i, chunk in enumerate(semantic_chunks[:3]):  # Log first 3 chunks
    logger.info(f"  Chunk {i}: {len(chunk['text'])} chars, type: {chunk.get('metadata', {}).get('type', 'unknown')}")
```

#### 1.2 Add Chunking Validation
```python
# Add validation function in chunking_utils.py:
def validate_chunks(chunks: List[Dict[str, Any]], original_text: str) -> Dict[str, Any]:
    """Validate chunk quality and coverage"""
    return {
        'total_chunks': len(chunks),
        'avg_chunk_size': sum(len(c['text']) for c in chunks) / len(chunks) if chunks else 0,
        'coverage': sum(len(c['text']) for c in chunks) / len(original_text),
        'empty_chunks': sum(1 for c in chunks if not c['text'].strip()),
        'chunk_types': Counter(c.get('metadata', {}).get('type', 'unknown') for c in chunks)
    }
```

#### 1.3 Create Diagnostic Command
Add to CLI (`scripts/cli/monitor.py`):
```python
@click.command()
@click.option('--document-id', required=True, help='Document ID to diagnose')
def diagnose_chunking(document_id: str):
    """Diagnose chunking issues for a specific document"""
    # Retrieve document text
    # Run chunking
    # Display validation results
    # Show chunk boundaries and types
```

### Phase 2: Optimization (Short-term)

#### 2.1 Enhanced Semantic Boundaries
Improve `plain_text_chunker.py` to better handle:
- **Legal Citations**: Keep case citations together
- **Numbered Lists**: Preserve list integrity
- **Contract Clauses**: Respect clause boundaries
- **Signature Blocks**: Isolate as separate chunks

#### 2.2 Chunk Metadata Enhancement
```python
def enhance_chunk_metadata(chunk: Dict[str, Any], position: int, total: int) -> Dict[str, Any]:
    """Add rich metadata to chunks"""
    chunk['metadata'].update({
        'position': position,
        'total_chunks': total,
        'has_citations': bool(re.search(r'\d+\s+[A-Z]\.\d+|v\.|vs\.', chunk['text'])),
        'has_dates': bool(re.search(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', chunk['text'])),
        'density_score': len(chunk['text'].split()) / len(chunk['text']) * 100,
        'chunk_id': f"{document_id}_chunk_{position:04d}"
    })
    return chunk
```

#### 2.3 Adaptive Chunk Sizing
```python
def calculate_optimal_chunk_size(text: str, doc_type: str) -> Tuple[int, int]:
    """Calculate optimal min/max chunk sizes based on document characteristics"""
    word_count = len(text.split())
    avg_sentence_length = len(text) / text.count('.') if text.count('.') > 0 else 50
    
    if doc_type == 'contract':
        return (500, 2000)  # Larger chunks for contracts
    elif doc_type == 'motion':
        return (300, 1500)  # Standard for motions
    elif word_count < 1000:
        return (200, 800)   # Smaller chunks for short documents
    else:
        return (300, 1500)  # Default
```

### Phase 3: Advanced Features (Long-term)

#### 3.1 Hybrid Chunking Strategy
Implement configurable chunking strategies:
```python
class ChunkingStrategy(Enum):
    PLAIN_TEXT_SEMANTIC = "plain_text_semantic"  # Current
    AI_GUIDED = "ai_guided"                      # OpenAI-based
    HYBRID = "hybrid"                            # Semantic + AI refinement
    LEGAL_SPECIALIST = "legal_specialist"        # Domain-specific rules

def chunk_document(text: str, strategy: ChunkingStrategy, **kwargs) -> List[Dict]:
    """Unified chunking interface with strategy selection"""
    if strategy == ChunkingStrategy.PLAIN_TEXT_SEMANTIC:
        return chunk_plain_text_semantically(text, **kwargs)
    elif strategy == ChunkingStrategy.AI_GUIDED:
        return chunk_with_ai_guidance(text, **kwargs)
    # ... etc
```

#### 3.2 Chunk Quality Scoring
```python
def score_chunk_quality(chunk: Dict[str, Any]) -> float:
    """Score chunk quality for downstream optimization"""
    score = 1.0
    
    # Penalize very short or very long chunks
    length = len(chunk['text'])
    if length < 100:
        score *= 0.7
    elif length > 2000:
        score *= 0.8
    
    # Reward semantic completeness
    if chunk['text'].strip().endswith('.'):
        score *= 1.1
    
    # Reward presence of key legal elements
    if chunk.get('metadata', {}).get('has_citations'):
        score *= 1.2
        
    return min(score, 1.0)
```

#### 3.3 Chunk Relationship Mapping
```python
def build_chunk_relationships(chunks: List[Dict]) -> List[Dict]:
    """Identify relationships between chunks"""
    relationships = []
    
    for i, chunk in enumerate(chunks):
        # Sequential relationship
        if i > 0:
            relationships.append({
                'source': chunks[i-1]['metadata']['chunk_id'],
                'target': chunk['metadata']['chunk_id'],
                'type': 'follows'
            })
        
        # Reference relationships (citations, cross-references)
        references = extract_references(chunk['text'])
        for ref in references:
            if target_chunk := find_chunk_with_reference(chunks, ref):
                relationships.append({
                    'source': chunk['metadata']['chunk_id'],
                    'target': target_chunk['metadata']['chunk_id'],
                    'type': 'references'
                })
    
    return relationships
```

### Phase 4: Integration Improvements

#### 4.1 Pre-Entity Extraction Validation
```python
def prepare_chunks_for_entity_extraction(chunks: List[Dict]) -> List[Dict]:
    """Validate and prepare chunks before entity extraction"""
    prepared = []
    
    for chunk in chunks:
        # Skip empty or too-short chunks
        if len(chunk['text'].strip()) < 50:
            logger.warning(f"Skipping chunk {chunk.get('metadata', {}).get('chunk_id')}: too short")
            continue
            
        # Ensure required metadata
        if 'metadata' not in chunk:
            chunk['metadata'] = {}
            
        # Add extraction hints
        chunk['metadata']['extraction_hints'] = {
            'likely_entity_count': estimate_entity_count(chunk['text']),
            'document_section': classify_section(chunk['text']),
            'priority': calculate_extraction_priority(chunk)
        }
        
        prepared.append(chunk)
    
    return prepared
```

#### 4.2 Chunk Caching Strategy
```python
def cache_chunking_result(document_id: str, chunks: List[Dict], strategy: str):
    """Cache chunking results for reprocessing scenarios"""
    cache_key = f"chunks:{document_id}:{strategy}:v2"
    cache_data = {
        'chunks': chunks,
        'strategy': strategy,
        'timestamp': datetime.utcnow().isoformat(),
        'version': '2.0'
    }
    
    redis_client.setex(
        cache_key,
        timedelta(days=7),
        json.dumps(cache_data, cls=DateTimeEncoder)
    )
```

### Phase 5: Monitoring and Observability

#### 4.1 Chunking Metrics
Track in application monitoring:
- Average chunks per document
- Chunk size distribution
- Chunking strategy usage
- Failed chunking attempts
- Time spent in chunking

#### 4.2 Quality Dashboards
Create Supabase views:
```sql
CREATE VIEW chunk_quality_metrics AS
SELECT 
    d.project_id,
    COUNT(DISTINCT c.document_id) as doc_count,
    AVG(LENGTH(c.text)) as avg_chunk_size,
    COUNT(c.id) as total_chunks,
    AVG(c.chunk_index) as avg_chunks_per_doc
FROM chunks c
JOIN source_documents d ON c.document_id = d.id
GROUP BY d.project_id;
```

## Implementation Priority

### Immediate Actions (Today)
1. Add diagnostic logging to verify chunking is working
2. Run diagnostic on a failing document
3. Verify database storage of chunks

### This Week
1. Implement chunk validation function
2. Add CLI diagnostic command
3. Enhance chunk metadata

### Next Sprint
1. Implement adaptive chunk sizing
2. Add chunk quality scoring
3. Create monitoring dashboard

### Future Enhancements
1. AI-guided chunking option
2. Legal-specific chunking rules
3. Chunk relationship mapping

## Success Metrics

1. **Chunk Coverage**: >95% of document text captured in chunks
2. **Semantic Integrity**: <5% of chunks split mid-sentence
3. **Processing Speed**: <2 seconds per document for chunking
4. **Entity Extraction Success**: >90% of chunks produce valid entities
5. **No Empty Chunks**: 0 empty chunks in production

## Risk Mitigation

1. **Backward Compatibility**: Keep existing chunking as default
2. **Gradual Rollout**: Test new strategies on subset of documents
3. **Fallback Logic**: Always have simple chunking as backup
4. **Monitoring**: Alert on chunking failures or anomalies

## Conclusion

The chunking system is fundamentally sound but needs:
1. Better observability to diagnose issues
2. Enhanced metadata for downstream processing
3. Adaptive strategies for different document types
4. Tighter integration with entity extraction

The proposed plan provides a path to optimize chunking while maintaining system stability and supporting the broader document processing pipeline.