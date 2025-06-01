Okay, this is a classic case of a pipeline mismatch causing downstream issues. The core problem, as identified in `context_175_textract_markdown_issue.md`, is that the system was trying to use an *artificially generated* markdown structure to guide the chunking of *plain text* obtained from Textract. This is bound to fail or produce suboptimal chunks.

Here's a detailed markdown recommendation for an optimal chunking method, keeping effective entity extraction and relationship building for a RAG application in mind:

---

# Recommendation: Optimized Text Chunking Strategy

## 1. Executive Summary

The current chunking mechanism, which relies on artificially generating markdown from Textract's plain text output and then using that markdown as a guide, is flawed and should be replaced. Textract provides clean, plain text with page separators (`<END_OF_PAGE>`). The optimal strategy involves:

1.  **Primary Split by Page:** Utilize Textract's `<END_OF_PAGE>` marker for an initial, high-level semantic split.
2.  **Secondary Split by Semantic Units (within pages):** Employ a robust plain text chunker (like LangChain's `RecursiveCharacterTextSplitter` or a refined version of the custom `chunk_plain_text_semantically` logic) to further divide page content into meaningful, overlapping chunks.
3.  **Rich Metadata:** Ensure chunks retain metadata like page number, character offsets, and potentially a chunk title/type if identifiable.

This approach directly processes the available plain text, respects document structure (pages, paragraphs), and creates chunks suitable for effective entity/relationship extraction and RAG.

## 2. Understanding the Current Problem (Recap)

*   **Input:** Textract (`textract_utils.py`) outputs plain text, with pages separated by `\n\n<END_OF_PAGE>\n\n`.
*   **Flawed Process (Old):**
    1.  `generate_simple_markdown` (in `text_processing.py` or `chunking_utils.py`) converts this plain text into *artificial* markdown (e.g., "ALL CAPS" -> "## ALL CAPS").
    2.  `chunk_markdown_text` (in `chunking_utils.py`) then tries to find these artificial markdown structures within the original plain text. This fails because the markdown syntax (`##`) isn't actually in the `raw_text_to_chunk`.
*   **Consequence:** Poor chunking, few chunks, fallback to simple size-based chunking, leading to issues with `ChunkingResultModel` and ineffective downstream processing.
*   **Partially Implemented Fix:** `text_processing.py` now calls `scripts.plain_text_chunker.chunk_plain_text_semantically`, which is a step in the right direction. This recommendation refines and formalizes that approach.

## 3. Core Principle for Solution

**Chunk based on the actual structure and content of the plain text provided by Textract, prioritizing natural semantic boundaries.** Avoid introducing artificial intermediate representations (like generated markdown) that don't exist in the source.

## 4. Proposed Chunking Strategy

The document processing flow for chunking should be:

```mermaid
graph TD
    A[Raw Document] --> B{OCR with Textract};
    B -- Plain Text Output --> C[Text Cleaning];
    C -- `text_with_page_markers` --> D{Primary Split by "<END_OF_PAGE>"};
    D -- List of Page Texts --> E{Loop through each Page};
    E -- Single Page Text --> F{Secondary Split: Semantic Plain Text Chunking};
    F -- Chunks from Page --> G[Store Chunks with Metadata];
    G --> H[Downstream: Entity Extraction, RAG];
```

### Step-by-Step Breakdown:

**Step 1: OCR & Initial Text Output**
*   As currently done by `textract_utils.py` (`process_textract_blocks_to_text`).
*   Output: A single string containing the entire document's text, with `\n\n<END_OF_PAGE>\n\n` separating pages.

**Step 2: Text Cleaning (Optional but Recommended)**
*   The `clean_extracted_text` function in `text_processing.py` can be used for basic normalization (e.g., removing `<|im_end|>`, normalizing excessive whitespace). This should be applied to the full text *before* page splitting or to individual page texts.

**Step 3: Primary Split by Page**
*   Take the full, cleaned text and split it using `\n\n<END_OF_PAGE>\n\n` as the delimiter.
*   This will result in a list of strings, where each string is the content of one page.
*   Keep track of the original page number for each segment.

**Step 4: Secondary Split - Semantic Plain Text Chunking (Per Page)**
For each "page text" string obtained from Step 3:
*   **Method A: LangChain's `RecursiveCharacterTextSplitter` (Recommended for robustness and ease of use)**
    *   Initialize `RecursiveCharacterTextSplitter` with appropriate parameters:
        *   `chunk_size`: Target size in characters (e.g., 1000-2000 characters, tunable based on LLM context for entity extraction). For RAG, 256-512 tokens is a common target. Convert characters to tokens approximately (1 token ~ 4 chars).
        *   `chunk_overlap`: (e.g., 100-200 characters or 20-50 tokens) to maintain context across chunks.
        *   `separators`: `["\n\n", "\n", ". ", " ", ""]` (Prioritize double newlines for paragraphs, then single newlines, then sentences if desired, then spaces, then characters as a last resort).
        *   `length_function`: `len` (for character count).
    *   Apply this splitter to the text of the current page.
*   **Method B: Custom Semantic Chunker (e.g., `plain_text_chunker.chunk_plain_text_semantically`)**
    *   This approach, as sketched in `context_175_textract_markdown_issue.md` and implemented in `text_processing.py` (via `plain_text_chunker.py`), is also valid. It typically involves splitting by paragraphs (`\n\n`) and then potentially merging or further splitting based on heuristics (e.g., heading-like lines, min/max chunk size).
    *   Ensure it handles character offsets correctly and allows for overlap.
    *   This method can be more tailored but requires careful implementation and testing.

**Step 5: Chunk Refinement (Optional)**
*   The `refine_chunks` function from `chunking_utils.py` (modified to work with plain text chunks if necessary) can be used to merge very small chunks into adjacent ones to meet a minimum size, if the secondary splitter produces them. This is often handled by good parameters in `RecursiveCharacterTextSplitter` anyway.

**Step 6: Metadata Assignment**
For each final chunk:
*   `chunk_uuid`: Unique identifier.
*   `document_uuid`: Link to the parent document.
*   `text_content`: The actual text of the chunk.
*   `page_number`: The page from which this chunk originated (from Step 3).
*   `char_start_index_in_page`: Character start offset *within that page's text*.
*   `char_end_index_in_page`: Character end offset *within that page's text*.
*   `char_start_index_in_doc`: (Optional but very useful for RAG source highlighting) Absolute character start offset *within the original document text*. This requires careful offset calculation across pages.
*   `char_end_index_in_doc`: Absolute character end offset *within the original document text*.
*   `chunk_index_in_page`: Sequential index of the chunk within its page.
*   `chunk_index_in_doc`: Overall sequential index of the chunk within the document.
*   `token_count`: (Approximate) number of tokens.
*   `metadata_json`: Store other relevant info, e.g., `{ "chunk_type": "paragraph" }` or if a heuristic identifies it as a heading.

**Step 7: Database Insertion**
*   Store these structured chunks in your database (Supabase). The `prepare_chunks_for_database` function in `chunking_utils.py` can be adapted.

## 5. Implementation Details & Code Snippet (Illustrative)

This modifies `text_processing.py :: process_document_with_semantic_chunking`.

```python
# In text_processing.py

from langchain.text_splitter import RecursiveCharacterTextSplitter
# from scripts.plain_text_chunker import chunk_plain_text_semantically # Keep if preferred

# ... (other imports)

def process_document_with_plain_text_chunking( # Renamed for clarity
    db_manager,
    document_sql_id: int,
    document_uuid: str,
    raw_text: str, # This is the full text from Textract
    ocr_metadata: Optional[Dict] = None,
    doc_category: str = 'document',
    use_structured_extraction: bool = True # For downstream entity extraction
) -> Tuple[ChunkingResultModel, Optional[StructuredExtractionResultModel]]:
    logger.info(f"Processing document {document_uuid} with plain text chunking")

    chunking_result = ChunkingResultModel(
        document_uuid=uuid.UUID(document_uuid),
        document_id=document_sql_id,
        strategy="recursive_plain_text_by_page", # Updated strategy name
        status=ProcessingResultStatus.SUCCESS
    )

    try:
        cleaned_full_text = clean_extracted_text(raw_text)
        page_texts_with_ends = cleaned_full_text.split("<END_OF_PAGE>") # Includes newlines around marker

        all_processed_chunks = []
        current_doc_char_offset = 0
        overall_chunk_idx = 0

        # Define your splitter once
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500, # Target characters per chunk
            chunk_overlap=150, # Characters of overlap
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""], # Prioritize paragraph breaks
            add_start_index=True # LangChain splitter can return start_index
        )

        for page_idx, page_text_raw in enumerate(page_texts_with_ends):
            page_text = page_text_raw.strip() # Remove leading/trailing whitespace from split
            if not page_text: # Skip empty pages that might result from split
                current_doc_char_offset += len(page_text_raw) # Account for original length including marker
                continue

            # LangChain's split_text returns list of strings. For offsets, use create_documents.
            # Or, manually track offsets if using a custom splitter or older LangChain.
            # For simplicity here, assuming `text_splitter.create_documents` or similar:
            
            page_langchain_docs = text_splitter.create_documents([page_text])

            for chunk_idx_in_page, lc_doc_chunk in enumerate(page_langchain_docs):
                chunk_text = lc_doc_chunk.page_content
                # `lc_doc_chunk.metadata['start_index']` is char_start_index_in_page
                char_start_in_page = lc_doc_chunk.metadata.get('start_index', 0) 
                char_end_in_page = char_start_in_page + len(chunk_text)

                # Calculate absolute offsets (simplified, ensure accuracy in implementation)
                # This needs to accurately reflect the original cleaned_full_text structure
                abs_char_start = current_doc_char_offset + char_start_in_page
                abs_char_end = abs_char_start + len(chunk_text)

                chunk_metadata_obj = ChunkMetadata(
                    chunk_type="paragraph", # Or detect if it's a heading
                    language="en", # Assuming English
                    page_numbers=[page_idx + 1] # 1-based page index
                )

                processed_chunk = ProcessedChunk(
                    chunk_id=uuid.uuid4(),
                    chunk_index=overall_chunk_idx,
                    text=chunk_text,
                    char_start=abs_char_start, # Absolute start
                    char_end=abs_char_end,     # Absolute end
                    token_count=len(chunk_text.split()), # Simple estimation
                    metadata=chunk_metadata_obj,
                    # Add page_char_start/end if needed for Pydantic model
                    page_char_start=char_start_in_page,
                    page_char_end=char_end_in_page
                )
                all_processed_chunks.append(processed_chunk)
                
                # Store in DB
                # Adapt db_manager.create_chunk_entry or use existing logic
                # Ensure metadata_json in DB stores page_number, char_start_in_page etc.
                db_manager.create_chunk_entry(
                    document_fk_id=document_sql_id,
                    document_uuid=document_uuid,
                    chunk_index=overall_chunk_idx,
                    text_content=chunk_text,
                    char_start_index=abs_char_start, # Use absolute for DB consistency
                    char_end_index=abs_char_end,
                    metadata_json={
                        "page_number": page_idx + 1,
                        "char_start_in_page": char_start_in_page,
                        "char_end_in_page": char_end_in_page,
                        "original_chunk_index_in_page": chunk_idx_in_page,
                        # any other metadata from chunk_metadata_obj
                    }
                )
                overall_chunk_idx += 1
            
            current_doc_char_offset += len(page_text_raw) # Advance by original length of page text + marker

        # Link chunks (previous_chunk_id, next_chunk_id)
        for i in range(len(all_processed_chunks)):
            if i > 0:
                all_processed_chunks[i].previous_chunk_id = all_processed_chunks[i-1].chunk_id
            if i < len(all_processed_chunks) - 1:
                all_processed_chunks[i].next_chunk_id = all_processed_chunks[i+1].chunk_id
        
        chunking_result.chunks = all_processed_chunks
        chunking_result.total_chunks = len(all_processed_chunks)
        chunking_result.total_characters = len(cleaned_full_text)
        if all_processed_chunks:
            chunking_result.average_chunk_size = sum(len(c.text) for c in all_processed_chunks) / len(all_processed_chunks)

        # ... (Structured Extraction Logic remains largely the same, operating on these new chunks)
        structured_extraction_result = None
        if use_structured_extraction and all_processed_chunks:
            # ... (Perform structured extraction as before)
            pass

        logger.info(f"Successfully processed document {document_uuid}: {len(all_processed_chunks)} chunks created")
        return chunking_result, structured_extraction_result

    except Exception as e:
        logger.error(f"Error processing document {document_uuid}: {e}", exc_info=True)
        chunking_result.status = ProcessingResultStatus.FAILED
        chunking_result.error_message = str(e)
        return chunking_result, None

```

## 6. Why This is an Improvement

*   **Accuracy:** Directly processes Textract's output without relying on fragile artificial markdown.
*   **Semantic Boundaries:** Prioritizes page breaks (`<END_OF_PAGE>`) and then paragraph/sentence breaks, leading to more semantically coherent chunks.
*   **Context Preservation:** Chunk overlap and page-level splitting help maintain context necessary for entity/relationship extraction.
*   **Robustness:** Less prone to errors caused by the mismatch between artificial markdown and plain text.
*   **Simplicity:** Conceptually simpler and aligns better with standard text processing practices.
*   **Standard Tools:** Leverages well-tested libraries like LangChain's text splitters if chosen.

## 7. Addressing Entity Extraction and RAG

*   **Entity Extraction:**
    *   Semantically coherent chunks with sufficient context (due to appropriate `chunk_size` and `overlap`) are better inputs for LLMs performing entity extraction.
    *   The "horrible prompt" for entity extraction (from `context_174`) can now operate on more reliable text segments.
    *   Storing `page_number` and character offsets allows entities to be precisely located within the original document.
*   **RAG (Retrieval Augmented Generation):**
    *   Well-defined chunks improve the quality of embeddings for semantic search.
    *   Retrieved chunks will have better context.
    *   The ability to reference `page_number` and provide precise text segments enhances the explainability and trustworthiness of RAG outputs.
    *   Overlapping chunks ensure that if a query matches content near a boundary, relevant context from both sides can be retrieved (depending on K value in retrieval).

## 8. Future Enhancements

1.  **Table Handling:** For documents with complex tables, integrate Textract's table extraction. Store table data (e.g., as HTML or markdown strings) and chunk it separately or summarize it. The summary could be embedded, and if retrieved, the full table data can be passed to the LLM. (See `5_Levels_Of_Text_Splitting.ipynb` for Unstructured.io ideas for PDFs).
2.  **Image Handling:** Similar to tables, if images are important, extract them, generate summaries/captions (e.g., using a multimodal LLM like GPT-4V), and link these back to text chunks based on proximity or page.
3.  **Advanced Semantic Chunking (AI-Based):** Once the deterministic approach is stable, consider implementing AI-based chunking (as proposed in `context_174_chunking_strategy_analysis.md` or Level 4/5 from the notebook) for documents requiring higher semantic precision, if cost and latency are acceptable. This would replace/augment Step 4 (Secondary Split).
4.  **Fine-tuning Chunk Parameters:** Experiment with `chunk_size` and `chunk_overlap` based on the specific LLMs used for entity extraction and RAG, and the document types encountered. Use evaluation frameworks (RAGAS, LangChain Evals) to measure effectiveness.
5.  **Hierarchical Chunking (ParentDocumentRetriever):** As mentioned in the notebook (Bonus Level), for very long documents or varied content, consider a parent-child chunking strategy where smaller sub-chunks are embedded for retrieval, but a larger parent chunk is provided to the LLM for context. The page-level split already provides a natural first level of hierarchy.

By adopting this plain-text-first, semantically-aware chunking strategy, the pipeline will be more robust, and the resulting chunks will be far more effective for the downstream tasks of entity extraction and RAG.

---