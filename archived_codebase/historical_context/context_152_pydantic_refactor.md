
Here's a conceptual overview of how Pydantic schemas should be integrated, forming the basis for the detailed task list (`context_153_pydantic_tasks.md`) that the agentic coding tool will generate and execute.

**Core Principle: Pydantic as the "Single Source of Truth" for Data Structures**

Instead of relying on dictionaries with implicit structures, or manually ensuring alignment with Supabase columns, Pydantic models will define the shape, types, and validation rules for your data objects.

**1. Identifying Key Data Entities for Pydantic Modeling:**

Based on your codebase (especially `supabase_utils.py`, `*_extraction.py`, `*_processor.py` files, and the Supabase schema `supabase_schema_27_05_25_214849.json`), the primary candidates for Pydantic models are:

*   **ProjectModel:** Representing the `projects` table.
    *   Fields: `id` (Optional[int]), `projectId` (uuid.UUID), `name` (str), `createdAt` (Optional[datetime]), `updatedAt` (Optional[datetime]), etc.
*   **SourceDocumentModel:** Representing the `source_documents` table. This is a critical model.
    *   Fields: `id` (Optional[int]), `document_uuid` (uuid.UUID), `project_fk_id` (Optional[int]), `project_uuid` (Optional[uuid.UUID]), `original_file_name` (str), `detected_file_type` (str), `raw_extracted_text` (Optional[str]), `ocr_metadata_json` (Optional[Dict[str, Any]]), `celery_status` (Optional[str]), `s3_key` (Optional[str]), etc.
    *   This model will be used when creating new documents, fetching them, and updating their status/content.
*   **Neo4jDocumentModel:** Representing the `neo4j_documents` table.
    *   Fields: `id` (Optional[int]), `documentId` (uuid.UUID), `source_document_fk_id` (int), `project_id` (int), `project_uuid` (uuid.UUID), `name` (str), `storagePath` (Optional[str]), `processingStatus` (str), `metadata_json` (Optional[Dict[str, Any]]), etc.
*   **ChunkModel:** Representing the `neo4j_chunks` table.
    *   Fields: `id` (Optional[int]), `chunkId` (uuid.UUID), `document_id` (int), `document_uuid` (uuid.UUID), `chunkIndex` (int), `text` (str), `char_start_index` (int), `char_end_index` (int), `metadata_json` (Optional[Dict[str, Any]]), `embedding` (Optional[List[float]]), etc.
    *   `chunking_utils.py` will produce lists of these.
*   **EntityMentionModel:** Representing `neo4j_entity_mentions`.
    *   Fields: `id` (Optional[int]), `entityMentionId` (uuid.UUID), `chunk_fk_id` (int), `chunk_uuid` (uuid.UUID), `value` (str), `entity_type` (str), `normalizedValue` (Optional[str]), `offsetStart` (Optional[int]), `offsetEnd` (Optional[int]), `resolved_canonical_id` (Optional[uuid.UUID]), `attributes_json` (Optional[Dict[str, Any]]), etc.
    *   `entity_extraction.py` will output these.
*   **CanonicalEntityModel:** Representing `neo4j_canonical_entities`.
    *   Fields: `id` (Optional[int]), `canonicalEntityId` (uuid.UUID), `documentId` (Optional[int]), `document_uuid` (Optional[uuid.UUID]), `canonicalName` (str), `entity_type` (str), `allKnownAliasesInDoc` (Optional[List[str]]), `mention_count` (Optional[int]), `embedding` (Optional[List[float]]), etc.
    *   `entity_resolution.py` and `entity_resolution_enhanced.py` will produce these.
*   **RelationshipStagingModel:** For `neo4j_relationships_staging`.
    *   Fields: `id` (Optional[int]), `fromNodeId` (str), `fromNodeLabel` (str), `toNodeId` (str), `toNodeLabel` (str), `relationshipType` (str), `properties` (Optional[Dict[str, Any]]), etc.
*   **TextractJobModel:** Representing the `textract_jobs` table.
    *   Fields: `id` (Optional[int]), `job_id` (str), `source_document_id` (int), `document_uuid` (uuid.UUID), `job_status` (str), `s3_input_bucket` (str), `s3_input_key` (str), etc.
*   **ImageProcessingResultModel:** Output of `image_processing.py`.
    *   Fields like `extracted_text` (str), `confidence_score` (float), `image_type` (str), `entities_detected` (List[str]), `processing_metadata` (Dict). This can be a nested Pydantic model.
*   **StructuredExtractionModels:** The dataclasses in `structured_extraction.py` (`DocumentMetadata`, `KeyFact`, `EntitySet`, `Relationship`, `StructuredChunkData`) should be converted to Pydantic models. This will allow for validation of LLM outputs for structured data.
*   **CeleryTaskPayloadModels:** For inputs to Celery tasks (e.g., `ProcessOCRTaskPayload`, `ProcessImageTaskPayload`).
*   **RedisCacheModels:** For objects stored in Redis (e.g., `CachedOCRResult`, `CachedEntityResolution`).

**2. How Pydantic Models Will Be Used:**

*   **Function Signatures:** Replace `Dict` or `List[Dict]` with specific Pydantic model type hints for function arguments and return values.
    *   Example: `def create_source_document_entry(...) -> SourceDocumentModel:`
*   **Data Ingestion/Creation:** When new data is created (e.g., reading a file, receiving API input), parse it into a Pydantic model instance. This validates the data at the entry point.
    *   Example (conceptual): `doc_data_from_file = {...}; pydantic_doc = SourceDocumentModel(**doc_data_from_file)`
*   **Database Interaction (`supabase_utils.py`):**
    *   **Insertion:** Functions that insert data (e.g., `create_source_document_entry`) will accept Pydantic model instances. Internally, they will convert the model to a dictionary using `model.model_dump(exclude_none=True)` before sending it to `supabase.table(...).insert(...)`.
    *   **Fetching:** Functions that fetch data will retrieve raw dictionaries from Supabase and then parse these dictionaries into Pydantic model instances. This validates that data from the DB conforms to expectations.
    *   **Updating:** Similar to insertion, update functions will take Pydantic models (or relevant parts), convert to dicts for the update payload.
*   **LLM Interactions:**
    *   **`structured_extraction.py`:** The LLM's JSON output for structured data should be parsed directly into the `StructuredChunkData` Pydantic model. This ensures the LLM is "speaking the right language." If parsing fails, it indicates a problem with the LLM's output or the prompt.
    *   **`entity_extraction.py` (OpenAI):** The JSON output from OpenAI for entities should be parsed into a `List[EntityMentionModel]`.
*   **Redis Caching (`redis_utils.py`):**
    *   **Setting Cache:** Before caching, Pydantic models will be serialized to JSON strings (`model.model_dump_json()`).
    *   **Getting Cache:** JSON strings retrieved from Redis will be parsed back into Pydantic models (`MyModel.model_validate_json(json_string)`).
*   **Inter-script/Inter-module Data Exchange:** Passing Pydantic models instead of raw dictionaries ensures that data contracts between different parts of the application are explicit and enforced.
*   **Error Handling:** Pydantic's `ValidationError` will be the primary mechanism for catching data-related errors, providing clear feedback on what went wrong.

**3. Key Benefits for Your Codebase:**

*   **Reduced Runtime Errors:** Catch data inconsistencies early. If data doesn't fit the Pydantic model, a `ValidationError` is raised immediately, pointing to the exact field and issue. This is much better than errors occurring deep within business logic due to unexpected data shapes.
*   **Improved Code Clarity & Maintainability:** Pydantic models act as living documentation for your data structures. Anyone reading the code can immediately understand the expected shape and type of data.
*   **Easier Refactoring:** If a data structure needs to change, updating the Pydantic model and then fixing the resulting validation errors across the codebase is a more guided process.
*   **Enhanced Developer Experience:** Autocompletion and type checking in IDEs.
*   **Alignment with Supabase:** Models can be designed to closely mirror Supabase table structures, making ORM-like interactions more straightforward. Fields can be marked as `Optional` if they are nullable in the DB or not always present. Default values can be set.
*   **Robust Redis Usage:** Ensures that what's stored in Redis and what's retrieved can be reliably deserialized and understood.

**4. Structure of Pydantic Model Definitions:**

A new file, perhaps `schemas.py` or `data_models.py`, should be created at a suitable location (e.g., in a core utilities directory) to house all these Pydantic model definitions. This promotes reusability and centralizes schema management.

```python
# Example (conceptual schemas.py)
import uuid
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime

class BaseTimestampModel(BaseModel):
    id: Optional[int] = Field(default=None, description="Database primary key")
    created_at: Optional[datetime] = Field(default_factory=datetime.now, alias="createdAt")
    updated_at: Optional[datetime] = Field(default_factory=datetime.now, alias="updatedAt")

    class Config:
        populate_by_name = True # Allows using alias or field name

class ProjectModel(BaseTimestampModel):
    project_id: uuid.UUID = Field(alias="projectId")
    name: str
    # ... other fields from projects table

class SourceDocumentModel(BaseTimestampModel):
    document_uuid: uuid.UUID
    project_fk_id: Optional[int] = None
    project_uuid: Optional[uuid.UUID] = None
    original_file_name: str
    detected_file_type: str
    raw_extracted_text: Optional[str] = None
    ocr_metadata_json: Optional[Dict[str, Any]] = Field(default=None, alias="ocrMetadataJson")
    celery_status: Optional[str] = Field(default="pending_intake")
    s3_key: Optional[str] = None
    # ... other fields matching source_documents table
    
    @validator('ocr_metadata_json', pre=True, always=True)
    def parse_ocr_metadata(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # Potentially log error or handle as needed
                return None 
        return v

# ... other models for Chunk, EntityMention, CanonicalEntity, etc.

# For structured_extraction.py outputs:
class StructuredDocumentMetadata(BaseModel):
    type: str
    date: Optional[str] = None # Consider datetime if always parsable
    parties: List[str] = []
    case_number: Optional[str] = None
    title: Optional[str] = None

class KeyFact(BaseModel):
    fact: str
    confidence: float
    page: Optional[int] = None # If available
    context: Optional[str] = None

# ... and so on for EntitySet, Relationship, StructuredChunkData
