import pytest
from unittest.mock import patch, MagicMock, PropertyMock, call, ANY
import uuid
from datetime import datetime, timezone

# Models and services to be tested or mocked
from scripts.pdf_tasks import PDFTask, extract_text_from_document, chunk_document_text
from scripts.db import DatabaseManager #, ProcessingStatus (Import ProcessingStatus if needed later for specific task tests)
from scripts.entity_service import EntityService
from scripts.graph_service import GraphService
from scripts.cache import CacheKeys # Assuming CacheKeys is an Enum or similar
from scripts.core.processing_models import OCRResultModel # For extract_text_from_document return type hint
from scripts.core.schemas import SourceDocumentModel # For type hinting if needed

# Pydantic models for testing if not importing directly
from pydantic import BaseModel, Field

# For simulating Celery task context if needed (though PDFTask itself is not a Celery task)
class MockCeleryTask:
    def __init__(self, request_id=None):
        self.request = MagicMock()
        self.request.id = request_id or str(uuid.uuid4())

    def update_state(self, state, meta):
        pass

# A simple mock for settings if PDFTask tries to access it.
class MockSettings:
    def __init__(self):
        self.DB_URL = "postgresql://user:pass@host:port/db"
        self.CELERY_BROKER_URL = "redis://localhost:6379/0"
        self.CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
        # Add other settings if PDFTask constructor or methods require them

# Global test data (if any specific needed for pdf_tasks)
TEST_DOC_UUID = uuid.uuid4()
TEST_FILE_PATH = "/tmp/test_document.pdf"

# Ensure that the PDFTask base class can be instantiated for testing its properties
# If it's an abstract class or has abstract methods, we might need a concrete subclass.
# Assuming PDFTask can be instantiated or its properties can be tested on a MagicMock instance.
# For property tests, we can define a dummy subclass if PDFTask() itself is not enough.
class DummyPDFTask(PDFTask):
    def __init__(self, document_id: str, file_path: str, settings: Any = None):
        super().__init__(document_id, file_path, settings if settings else MockSettings())

    def run(self, *args, **kwargs): # Abstract method if any
        pass

    def on_success(self, retval, task_id, args, kwargs): # Abstract method if any
        pass

    def on_failure(self, exc, task_id, args, kwargs, einfo): # Abstract method if any
        pass

    # Add other abstract methods if PDFTask has them
    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        pass

    def before_start(self, task_id, args, kwargs):
        pass


class TestPDFTaskProperties:

    @patch('scripts.pdf_tasks.DatabaseManager') # Patch DatabaseManager where it's used by PDFTask
    def test_db_manager_property(self, MockDatabaseManager: MagicMock):
        # Mock the instance returned by DatabaseManager()
        mock_db_instance = MockDatabaseManager.return_value

        task = DummyPDFTask(document_id=str(TEST_DOC_UUID), file_path=TEST_FILE_PATH)

        # First access
        db_manager1 = task.db_manager
        MockDatabaseManager.assert_called_once_with(validate_conformance_on_init=True)
        assert db_manager1 == mock_db_instance

        # Second access
        db_manager2 = task.db_manager
        MockDatabaseManager.assert_called_once() # Still called only once (cached instance)
        assert db_manager2 == mock_db_instance
        assert db_manager1 == db_manager2 # Same instance

    @patch('scripts.pdf_tasks.EntityService') # Patch where it's used
    @patch('scripts.pdf_tasks.DatabaseManager') # Also patch DBManager to control its instance
    def test_entity_service_property(self, MockDatabaseManager: MagicMock, MockEntityService: MagicMock):
        mock_db_mgr_instance = MockDatabaseManager.return_value
        mock_entity_svc_instance = MockEntityService.return_value

        task = DummyPDFTask(document_id=str(TEST_DOC_UUID), file_path=TEST_FILE_PATH)

        # First access to entity_service - this will also access db_manager first
        entity_service1 = task.entity_service

        # db_manager property should be called, initializing DatabaseManager
        MockDatabaseManager.assert_called_once_with(validate_conformance_on_init=True)
        # EntityService should be initialized with the db_manager instance
        MockEntityService.assert_called_once_with(db_manager=mock_db_mgr_instance)
        assert entity_service1 == mock_entity_svc_instance

        # Second access
        entity_service2 = task.entity_service
        MockEntityService.assert_called_once() # Still called only once
        assert entity_service2 == mock_entity_svc_instance
        assert entity_service1 == entity_service2

    @patch('scripts.pdf_tasks.GraphService') # Patch where it's used
    @patch('scripts.pdf_tasks.DatabaseManager') # Control DBManager instance
    def test_graph_service_property(self, MockDatabaseManager: MagicMock, MockGraphService: MagicMock):
        mock_db_mgr_instance = MockDatabaseManager.return_value
        mock_graph_svc_instance = MockGraphService.return_value

        task = DummyPDFTask(document_id=str(TEST_DOC_UUID), file_path=TEST_FILE_PATH)

        # First access
        graph_service1 = task.graph_service
        MockDatabaseManager.assert_called_once_with(validate_conformance_on_init=True)
        MockGraphService.assert_called_once_with(db_manager=mock_db_mgr_instance)
        assert graph_service1 == mock_graph_svc_instance

        # Second access
        graph_service2 = task.graph_service
        MockGraphService.assert_called_once()
        assert graph_service2 == mock_graph_svc_instance
        assert graph_service1 == graph_service2

    # Test that db_manager's validate_conformance is actually triggered by DatabaseManager.__init__
    # This requires a slightly different setup if we want to assert the internal call within DatabaseManager
    # For now, the above tests confirm DatabaseManager is initialized with validate_conformance_on_init=True,
    # which is the specified behavior to test for the PDFTask property.
    # A separate test for DatabaseManager.__init__ itself (in test_db.py) covers validate_conformance call.


# Define a common patcher for PDFTask methods/properties used in extract_text_from_document
# This avoids repeating many @patch decorators for each test method.
# These are mocks for dependencies *of the task function*, not the PDFTask class properties.
extract_text_common_patches = [
    patch('scripts.pdf_tasks.validate_document_exists', autospec=True),
    patch('scripts.pdf_tasks.update_document_state', autospec=True),
    patch('scripts.pdf_tasks.get_redis_manager', autospec=True),
    patch('scripts.pdf_tasks.extract_text_from_pdf', autospec=True),
    patch.object(PDFTask, 'db_manager', new_callable=PropertyMock) # Mock the db_manager property of PDFTask
]

# Helper to apply multiple decorators
def apply_patches(patches):
    def decorator(func):
        for p in reversed(patches): # Apply patches from bottom up
            func = p(func)
        return func
    return decorator


class TestExtractTextFromDocumentTask:

    @apply_patches(extract_text_common_patches)
    def test_extract_text_cached_path(
        self, mock_db_manager_prop: PropertyMock, mock_extract_text_pdf: MagicMock,
        mock_get_redis_mgr: MagicMock, mock_update_doc_state: MagicMock, mock_validate_exists: MagicMock
    ):
        mock_redis_instance = mock_get_redis_mgr.return_value
        cached_data = {"text": "Cached OCR text", "pages": 1, "confidence": 0.95}
        mock_redis_instance.get_dict.return_value = cached_data

        # Mock the PDFTask instance that would be 'self' for the task function
        # In Celery, 'self' would be the task instance. Here we simulate it.
        mock_task_instance = MagicMock(spec=PDFTask)
        mock_task_instance.document_id = str(TEST_DOC_UUID)
        mock_task_instance.file_path = TEST_FILE_PATH
        # Ensure the mocked db_manager property returns another mock
        mock_db_manager_instance = MagicMock(spec=DatabaseManager)
        mock_db_manager_prop.return_value = mock_db_manager_instance

        # Call the task function, passing the mocked task instance as 'self'
        result = extract_text_from_document(mock_task_instance)

        cache_key = CacheKeys.ocr_result_for_doc_id(mock_task_instance.document_id)
        mock_redis_instance.get_dict.assert_called_once_with(cache_key)
        mock_extract_text_pdf.assert_not_called() # Should not call actual OCR

        mock_update_doc_state.assert_called_once_with(
            db_manager=mock_db_manager_instance,
            document_id=mock_task_instance.document_id,
            state="completed", # Assuming this is the state for cached success
            state_description="from_cache",
            celery_task_id=None # Task ID not directly available unless extract_text_from_document is a bound task
        )
        assert result == cached_data

    @apply_patches(extract_text_common_patches)
    def test_extract_text_non_cached_path_success(
        self, mock_db_manager_prop: PropertyMock, mock_extract_text_pdf: MagicMock,
        mock_get_redis_mgr: MagicMock, mock_update_doc_state: MagicMock, mock_validate_exists: MagicMock
    ):
        mock_redis_instance = mock_get_redis_mgr.return_value
        mock_redis_instance.get_dict.return_value = None # No cache hit

        mock_validate_exists.return_value = True # Document exists

        ocr_success_result = OCRResultModel(
            document_uuid=TEST_DOC_UUID,
            provider="mock_ocr",
            file_type="pdf",
            full_text="Successfully extracted text.",
            average_confidence=0.98,
            pages=[] # Simplified
        )
        mock_extract_text_pdf.return_value = ocr_success_result

        mock_task_instance = MagicMock(spec=PDFTask)
        mock_task_instance.document_id = str(TEST_DOC_UUID)
        mock_task_instance.file_path = TEST_FILE_PATH
        mock_db_manager_instance = MagicMock(spec=DatabaseManager)
        mock_db_manager_prop.return_value = mock_db_manager_instance

        # Simulate task_id if update_document_state needs it from bound task
        # extract_text_from_document is a function, not a bound task method by default from snippet
        # If it were a bound task, self.request.id would be available.
        # Let's assume it's passed or None for now.
        # The function signature is `extract_text_from_document(self: PDFTask, celery_task_id: Optional[str] = None)`
        # So we need to pass it.
        test_celery_task_id = "celery-task-123"

        result = extract_text_from_document(mock_task_instance, celery_task_id=test_celery_task_id)

        cache_key = CacheKeys.ocr_result_for_doc_id(mock_task_instance.document_id)
        mock_redis_instance.get_dict.assert_called_once_with(cache_key)
        mock_validate_exists.assert_called_once_with(mock_db_manager_instance, mock_task_instance.document_id)
        mock_extract_text_pdf.assert_called_once_with(mock_task_instance.file_path, mock_task_instance.document_id)

        mock_redis_instance.store_dict.assert_called_once_with(cache_key, ocr_success_result.model_dump())

        mock_update_doc_state.assert_called_once_with(
            db_manager=mock_db_manager_instance,
            document_id=mock_task_instance.document_id,
            state="ocr_completed", # Or similar based on actual state machine
            state_description=ocr_success_result.provider,
            celery_task_id=test_celery_task_id,
            commit=True,
            processing_time=ANY, # ANY since actual time is hard to mock exactly
            result_payload=ocr_success_result.model_dump()
        )
        assert result == ocr_success_result.model_dump() # Task returns dict

    @apply_patches(extract_text_common_patches)
    def test_extract_text_validate_exists_false_raises_error(
        self, mock_db_manager_prop: PropertyMock, mock_extract_text_pdf: MagicMock,
        mock_get_redis_mgr: MagicMock, mock_update_doc_state: MagicMock, mock_validate_exists: MagicMock
    ):
        mock_redis_instance = mock_get_redis_mgr.return_value
        mock_redis_instance.get_dict.return_value = None # No cache

        mock_validate_exists.return_value = False # Document does not exist

        mock_task_instance = MagicMock(spec=PDFTask)
        mock_task_instance.document_id = str(TEST_DOC_UUID)
        mock_db_manager_instance = MagicMock(spec=DatabaseManager)
        mock_db_manager_prop.return_value = mock_db_manager_instance

        with pytest.raises(ValueError) as exc_info:
            extract_text_from_document(mock_task_instance)

        assert f"Document with ID {mock_task_instance.document_id} not found or accessible." in str(exc_info.value)
        mock_extract_text_pdf.assert_not_called()
        mock_update_doc_state.assert_called_once_with( # Should still update state to failed
            db_manager=mock_db_manager_instance,
            document_id=mock_task_instance.document_id,
            state="ocr_failed",
            state_description=ANY, # Error message
            celery_task_id=None, # No celery_task_id passed in this call
            commit=True
        )


    @apply_patches(extract_text_common_patches)
    def test_extract_text_ocr_failure(
        self, mock_db_manager_prop: PropertyMock, mock_extract_text_pdf: MagicMock,
        mock_get_redis_mgr: MagicMock, mock_update_doc_state: MagicMock, mock_validate_exists: MagicMock
    ):
        mock_redis_instance = mock_get_redis_mgr.return_value
        mock_redis_instance.get_dict.return_value = None
        mock_validate_exists.return_value = True

        ocr_failure_result = OCRResultModel(
            document_uuid=TEST_DOC_UUID, provider="mock_ocr_fail", file_type="pdf",
            status="failed", # Using string status from OCRResultModel if it's not an Enum
            error_message="OCR engine exploded"
        )
        # If OCRResultModel.status is an Enum (ProcessingResultStatus), use that:
        # from scripts.core.processing_models import ProcessingResultStatus
        # ocr_failure_result.status = ProcessingResultStatus.FAILED
        # For now, assuming string based on current OCRResultModel structure in prompt.
        # Let's assume it's an enum as it's better practice.
        from scripts.core.processing_models import ProcessingResultStatus
        ocr_failure_result.status = ProcessingResultStatus.FAILED

        mock_extract_text_pdf.return_value = ocr_failure_result

        mock_task_instance = MagicMock(spec=PDFTask)
        mock_task_instance.document_id = str(TEST_DOC_UUID)
        mock_task_instance.file_path = TEST_FILE_PATH
        mock_db_manager_instance = MagicMock(spec=DatabaseManager)
        mock_db_manager_prop.return_value = mock_db_manager_instance
        test_celery_task_id = "celery-fail-456"

        result = extract_text_from_document(mock_task_instance, celery_task_id=test_celery_task_id)

        mock_update_doc_state.assert_called_once_with(
            db_manager=mock_db_manager_instance,
            document_id=mock_task_instance.document_id,
            state="ocr_failed",
            state_description=ocr_failure_result.error_message,
            celery_task_id=test_celery_task_id,
            commit=True,
            processing_time=ANY,
            result_payload=ocr_failure_result.model_dump()
        )
        assert result == ocr_failure_result.model_dump()

    @apply_patches(extract_text_common_patches)
    @patch('scripts.pdf_tasks.logger.error') # Mock logger for exception case
    def test_extract_text_general_exception(
        self, mock_logger_error: MagicMock,
        mock_db_manager_prop: PropertyMock, mock_extract_text_pdf: MagicMock,
        mock_get_redis_mgr: MagicMock, mock_update_doc_state: MagicMock, mock_validate_exists: MagicMock
    ):
        mock_redis_instance = mock_get_redis_mgr.return_value
        mock_redis_instance.get_dict.return_value = None
        mock_validate_exists.return_value = True

        general_error = Exception("Something broke badly")
        mock_extract_text_pdf.side_effect = general_error

        mock_task_instance = MagicMock(spec=PDFTask)
        mock_task_instance.document_id = str(TEST_DOC_UUID)
        mock_task_instance.file_path = TEST_FILE_PATH
        mock_db_manager_instance = MagicMock(spec=DatabaseManager)
        mock_db_manager_prop.return_value = mock_db_manager_instance
        test_celery_task_id = "celery-exception-789"

        with pytest.raises(Exception) as exc_info: # Task re-raises the exception
             extract_text_from_document(mock_task_instance, celery_task_id=test_celery_task_id)

        assert exc_info.value == general_error # Check if the original exception is re-raised

        mock_logger_error.assert_called_once()
        assert "Unhandled exception in extract_text_from_document" in mock_logger_error.call_args[0][0]

        mock_update_doc_state.assert_called_once_with(
            db_manager=mock_db_manager_instance,
            document_id=mock_task_instance.document_id,
            state="ocr_failed",
            state_description=str(general_error),
            celery_task_id=test_celery_task_id,
            commit=True,
            processing_time=ANY
        )
