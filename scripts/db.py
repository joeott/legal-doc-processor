"""
Unified database module for the PDF processing pipeline.
Combines Supabase operations, Pydantic-aware database handling, and migration utilities.
"""

import os
import logging
import json
import time
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import List, Dict, Optional, Tuple, Union, Type, TypeVar, Any
from dataclasses import dataclass
from functools import wraps

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel, ValidationError

# Import our Pydantic models from consolidated location
from scripts.models import (
    ProjectMinimal as ProjectModel,
    SourceDocumentMinimal as SourceDocumentModel,
    DocumentChunkMinimal as ChunkModel,
    EntityMentionMinimal as EntityMentionModel,
    CanonicalEntityMinimal as CanonicalEntityModel,
    RelationshipStagingMinimal as RelationshipStagingModel,
    ProcessingStatus,
    ProcessingTaskMinimal
)

# Import JSON encoder - TODO: Move this to scripts/ if needed
from scripts.core.json_serializer import PydanticJSONEncoder

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


# ========== Connection Management ==========

# Import global engine and session factory from config
from scripts.config import db_engine, DBSessionLocal

# The engine is now db_engine from scripts.config
engine = db_engine  # For backward compatibility if other modules import 'engine' from 'scripts.db'
# SessionLocal is now DBSessionLocal from scripts.config

def get_db():
    """Get database session with automatic cleanup."""
    db = DBSessionLocal()
    try:
        yield db
        db.commit()
    except:
        db.rollback()
        raise
    finally:
        db.close()


# ========== Serialization ==========

class PydanticSerializer:
    """Handles all Pydantic model serialization consistently."""
    
    @staticmethod
    def serialize(obj: Any) -> Any:
        """Serialize any object to JSON-compatible format."""
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode='json')
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, uuid.UUID):
            return str(obj)
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, bytes):
            return obj.decode('utf-8')
        elif hasattr(obj, 'model_dump'):
            return obj.model_dump(mode='json')
        return obj
    
    @staticmethod
    def deserialize(data: Dict[str, Any], model_class: Type[T], table_name: str = None) -> T:
        """Deserialize data to Pydantic model with validation."""
        try:
            # Clean empty strings
            cleaned = {k: None if v == "" else v for k, v in data.items()}
            
            # If table name is provided, apply reverse mapping
            if table_name:
                try:
                    from scripts.enhanced_column_mappings import reverse_map_from_db
                    cleaned = reverse_map_from_db(table_name, cleaned)
                except ImportError:
                    # Enhanced mappings not available, use data as-is
                    pass
            
            return model_class.model_validate(cleaned)
        except ValidationError as e:
            logger.error(f"Validation failed for {model_class.__name__}: {e}")
            raise


# ========== Migration Support ==========

@dataclass
class ValidationResult:
    """Result of validating a database record against a Pydantic model"""
    table_name: str
    record_id: Optional[int]
    is_valid: bool
    model_instance: Optional[BaseModel] = None
    errors: List[str] = None
    warnings: List[str] = None
    suggested_fixes: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.suggested_fixes is None:
            self.suggested_fixes = []


@dataclass
class MigrationReport:
    """Comprehensive report of database migration validation"""
    total_records: int
    valid_records: int
    invalid_records: int
    tables_validated: List[str]
    validation_results: List[ValidationResult]
    error_summary: Dict[str, int]
    generated_at: datetime
    
    @property
    def success_rate(self) -> float:
        """Calculate the success rate of validation"""
        if self.total_records == 0:
            return 0.0
        return (self.valid_records / self.total_records) * 100


class DatabaseType:
    """Database type definitions for migration."""
    PROJECTS = ("projects", ProjectModel)
    SOURCE_DOCUMENTS = ("source_documents", SourceDocumentModel)
    # NEO4J_DOCUMENTS = ("neo4j_documents", Neo4jDocumentModel)  # Not in consolidated models
    CHUNKS = ("document_chunks", ChunkModel)
    ENTITY_MENTIONS = ("entity_mentions", EntityMentionModel)
    CANONICAL_ENTITIES = ("canonical_entities", CanonicalEntityModel)
    RELATIONSHIP_STAGING = ("relationship_staging", RelationshipStagingModel)
    # TEXTRACT_JOBS = ("textract_jobs", TextractJobModel)  # Not in consolidated models
    # IMPORT_SESSIONS = ("import_sessions", ImportSessionModel)  # Not in consolidated models
    # CHUNK_EMBEDDINGS = ("chunk_embeddings", ChunkEmbeddingModel)  # Not in consolidated models
    # CANONICAL_ENTITY_EMBEDDINGS = ("canonical_entity_embeddings", CanonicalEntityEmbeddingModel)  # Not in consolidated models
    # PROCESSING_HISTORY = ("document_processing_history", DocumentProcessingHistoryModel)  # Not in consolidated models
    
    @classmethod
    def all_types(cls) -> List[Tuple[str, Type[BaseModel]]]:
        """Get all database types"""
        return [
            cls.PROJECTS, cls.SOURCE_DOCUMENTS,
            cls.CHUNKS, cls.ENTITY_MENTIONS, cls.CANONICAL_ENTITIES,
            cls.RELATIONSHIP_STAGING
        ]


# ========== Pydantic Database Manager ==========

class PydanticDatabase:
    """Database operations with automatic Pydantic model handling."""
    
    def __init__(self):
        """Initialize database handler."""
        self.serializer = PydanticSerializer()
        self.encoder_class = PydanticJSONEncoder  # Store the class, not an instance
    
    def serialize_for_db(self, model: BaseModel) -> Dict[str, Any]:
        """Serialize Pydantic model for database insertion."""
        data = model.model_dump(mode='json')
        
        # Convert None to actual NULL for database
        cleaned = {}
        for key, value in data.items():
            if value is None:
                cleaned[key] = None
            elif isinstance(value, dict):
                cleaned[key] = json.dumps(value, cls=self.encoder_class)
            elif isinstance(value, list):
                cleaned[key] = json.dumps(value, cls=self.encoder_class)
            else:
                cleaned[key] = self.serializer.serialize(value)
        
        return cleaned
    
    def create(
        self,
        table: str,
        model: BaseModel,
        returning: bool = True
    ) -> Optional[T]:
        """Create a record from a Pydantic model."""
        from scripts.rds_utils import insert_record
        try:
            data = self.serialize_for_db(model)
            
            if returning:
                result = insert_record(table, data)
                if result:
                    return self.serializer.deserialize(result, type(model), table)
            else:
                insert_record(table, data)
                
            return None
            
        except Exception as e:
            logger.error(f"Database create error in {table}: {e}")
            raise
    
    def update(
        self,
        table: str,
        model: BaseModel,
        match_fields: Dict[str, Any],
        returning: bool = True
    ) -> Optional[T]:
        """Update a record from a Pydantic model."""
        from scripts.rds_utils import update_record
        try:
            data = self.serialize_for_db(model)
            
            if returning:
                result = update_record(table, data, match_fields)
                if result:
                    return self.serializer.deserialize(result, type(model))
            else:
                update_record(table, data, match_fields)
                
            return None
            
        except Exception as e:
            logger.error(f"Database update error in {table}: {e}")
            raise
    
    def get(
        self,
        table: str,
        model_class: Type[T],
        match_fields: Dict[str, Any]
    ) -> Optional[T]:
        """Get a single record as a Pydantic model."""
        from scripts.rds_utils import select_records
        try:
            logger.debug(f"PydanticDatabase.get called - table: {table}, match_fields: {match_fields}")
            results = select_records(table, match_fields, limit=1)
            logger.debug(f"select_records returned: {results}")
            
            if results and len(results) > 0:
                return self.serializer.deserialize(results[0], model_class, table)
                
            return None
            
        except (Exception, ValidationError) as e:
            logger.error(f"Database get error in {table}: {e}")
            return None
    
    def list(
        self,
        table: str,
        model_class: Type[T],
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        order_by: Optional[str] = None
    ) -> List[T]:
        """List records as Pydantic models."""
        from scripts.rds_utils import select_records
        try:
            # Note: select_records doesn't support list filters, so we'll just use simple equality
            results = select_records(table, filters, limit=limit, order_by=order_by)
            
            models = []
            for data in results:
                try:
                    model = self.serializer.deserialize(data, model_class)
                    models.append(model)
                except ValidationError as e:
                    logger.warning(f"Skipping invalid record in {table}: {e}")
            
            return models
            
        except Exception as e:
            logger.error(f"Database list error in {table}: {e}")
            return []
    
    def delete(
        self,
        table: str,
        match_fields: Dict[str, Any]
    ) -> int:
        """Delete records matching criteria."""
        from scripts.rds_utils import delete_records
        try:
            count = delete_records(table, match_fields)
            return count
            
        except Exception as e:
            logger.error(f"Database delete error in {table}: {e}")
            return 0


# ========== Main Database Manager ==========

class DatabaseManager:
    """
    Unified database operations manager.
    Combines all database operations with Pydantic model support and conformance validation.
    """
    
    def __init__(self, validate_conformance: bool = True):
        """Initialize database manager with optional conformance validation."""
        self.pydantic_db = PydanticDatabase()
        self.serializer = PydanticSerializer()
        self._request_count = 0
        self._error_count = 0
        self._last_request_time = None
        self.conformance_validated = False
        self.validate_on_init = validate_conformance
        
        # Initialize conformance validator if requested
        if self.validate_on_init:
            self.validate_conformance()
    
    def validate_conformance(self) -> bool:
        """
        Validate schema conformance before operations.
        
        Returns:
            True if conformant
            
        Raises:
            ConformanceError if not conformant
        """
        # Check if we should skip conformance check
        from scripts.config import SKIP_CONFORMANCE_CHECK, USE_MINIMAL_MODELS
        
        if SKIP_CONFORMANCE_CHECK:
            logger.warning("Skipping conformance validation due to SKIP_CONFORMANCE_CHECK=true")
            self.conformance_validated = True
            return True
            
        if USE_MINIMAL_MODELS:
            logger.info("Using minimal models - reduced conformance requirements")
            
        if self.conformance_validated:
            return True
            
        try:
            from scripts.core.conformance_validator import ConformanceValidator, ConformanceError # Keep import here

            validator = ConformanceValidator()
            # Assuming validate_with_recovery returns: success (bool), report (ConformanceReport), recovery_actions (list)
            success, report, recovery_actions = validator.validate_with_recovery(auto_fix=False)

            if not success:
                # Extract critical issues from the report's issues list
                error_issues = [i for i in report.issues if i.severity == "error"]
                # Raise ConformanceError with the report for detailed diagnostics
                raise ConformanceError(
                    f"Schema conformance failure: {len(error_issues)} critical issues found. Recovery actions taken: {recovery_actions}",
                    report
                )

            self.conformance_validated = True
            logger.info("Database schema conformance validated successfully")
            return True

        except ImportError:
            logger.warning("ConformanceValidator or related components import failed. Proceeding without schema conformance validation. THIS IS A DEGRADED STATE and may lead to runtime errors if the schema is incompatible.")
            self.conformance_validated = True # Consistent with original behavior of allowing operation
            return True # Indicate that, for the purpose of this check, we are proceeding as if validated (degraded mode)

        except ConformanceError as ce:
            logger.error(f"Caught schema conformance failure: {ce}") # Log the error message from ConformanceError
            self.conformance_validated = False # Mark as not conformant
            raise # Re-raise the ConformanceError to be handled by the caller

        except Exception as e: # Catch any other unexpected exceptions during the validation process
            logger.critical(f"Unexpected critical error during conformance validation: {e}", exc_info=True)
            self.conformance_validated = False # Do not mark as validated
            raise # Re-raise to prevent proceeding with a potentially compromised DatabaseManager
    
    def get_session(self):
        """Get database session with automatic cleanup and conformance validation."""
        if not self.conformance_validated:
            self.validate_conformance()
            
        return get_db()
    
    def execute_with_transaction(self, operations: callable, *args, **kwargs):
        """
        Execute operations within a transaction with automatic rollback.
        
        Args:
            operations: Callable that takes a session as first argument
            *args, **kwargs: Arguments to pass to operations
            
        Returns:
            Result of operations
        """
        if not self.conformance_validated:
            self.validate_conformance()
            
        session = DBSessionLocal()
        try:
            result = operations(session, *args, **kwargs)
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            logger.error(f"Transaction failed, rolled back: {e}")
            raise
        finally:
            session.close()
    
    # ========== URL Generation ==========
    
    def generate_document_url(self, file_path: str, use_signed_url: bool = True) -> str:
        """
        Generate a URL for a document stored in S3.
        
        Args:
            file_path: Path to the file in S3 or direct URL
            use_signed_url: Whether to generate a signed URL
            
        Returns:
            URL for the document
        """
        from scripts.rds_utils import generate_document_url
        return generate_document_url(file_path, use_signed_url)
    
    # ========== Project Operations ==========
    
    def get_project_by_id(self, project_id: int) -> Optional[ProjectModel]:
        """Get project by ID."""
        return self.pydantic_db.get(
            "projects",
            ProjectModel,
            {"id": project_id}
        )
    
    def get_projects_by_name(self, name: str, fuzzy: bool = False) -> List[ProjectModel]:
        """Get projects by name with optional fuzzy matching."""
        from scripts.rds_utils import execute_query
        try:
            if fuzzy:
                # Use ILIKE for case-insensitive fuzzy matching
                query = "SELECT * FROM projects WHERE name ILIKE :name"
                results = execute_query(query, {"name": f"%{name}%"})
            else:
                query = "SELECT * FROM projects WHERE name = :name"
                results = execute_query(query, {"name": name})
            
            projects = []
            for data in results:
                try:
                    project = ProjectModel.model_validate(data)
                    projects.append(project)
                except ValidationError as e:
                    logger.warning(f"Invalid project data: {e}")
            
            return projects
            
        except Exception as e:
            logger.error(f"Error getting projects by name: {e}")
            return []
    
    def create_project(self, project: ProjectModel) -> Optional[ProjectModel]:
        """Create a new project."""
        return self.pydantic_db.create("projects", project)
    
    # ========== Document Operations ==========
    
    def create_source_document(self, document: SourceDocumentModel) -> Optional[SourceDocumentModel]:
        """Create a source document entry."""
        return self.pydantic_db.create("source_documents", document)
    
    def update_source_document(self, document: SourceDocumentModel) -> Optional[SourceDocumentModel]:
        """Update a source document."""
        return self.pydantic_db.update(
            "source_documents",
            document,
            {"id": document.id} if document.id else {"document_uuid": str(document.document_uuid)}
        )
    
    def get_source_document(self, document_uuid: str) -> Optional[SourceDocumentModel]:
        """Get source document by UUID."""
        logger.info(f"Getting source document with UUID: {document_uuid}")
        result = self.pydantic_db.get(
            "source_documents",
            SourceDocumentModel,
            {"document_uuid": document_uuid}
        )
        logger.info(f"Source document lookup result: {result}")
        return result
    
    def update_document_status(
        self,
        document_uuid: str,
        status: ProcessingStatus,
        error_message: Optional[str] = None
    ) -> bool:
        """Update document processing status."""
        from scripts.rds_utils import update_record
        try:
            update_data = {
                "processing_status": status.value,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            if error_message:
                update_data["error_message"] = error_message
            
            if status == ProcessingStatus.COMPLETED:
                update_data["processing_completed_at"] = datetime.now(timezone.utc).isoformat()
            
            result = update_record(
                "source_documents",
                update_data,
                {"document_uuid": document_uuid}
            )
            
            return result is not None
            
        except Exception as e:
            logger.error(f"Error updating document status: {e}")
            return False
    
    # ========== Chunk Operations ==========
    
    def create_chunks(self, chunks: List[ChunkModel]) -> List[ChunkModel]:
        """Create multiple chunks efficiently."""
        if not chunks:
            return []
        
        created = []
        for chunk in chunks:
            result = self.pydantic_db.create("document_chunks", chunk)
            if result:
                created.append(result)
        
        return created
    
    def get_document_chunks(self, document_uuid: str) -> List[ChunkModel]:
        """Get all chunks for a document."""
        return self.pydantic_db.list(
            "document_chunks",
            ChunkModel,
            {"document_uuid": document_uuid},
            order_by="chunk_index"
        )
    
    # ========== Entity Operations ==========
    
    def create_entity_mentions(self, mentions: List[EntityMentionModel]) -> List[EntityMentionModel]:
        """Create multiple entity mentions."""
        created = []
        for mention in mentions:
            result = self.pydantic_db.create("entity_mentions", mention)
            if result:
                created.append(result)
        return created
    
    def get_entity_mentions(self, document_uuid: str) -> List[EntityMentionModel]:
        """Get all entity mentions for a document."""
        return self.pydantic_db.list(
            "entity_mentions",
            EntityMentionModel,
            {"document_uuid": document_uuid}
        )
    
    def create_canonical_entities(self, entities: List[CanonicalEntityModel]) -> List[CanonicalEntityModel]:
        """Create canonical entities."""
        created = []
        for entity in entities:
            result = self.pydantic_db.create("canonical_entities", entity)
            if result:
                created.append(result)
        return created
    
    # ========== Relationship Operations ==========
    
    def create_relationship_staging(self, relationship: RelationshipStagingModel) -> Optional[RelationshipStagingModel]:
        """Create a relationship in staging."""
        return self.pydantic_db.create("relationship_staging", relationship)
    
    def get_staged_relationships(self, document_uuid: str) -> List[RelationshipStagingModel]:
        """Get all staged relationships for a document."""
        return self.pydantic_db.list(
            "relationship_staging",
            RelationshipStagingModel,
            {"source_id": document_uuid}
        )
    
    # ========== Textract Operations ==========
    
    def create_textract_job_entry(
        self,
        source_document_id: int,
        document_uuid: uuid.UUID,
        job_id: str,
        s3_input_bucket: str,
        s3_input_key: str,
        job_type: str = 'DetectDocumentText',
        s3_output_bucket: Optional[str] = None,
        s3_output_key: Optional[str] = None,
        client_request_token: Optional[str] = None,
        job_tag: Optional[str] = None,
        job_status: str = 'IN_PROGRESS',
        sns_topic_arn: Optional[str] = None
    ):  # -> Optional[TextractJobModel]:  # Model not in consolidated
        """Create a Textract job entry in the database.
        Note: TextractJobModel not in consolidated models, returns dict instead."""
        try:
            # Create a dictionary with the correct column names
            job_data = {
                'job_id': job_id,
                'document_uuid': str(document_uuid),
                'job_type': job_type,
                'status': job_status,  # Changed from job_status to status
                'created_at': datetime.now(timezone.utc),
                'started_at': datetime.now(timezone.utc),
                'metadata': {
                    's3_input_bucket': s3_input_bucket,
                    's3_input_key': s3_input_key,
                    's3_output_bucket': s3_output_bucket,
                    's3_output_key': s3_output_key,
                    'job_tag': job_tag,
                    'sns_topic_arn': sns_topic_arn,
                    'source_document_id': source_document_id
                }
            }
            
            # Remove None values from metadata
            job_data['metadata'] = {k: v for k, v in job_data['metadata'].items() if v is not None}
            
            # Create the job entry using raw SQL since we don't have the exact model
            from scripts.rds_utils import insert_record
            result = insert_record("textract_jobs", job_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error creating Textract job entry: {e}")
            return None
    
    def get_textract_job_by_job_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get Textract job by job ID."""
        try:
            from scripts.rds_utils import select_records
            results = select_records(
                "textract_jobs",
                where={"job_id": job_id},
                limit=1
            )
            if results:
                return results[0]
            return None
        except Exception as e:
            logger.error(f"Error getting Textract job: {e}")
            return None
    
    def update_textract_job_status(
        self,
        job_id: str,
        status: str,
        error_message: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        pages_processed: Optional[int] = None,
        page_count: Optional[int] = None,
        processed_pages: Optional[int] = None,
        avg_confidence: Optional[float] = None,
        warnings_json: Optional[List[Any]] = None,
        completed_at_override: Optional[datetime] = None
    ) -> bool:
        """Update Textract job status."""
        from scripts.rds_utils import update_record
        try:
            update_data = {
                "status": status,  # Changed from job_status to status
            }
            
            if error_message:
                update_data["error_message"] = error_message  # Changed from status_message
            
            # Use completed_at_override if provided, otherwise completed_at
            if completed_at_override:
                update_data["completed_at"] = completed_at_override.isoformat()
            elif completed_at:
                update_data["completed_at"] = completed_at.isoformat()
            
            # Handle page_count (prefer page_count over pages_processed)
            if page_count is not None:
                update_data["page_count"] = page_count
            elif pages_processed is not None:
                update_data["page_count"] = pages_processed
            elif processed_pages is not None:
                update_data["page_count"] = processed_pages
            
            # Add additional metadata to the metadata JSON field
            metadata_updates = {}
            if avg_confidence is not None:
                metadata_updates["avg_confidence"] = avg_confidence
            if warnings_json is not None:
                metadata_updates["warnings"] = warnings_json
                
            if metadata_updates:
                # Get existing metadata and update it
                existing_job = self.get_textract_job_by_job_id(job_id)
                if existing_job and existing_job.get('metadata'):
                    existing_metadata = existing_job['metadata']
                    if isinstance(existing_metadata, dict):
                        existing_metadata.update(metadata_updates)
                        update_data["metadata"] = existing_metadata
                    else:
                        update_data["metadata"] = metadata_updates
                else:
                    update_data["metadata"] = metadata_updates
            
            result = update_record(
                "textract_jobs",
                update_data,
                {"job_id": job_id}
            )
            
            return result is not None
            
        except Exception as e:
            logger.error(f"Error updating Textract job status: {e}")
            return False
    
    def update_source_document_with_textract_outcome(
        self,
        source_doc_sql_id: int,
        textract_job_id: str,
        textract_job_status: str,
        raw_text: Optional[str] = None,
        markdown_text: Optional[str] = None,
        ocr_metadata: Optional[Dict[str, Any]] = None,
        job_started_at: Optional[datetime] = None,
        job_completed_at: Optional[datetime] = None,
        textract_warnings_json: Optional[List[Any]] = None,
        textract_confidence: Optional[float] = None
    ) -> bool:
        """Update source document with Textract processing results."""
        from scripts.rds_utils import update_record
        try:
            update_data = {
                "textract_job_id": textract_job_id,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Update status based on Textract job status
            if textract_job_status == 'SUCCEEDED':
                update_data["celery_status"] = ProcessingStatus.OCR_COMPLETED.value
                update_data["ocr_completed_at"] = datetime.now(timezone.utc).isoformat()
                if raw_text:
                    update_data["raw_extracted_text"] = raw_text
                if markdown_text:
                    update_data["markdown_text"] = markdown_text
                if ocr_metadata:
                    update_data["ocr_metadata_json"] = json.dumps(ocr_metadata, cls=self.pydantic_db.encoder_class)
            elif textract_job_status == 'FAILED':
                update_data["celery_status"] = ProcessingStatus.OCR_FAILED.value
                update_data["error_message"] = f"Textract job {textract_job_id} failed"
            
            result = update_record(
                "source_documents",
                update_data,
                {"id": source_doc_sql_id}
            )
            
            return result is not None
            
        except Exception as e:
            logger.error(f"Error updating source document with Textract outcome: {e}")
            return False
    
    # ========== Migration Support ==========
    
    def validate_table_data(
        self,
        table_name: str,
        model_class: Type[BaseModel],
        limit: Optional[int] = None
    ) -> List[ValidationResult]:
        """Validate all records in a table against a Pydantic model."""
        from scripts.rds_utils import select_records
        results = []
        
        try:
            records = select_records(table_name, limit=limit)
            
            for record in records:
                record_id = record.get('id')
                
                try:
                    # Try to create model instance
                    model = create_model_from_db(record, model_class)
                    
                    result = ValidationResult(
                        table_name=table_name,
                        record_id=record_id,
                        is_valid=True,
                        model_instance=model
                    )
                    
                except ValidationError as e:
                    # Validation failed
                    result = ValidationResult(
                        table_name=table_name,
                        record_id=record_id,
                        is_valid=False,
                        errors=[str(err) for err in e.errors()]
                    )
                    
                    # Add suggested fixes
                    for error in e.errors():
                        if error['type'] == 'missing':
                            result.suggested_fixes.append(
                                f"Add required field '{error['loc'][0]}' with appropriate default value"
                            )
                        elif error['type'] == 'type_error':
                            result.suggested_fixes.append(
                                f"Convert field '{error['loc'][0]}' to type {error['ctx']['expected_type']}"
                            )
                
                except Exception as e:
                    # Other errors
                    result = ValidationResult(
                        table_name=table_name,
                        record_id=record_id,
                        is_valid=False,
                        errors=[f"Unexpected error: {str(e)}"]
                    )
                
                results.append(result)
        
        except Exception as e:
            logger.error(f"Error validating table {table_name}: {e}")
        
        return results
    
    def generate_migration_report(
        self,
        tables: Optional[List[Tuple[str, Type[BaseModel]]]] = None
    ) -> MigrationReport:
        """Generate a comprehensive migration validation report."""
        if tables is None:
            tables = DatabaseType.all_types()
        
        all_results = []
        error_summary = {}
        
        for table_name, model_class in tables:
            logger.info(f"Validating table: {table_name}")
            results = self.validate_table_data(table_name, model_class)
            all_results.extend(results)
            
            # Count errors by type
            for result in results:
                if not result.is_valid:
                    for error in result.errors:
                        error_type = error.split(':')[0] if ':' in error else 'general'
                        error_summary[error_type] = error_summary.get(error_type, 0) + 1
        
        # Calculate totals
        total = len(all_results)
        valid = sum(1 for r in all_results if r.is_valid)
        invalid = total - valid
        
        return MigrationReport(
            total_records=total,
            valid_records=valid,
            invalid_records=invalid,
            tables_validated=[t[0] for t in tables],
            validation_results=all_results,
            error_summary=error_summary,
            generated_at=datetime.now(timezone.utc)
        )
    
    # ========== Utility Methods ==========
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get database connection statistics."""
        return {
            "total_requests": self._request_count,
            "total_errors": self._error_count,
            "error_rate": self._error_count / self._request_count if self._request_count > 0 else 0,
            "last_request": self._last_request_time.isoformat() if self._last_request_time else None,
            "client_status": "connected"  # Always connected with connection pool
        }
    
    def health_check(self) -> bool:
        """Check database health."""
        from scripts.rds_utils import test_connection
        return test_connection()
    
    # ========== Context Manager Support ==========
    
    def __aenter__(self):
        """Async context manager entry."""
        return self
    
    def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        # Could add cleanup logic here if needed
        pass


# ========== Legacy Compatibility Layer ==========

class SupabaseManager(DatabaseManager):
    """
    Legacy compatibility wrapper for existing code.
    Maintains the old SupabaseManager interface while using the new implementation.
    """
    
    def __init__(self):
        """Initialize with backward compatibility."""
        super().__init__()
        logger.info("SupabaseManager initialized (using new DatabaseManager)")
    
    # Add any legacy methods that need special handling here
    def create_source_document_entry(self, document_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Legacy method for creating source documents."""
        try:
            # Convert dict to model
            if 'document_uuid' in document_data and isinstance(document_data['document_uuid'], str):
                document_data['document_uuid'] = uuid.UUID(document_data['document_uuid'])
            
            model = SourceDocumentModel(**document_data)
            result = self.pydantic_db.create("source_documents", model, returning=True)
            
            if result:
                return result.model_dump(mode='json')
            return None
            
        except Exception as e:
            logger.error(f"Error in legacy create_source_document_entry: {e}")
            return None


# ========== Utility Functions ==========

def get_database_manager() -> DatabaseManager:
    """Get database manager instance."""
    return DatabaseManager()


def get_supabase_manager() -> SupabaseManager:
    """Get Supabase manager instance (legacy compatibility)."""
    return SupabaseManager()


# ========== Export All ==========

__all__ = [
    # Classes
    'DatabaseManager',
    'SupabaseManager',
    'PydanticDatabase',
    'PydanticSerializer',
    'DatabaseType',
    'ValidationResult',
    'MigrationReport',
    
    # Functions
    'get_database_manager',
    'get_supabase_manager',
    'get_db',  # Export the RDS session getter instead
    'engine'   # Export the engine for backward compatibility
]