# Context 174: Chunking Strategy Analysis & Improvements

## Date: 2025-05-28

## Executive Summary

After thorough investigation, the document processing pipeline uses a **markdown-guided chunking approach** rather than AI-based chunking. The chunking is performed using regex patterns and structural analysis, not OpenAI API calls. The "horrible prompt" the user saw in OpenAI logs is likely from the **entity extraction** phase, not chunking.

## Current Chunking Strategy

### 1. Markdown Generation (Non-AI)
```python
def generate_simple_markdown(text: str) -> str:
    # Uses regex patterns to identify:
    # - All-caps short text → ## Heading
    # - Numbered items → ### Subheading
    # - Everything else → Regular paragraphs
```

### 2. Structural Chunking
- Splits text based on markdown structure
- Uses heading patterns and paragraph breaks
- Falls back to simple size-based chunking if markdown fails
- No AI/LLM calls involved

### 3. Where AI IS Used
- **Entity Extraction**: Very detailed prompt for extracting legal entities
- **Structured Extraction**: Extracting metadata from chunks (if enabled)
- **NOT for chunking**: The chunking itself is deterministic

## Potential Confusion Sources

### 1. Entity Extraction Prompt (What User Likely Saw)
The entity extraction uses a very verbose prompt that could be mistaken for chunking:
```python
prompt = f"""You are an expert Legal Document Entity Extraction Specialist AI.
Your primary goal is to meticulously analyze legal text and extract named entities...
[VERY LONG PROMPT]
"""
```

### 2. Structured Extraction (If Enabled)
When `USE_STRUCTURED_EXTRACTION` is enabled, each chunk is analyzed by AI to extract:
- Document metadata
- Key facts
- Entities
- Relationships

## Proposed AI-Based Chunking Strategy

If we want to implement true AI-based semantic chunking, here's an optimal approach:

### 1. Improved System Message
```python
CHUNKING_SYSTEM_MESSAGE = """You are an AI assistant specialized in semantic chunking of legal documents. 
You analyze document structure and content to create meaningful, self-contained chunks.
Return ONLY valid JSON with no additional text, no markdown formatting, and no explanations.
Your entire response must be parseable by json.loads()."""
```

### 2. Optimized Chunking Prompt
```python
def create_semantic_chunking_prompt(text: str, doc_type: str = "legal") -> str:
    return f"""Semantically chunk this {doc_type} document into coherent sections.

Document Text:
{text}

Return a JSON object with this EXACT structure:
{{
  "chunks": [
    {{
      "title": "Brief descriptive title for this chunk",
      "start_char": 0,
      "end_char": 500,
      "text": "The actual text content of this chunk",
      "chunk_type": "introduction|argument|fact|conclusion|procedural|other",
      "entities_mentioned": ["list", "of", "key", "entities"],
      "semantic_tags": ["relevant", "tags"]
    }}
  ],
  "document_metadata": {{
    "title": "Overall document title if identifiable",
    "type": "motion|complaint|order|contract|correspondence|other",
    "total_chunks": 5
  }}
}}

Chunking Guidelines:
1. Each chunk should be 200-1000 words (adjust based on semantic boundaries)
2. Preserve complete thoughts and legal arguments
3. Keep related facts and reasoning together
4. Identify natural document divisions (sections, arguments, etc.)
5. Maintain chronological or logical flow

CRITICAL: Return ONLY the JSON object. No explanations."""
```

### 3. Implementation Approach
```python
@rate_limit(key="openai_chunking", limit=10, window=60)
def semantic_chunk_with_ai(text: str, doc_type: str = "legal") -> List[Dict]:
    """Use AI to semantically chunk document text"""
    
    # For very long documents, process in segments
    MAX_CONTEXT = 12000  # Leave room for response
    
    if len(text) > MAX_CONTEXT:
        # Process in overlapping segments
        segments = create_overlapping_segments(text, MAX_CONTEXT, overlap=500)
        all_chunks = []
        
        for segment in segments:
            chunks = call_openai_chunking(segment, doc_type)
            all_chunks.extend(reconcile_chunks(chunks, segment.offset))
            
        return merge_adjacent_chunks(all_chunks)
    else:
        return call_openai_chunking(text, doc_type)
```

## Benefits of AI-Based Chunking

1. **Semantic Coherence**: Chunks based on meaning, not just structure
2. **Context Awareness**: Understanding legal document flow
3. **Dynamic Sizing**: Chunks sized based on content complexity
4. **Better Entity Grouping**: Related entities stay together
5. **Improved Downstream Processing**: Better input for entity extraction

## Risks and Mitigations

### 1. Cost
- **Risk**: OpenAI API calls for every document
- **Mitigation**: Cache results, use for high-value documents only

### 2. Latency
- **Risk**: Slower than regex-based chunking
- **Mitigation**: Async processing, parallel segment handling

### 3. Token Limits
- **Risk**: Long documents exceed context window
- **Mitigation**: Segment processing with overlap reconciliation

### 4. Inconsistency
- **Risk**: Non-deterministic results
- **Mitigation**: Temperature=0, structured output format

## Recommendation

1. **Keep Current System**: The markdown-guided approach is fast and deterministic
2. **Add AI Option**: Implement AI chunking as an optional premium feature
3. **Fix Prompt Verbosity**: Simplify entity extraction prompt
4. **Clear Separation**: Make it obvious which prompts are for what purpose

## Immediate Actions

1. **Fix Entity Extraction Prompt**: Make it concise and focused
2. **Add Chunking Strategy Config**: Allow choice between methods
3. **Improve Logging**: Clear labels for what each AI call is doing
4. **Document the Flow**: Make it clear where AI is and isn't used

## Code Quality Improvements

The current code has good separation of concerns:
- Chunking logic separate from AI calls
- Clear abstraction layers
- Good error handling

The confusion likely stems from:
1. Verbose prompts in entity extraction
2. Multiple AI touchpoints in the pipeline
3. Lack of clear documentation about what each phase does

## Next Steps

1. Implement the `ChunkingResultModel` len() fix (already identified)
2. Optionally implement AI-based chunking as described above
3. Simplify existing AI prompts for clarity
4. Add better pipeline visualization/documentation