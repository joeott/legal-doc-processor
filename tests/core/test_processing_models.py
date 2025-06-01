import pytest
import uuid
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError, BaseModel

# Import models from scripts.core.processing_models
from scripts.core.processing_models import (
    BaseProcessingResult,
    ProcessingResultStatus,
    OCRResultModel,
    OCRPageResult,
    ChunkingResultModel,
    ProcessedChunk,
    ChunkMetadata,
)

# Helper to compare datetimes with a tolerance
def assert_datetime_close(dt1, dt2, tolerance_seconds=2):
    assert abs((dt1 - dt2).total_seconds()) < tolerance_seconds

# Tests for BaseProcessingResult
class TestBaseProcessingResult:
    def test_successful_creation_required_fields(self):
        doc_uuid = uuid.uuid4()
        result = BaseProcessingResult(document_uuid=doc_uuid)
        assert result.document_uuid == doc_uuid
        assert isinstance(result.processing_timestamp, datetime)
        # Ensure timestamp is timezone-aware (UTC by default in Pydantic v2 with default_factory=datetime.utcnow)
        # or naive but close to now if model uses datetime.now without timezone
        if result.processing_timestamp.tzinfo is not None:
            assert_datetime_close(result.processing_timestamp, datetime.now(timezone.utc))
        else: # If model uses naive datetime.now()
            assert_datetime_close(result.processing_timestamp, datetime.now())

        assert result.status == ProcessingResultStatus.SUCCESS
        assert result.metadata == {}
        assert result.error_message is None

    def test_successful_creation_all_fields(self):
        doc_uuid = uuid.uuid4()
        ts = datetime.now(timezone.utc) - timedelta(minutes=5)
        result = BaseProcessingResult(
            document_uuid=doc_uuid,
            processing_timestamp=ts,
            status=ProcessingResultStatus.FAILURE,
            metadata={"key": "value"},
            error_message="Something went wrong"
        )
        assert result.document_uuid == doc_uuid
        assert result.processing_timestamp == ts
        assert result.status == ProcessingResultStatus.FAILURE
        assert result.metadata == {"key": "value"}
        assert result.error_message == "Something went wrong"

    def test_serialization_to_dict_json(self):
        doc_uuid = uuid.uuid4()
        ts = datetime.now(timezone.utc) # Ensure timezone aware for consistent ISO format
        result = BaseProcessingResult(
            document_uuid=doc_uuid,
            processing_timestamp=ts,
            status=ProcessingResultStatus.PARTIAL_SUCCESS,
            metadata={"source": "test_serialization"}
        )

        result_dict = result.model_dump()
        assert result_dict["document_uuid"] == str(doc_uuid)
        assert result_dict["processing_timestamp"] == ts.isoformat().replace("+00:00", "Z") # Pydantic v2 default
        assert result_dict["status"] == "partial_success" # Enum value
        assert result_dict["metadata"] == {"source": "test_serialization"}

        result_json = result.model_dump_json()
        expected_json_timestamp = ts.isoformat()
        # Pydantic v2 for datetime.utcnow() produces 'Z' for UTC timezone offset
        if expected_json_timestamp.endswith("+00:00"):
             expected_json_timestamp = expected_json_timestamp.replace("+00:00", "Z")

        assert f'"document_uuid":"{str(doc_uuid)}"' in result_json
        assert f'"processing_timestamp":"{expected_json_timestamp}"' in result_json
        assert '"status":"partial_success"' in result_json
        assert '"metadata":{{"source":"test_serialization"}}' in result_json # Be careful with dict in JSON string

    def test_missing_document_uuid_raises_error(self):
        with pytest.raises(ValidationError):
            BaseProcessingResult() # document_uuid is required


# Tests for OCRPageResult
class TestOCRPageResult:
    def test_successful_creation_required_fields(self):
        page = OCRPageResult(page_number=1, text="Page 1 text.", confidence=0.95)
        assert page.page_number == 1
        assert page.text == "Page 1 text."
        assert page.confidence == 0.95
        assert page.word_count == 0 # Default value, not calculated
        assert page.line_count == 0 # Default value, not calculated
        assert page.warnings == []
        assert page.metadata == {}

    def test_confidence_validator(self):
        page_low = OCRPageResult(page_number=1, text="low", confidence=-0.5)
        assert page_low.confidence == 0.0 # Clamped

        page_high = OCRPageResult(page_number=2, text="high", confidence=1.5)
        assert page_high.confidence == 1.0 # Clamped

        page_valid = OCRPageResult(page_number=3, text="valid", confidence=0.8)
        assert page_valid.confidence == 0.8

    # Removed test_default_calculations_word_line_count as it was based on incorrect assumption
    # word_count and line_count are simple fields with default 0, not auto-calculated from text.

    def test_all_fields_provided(self):
        warnings_list = ["Low contrast on image"]
        metadata_dict = {"ocr_engine_version": "v2.3"}
        page = OCRPageResult(
            page_number=5,
            text="Detailed page text.",
            confidence=0.88,
            word_count=4, # Explicitly provide if not auto-calculated as expected
            line_count=1, # Explicitly provide
            warnings=warnings_list,
            metadata=metadata_dict
        )
        assert page.page_number == 5
        assert page.text == "Detailed page text."
        assert page.confidence == 0.88
        assert page.word_count == 4
        assert page.line_count == 1
        assert page.warnings == warnings_list
        assert page.metadata == metadata_dict


# Tests for OCRResultModel
class TestOCRResultModel:
    def test_successful_creation_required_fields(self):
        doc_uuid = uuid.uuid4()
        result = OCRResultModel(
            document_uuid=doc_uuid,
            provider="test_provider",
            file_type="pdf"
        )
        assert result.document_uuid == doc_uuid
        assert result.provider == "test_provider"
        assert result.file_type == "pdf"

        # Inherited fields from BaseProcessingResult
        assert isinstance(result.processing_timestamp, datetime)
        assert result.status == ProcessingResultStatus.SUCCESS
        assert result.metadata == {}

        # OCRResultModel specific defaults
        assert result.total_pages == 1 # Default for total_pages
        assert result.pages == []
        assert result.full_text == "" # Default, before validator
        assert result.average_confidence == 0.0 # Default, before validator

    def test_average_confidence_calculation(self):
        doc_uuid = uuid.uuid4()
        pages_data = [
            OCRPageResult(page_number=1, text="Page 1", confidence=0.8),
            OCRPageResult(page_number=2, text="Page 2", confidence=0.9),
            OCRPageResult(page_number=3, text="Page 3", confidence=0.7),
        ]
        result = OCRResultModel(
            document_uuid=doc_uuid,
            provider="test_calc",
            file_type="tiff",
            pages=pages_data
        )
        # Validator should calculate this
        expected_avg_conf = (0.8 + 0.9 + 0.7) / 3
        assert abs(result.average_confidence - expected_avg_conf) < 0.0001

        # Test with average_confidence provided AND pages present (validator should still recalculate from pages)
        result_recalculated = OCRResultModel(
            document_uuid=doc_uuid,
            provider="test_calc",
            file_type="tiff",
            pages=pages_data, # pages are present
            average_confidence=0.99 # This provided value should be ignored by validator
        )
        assert abs(result_recalculated.average_confidence - expected_avg_conf) < 0.0001 # Should be calculated from pages

        # Test with average_confidence provided AND NO pages (validator should use provided value)
        result_provided_no_pages = OCRResultModel(
            document_uuid=doc_uuid,
            provider="test_calc",
            file_type="tiff",
            pages=[], # No pages
            average_confidence=0.95
        )
        assert result_provided_no_pages.average_confidence == 0.95


    def test_combine_page_text_validator(self):
        doc_uuid = uuid.uuid4()
        pages_data = [
            OCRPageResult(page_number=1, text="First page content.", confidence=0.9),
            OCRPageResult(page_number=2, text="Second page here.", confidence=0.8),
        ]
        result = OCRResultModel(
            document_uuid=doc_uuid,
            provider="test_text",
            file_type="pdf",
            pages=pages_data
        )
        # Validator should combine text
        expected_full_text = "First page content.\n\nSecond page here."
        assert result.full_text == expected_full_text

        # Test with full_text provided (should not be overridden)
        custom_text = "This is custom full text."
        result_provided_text = OCRResultModel(
            document_uuid=doc_uuid,
            provider="test_text",
            file_type="pdf",
            pages=pages_data,
            full_text=custom_text
        )
        assert result_provided_text.full_text == custom_text

    def test_serialization(self):
        doc_uuid = uuid.uuid4()
        ts = datetime.now(timezone.utc)
        page1 = OCRPageResult(page_number=1, text="Hello", confidence=0.99, word_count=1, line_count=1)
        ocr_result = OCRResultModel(
            document_uuid=doc_uuid,
            processing_timestamp=ts,
            provider="TestOCR",
            file_type="png",
            total_pages=1,
            pages=[page1],
            average_confidence=0.99, # Explicitly set due to validator behavior if pages were added later
            full_text="Hello",      # Explicitly set
            status=ProcessingResultStatus.SUCCESS,
            metadata={"engine": "v3"}
        )

        ocr_dict = ocr_result.model_dump()
        assert ocr_dict["document_uuid"] == str(doc_uuid)
        assert ocr_dict["provider"] == "TestOCR"
        assert ocr_dict["file_type"] == "png"
        assert ocr_dict["total_pages"] == 1
        assert len(ocr_dict["pages"]) == 1
        assert ocr_dict["pages"][0]["text"] == "Hello"
        assert ocr_dict["average_confidence"] == 0.99
        assert ocr_dict["full_text"] == "Hello"
        assert ocr_dict["status"] == "success"

        ocr_json = ocr_result.model_dump_json()
        assert f'"provider":"TestOCR"' in ocr_json
        assert f'"average_confidence":0.99' in ocr_json
        assert '"pages":[{"page_number":1,"text":"Hello","confidence":0.99,"word_count":1,"line_count":1,"warnings":[],"metadata":{}}]}' in ocr_json

    def test_all_fields_creation(self):
        doc_uuid = uuid.uuid4()
        ts = datetime.now(timezone.utc)
        page1 = OCRPageResult(page_number=1, text="Page one text", confidence=0.85)
        result = OCRResultModel(
            document_uuid=doc_uuid,
            processing_timestamp=ts,
            status=ProcessingResultStatus.PARTIAL,
            error_message="Page 2 failed OCR",
            processing_time_seconds=12.5,
            metadata={"source_system": "scanner_X"},
            provider="AdvancedOCR",
            total_pages=2,
            pages=[page1],
            full_text="Page one text\n\n[Page 2 missing]", # Provided
            average_confidence=0.85, # Provided
            textract_job_id="job-123",
            textract_warnings=["Visibility low on page 2"],
            file_type="jpeg",
            file_size_bytes=102400
        )
        assert result.textract_job_id == "job-123"
        assert result.file_size_bytes == 102400
        assert result.status == ProcessingResultStatus.PARTIAL
        assert result.average_confidence == 0.85 # Check it uses provided not recalculated
        assert result.full_text == "Page one text\n\n[Page 2 missing]" # Check it uses provided


# Tests for ChunkMetadata and ProcessedChunk
class TestChunkModels:
    def test_chunk_metadata_creation_defaults(self):
        meta = ChunkMetadata()
        assert meta.section_title is None
        assert meta.section_number is None
        assert meta.page_numbers == []
        assert meta.is_continuation is False
        assert meta.chunk_type == "paragraph"
        assert meta.language == "en"

    def test_chunk_metadata_all_fields(self):
        page_nums = [1, 2]
        meta = ChunkMetadata(
            section_title="Chapter 1",
            section_number="1.1",
            page_numbers=page_nums,
            is_continuation=True,
            chunk_type="list_item",
            language="fr"
        )
        assert meta.section_title == "Chapter 1"
        assert meta.section_number == "1.1"
        assert meta.page_numbers == page_nums
        assert meta.is_continuation is True
        assert meta.chunk_type == "list_item"
        assert meta.language == "fr"

    def test_processed_chunk_creation_required_fields(self):
        chunk = ProcessedChunk(
            chunk_index=0,
            text="This is a chunk.",
            char_start=0,
            char_end=16
        )
        assert isinstance(chunk.chunk_id, uuid.UUID)
        assert chunk.chunk_index == 0
        assert chunk.text == "This is a chunk."
        assert chunk.char_start == 0
        assert chunk.char_end == 16
        assert chunk.token_count == 4 # Estimated: len("This is a chunk.") // 4 = 16 // 4 = 4
        assert isinstance(chunk.metadata, ChunkMetadata)
        assert chunk.previous_chunk_id is None
        assert chunk.next_chunk_id is None

    def test_processed_chunk_token_count_estimation(self):
        text1 = "Short." # 6 chars -> 1 token
        chunk1 = ProcessedChunk(chunk_index=0, text=text1, char_start=0, char_end=len(text1))
        assert chunk1.token_count == 1

        text2 = "This is a bit longer." # 21 chars -> 5 tokens
        chunk2 = ProcessedChunk(chunk_index=1, text=text2, char_start=0, char_end=len(text2))
        assert chunk2.token_count == 5

        # Test with token_count provided (should not be overridden)
        chunk_provided_tokens = ProcessedChunk(
            chunk_index=2, text="Text.", char_start=0, char_end=5, token_count=100
        )
        assert chunk_provided_tokens.token_count == 100

        # Test with empty text
        chunk_empty_text = ProcessedChunk(chunk_index=3, text="", char_start=0, char_end=0)
        assert chunk_empty_text.token_count == 0


    def test_processed_chunk_all_fields(self):
        chunk_id_val = uuid.uuid4()
        prev_id_val = uuid.uuid4()
        next_id_val = uuid.uuid4()
        meta = ChunkMetadata(section_title="Intro")

        chunk = ProcessedChunk(
            chunk_id=chunk_id_val,
            chunk_index=1,
            text="Detailed chunk content.",
            char_start=100,
            char_end=125,
            token_count=7, # Explicitly set
            metadata=meta,
            previous_chunk_id=prev_id_val,
            next_chunk_id=next_id_val
        )
        assert chunk.chunk_id == chunk_id_val
        assert chunk.chunk_index == 1
        assert chunk.text == "Detailed chunk content."
        assert chunk.char_start == 100
        assert chunk.char_end == 125
        assert chunk.token_count == 7 # Not overridden
        assert chunk.metadata.section_title == "Intro"
        assert chunk.previous_chunk_id == prev_id_val
        assert chunk.next_chunk_id == next_id_val


# Tests for ChunkingResultModel
class TestChunkingResultModel:
    def test_successful_creation_required_fields(self):
        doc_uuid = uuid.uuid4()
        result = ChunkingResultModel(document_uuid=doc_uuid, document_id=123)
        assert result.document_uuid == doc_uuid
        assert result.document_id == 123

        # Inherited fields
        assert isinstance(result.processing_timestamp, datetime)
        assert result.status == ProcessingResultStatus.SUCCESS

        # Model specific defaults
        assert result.chunks == []
        assert result.total_chunks == 0 # Default, before validator
        assert result.strategy == "semantic"
        assert result.max_chunk_size == 1000
        assert result.chunk_overlap == 100
        assert result.average_chunk_size == 0.0 # Default, before validator
        assert result.total_characters == 0
        assert result.chunks_with_entities == 0

    def test_count_chunks_and_average_size_validators(self):
        doc_uuid = uuid.uuid4()
        chunks_data = [
            ProcessedChunk(chunk_index=0, text="First chunk.", char_start=0, char_end=12, token_count=3), # 12 chars
            ProcessedChunk(chunk_index=1, text="Second chunk here.", char_start=13, char_end=31, token_count=4) # 18 chars
        ]
        result = ChunkingResultModel(
            document_uuid=doc_uuid,
            document_id=1,
            chunks=chunks_data
        )
        assert result.total_chunks == 2 # Calculated by validator
        expected_avg_size = (12 + (31-13)) / 2.0 # (12 + 18) / 2 = 15.0
        assert abs(result.average_chunk_size - expected_avg_size) < 0.0001

        # Test with provided values (should be overridden by validators if chunks are present)
        result_provided = ChunkingResultModel(
            document_uuid=doc_uuid,
            document_id=1,
            chunks=chunks_data,
            total_chunks=100, # Should be ignored
            average_chunk_size=500.0 # Should be ignored
        )
        assert result_provided.total_chunks == 2
        assert abs(result_provided.average_chunk_size - expected_avg_size) < 0.0001

        # Test with no chunks (provided values should be kept if not default, or default if default)
        result_no_chunks_provided = ChunkingResultModel(
            document_uuid=doc_uuid,
            document_id=1,
            chunks=[],
            total_chunks=5, # Should be kept if validator only runs on present chunks
            average_chunk_size=20.0 # Should be kept
        )
        # The current validator logic:
        # if hasattr(info, 'data') and 'chunks' in info.data: return len(info.data['chunks']) -> so 0 if chunks=[]
        # if hasattr(info, 'data') and 'chunks' in info.data and info.data['chunks']: (evaluates to false if chunks is empty) -> returns original v
        assert result_no_chunks_provided.total_chunks == 0 # Validator recalculates to 0 because chunks=[]
        assert result_no_chunks_provided.average_chunk_size == 20.0 # Validator returns original 'v' (20.0) because chunks is empty

        result_no_chunks_default = ChunkingResultModel(document_uuid=doc_uuid, document_id=1)
        assert result_no_chunks_default.total_chunks == 0
        assert result_no_chunks_default.average_chunk_size == 0.0


    def test_serialization(self):
        doc_uuid = uuid.uuid4()
        ts = datetime.now(timezone.utc)
        chunk1 = ProcessedChunk(chunk_index=0, text="Chunk1", char_start=0, char_end=6, token_count=1)

        result = ChunkingResultModel(
            document_uuid=doc_uuid,
            document_id=2,
            processing_timestamp=ts,
            status=ProcessingResultStatus.SUCCESS,
            chunks=[chunk1],
            total_chunks=1, # Explicitly set, matches validator if chunks=[chunk1]
            average_chunk_size=6.0, # Explicitly set, matches validator
            strategy="fixed_size",
            metadata={"custom_key": "val"}
        )

        result_dict = result.model_dump()
        assert result_dict["document_uuid"] == str(doc_uuid)
        assert result_dict["document_id"] == 2
        assert result_dict["total_chunks"] == 1
        assert result_dict["average_chunk_size"] == 6.0
        assert result_dict["strategy"] == "fixed_size"
        assert len(result_dict["chunks"]) == 1
        assert result_dict["chunks"][0]["text"] == "Chunk1"
        assert result_dict["metadata"] == {"custom_key": "val"}

        result_json = result.model_dump_json()
        assert f'"document_id":2' in result_json
        assert f'"total_chunks":1' in result_json
        assert f'"strategy":"fixed_size"' in result_json
        assert '"chunks":[{' in result_json # Check for chunk structure start
