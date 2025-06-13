**CRITICAL MANDATE: STRICT ADHERENCE REQUIRED. FAILURE TO COMPLY WILL COMPROMISE THE ENTIRE PROJECT.**

**ABSOLUTELY NO NEW SCRIPTS ARE TO BE CREATED DURING THIS REFACTORING PROCESS. ALL MODIFICATIONS MUST OCCUR WITHIN THE EXISTING SCRIPT FILES AS SPECIFIED. THE INTEGRITY OF THE CURRENT FILE STRUCTURE IS PARAMOUNT. ANY DEVIATION WILL BE CONSIDERED A CATASTROPHIC FAILURE. ALL OUTPUTS AND VERIFICATIONS MUST CONTINUE TO BE LOGGED AS SEQUENTIALLY NUMBERED `context_` DOCUMENTS IN THE `/ai_docs/` DIRECTORY. THIS IS NON-NEGOTIABLE.**

---

## Comprehensive Langchain Refactoring Document

**Objective:** To strategically refactor the existing document processing pipeline by integrating Langchain components. This aims to improve LLM interaction, standardize text processing, enhance caching for LLM calls, and streamline data flow, while strictly adhering to the existing script structure.

**Core Langchain Integration Concepts for This Pipeline:**

1.  **Langchain Expression Language (LCEL) and Celery Integration:**
    *   **LCEL Chains:** Complex LLM interactions (like entity extraction and potentially resolution) will be defined as LCEL chains primarily within `entity_service.py`. These chains will consist of `PromptTemplate` (or `ChatPromptTemplate`), a Langchain `ChatModel` (e.g., `ChatOpenAI`), and an `OutputParser` (e.g., `PydanticOutputParser`).
    *   **Celery Task Invocation:** Celery tasks in `pdf_tasks.py` will call service methods that internally use these LCEL chains. The LCEL chains will be invoked synchronously using `.invoke()`. Langchain (with `openai` client v1.x+) manages the underlying asynchronous HTTP calls to the LLM API, but the `.invoke()` call itself is blocking from the Celery task's perspective. This means Celery tasks do *not* need to become `async def`. The result of the LCEL chain is returned synchronously to the Celery task.
    *   **Celery Orchestration:** The existing Celery `chain()` and `group()` for orchestrating tasks (OCR -> Chunking -> Entities -> etc.) will remain. LCEL refactors the *internal logic* of specific Celery tasks, not the Celery-level pipeline definition.

2.  **Langchain Caching with Redis:**
    *   **`LLMCache`:** Langchain's global `llm_cache` (and optionally `embedding_cache`) will be configured to use `langchain_community.cache.RedisCache`. This will be initialized using your existing Redis connection provided by `scripts.cache.get_redis_manager().get_client()`.
    *   **Scope:** This cache automatically handles caching of LLM prompt/completion pairs and embedding requests made *through Langchain components*.
    *   **Coexistence:** Your existing `RedisManager` and `@redis_cache` decorator in `scripts.cache.py` will continue to function for application-level caching of entire function outputs, task states, etc. Langchain's cache provides more granular caching for the LLM/embedding steps *within* those functions.

3.  **Pydantic Model Interactions:**
    *   **Output Parsing:** For LLM interactions, `PydanticOutputParser` will be used to parse the LLM's JSON output directly into Pydantic model instances. This often requires a "wrapper" Pydantic model if the LLM is expected to return a list as the root of its JSON (e.g., `class EntityList(BaseModel): entities: List[EntityMentionMinimal]`).
    *   **Existing DB Models:** Your Pydantic models in `scripts.models.py` (like `EntityMentionMinimal`) designed for database interaction will be the target output of these parsers. No major changes to these core models are anticipated due to Langchain integration itself.

4.  **Database Loads to RDS from LCEL Outputs:**
    *   **Data Flow:** The refactored service methods (e.g., in `entity_service.py`) will invoke LCEL chains. These chains will return Pydantic model instances.
    *   **Unchanged DB Logic:** The existing `DatabaseManager` methods in `scripts.db.py` will then take these Pydantic objects and save them to RDS. The core database insertion/update logic remains largely unchanged, as it will operate on the same type of Pydantic objects it (presumably) already handles.

---

**Phased Implementation Task List**

**CRITICAL REMINDER FOR EACH PHASE:** After completing the tasks in each phase, run the entire pipeline with a representative set of production data. Verify all outputs meticulously and document the results, including any errors or deviations, in a new, sequentially numbered `context_` document in the `/ai_docs/` directory. **DO NOT PROCEED TO THE NEXT PHASE UNTIL THE CURRENT PHASE IS FULLY VERIFIED AND STABLE.**

---

**Phase 1: Foundational - Langchain Caching & Basic LLM Setup**

*   **Target Script(s):** `entity_service.py`, potentially a new setup section in `scripts.config.py` or at the application entry point (e.g., `celery_app.py` or where Celery workers are initialized).
*   **Objective:** Initialize Langchain's global LLM cache to use the existing Redis instance. Set up the basic `ChatOpenAI` LLM instance in `EntityService`.
*   **Tasks:**
    1.  **Modify `entity_service.py` (or a central config/setup location):**
        *   **Import necessary Langchain components:**
            ```python
            # At the top of entity_service.py
            import langchain
            from langchain_community.cache import RedisCache
            from langchain_openai import ChatOpenAI
            from scripts.cache import get_redis_manager # Your existing RedisManager
            from scripts.config import OPENAI_API_KEY, OPENAI_MODEL, LLM_MODEL_FOR_RESOLUTION
            ```
        *   **Initialize Langchain Redis Cache:**
            This should be done once when the application/worker starts. If `EntityService` is instantiated per task or frequently, this setup should be global. A good place could be in `celery_app.py` within a `worker_process_init` signal handler, or ensure `EntityService` is a long-lived object if possible. For now, let's assume it can be placed near the `EntityService` instantiation or its `__init__`.
            ```python
            # Inside EntityService.__init__ or a global setup block called once per worker
            # Ensure this runs only once per process if EntityService is re-instantiated often
            if not hasattr(langchain, 'llm_cache') or langchain.llm_cache is None:
                try:
                    redis_client_for_langchain = get_redis_manager().get_client() # Get a raw redis.Redis client
                    if redis_client_for_langchain:
                        langchain.set_llm_cache(RedisCache(redis_client_for_langchain))
                        # Optionally, if you plan to use Langchain embeddings:
                        # from langchain.globals import set_embedding_cache
                        # set_embedding_cache(RedisCache(redis_client_for_langchain))
                        logger.info("Langchain LLM RedisCache initialized.")
                    else:
                        logger.warning("Could not get Redis client for Langchain cache. Langchain caching will be in-memory or disabled.")
                except Exception as e:
                    logger.error(f"Failed to initialize Langchain RedisCache: {e}. Langchain caching may be impacted.")
            ```
        *   **Initialize `ChatOpenAI` instance in `EntityService.__init__`:**
            ```python
            # Inside EntityService.__init__ method
            self.llm = ChatOpenAI(api_key=self.api_key, model=OPENAI_MODEL) # For general extraction
            self.resolution_llm = ChatOpenAI(api_key=self.api_key, model=LLM_MODEL_FOR_RESOLUTION) # For resolution
            ```
*   **Verification:**
    *   Run the pipeline with production data.
    *   Observe logs for "Langchain LLM RedisCache initialized."
    *   Manually check Redis (e.g., using `redis-cli KEYS "langchain:llm:*"`) after some LLM calls (even if not yet refactored via LCEL, direct `ChatOpenAI` calls will use the global cache if set) to see if Langchain cache keys are being created.
    *   Ensure no new errors are introduced.
    *   Document results in `/ai_docs/context_XYZ_phase1_verification.txt`.

---

**Phase 2: Text Chunking Refactor**

*   **Target Script(s):** `chunking_utils.py`, `pdf_tasks.py`.
*   **Objective:** Replace custom chunking logic with Langchain's `TextSplitter` classes.
*   **Tasks:**
    1.  **Modify `chunking_utils.py`:**
        *   **Import Langchain splitters:**
            ```python
            from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
            ```
        *   **Refactor `simple_chunk_text`:**
            ```python
            # In chunking_utils.py
            def simple_chunk_text_langchain(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[Dict[str, Any]]:
                logger.info(f"Using Langchain RecursiveCharacterTextSplitter with chunk_size={chunk_size}, overlap={overlap}")
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=chunk_size,
                    chunk_overlap=overlap,
                    length_function=len,
                    is_separator_regex=False,
                )
                split_texts = text_splitter.split_text(text)
                
                chunks = []
                current_pos = 0
                for i, chunk_text_content in enumerate(split_texts):
                    start_char = text.find(chunk_text_content, current_pos)
                    if start_char == -1: # Should not happen with RecursiveCharacterTextSplitter on whole text
                        start_char = current_pos # Fallback
                    end_char = start_char + len(chunk_text_content)
                    chunks.append({
                        'text': chunk_text_content,
                        'char_start_index': start_char,
                        'char_end_index': end_char,
                        'metadata': { # Mimic existing structure
                            'heading_level': 0,
                            'heading_text': f'LC_Simple_Chunk_{i}',
                            'chunk_method': 'langchain_recursive'
                        }
                    })
                    current_pos = start_char + int(len(chunk_text_content) * (1 - (overlap / chunk_size if chunk_size > 0 else 0))) # Approximate next search start
                logger.info(f"Created {len(chunks)} chunks using Langchain RecursiveCharacterTextSplitter")
                return chunks
            ```
            *   **Note:** Replace the existing `simple_chunk_text` with this or have `pdf_tasks.py` call this new one. The key is adapting the output to the `List[Dict[str, Any]]` structure your pipeline expects if it's not `List[str]`. The `char_start_index` calculation for `RecursiveCharacterTextSplitter` when used with `split_text` requires finding the substring, which is less ideal than `create_documents` which preserves some metadata but might require more adaptation.
        *   **Refactor `chunk_markdown_text` (More Complex):**
            ```python
            # In chunking_utils.py
            def chunk_markdown_text_langchain(markdown_guide: str, raw_text_to_chunk: str) -> List[Dict[str, Any]]:
                logger.info("Starting chunking of raw text using Langchain MarkdownHeaderTextSplitter.")
                headers_to_split_on = [
                    ("#", "Header 1"),
                    ("##", "Header 2"),
                    ("###", "Header 3"),
                    ("####", "Header 4"),
                    ("#####", "Header 5"),
                    ("######", "Header 6"),
                ]
                markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=False)
                # This splits the markdown_guide itself
                md_header_splits = markdown_splitter.split_text(markdown_guide)

                final_chunks = []
                current_search_offset_raw = 0

                for i, doc_chunk in enumerate(md_header_splits):
                    # doc_chunk.page_content is the text under that header from the markdown_guide
                    # doc_chunk.metadata contains the header information (e.g., {'Header 1': 'Title'})
                    md_segment_text = doc_chunk.page_content
                    header_metadata = doc_chunk.metadata

                    # Your existing logic to find this segment in raw_text_to_chunk is still needed
                    # The _basic_strip_markdown_for_search function might still be useful here
                    searchable_text = _basic_strip_markdown_for_search(md_segment_text) # Assuming you keep this helper

                    if not searchable_text.strip():
                        logger.debug(f"Markdown split segment {i} is empty after stripping, skipping.")
                        continue
                    
                    start_index_raw = raw_text_to_chunk.find(searchable_text, current_search_offset_raw)
                    
                    if start_index_raw != -1:
                        end_index_raw = start_index_raw + len(searchable_text)
                        chunk_text_raw = raw_text_to_chunk[start_index_raw:end_index_raw]
                        
                        # Adapt header_metadata to your existing metadata structure
                        current_heading_level = 0
                        current_heading_text = "N/A"
                        if "Header 1" in header_metadata: current_heading_level = 1; current_heading_text = header_metadata["Header 1"]
                        elif "Header 2" in header_metadata: current_heading_level = 2; current_heading_text = header_metadata["Header 2"]
                        # ... and so on for other header levels

                        final_chunks.append({
                            'text': chunk_text_raw,
                            'char_start_index': start_index_raw,
                            'char_end_index': end_index_raw,
                            'metadata': {
                                'heading_level': current_heading_level,
                                'heading_text': current_heading_text,
                                'original_markdown_headers': header_metadata # Store original Langchain metadata
                            }
                        })
                        current_search_offset_raw = end_index_raw
                    else:
                        logger.warning(f"Langchain Markdown segment {i} (header: {header_metadata}) NOT FOUND in raw text. Search text: '{searchable_text[:100]}...'")
                
                logger.info(f"Created {len(final_chunks)} chunks from raw text using Langchain MarkdownHeaderTextSplitter and alignment.")
                return final_chunks
            ```
    2.  **Modify `pdf_tasks.py`:**
        *   In `chunk_document_text` task:
            *   Update the call from `simple_chunk_text(...)` to `simple_chunk_text_langchain(...)` (or your chosen name).
            *   If `chunk_markdown_text` is used elsewhere and needs to be refactored, update its call site too. Ensure the returned `List[Dict[str, Any]]` matches what the rest of the `chunk_document_text` task expects for creating Pydantic models and DB insertion.

*   **Verification:**
    *   Run the pipeline with production data.
    *   Compare the chunking output (number of chunks, content, `char_start_index`, `char_end_index`) with the output from before the refactor. Some differences are expected and potentially desirable if Langchain splitters are better.
    *   Ensure chunks are correctly stored in RDS and cached in Redis.
    *   Verify downstream tasks (entity extraction) still function correctly with the new chunks.
    *   Document results in `/ai_docs/context_XYZ_phase2_verification.txt`.

---

**Phase 3: Entity Extraction Refactor with LCEL**

*   **Target Script(s):** `entity_service.py`, `pdf_tasks.py`.
*   **Objective:** Refactor the core entity extraction logic in `EntityService` to use an LCEL chain with `PydanticOutputParser`.
*   **Tasks:**
    1.  **Modify `entity_service.py`:**
        *   **Define Pydantic wrapper for LLM list output (if not already done):**
            ```python
            # In entity_service.py
            from pydantic import BaseModel # Ensure BaseModel is imported
            from typing import List
            from scripts.models import EntityMentionMinimal 
            # ^ Assuming EntityMentionMinimal has 'text', 'type', 'start_char', 'end_char', 'confidence_score'
            # and other fields your prompt asks for, or adjust the prompt/parser.

            class LLMEntityOutput(BaseModel): # For parsing the direct LLM JSON
                text: str
                type: str
                start: int # Note: prompt asks for 'start', 'end'
                end: int
                confidence: float

            class LLMEntityListOutput(BaseModel):
                entities: List[LLMEntityOutput]
            ```
        *   **Update `EntityService.__init__` (or refactor `_extract_entities_openai_validated`):**
            ```python
            # In EntityService.__init__
            from langchain_core.output_parsers import PydanticOutputParser
            from langchain_core.prompts import ChatPromptTemplate

            # ... self.llm already initialized from Phase 1 ...
            self.entity_extraction_parser = PydanticOutputParser(pydantic_object=LLMEntityListOutput)
            
            # Use the optimized prompt content from previous discussions
            # Ensure the prompt includes "{format_instructions}" where the parser's instructions should go.
            # And "{chunk_text}" and "{few_shot_examples}" as input variables.
            # The prompt content will be the multi-line string you developed.
            # For example:
            optimized_prompt_template_str = """System: You are an expert AI assistant... (your full system prompt)

User:
Your task is to extract entities... (your full user prompt, including examples)
{format_instructions}

Text to analyze:
{chunk_text}
""" # NOTE: Make sure your few_shot_examples are part of the main prompt string if static,
  # or pass them as an input_variable if they change per call.
  # For simplicity, embedding them in the template string as you did previously is fine if they don't change.

            self.entity_extraction_prompt = ChatPromptTemplate.from_template(optimized_prompt_template_str)
            
            self.entity_extraction_chain = (
                self.entity_extraction_prompt |
                self.llm |
                self.entity_extraction_parser
            )
            ```
        *   **Create/Refactor `_perform_entity_extraction_lcel` (replaces `_extract_entities_openai_validated` logic):**
            ```python
            # In EntityService class
            def _perform_entity_extraction_lcel(self, chunk_text: str, chunk_uuid: uuid.UUID, document_uuid: uuid.UUID) -> List[EntityMentionMinimal]:
                # The few-shot examples are now part of the ChatPromptTemplate string.
                # The format_instructions are also automatically injected by PydanticOutputParser.
                try:
                    # Use the main LLM instance
                    parsed_result: LLMEntityListOutput = self.entity_extraction_chain.invoke({
                        "chunk_text": chunk_text,
                        "format_instructions": self.entity_extraction_parser.get_format_instructions() 
                        # ^ Ensure this is correctly passed or pre-formatted into the prompt
                    })
                    
                    # Convert LLMEntityOutput to EntityMentionMinimal
                    entity_mentions = []
                    for llm_entity in parsed_result.entities:
                        # Filter and fix types again, as LLM might not perfectly adhere
                        # This can re-use parts of your existing _filter_and_fix_entities
                        valid_type = self._filter_and_fix_entity_type_from_llm(llm_entity.type) # New helper
                        if not valid_type:
                            continue

                        entity_mentions.append(
                            EntityMentionMinimal(
                                mention_uuid=uuid.uuid4(),
                                document_uuid=document_uuid,
                                chunk_uuid=chunk_uuid,
                                entity_text=llm_entity.text,
                                entity_type=valid_type,
                                start_char=llm_entity.start, # map from 'start'
                                end_char=llm_entity.end,     # map from 'end'
                                confidence_score=llm_entity.confidence,
                                created_at=datetime.utcnow()
                            )
                        )
                    return entity_mentions
                except Exception as e:
                    logger.error(f"LCEL Entity Extraction chain failed for chunk {chunk_uuid}: {e}")
                    # Consider how to handle Langchain's specific exceptions like OutputParsingError
                    return [] # Return empty list on failure to allow pipeline to continue if desired

            def _filter_and_fix_entity_type_from_llm(self, entity_type_str: str) -> Optional[str]:
                # Simplified version of your _filter_and_fix_entities, focused on type string
                ALLOWED_ENTITY_TYPES = {'PERSON', 'ORG', 'LOCATION', 'DATE'}
                ENTITY_TYPE_MAPPING = { # From your entity_service
                    'PERSON': 'PERSON', 'PEOPLE': 'PERSON', 'NAME': 'PERSON', 'ATTORNEY': 'PERSON', 'JUDGE': 'PERSON',
                    'ORG': 'ORG', 'ORGANIZATION': 'ORG', 'COMPANY': 'ORG', 'CORPORATION': 'ORG', 'COURT': 'ORG', 'LAW_FIRM': 'ORG',
                    'LOCATION': 'LOCATION', 'PLACE': 'LOCATION', 'ADDRESS': 'LOCATION', 'CITY': 'LOCATION', 'STATE': 'LOCATION', 'COUNTRY': 'LOCATION',
                    'DATE': 'DATE', 'TIME': 'DATE', 'DATETIME': 'DATE', 'YEAR': 'DATE',
                }
                entity_type_upper = entity_type_str.upper()
                mapped_type = ENTITY_TYPE_MAPPING.get(entity_type_upper)
                if mapped_type and mapped_type in ALLOWED_ENTITY_TYPES:
                    return mapped_type
                if entity_type_upper in ALLOWED_ENTITY_TYPES: # Already a valid type
                    return entity_type_upper
                logger.debug(f"Filtering out LLM entity type: {entity_type_str}")
                return None

            # Ensure extract_entities_from_chunk calls this new LCEl method
            # The main logic of extract_entities_from_chunk (caching, validation) can remain,
            # but the core extraction call changes.
            # Original _extract_entities_openai_validated is replaced by _perform_entity_extraction_lcel
            # Original _extract_entities_local_ner_validated remains as a fallback if OpenAI/LCEL is not used.
            ```
    2.  **Modify `pdf_tasks.py` (`extract_entities_from_chunks` task):**
        *   The call to `self.entity_service.extract_entities_from_chunk(...)` will now use the LCEL-backed implementation.
        *   The structure of the returned `EntityExtractionResultModel` (or `List[EntityMentionMinimal]`) from the service method should ideally remain compatible with what the Celery task expects for database insertion (`self.db_manager.create_entity_mentions`). The example above for `_perform_entity_extraction_lcel` now directly returns `List[EntityMentionMinimal]`, simplifying the Celery task's adaptation.
        *   The Celery task will need to instantiate `EntityService` if it doesn't already, ensuring the LLM and chain are set up.
            ```python
            # In pdf_tasks.py, within extract_entities_from_chunks
            # ...
            # Ensure self.entity_service is initialized (e.g., in PDFTask base or here)
            if not hasattr(self, 'entity_service') or self.entity_service is None:
                self.entity_service = EntityService(self.db_manager) # From PDFTask base

            # ... inside the loop for chunks ...
            result_entities_for_chunk = self.entity_service._perform_entity_extraction_lcel( # Or the public method that calls it
                chunk_text=chunk_text,
                chunk_uuid=uuid.UUID(chunk['chunk_uuid']), # ensure UUID object
                document_uuid=document_uuid_obj # ensure UUID object
            )
            all_entity_mentions.extend(result_entities_for_chunk)
            # ... rest of the logic for storing ...
            ```

*   **Verification:**
    *   Run the pipeline with production data.
    *   Verify entities are extracted and match the quality/types expected.
    *   Check Redis for Langchain LLM cache entries (`langchain:llm:...`).
    *   Confirm entities are correctly stored in RDS.
    *   Document results in `/ai_docs/context_XYZ_phase3_verification.txt`.

---

**Phase 4: Entity Resolution Refactor with LCEL (If LLM-based)**

*   **Target Script(s):** `entity_service.py`, `pdf_tasks.py`.
*   **Objective:** If `_resolve_entities_with_llm` is used and is a target for refactor, convert it to an LCEL chain.
*   **Tasks:**
    1.  **Modify `entity_service.py`:**
        *   **Define Pydantic models for LLM resolution output (if different from extraction):**
            ```python
            # In entity_service.py (if needed for resolution output)
            class LLMResolutionGroup(BaseModel):
                canonical_name: str
                mention_texts: List[str]

            class LLMResolutionOutput(BaseModel):
                resolved_groups: List[LLMResolutionGroup]
            ```
        *   **Update `EntityService.__init__` for resolution chain:**
            ```python
            # In EntityService.__init__
            self.entity_resolution_parser = PydanticOutputParser(pydantic_object=LLMResolutionOutput)
            # Define your specific prompt for LLM-based entity resolution.
            # It should take 'entity_mentions_json_str' and 'entity_type' as input variables.
            # And include '{format_instructions}'.
            resolution_prompt_str = """System: You are an expert in resolving entity mentions to canonical forms.

User:
Resolve the following {entity_type} entity mentions into canonical groups.
Mentions:
{entity_mentions_json_str}

{format_instructions}

Respond with a JSON object containing a single key "resolved_groups".
Each group should have a "canonical_name" and a list of "mention_texts" belonging to it.
"""
            self.entity_resolution_prompt = ChatPromptTemplate.from_template(resolution_prompt_str)
            self.entity_resolution_chain = (
                self.entity_resolution_prompt |
                self.resolution_llm | # Use the specific LLM for resolution
                self.entity_resolution_parser
            )
            ```
        *   **Refactor `_resolve_entities_with_llm` to use the LCEL chain:**
            ```python
            # In EntityService class
            def _resolve_entities_with_llm_lcel(self, mentions: List[EntityMentionModel], entity_type: str) -> List[CanonicalEntityMinimal]:
                if not mentions: return []
                mention_texts_for_prompt = [m.entity_text for m in mentions]
                
                try:
                    # Ensure the input to the chain matches the prompt variables
                    llm_input = {
                        "entity_type": entity_type,
                        "entity_mentions_json_str": json.dumps(mention_texts_for_prompt), # LLM likely prefers string list
                        "format_instructions": self.entity_resolution_parser.get_format_instructions()
                    }
                    resolution_output: LLMResolutionOutput = self.entity_resolution_chain.invoke(llm_input)
                    
                    canonical_entities_minimal = []
                    for group in resolution_output.resolved_groups:
                        # Find original EntityMentionModel objects that match the texts in this group
                        # This part needs careful implementation to map back correctly.
                        # For simplicity, assuming group.mention_texts are sufficient for now
                        # to create the CanonicalEntityMinimal.
                        
                        # Collect all mention_uuids that correspond to the mention_texts in this group
                        current_group_mention_uuids = []
                        for m_model in mentions:
                            if m_model.entity_text in group.mention_texts:
                                current_group_mention_uuids.append(m_model.mention_uuid)

                        canonical_entities_minimal.append(
                            CanonicalEntityMinimal(
                                canonical_entity_uuid=uuid.uuid4(),
                                canonical_name=group.canonical_name,
                                entity_type=entity_type,
                                aliases=list(set(group.mention_texts)),
                                mention_count=len(current_group_mention_uuids), # Or len(group.mention_texts)
                                confidence_score=0.9, # Example
                                metadata={'mention_uuids': [str(uid) for uid in current_group_mention_uuids]} # Store original mention UUIDs if needed
                            )
                        )
                    return canonical_entities_minimal
                except Exception as e:
                    logger.error(f"LCEL Entity Resolution chain failed for type {entity_type}: {e}")
                    # Fallback to fuzzy or other non-LLM method if available
                    return self._resolve_entities_fuzzy(mentions, entity_type) # Example fallback
            ```
    2.  **Modify `pdf_tasks.py` (`resolve_document_entities` task):**
        *   Ensure it calls the new LCEL-based resolution method in `EntityService`.
        *   The task should receive `List[CanonicalEntityMinimal]` and pass it to `save_canonical_entities_to_db` and `update_entity_mentions_with_canonical`.

*   **Verification:**
    *   Run the pipeline.
    *   Check the quality of entity resolution and the `canonical_entities` table in RDS.
    *   Verify Langchain LLM cache usage for resolution calls.
    *   Document results in `/ai_docs/context_XYZ_phase4_verification.txt`.

---

**Phase 5: (Optional) Embedding Refactor**

*   **Target Script(s):** `entity_service.py` (if `_get_entity_embedding` is actively used and a target for refactor).
*   **Objective:** Standardize embedding generation using Langchain's `OpenAIEmbeddings`.
*   **Tasks:**
    1.  **Modify `entity_service.py`:**
        *   **Import `OpenAIEmbeddings`:**
            ```python
            from langchain_openai import OpenAIEmbeddings
            ```
        *   **Initialize in `EntityService.__init__`:**
            ```python
            # In EntityService.__init__
            self.embedding_model = OpenAIEmbeddings(api_key=self.api_key, model="text-embedding-3-small") # Or your preferred model
            ```
        *   **Refactor `_get_entity_embedding`:**
            ```python
            # In EntityService class
            def _get_entity_embedding_langchain(self, entity_text: str, entity_type: str) -> Optional[List[float]]:
                # Contextualization can be done here before passing to embed_query
                contextual_text = f"{entity_type}: {entity_text}" # Simple example
                try:
                    embedding_vector = self.embedding_model.embed_query(contextual_text)
                    return embedding_vector # Returns List[float]
                except Exception as e:
                    logger.error(f"Langchain embedding failed for '{entity_text}': {e}")
                    return None
            ```
*   **Verification:**
    *   If embeddings are stored or used, verify their generation and format.
    *   Check for Langchain embedding cache hits in Redis if caching for embeddings was enabled.
    *   Document results in `/ai_docs/context_XYZ_phase5_verification.txt`.

---

**Phase 6: (Secondary/Optional) Textract Document Loading**

*   **Target Script(s):** `textract_utils.py`, `pdf_tasks.py`.
*   **Objective:** Explore using Langchain's `AmazonTextractPDFLoader` (or a custom wrapper) to standardize OCR output into Langchain `Document` objects if this simplifies downstream processing within a more Langchain-native pipeline.
*   **Considerations:**
    *   This is a more significant architectural shift for the OCR part.
    *   The current `textract_utils.py` has detailed logic for handling async jobs, scanned PDFs, and caching, which would need to be carefully mapped or replaced.
    *   The benefit is that `DocumentLoaders` directly output `List[Document]` which `TextSplitters` consume, potentially streamlining the OCR-to-Chunking transition if the entire pipeline becomes more LCEL-centric.
    *   **This phase might be deferred or deemed too complex given the "no new scripts" constraint and the existing investment in `textract_utils.py`.**
*   **If Proceeding (Simplified Sketch):**
    1.  **Modify `textract_utils.py` or `pdf_tasks.py`:**
        *   Import `AmazonTextractPDFLoader`.
        *   In a section of `extract_text_from_document` (or its equivalent for polling results), after obtaining the raw Textract JSON output:
            ```python
            # This is a conceptual sketch. The AmazonTextractPDFLoader typically takes an S3 path.
            # You might need to adapt it or use the raw Textract response with a custom
            # function to convert it into Langchain Document objects.
            # from langchain_community.document_loaders import AmazonTextractPDFLoader
            
            # If loader works with S3 path:
            # loader = AmazonTextractPDFLoader(s3_path=f"s3://{s3_bucket}/{s3_key}")
            # documents: List[Document] = loader.load()
            # combined_text = "\\n\\n".join([doc.page_content for doc in documents])
            # metadata would need to be aggregated from doc.metadata
            ```
*   **Verification:**
    *   Ensure OCR quality is maintained.
    *   Verify that the `Document` objects produced are compatible with subsequent Langchain text splitters.
    *   Document results.

---

This phased approach allows for incremental refactoring and verification, minimizing risk. Remember the **CRITICAL MANDATE** at each step. Good luck!