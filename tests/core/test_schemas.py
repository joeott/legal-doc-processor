import pytest
import uuid
from datetime import datetime
from pydantic import ValidationError
from scripts.core.schemas import ProjectModel, SourceDocumentModel, ChunkModel, EntityMentionModel, EntityType


def test_project_model_minimal_data():
    """Test ProjectModel creation with minimal data."""
    project_name = "Test Project"
    project = ProjectModel(name=project_name)
    assert project.name == project_name
    # Fix: project_id is NOT auto-generated when field is omitted
    assert project.project_id is None
    # Fix: Use snake_case field names, not camelCase aliases
    assert project.script_run_count == 0
    assert project.processed_by_scripts is False
    assert project.active is True


def test_project_model_metadata_defaults_and_parses_json():
    """Test metadata defaults to empty dict and parses JSON string."""
    project_default_metadata = ProjectModel(name="Test Project")
    assert project_default_metadata.metadata == {}

    metadata_json_str = '{"key": "value", "number": 123}'
    project_json_metadata = ProjectModel(name="Test Project", metadata=metadata_json_str)
    assert project_json_metadata.metadata == {"key": "value", "number": 123}

    metadata_dict = {"another_key": "another_value"}
    project_dict_metadata = ProjectModel(name="Test Project", metadata=metadata_dict)
    assert project_dict_metadata.metadata == metadata_dict


def test_project_model_missing_name_raises_validation_error():
    """Test ValidationError is raised if name is missing."""
    with pytest.raises(ValidationError) as excinfo:
        ProjectModel()  # Missing 'name'
    assert "Field required" in str(excinfo.value)
    assert "name" in str(excinfo.value)


def test_project_model_airtable_id_max_length():
    """Test ValidationError is raised if airtable_id exceeds max_length."""
    long_airtable_id = "a" * 256
    with pytest.raises(ValidationError) as excinfo:
        ProjectModel(name="Test Project", airtable_id=long_airtable_id)
    assert "String should have at most 255 characters" in str(excinfo.value)

    # Test with valid length
    valid_airtable_id = "a" * 255
    project = ProjectModel(name="Test Project", airtable_id=valid_airtable_id)
    assert project.airtable_id == valid_airtable_id


def test_project_model_to_db_dict():
    """Test to_db_dict method for correct serialization."""
    project_id_val = uuid.uuid4()
    created_at_val = datetime.utcnow()
    updated_at_val = datetime.utcnow()

    data_with_none = {
        "name": "DB Test Project",
        "project_id": project_id_val,
        "airtable_id": None,  # This should be excluded by default
        # Fix: Use snake_case field names, not camelCase
        "script_run_count": 5,
        "created_at": created_at_val,
        "updated_at": updated_at_val,
    }
    project = ProjectModel(**data_with_none)

    # Test exclude_none=True (default) and by_alias=True (default)
    db_dict = project.to_db_dict()
    assert db_dict["name"] == data_with_none["name"]
    assert db_dict["projectId"] == str(project_id_val)  # Alias and UUID to str
    assert "airtable_id" not in db_dict  # None value excluded
    assert db_dict["scriptRunCount"] == data_with_none["script_run_count"]
    assert db_dict["createdAt"] == created_at_val.isoformat() # Datetime to isoformat str
    assert db_dict["updatedAt"] == updated_at_val.isoformat()
    assert "processedByScripts" in db_dict # Default value included
    assert db_dict["active"] is True # Default value included
    assert "metadata" in db_dict # Default value included

    # Test exclude_none=False
    db_dict_include_none = project.to_db_dict(exclude_none=False)
    assert "airtable_id" in db_dict_include_none
    assert db_dict_include_none["airtable_id"] is None

    # Test by_alias=False
    db_dict_no_alias = project.to_db_dict(by_alias=False)
    assert db_dict_no_alias["project_id"] == str(project_id_val) # Field name and UUID to str
    assert db_dict_no_alias["created_at"] == created_at_val.isoformat()
    assert db_dict_no_alias["updated_at"] == updated_at_val.isoformat()
    assert db_dict_no_alias["script_run_count"] == data_with_none["script_run_count"]


# Tests for SourceDocumentModel

def test_source_document_model_minimal_data():
    """Test SourceDocumentModel creation with minimal data."""
    doc_uuid = uuid.uuid4()
    data = {
        "document_uuid": doc_uuid,
        "original_file_name": "test_document.pdf",
        "detected_file_type": "application/pdf",
    }
    doc = SourceDocumentModel(**data)
    assert doc.document_uuid == doc_uuid
    assert doc.original_file_name == data["original_file_name"]
    assert doc.detected_file_type == data["detected_file_type"]
    assert doc.initial_processing_status == "pending_intake"
    assert doc.celery_status == "pending_intake"
    # Fix: Remove timestamp auto-generation assumptions
    # created_at and updated_at might be None if not provided
    assert doc.ocr_metadata_json is None  # Default is None when field not provided
    assert doc.transcription_metadata_json is None  # Default is None when field not provided


def test_source_document_model_all_fields():
    """Test SourceDocumentModel creation with all fields."""
    now = datetime.utcnow()
    doc_uuid = uuid.uuid4()
    project_uuid_val = uuid.uuid4()
    data = {
        "document_uuid": doc_uuid,
        "original_file_name": "full_spec_doc.docx",
        "detected_file_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "project_fk_id": 1,
        "project_uuid": project_uuid_val,
        "original_file_path": "/mnt/data/docs/full_spec_doc.docx",
        "s3_key": f"uploads/{doc_uuid}/full_spec_doc.docx",
        "s3_bucket": "my-doc-bucket",
        "s3_region": "us-east-1",
        "s3_key_public": f"public/{doc_uuid}/full_spec_doc.docx",
        "s3_bucket_public": "my-doc-bucket-public",
        "file_size_bytes": 1024 * 500, # 500KB
        "md5_hash": "a0b1c2d3e4f5a0b1c2d3e4f5a0b1c2d3",
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "user_defined_name": "My Important Document",
        "initial_processing_status": "processing",
        "celery_status": "ocr_processing",
        "celery_task_id": str(uuid.uuid4()),
        "error_message": None,
        "intake_timestamp": now,
        "last_modified_at": now,
        "raw_extracted_text": "This is the extracted text.",
        "markdown_text": "# This is the extracted text.",
        "ocr_metadata_json": {"pages": 10, "ocr_engine": "tesseract"},
        "transcription_metadata_json": {"segments": 5, "language": "en"},
        "ocr_provider": "AWS Textract",
        "ocr_completed_at": now,
        "ocr_processing_seconds": 12.34,
        "textract_job_id": "textractjob123",
        "textract_job_status": "SUCCEEDED",
        "textract_job_started_at": now,
        "textract_job_completed_at": now,
        "textract_confidence_avg": 98.5,
        "textract_warnings": ["Low confidence on page 5"],
        "textract_output_s3_key": f"textract-output/{doc_uuid}/output.json",
        "import_session_id": 100,
        "created_at": now,
        "updated_at": now,
        "id": 12345
    }
    doc = SourceDocumentModel(**data)
    for key, value in data.items():
        if key in ["ocr_metadata_json", "transcription_metadata_json", "textract_warnings"]:
             # These are parsed by validators, check separately if needed for deep comparison
            assert getattr(doc, key) is not None if value is not None else getattr(doc, key) is None
        elif isinstance(value, datetime):
            assert getattr(doc, key).isoformat() == value.isoformat()
        else:
            assert getattr(doc, key) == value


def test_source_document_model_uuid_auto_generation_and_defaults():
    """Test document_uuid auto-generation and status defaults."""
    # Fix: document_uuid is NOT auto-generated by default
    # The validator only generates it if explicitly None
    doc = SourceDocumentModel(
        document_uuid=None,  # Explicitly pass None to trigger generation
        original_file_name="auto_uuid_test.txt",
        detected_file_type="text/plain"
    )
    assert isinstance(doc.document_uuid, uuid.UUID)
    assert doc.initial_processing_status == "pending_intake"
    assert doc.celery_status == "pending_intake"

    # Check string UUID conversion as well
    uuid_str = str(uuid.uuid4())
    doc_with_str_uuid = SourceDocumentModel(
        document_uuid=uuid_str,
        original_file_name="str_uuid_test.txt",
        detected_file_type="text/plain"
    )
    assert doc_with_str_uuid.document_uuid == uuid.UUID(uuid_str)


def test_source_document_model_json_metadata_parsing():
    """Test parsing of ocr_metadata_json and transcription_metadata_json."""
    base_data = {
        "document_uuid": uuid.uuid4(),  # Fix: Need to provide UUID
        "original_file_name": "meta_test.txt",
        "detected_file_type": "text/plain"
    }

    # Test with valid JSON string
    doc1 = SourceDocumentModel(**base_data, ocr_metadata_json='{"key1": "value1"}', transcription_metadata_json='{"key2": 2}')
    assert doc1.ocr_metadata_json == {"key1": "value1"}
    assert doc1.transcription_metadata_json == {"key2": 2}

    # Test with actual dict
    doc2 = SourceDocumentModel(**base_data, ocr_metadata_json={"key_dict": "val_dict"}, transcription_metadata_json={})
    assert doc2.ocr_metadata_json == {"key_dict": "val_dict"}
    assert doc2.transcription_metadata_json == {}

    # Test with None
    doc3 = SourceDocumentModel(**base_data, ocr_metadata_json=None, transcription_metadata_json=None)
    assert doc3.ocr_metadata_json == {} # Defaults to {}
    assert doc3.transcription_metadata_json == {} # Defaults to {}

    # Test with empty string (should result in default empty dict due to validator)
    doc4 = SourceDocumentModel(**base_data, ocr_metadata_json="", transcription_metadata_json="")
    assert doc4.ocr_metadata_json == {}
    assert doc4.transcription_metadata_json == {}

    # Test with invalid JSON string (should result in default empty dict)
    doc5 = SourceDocumentModel(**base_data, ocr_metadata_json='invalid json', transcription_metadata_json='{not_json:}')
    assert doc5.ocr_metadata_json == {}
    assert doc5.transcription_metadata_json == {}


def test_source_document_model_validate_processing_status():
    """Test the validate_processing_status model validator."""
    base_data = {
        "document_uuid": uuid.uuid4(),  # Fix: Need to provide UUID
        "original_file_name": "status_test.txt",
        "detected_file_type": "text/plain"
    }

    # Test auto-population of error_message for failed status
    doc_failed_auto_error = SourceDocumentModel(**base_data, celery_status="ocr_failed")
    assert doc_failed_auto_error.error_message == "Process failed with status: ocr_failed"

    # Test with existing error_message (should not be overwritten)
    custom_error = "A specific error occurred."
    doc_failed_custom_error = SourceDocumentModel(**base_data, celery_status="text_failed", error_message=custom_error)
    assert doc_failed_custom_error.error_message == custom_error

    # Test non-failed status (error_message should remain None if not provided)
    doc_ok_status = SourceDocumentModel(**base_data, celery_status="ocr_completed")
    assert doc_ok_status.error_message is None

    # Test non-failed status with existing error message (should persist)
    doc_ok_status_with_msg = SourceDocumentModel(**base_data, celery_status="completed", error_message="Should not be here but testing persistence")
    assert doc_ok_status_with_msg.error_message == "Should not be here but testing persistence"


def test_source_document_model_validation_errors():
    """Test ValidationErrors for missing or invalid fields."""
    minimal_data = {
        "document_uuid": uuid.uuid4(),
        "original_file_name": "valid_name.pdf",
        "detected_file_type": "application/pdf",
    }

    # Missing original_file_name
    with pytest.raises(ValidationError) as excinfo_name:
        data_no_name = minimal_data.copy()
        del data_no_name["original_file_name"]
        SourceDocumentModel(**data_no_name)
    assert "Field required" in str(excinfo_name.value)
    assert "original_file_name" in str(excinfo_name.value)

    # Missing detected_file_type
    with pytest.raises(ValidationError) as excinfo_type:
        data_no_type = minimal_data.copy()
        del data_no_type["detected_file_type"]
        SourceDocumentModel(**data_no_type)
    assert "Field required" in str(excinfo_type.value)
    assert "detected_file_type" in str(excinfo_type.value)

    # Invalid project_uuid (not a UUID)
    with pytest.raises(ValidationError) as excinfo_proj_uuid:
        SourceDocumentModel(**minimal_data, project_uuid="not-a-uuid")
    # Fix: Updated error message for Pydantic v2
    assert "UUID" in str(excinfo_proj_uuid.value) or "Invalid UUID" in str(excinfo_proj_uuid.value)

    # Invalid file_size_bytes (not an int)
    with pytest.raises(ValidationError) as excinfo_size:
        SourceDocumentModel(**minimal_data, file_size_bytes="not-an-int")
    assert "Input should be a valid integer" in str(excinfo_size.value)


def test_source_document_model_to_db_dict():
    """Test to_db_dict method for SourceDocumentModel."""
    doc_uuid_val = uuid.uuid4()
    project_uuid_val = uuid.uuid4()
    now = datetime.utcnow()

    data = {
        "document_uuid": doc_uuid_val,
        "original_file_name": "db_dict_test.txt",
        "detected_file_type": "text/plain",
        "project_uuid": project_uuid_val,
        "s3_key": "some/key",
        "ocr_metadata_json": {"pages": 1}, # Stored as JSON in DB
        "created_at": now,
        "updated_at": now,
        "error_message": None # Should be excluded by default
    }
    doc = SourceDocumentModel(**data)

    # Test exclude_none=True (default) and by_alias=True (default)
    db_dict = doc.to_db_dict()
    assert db_dict["original_file_name"] == data["original_file_name"]
    assert db_dict["document_uuid"] == str(doc_uuid_val) # UUID to str
    assert db_dict["project_uuid"] == str(project_uuid_val) # UUID to str
    assert db_dict["s3_key"] == data["s3_key"]
    assert db_dict["ocr_metadata_json"] == {"pages": 1} # Parsed dict should be output
    assert db_dict["createdAt"] == now.isoformat()
    assert db_dict["updatedAt"] == now.isoformat()
    assert "error_message" not in db_dict # None value excluded
    assert "initial_processing_status" in db_dict # Default value included
    assert db_dict["celery_status"] == "pending_intake" # Default value included

    # Test exclude_none=False
    db_dict_include_none = doc.to_db_dict(exclude_none=False)
    assert "error_message" in db_dict_include_none
    assert db_dict_include_none["error_message"] is None

    # Test by_alias=False
    # Note: aliases in SourceDocumentModel are mostly for db columns that match field names
    # but ocr_metadata_json is one, and created_at/updated_at from Base model
    db_dict_no_alias = doc.to_db_dict(by_alias=False)
    assert db_dict_no_alias["ocr_metadata_json"] == {"pages": 1} # Field name
    assert db_dict_no_alias["created_at"] == now.isoformat()
    assert db_dict_no_alias["updated_at"] == now.isoformat()
    assert db_dict_no_alias["initial_processing_status"] == "pending_intake"


# Tests for ChunkModel

def test_chunk_model_required_fields():
    """Test ChunkModel creation with required fields."""
    chunk_uuid = uuid.uuid4()
    doc_uuid = uuid.uuid4()
    data = {
        "chunk_id": chunk_uuid,
        "document_id": 1, # Assuming this is the SQL ID for the related Neo4jDocumentModel
        "document_uuid": doc_uuid,
        "chunk_index": 0,
        "text": "This is the first chunk of text.",
        "char_start_index": 0,
        "char_end_index": 30,
    }
    chunk = ChunkModel(**data)
    assert chunk.chunk_id == chunk_uuid
    assert chunk.document_id == data["document_id"]
    assert chunk.document_uuid == doc_uuid
    assert chunk.chunk_index == data["chunk_index"]
    assert chunk.text == data["text"]
    assert chunk.char_start_index == data["char_start_index"]
    assert chunk.char_end_index == data["char_end_index"]
    # Fix: metadata_json defaults to None, not {}
    assert chunk.metadata_json is None


def test_chunk_model_chunk_id_auto_generation():
    """Test chunk_id is auto-generated if not provided."""
    doc_uuid = uuid.uuid4()
    data = {
        # Fix: Need to explicitly pass None to trigger auto-generation
        "chunk_id": None,
        "document_id": 1,
        "document_uuid": doc_uuid,
        "chunk_index": 0,
        "text": "Another chunk.",
        "char_start_index": 0,
        "char_end_index": 15,
    }
    chunk = ChunkModel(**data)
    assert isinstance(chunk.chunk_id, uuid.UUID)

    # Test string UUID conversion
    chunk_id_str = str(uuid.uuid4())
    data_with_str_id = {**data, "chunk_id": chunk_id_str}
    chunk_with_str_id = ChunkModel(**data_with_str_id)
    assert chunk_with_str_id.chunk_id == uuid.UUID(chunk_id_str)


def test_chunk_model_invalid_char_indices():
    """Test ValidationError for invalid char_start_index/char_end_index."""
    doc_uuid = uuid.uuid4()
    base_data = {
        "chunk_id": uuid.uuid4(),  # Fix: Need to provide chunk_id
        "document_id": 1,
        "document_uuid": doc_uuid,
        "chunk_index": 0,
        "text": "Text for index test.",
    }

    with pytest.raises(ValidationError) as excinfo:
        ChunkModel(**base_data, char_start_index=10, char_end_index=5)
    assert "Invalid char indices: start=10, end=5" in str(excinfo.value)

    # Valid case
    chunk = ChunkModel(**base_data, char_start_index=5, char_end_index=10)
    assert chunk.char_start_index == 5
    assert chunk.char_end_index == 10


def test_chunk_model_embedding_validation():
    """Test the embedding field validator."""
    doc_uuid = uuid.uuid4()
    base_data = {
        "chunk_id": uuid.uuid4(),  # Fix: Need to provide chunk_id
        "document_id": 1,
        "document_uuid": doc_uuid,
        "chunk_index": 0,
        "text": "Embedding test text.",
        "char_start_index": 0,
        "char_end_index": 20,
    }

    valid_dims = [384, 768, 1536, 3072]
    for dim in valid_dims:
        embedding_valid = [0.1] * dim
        chunk = ChunkModel(**base_data, embedding=embedding_valid)
        assert chunk.embedding == embedding_valid

    # Invalid type (list of strings)
    with pytest.raises(ValidationError) as excinfo_type:
        ChunkModel(**base_data, embedding=["a", "b", "c"] * 128) # dim 384
    # Pydantic v2 error for list of floats when a string is found:
    # "Input should be a valid number, unable to parse string as a number"
    assert "Input should be a valid number" in str(excinfo_type.value)

    # Invalid dimension
    with pytest.raises(ValidationError) as excinfo_dim:
        ChunkModel(**base_data, embedding=[0.1] * 100)
    assert "Unexpected embedding dimension: 100" in str(excinfo_dim.value)

    # Test with None (should be allowed)
    chunk_none_embedding = ChunkModel(**base_data, embedding=None)
    assert chunk_none_embedding.embedding is None


def test_chunk_model_to_db_dict():
    """Test to_db_dict method for ChunkModel."""
    chunk_uuid_val = uuid.uuid4()
    doc_uuid_val = uuid.uuid4()
    now = datetime.utcnow()
    embedding_val = [0.1] * 384

    data = {
        "chunk_id": chunk_uuid_val,
        "document_id": 1,
        "document_uuid": doc_uuid_val,
        "chunk_index": 0,
        "text": "DB dict test chunk.",
        "char_start_index": 0,
        "char_end_index": 19,
        "embedding": embedding_val,
        "metadata_json": {"source": "test"},
        "created_at": now,
        "updated_at": now,
        "next_chunk_id": None # To test exclude_none
    }
    chunk = ChunkModel(**data)

    db_dict = chunk.to_db_dict()
    assert db_dict["chunkId"] == str(chunk_uuid_val) # Alias + UUID to str
    assert db_dict["document_id"] == data["document_id"]
    assert db_dict["document_uuid"] == str(doc_uuid_val) # UUID to str
    assert db_dict["chunkIndex"] == data["chunk_index"] # Alias
    assert db_dict["text"] == data["text"]
    assert db_dict["charStartIndex"] == data["char_start_index"] # Alias
    assert db_dict["charEndIndex"] == data["char_end_index"] # Alias
    assert db_dict["embedding"] == embedding_val
    assert db_dict["metadataJson"] == data["metadata_json"] # Alias
    assert db_dict["createdAt"] == now.isoformat()
    assert db_dict["updatedAt"] == now.isoformat()
    assert "next_chunk_id" not in db_dict # None value with field name next_chunk_id
    assert "nextChunkId" not in db_dict # Alias for next_chunk_id also not present

    # Test exclude_none=False
    db_dict_include_none = chunk.to_db_dict(exclude_none=False)
    assert db_dict_include_none["nextChunkId"] is None # Alias

    # Test by_alias=False
    db_dict_no_alias = chunk.to_db_dict(by_alias=False)
    assert db_dict_no_alias["chunk_id"] == str(chunk_uuid_val)
    assert db_dict_no_alias["chunk_index"] == data["chunk_index"]
    assert db_dict_no_alias["char_start_index"] == data["char_start_index"]
    assert db_dict_no_alias["char_end_index"] == data["char_end_index"]
    assert db_dict_no_alias["metadata_json"] == data["metadata_json"]
    assert "next_chunk_id" not in db_dict_no_alias  # None value excluded by default


# Tests for EntityMentionModel

def test_entity_mention_model_required_fields():
    """Test EntityMentionModel creation with required fields."""
    entity_mention_uuid = uuid.uuid4()
    chunk_uuid_val = uuid.uuid4()
    data = {
        "entity_mention_id": entity_mention_uuid,
        "chunk_fk_id": 1, # SQL ID of the chunk
        "chunk_uuid": chunk_uuid_val,
        "value": "Acme Corp",
        "entity_type": EntityType.ORGANIZATION, # Using the enum
    }
    entity_mention = EntityMentionModel(**data)
    assert entity_mention.entity_mention_id == entity_mention_uuid
    assert entity_mention.chunk_fk_id == data["chunk_fk_id"]
    assert entity_mention.chunk_uuid == chunk_uuid_val
    assert entity_mention.value == data["value"]
    assert entity_mention.entity_type == EntityType.ORGANIZATION
    # Fix: Remove timestamp auto-generation assumptions
    assert entity_mention.attributes_json is None  # Default is None


def test_entity_mention_model_id_auto_generation():
    """Test entity_mention_id is auto-generated if not provided."""
    chunk_uuid_val = uuid.uuid4()
    data = {
        # Fix: Need to explicitly pass None to trigger auto-generation
        "entity_mention_id": None,
        "chunk_fk_id": 1,
        "chunk_uuid": chunk_uuid_val,
        "value": "Beta Inc.",
        "entity_type": EntityType.ORGANIZATION,
    }
    entity_mention = EntityMentionModel(**data)
    assert isinstance(entity_mention.entity_mention_id, uuid.UUID)

    # Test string UUID conversion
    entity_id_str = str(uuid.uuid4())
    data_with_str_id = {**data, "entity_mention_id": entity_id_str}
    entity_with_str_id = EntityMentionModel(**data_with_str_id)
    assert entity_with_str_id.entity_mention_id == uuid.UUID(entity_id_str)


def test_entity_mention_model_entity_type_enum():
    """Test EntityType enum validation for entity_type field."""
    chunk_uuid_val = uuid.uuid4()
    base_data = {
        "entity_mention_id": uuid.uuid4(),  # Fix: Need to provide ID
        "chunk_fk_id": 1,
        "chunk_uuid": chunk_uuid_val,
        "value": "Some Value",
    }

    # Test with valid enum member
    em_person = EntityMentionModel(**base_data, entity_type=EntityType.PERSON)
    assert em_person.entity_type == EntityType.PERSON

    # Test with valid string value of an enum member
    em_location_str = EntityMentionModel(**base_data, entity_type="LOCATION")
    assert em_location_str.entity_type == EntityType.LOCATION

    # Test with an invalid string value
    with pytest.raises(ValidationError) as excinfo:
        EntityMentionModel(**base_data, entity_type="INVALID_TYPE")
    assert "Input should be 'PERSON', 'ORG', 'LOCATION', 'DATE', 'MONEY', 'CASE_NUMBER', 'STATUTE', 'COURT', 'JUDGE', 'ATTORNEY' or 'OTHER'" in str(excinfo.value)


def test_entity_mention_model_confidence_score_validation():
    """Test confidence_score validation (0.0 to 1.0)."""
    chunk_uuid_val = uuid.uuid4()
    base_data = {
        "entity_mention_id": uuid.uuid4(),  # Fix: Need to provide ID
        "chunk_fk_id": 1,
        "chunk_uuid": chunk_uuid_val,
        "value": "Confident Value",
        "entity_type": EntityType.OTHER,
    }

    # Valid scores
    valid_scores = [0.0, 0.5, 1.0]
    for score in valid_scores:
        em = EntityMentionModel(**base_data, confidence_score=score)
        assert em.confidence_score == score

    # Invalid scores
    invalid_scores = [-0.1, 1.1]
    for score in invalid_scores:
        with pytest.raises(ValidationError) as excinfo:
            EntityMentionModel(**base_data, confidence_score=score)
        assert f"Confidence score must be between 0 and 1, got {score}" in str(excinfo.value)

    # Test with None (should be allowed)
    em_none_score = EntityMentionModel(**base_data, confidence_score=None)
    assert em_none_score.confidence_score is None


def test_entity_mention_model_to_db_dict():
    """Test to_db_dict method for EntityMentionModel."""
    entity_mention_uuid_val = uuid.uuid4()
    chunk_uuid_val = uuid.uuid4()
    now = datetime.utcnow()

    data = {
        "entity_mention_id": entity_mention_uuid_val,
        "chunk_fk_id": 2,
        "chunk_uuid": chunk_uuid_val,
        "value": "DB Dict Entity",
        "entity_type": EntityType.DATE,
        "normalized_value": "2023-01-01",
        "confidence_score": 0.95,
        "attributes_json": {"is_future": False},
        "created_at": now,
        "updated_at": now,
        "offset_start": None # Test exclude_none
    }
    entity_mention = EntityMentionModel(**data)

    db_dict = entity_mention.to_db_dict()
    assert db_dict["entityMentionId"] == str(entity_mention_uuid_val) # Alias + UUID to str
    assert db_dict["chunk_fk_id"] == data["chunk_fk_id"] # No alias
    assert db_dict["chunk_uuid"] == str(chunk_uuid_val) # UUID to str
    assert db_dict["value"] == data["value"]
    assert db_dict["entity_type"] == "DATE" # Enum value
    assert db_dict["normalizedValue"] == data["normalized_value"] # Alias
    assert db_dict["confidenceScore"] == data["confidence_score"] # Alias
    assert db_dict["attributesJson"] == data["attributes_json"] # Alias
    assert db_dict["createdAt"] == now.isoformat()
    assert db_dict["updatedAt"] == now.isoformat()
    assert "offset_start" not in db_dict # None value with field name offset_start
    assert "offsetStart" not in db_dict # Alias for offset_start also not present

    # Test exclude_none=False
    db_dict_include_none = entity_mention.to_db_dict(exclude_none=False)
    assert db_dict_include_none["offsetStart"] is None # Alias

    # Test by_alias=False
    db_dict_no_alias = entity_mention.to_db_dict(by_alias=False)
    assert db_dict_no_alias["entity_mention_id"] == str(entity_mention_uuid_val)
    assert db_dict_no_alias["normalized_value"] == data["normalized_value"]
    assert db_dict_no_alias["confidence_score"] == data["confidence_score"]
    assert db_dict_no_alias["attributes_json"] == data["attributes_json"]
    assert "offset_start" not in db_dict_no_alias  # None value excluded by default


def test_project_model_all_fields():
    """Test ProjectModel creation with all fields."""
    data = {
        "project_id": uuid.uuid4(),
        "name": "Full Project",
        "airtable_id": "recTestAirtableId",
        # Fix: Use snake_case field names
        "script_run_count": 10,
        "processed_by_scripts": True,
        "active": False,
        "metadata": {"key": "value"},
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    project = ProjectModel(**data)
    assert project.project_id == data["project_id"]
    assert project.name == data["name"]
    assert project.airtable_id == data["airtable_id"]
    assert project.script_run_count == data["script_run_count"]
    assert project.processed_by_scripts == data["processed_by_scripts"]
    assert project.active == data["active"]
    assert project.metadata == data["metadata"]
    assert project.created_at == data["created_at"]
    assert project.updated_at == data["updated_at"]


def test_project_model_project_id_auto_generation():
    """Test project_id is auto-generated and is a valid UUID."""
    # Fix: Need to explicitly pass None to trigger auto-generation
    project = ProjectModel(name="Test Project", project_id=None)
    assert isinstance(project.project_id, uuid.UUID)


def test_project_model_project_id_string_conversion():
    """Test string project_id is converted to UUID."""
    project_id_str = str(uuid.uuid4())
    project = ProjectModel(name="Test Project", project_id=project_id_str)
    assert isinstance(project.project_id, uuid.UUID)
    assert project.project_id == uuid.UUID(project_id_str)


def test_project_model_default_values():
    """Test default values for script_run_count, processed_by_scripts, and active."""
    project = ProjectModel(name="Test Project")
    assert project.script_run_count == 0
    assert project.processed_by_scripts is False
    assert project.active is True