# supabase_utils.py
import os
import logging
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple, Union
from supabase import create_client, Client
import uuid

# Import our Pydantic models
from scripts.core.schemas import (
    ProjectModel, SourceDocumentModel, Neo4jDocumentModel, 
    ChunkModel, EntityMentionModel, CanonicalEntityModel,
    RelationshipStagingModel, TextractJobModel, ProcessingStatus,
    create_model_from_db
)
from pydantic import ValidationError

logger = logging.getLogger(__name__)

def get_supabase_client() -> Client:
    """
    Get a properly configured Supabase client.
    
    Returns:
        Supabase client instance
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set")
    
    return create_client(url, key)

def generate_document_url(file_path: str, use_signed_url: bool = True) -> str:
    """
    Generate a URL for a document stored in Supabase Storage or S3.
    This is a standalone function that doesn't require a SupabaseManager instance.
    
    Args:
        file_path: Path to the file in Supabase Storage or S3 URL
        use_signed_url: Whether to generate a signed URL (default: True for Mistral OCR compatibility)
        
    Returns:
        URL for the document (signed or public based on use_signed_url)
    """
    # Check if file_path is already a fully qualified path
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    
    # Handle S3 paths
    if file_path.startswith('s3://'):
        # S3 path - use S3StorageManager
        from s3_storage import S3StorageManager
        s3_manager = S3StorageManager()
        
        # Extract bucket and key from s3://bucket/key format
        parts = file_path.replace('s3://', '').split('/', 1)
        bucket = parts[0]
        key = parts[1]
        
        return s3_manager.generate_presigned_url_for_ocr(key, bucket)
        
    logger.info(f"Generating {'signed' if use_signed_url else 'public'} URL for file: {file_path}")
    
    try:
        # Get Supabase client
        client = get_supabase_client()
        
        # Check if file_path includes the bucket name
        parts = file_path.split('/')
        
        # Default bucket is 'documents' per upload.js
        bucket = 'documents'
        path = file_path
        
        # If file_path starts with a bucket name, extract it
        if len(parts) > 1 and parts[0] in ['documents', 'uploads']:
            bucket = parts[0]
            path = '/'.join(parts[1:])
        
        # Special handling: if path starts with 'uploads/', it's already the path within the 'documents' bucket
        # This matches the upload.js behavior where files go to 'documents' bucket with path 'uploads/[filename]'
        if not path.startswith('uploads/') and 'uploads/' in path:
            # Extract just the uploads/filename part
            uploads_idx = path.find('uploads/')
            if uploads_idx != -1:
                path = path[uploads_idx:]
        
        if use_signed_url:
            # Generate a signed URL with 1 hour expiry for Mistral OCR access
            expires_in = 3600  # 1 hour in seconds
            signed_url_response = client.storage.from_(bucket).create_signed_url(path, expires_in)
            
            if 'signedURL' in signed_url_response:
                signed_url = signed_url_response['signedURL']
            elif 'data' in signed_url_response and 'signedURL' in signed_url_response['data']:
                signed_url = signed_url_response['data']['signedURL']
            else:
                # Fallback if response format is different
                signed_url = signed_url_response.get('signedUrl', signed_url_response.get('signed_url', ''))
            
            if not signed_url:
                logger.error(f"Failed to get signed URL from response: {signed_url_response}")
                raise ValueError("Failed to generate signed URL")
                
            logger.info(f"Generated signed URL (expires in {expires_in}s): {signed_url[:100]}...")
            return signed_url
        else:
            # Get the Supabase Storage URL for this file (public URL)
            public_url = client.storage.from_(bucket).get_public_url(path)
            
            # Remove trailing ? if present (Supabase client sometimes adds it)
            if public_url.endswith('?'):
                public_url = public_url[:-1]
            
            logger.info(f"Generated public URL: {public_url}")
            return public_url
        
    except Exception as e:
        logger.error(f"Error generating {'signed' if use_signed_url else 'public'} URL: {str(e)}")
        raise

class SupabaseManager:
    """Manages all Supabase database operations for the Legal NLP Pipeline"""
    
    def __init__(self):
        """Initialize Supabase client with error handling"""
        try:
            self.url = os.getenv("SUPABASE_URL")
            self.key = os.getenv("SUPABASE_ANON_KEY")
            self.service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            
            if not self.url or not self.key:
                raise ValueError("Missing SUPABASE_URL or SUPABASE_ANON_KEY environment variables")
            
            self.client: Client = create_client(self.url, self.key)
            
            # Create service role client for operations requiring elevated permissions
            if self.service_role_key:
                self.service_client: Client = create_client(self.url, self.service_role_key)
                logger.info("Service role client initialized for elevated operations")
            else:
                self.service_client = self.client
                logger.warning("SUPABASE_SERVICE_ROLE_KEY not found, using anon key for all operations")
            
            logger.info(f"Supabase client initialized successfully for URL: {self.url}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {str(e)}")
            raise
    
    # === Project Management ===
    
    def get_or_create_project(self, project_id: str, name: str = "Default Project") -> Tuple[Optional[ProjectModel], int, str]:
        """
        Get existing project or create new one if it doesn't exist.
        
        Args:
            project_id: Project identifier (will be converted to UUID if needed)
            name: Project name for new projects
            
        Returns:
            Tuple of (ProjectModel, sql_id, project_uuid)
        """
        logger.info(f"Checking for project: {project_id}")
        
        try:
            # Check if project exists using projectId (per schema)
            response = self.client.table('projects').select('*').eq('projectId', project_id).execute()
            
            if response.data:
                # Create ProjectModel from existing data
                project_data = response.data[0]
                try:
                    project_model = create_model_from_db(ProjectModel, project_data)
                    logger.info(f"Using existing project with ID: {project_model.id}")
                    return project_model, project_model.id, project_model.project_id
                except ValidationError as e:
                    logger.warning(f"Validation error for existing project data: {e}")
                    # Fall back to raw data access for backwards compatibility
                    project_id_sql = project_data['id']
                    project_uuid = project_data['projectId']
                    logger.info(f"Using existing project with ID: {project_id_sql} (validation failed)")
                    return None, project_id_sql, project_uuid
            
            # Create new project with UUID format that matches check constraint
            project_uuid = project_id if self._is_valid_uuid(project_id) else str(uuid.uuid4())
            
            # Create ProjectModel for validation
            project_model = ProjectModel(
                project_id=project_uuid,
                name=name,
                script_run_count=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            # Convert to dict for database insertion
            project_dict = project_model.model_dump(by_alias=True, exclude={'id', 'created_at', 'updated_at'}, mode='json')
            
            # Remove processedByScripts if it's being included incorrectly
            if 'processedByScripts' in project_dict and project_dict['processedByScripts'] is False:
                project_dict.pop('processedByScripts', None)
            
            response = self.client.table('projects').insert(project_dict).execute()
            
            # Update model with the returned ID
            project_data = response.data[0]
            project_model = create_model_from_db(ProjectModel, project_data)
            
            logger.info(f"Created new project with SQL ID: {project_model.id}, UUID: {project_model.project_id}")
            return project_model, project_model.id, project_model.project_id
            
        except Exception as e:
            logger.error(f"Error in get_or_create_project: {str(e)}")
            raise
    
    # === Source Document Management ===
    
    def create_source_document_entry(self, project_fk_id: int, project_uuid: str, 
                                    original_file_path: str, original_file_name: str, 
                                    detected_file_type: str) -> Tuple[SourceDocumentModel, int, str]:
        """
        Create a new source document entry.
        
        Args:
            project_fk_id: Foreign key to projects table
            project_uuid: Project UUID for linking
            original_file_path: Path to the original file
            original_file_name: Name of the original file
            detected_file_type: Type of file detected
            
        Returns:
            Tuple of (SourceDocumentModel, sql_id, document_uuid)
        """
        logger.info(f"Creating source document entry for: {original_file_name}")
        
        try:
            # Create SourceDocumentModel for validation
            document_model = SourceDocumentModel(
                document_uuid=None,  # Will be auto-generated by validator
                project_fk_id=project_fk_id,
                project_uuid=project_uuid,
                original_file_path=original_file_path,
                original_file_name=original_file_name,
                detected_file_type=detected_file_type,
                initial_processing_status=ProcessingStatus.PENDING_INTAKE,
                intake_timestamp=datetime.now(timezone.utc)
            )
            
            # Convert to dict for database insertion
            document_dict = document_model.model_dump(by_alias=False, exclude={'id', 'created_at', 'updated_at'}, mode='json')
            
            response = self.client.table('source_documents').insert(document_dict).execute()
            
            # Create model from returned data
            document_data = response.data[0]
            document_model = create_model_from_db(SourceDocumentModel, document_data)
            
            logger.info(f"Created source document with SQL ID: {document_model.id}, UUID: {document_model.document_uuid}")
            return document_model, document_model.id, document_model.document_uuid
            
        except Exception as e:
            logger.error(f"Error creating source document: {str(e)}")
            raise
    
    def update_source_document_text(self, source_doc_sql_id: int, raw_text: str, 
                                   ocr_meta_json: Optional[Dict] = None, 
                                   status: str = "ocr_complete") -> None:
        """Update source document with extracted text and metadata"""
        logger.info(f"Updating source document {source_doc_sql_id} with OCR results")
        
        try:
            # Validate update data against SourceDocumentModel fields
            # Create a partial model to validate just the fields we're updating
            validation_data = {
                'raw_extracted_text': raw_text,
                'initial_processing_status': status
            }
            
            # Validate status is valid ProcessingStatus
            try:
                ProcessingStatus(status)
            except ValueError:
                logger.warning(f"Invalid processing status: {status}, using 'ocr_complete'")
                status = "ocr_complete"
                validation_data['initial_processing_status'] = status
            
            update_data = validation_data.copy()
            
            if ocr_meta_json:
                # Ensure OCR metadata is properly formatted
                if isinstance(ocr_meta_json, str):
                    try:
                        ocr_meta_json = json.loads(ocr_meta_json)
                    except json.JSONDecodeError:
                        logger.warning("Invalid OCR metadata JSON string, skipping")
                        ocr_meta_json = None
                
                if ocr_meta_json:
                    update_data['ocr_metadata_json'] = json.dumps(ocr_meta_json)
            
            response = self.client.table('source_documents').update(update_data).eq('id', source_doc_sql_id).execute()
            logger.info(f"Updated source document {source_doc_sql_id} with {len(raw_text) if raw_text else 0} characters")
            
        except Exception as e:
            logger.error(f"Error updating source document: {str(e)}")
            # Don't raise the error for now - there's a database trigger issue
            logger.warning(f"Continuing despite database trigger error: {e}")
    
    # === Neo4j Document Management ===
    
    def create_neo4j_document_entry(self, source_doc_fk_id: int, source_doc_uuid: str, 
                                    project_fk_id: int, project_uuid: str, 
                                    file_name: str) -> Tuple[int, str]:
        """Create a neo4j document entry"""
        logger.info(f"Creating neo4j document entry for: {file_name}")
        
        try:
            # Use the passed-in source_doc_uuid as the documentId for neo4j_documents
            doc_uuid = source_doc_uuid  # Key change: doc_uuid IS the source_doc_uuid
            
            # Get storage path from source document
            source_response = self.client.table('source_documents').select('original_file_path').eq('id', source_doc_fk_id).execute()
            storage_path = source_response.data[0]['original_file_path'] if source_response.data else None
            
            document = {
                'documentId': doc_uuid,  # Now uses the source_doc_uuid
                'source_document_fk_id': source_doc_fk_id,
                # 'source_document_uuid': source_doc_uuid,  # REMOVE THIS LINE - column no longer exists
                'project_id': project_fk_id,  # Match schema field name
                'project_uuid': project_uuid,  # Add link via UUID
                'name': file_name,
                'storagePath': storage_path,  # Match schema field name
                'processingStatus': 'pending_metadata',  # Match schema field name
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat()
            }
            
            response = self.client.table('neo4j_documents').insert(document).execute()
            doc_id = response.data[0]['id']
            logger.info(f"Created neo4j document with SQL ID: {doc_id}, UUID: {doc_uuid}")
            return doc_id, doc_uuid
            
        except Exception as e:
            logger.error(f"Error creating neo4j document: {str(e)}")
            raise
    
    def update_neo4j_document_details(self, neo4j_doc_sql_id: int, category: Optional[str] = None,
                                     file_type: Optional[str] = None, cleaned_text: Optional[str] = None,
                                     status: Optional[str] = None, metadata_json: Optional[Dict] = None) -> None:
        """Update neo4j document with processing details"""
        logger.info(f"Updating neo4j document {neo4j_doc_sql_id}")
        
        try:
            update_data = {'updatedAt': datetime.now().isoformat()}
            
            if category is not None:
                update_data['category'] = category
            if file_type is not None:
                update_data['fileType'] = file_type  # Match schema field name
            if cleaned_text is not None:
                update_data['cleaned_text_for_chunking'] = cleaned_text
            if status is not None:
                update_data['processingStatus'] = status  # Match schema field name
            if metadata_json is not None:
                # Convert to string if it's not already
                if isinstance(metadata_json, dict):
                    update_data['metadata_json'] = json.dumps(metadata_json)
                else:
                    update_data['metadata_json'] = metadata_json
            
            response = self.client.table('neo4j_documents').update(update_data).eq('id', neo4j_doc_sql_id).execute()
            logger.info(f"Updated neo4j document {neo4j_doc_sql_id}")
            
        except Exception as e:
            logger.error(f"Error updating neo4j document: {str(e)}")
            raise
    
    def update_neo4j_document_status(self, neo4j_doc_sql_id: int, status: str) -> None:
        """Update only the processing status of a neo4j document"""
        logger.info(f"Updating neo4j document {neo4j_doc_sql_id} status to {status}")
        
        try:
            update_data = {
                'processingStatus': status,  # Match schema field name
                'updatedAt': datetime.now().isoformat()
            }
            
            response = self.client.table('neo4j_documents').update(update_data).eq('id', neo4j_doc_sql_id).execute()
            logger.info(f"Updated neo4j document {neo4j_doc_sql_id} status to {status}")
            
        except Exception as e:
            logger.error(f"Error updating neo4j document status: {str(e)}")
            raise
    
    # === Chunk Management ===
    
    def create_chunk_entry(self, document_fk_id: int, document_uuid: str, 
                          chunk_index: int, text_content: str,
                          cleaned_text: Optional[str] = None,
                          char_start_index: Optional[int] = None,
                          char_end_index: Optional[int] = None,
                          metadata_json: Optional[Dict] = None) -> Tuple[int, str]:
        """Create a chunk entry"""
        logger.info(f"Creating chunk {chunk_index} for document {document_fk_id}")
        
        try:
            # Generate UUID that matches the schema's CHECK constraint
            chunk_uuid = str(uuid.uuid4())
            
            chunk = {
                'chunkId': chunk_uuid,  # Match schema field name
                'document_id': document_fk_id,
                'document_uuid': document_uuid,  # Add link via UUID
                'chunkIndex': chunk_index,  # Match schema field name
                'text': text_content,  # Match schema field name
                'cleanedText': cleaned_text or text_content,  # Match schema field name
                'processingStatus': 'pending_ner',  # Match schema field name
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat()
            }
            
            # Add optional fields
            if char_start_index is not None:
                chunk['char_start_index'] = char_start_index
            if char_end_index is not None:
                chunk['char_end_index'] = char_end_index
            if metadata_json is not None:
                # Convert to string if it's not already
                if isinstance(metadata_json, dict):
                    chunk['metadata_json'] = json.dumps(metadata_json)
                else:
                    chunk['metadata_json'] = metadata_json
            
            response = self.client.table('neo4j_chunks').insert(chunk).execute()
            chunk_id = response.data[0]['id']
            logger.info(f"Created chunk with SQL ID: {chunk_id}, UUID: {chunk_uuid}, index: {chunk_index}")
            return chunk_id, chunk_uuid
            
        except Exception as e:
            logger.error(f"Error creating chunk: {str(e)}")
            raise
    
    # === Entity Management ===
    
    def create_entity_mention_entry(self, chunk_sql_id: int, chunk_uuid: str, 
                                   value: str, entity_type_label: str,
                                   norm_value: Optional[str] = None,
                                   display_value: Optional[str] = None,
                                   rationale: Optional[str] = None,
                                   attributes_json_str: Optional[str] = None,
                                   phone: Optional[str] = None,
                                   email: Optional[str] = None,
                                   start_offset: Optional[int] = None,
                                   end_offset: Optional[int] = None) -> Tuple[int, str]:
        """Create an entity mention entry"""
        logger.info(f"Creating entity mention for chunk {chunk_sql_id}")
        
        try:
            # Generate UUID that matches the schema's CHECK constraint
            mention_uuid = str(uuid.uuid4())
            
            entity_mention = {
                'entityMentionId': mention_uuid,  # Match schema field name
                'chunk_fk_id': chunk_sql_id,
                'chunk_uuid': chunk_uuid,  # Add link via UUID
                'value': value,  # Match schema field name
                'entity_type': entity_type_label,  # Match schema field name
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat()
            }
            
            # Add optional fields if they exist
            if norm_value is not None:
                entity_mention['normalizedValue'] = norm_value  # Match schema field name
            if display_value is not None:
                entity_mention['displayValue'] = display_value  # Match schema field name
            if rationale is not None:
                entity_mention['rationale'] = rationale
            if phone is not None:
                entity_mention['phone'] = phone
            if email is not None:
                entity_mention['email'] = email
            if start_offset is not None:
                entity_mention['start_char_offset_in_chunk'] = start_offset
            if end_offset is not None:
                entity_mention['end_char_offset_in_chunk'] = end_offset
            
            response = self.client.table('neo4j_entity_mentions').insert(entity_mention).execute()
            mention_id = response.data[0]['id']
            logger.info(f"Created entity mention with SQL ID: {mention_id}, UUID: {mention_uuid}")
            return mention_id, mention_uuid
            
        except Exception as e:
            logger.error(f"Error creating entity mention: {str(e)}")
            logger.error(f"Entity mention data that failed: {json.dumps(entity_mention, indent=2)}")
            if hasattr(e, 'response') and hasattr(e.response, 'json'):
                try:
                    error_details = e.response.json()
                    logger.error(f"Supabase error details: {json.dumps(error_details, indent=2)}")
                except:
                    pass
            raise
    
    def create_canonical_entity_entry(self, neo4j_doc_sql_id: int, document_uuid: str,
                                   canonical_name: str, entity_type_label: str,
                                   aliases_json: Optional[List[str]] = None,
                                   mention_count: Optional[int] = None,
                                   first_seen_idx: Optional[int] = None,
                                   emails: Optional[List[str]] = None,
                                   phones: Optional[List[str]] = None,
                                   entity_source: str = "extraction") -> Tuple[int, str]:
        """Create a canonical entity entry"""
        logger.info(f"Creating canonical entity for document {neo4j_doc_sql_id}")
        
        try:
            # Generate UUID that matches the schema's CHECK constraint
            canonical_uuid = str(uuid.uuid4())
            
            canonical_entity = {
                'canonicalEntityId': canonical_uuid,  # Match schema field name
                'documentId': neo4j_doc_sql_id,  # Match schema field name 
                'document_uuid': document_uuid,  # Add link via UUID
                'canonicalName': canonical_name,  # Match schema field name
                'entity_type': entity_type_label,  # Match schema field name
                'entity_source': entity_source,
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat()
            }
            
            # Add optional fields
            if aliases_json:
                canonical_entity['allKnownAliasesInDoc'] = aliases_json if isinstance(aliases_json, str) else json.dumps(aliases_json)  # Match schema field name
            
            if mention_count is not None:
                canonical_entity['mention_count'] = mention_count
                
            if first_seen_idx is not None:
                canonical_entity['firstSeenAtChunkIndex'] = first_seen_idx  # Match schema field name
                
            if emails:
                canonical_entity['emails'] = emails if isinstance(emails, str) else json.dumps(emails)  # Match schema field name
                
            if phones:
                canonical_entity['phones'] = phones if isinstance(phones, str) else json.dumps(phones)  # Match schema field name
            
            response = self.client.table('neo4j_canonical_entities').insert(canonical_entity).execute()
            entity_id = response.data[0]['id']
            logger.info(f"Created canonical entity with SQL ID: {entity_id}, UUID: {canonical_uuid}")
            return entity_id, canonical_uuid
            
        except Exception as e:
            logger.error(f"Error creating canonical entity: {str(e)}")
            raise
    
    def update_entity_mention_with_canonical_id(self, em_sql_id: int, canonical_entity_neo4j_uuid: str) -> None:
        """Update entity mention with its resolved canonical entity ID (for relationships)"""
        logger.info(f"Updating entity mention {em_sql_id} with canonical entity ID {canonical_entity_neo4j_uuid}")
        
        try:
            # We don't directly store the canonical entity ID in the entity mention table
            # This is handled through the relationships_staging table instead
            # This is a placeholder for future implementation if needed
            pass
            
        except Exception as e:
            logger.error(f"Error updating entity mention: {str(e)}")
            raise
    
    # === Relationship Management ===
    
    def create_relationship_staging(self, from_node_id: str, from_node_label: str,
                                   to_node_id: str, to_node_label: str,
                                   relationship_type: str, properties: Optional[Dict] = None) -> int:
        """Create a relationship staging entry"""
        logger.info(f"Creating relationship: {from_node_label}({from_node_id}) -[{relationship_type}]-> {to_node_label}({to_node_id})")
        
        try:
            relationship = {
                'fromNodeId': from_node_id,  # Match existing schema
                'fromNodeLabel': from_node_label,  # Match existing schema
                'toNodeId': to_node_id,  # Match existing schema
                'toNodeLabel': to_node_label,  # Match existing schema
                'relationshipType': relationship_type,  # Match existing schema
                'batchProcessId': str(uuid.uuid4()),  # Match existing schema
                'createdAt': datetime.now().isoformat()  # Match existing schema
            }
            
            # Add properties as JSONB if provided
            if properties:
                relationship['properties'] = properties if isinstance(properties, str) else json.dumps(properties)  # Match schema field name
            
            response = self.service_client.table('neo4j_relationships_staging').insert(relationship).execute()
            rel_id = response.data[0]['id']
            logger.info(f"Created relationship staging with SQL ID: {rel_id}")
            return rel_id
            
        except Exception as e:
            logger.error(f"Error creating relationship: {str(e)}")
            raise
    
    # === Helper Methods ===
    
    def _is_valid_uuid(self, val: str) -> bool:
        """Check if a string is a valid UUID format"""
        try:
            uuid_obj = uuid.UUID(str(val))
            return str(uuid_obj) == val
        except (ValueError, AttributeError, TypeError):
            return False
    
    def get_public_url_for_document(self, file_path: str) -> str:
        """
        Generate a public URL for a file in Supabase Storage.
        
        Args:
            file_path: Path to the file in the Storage bucket
            
        Returns:
            Public URL for accessing the file
        """
        # Check if file_path is already a fully qualified path
        if file_path.startswith("http://") or file_path.startswith("https://"):
            return file_path
            
        logger.info(f"Generating public URL for file: {file_path}")
        
        try:
            # Check if file_path includes the bucket name
            parts = file_path.split('/')
            
            # Default bucket is 'documents' per upload.js
            bucket = 'documents'
            path = file_path
            
            # If file_path starts with a bucket name, extract it
            if len(parts) > 1 and parts[0] in ['documents', 'uploads']:
                bucket = parts[0]
                path = '/'.join(parts[1:])
            
            # Get the Supabase Storage URL for this file
            storage_response = self.client.storage.from_(bucket).get_public_url(path)
            
            public_url = storage_response
            
            logger.info(f"Generated public URL: {public_url}")
            return public_url
            
        except Exception as e:
            logger.error(f"Error generating public URL: {str(e)}")
            raise
    
    def get_project_by_sql_id_or_global_project_id(self, project_sql_id_param, global_project_id_config):
        """Get project UUID either by SQL ID or by global project ID"""
        logger.info(f"Looking up project UUID for SQL ID: {project_sql_id_param} or Global ID: {global_project_id_config}")
        
        try:
            if project_sql_id_param:
                response = self.client.table('projects').select('projectId').eq('id', project_sql_id_param).execute()
                if response.data:
                    logger.info(f"Found project UUID by SQL ID: {response.data[0]['projectId']}")
                    return response.data[0]['projectId']
            
            # Fallback to global project ID if specific not found or not given
            response = self.client.table('projects').select('projectId').eq('projectId', global_project_id_config).execute()
            if response.data:
                logger.info(f"Found project UUID by Global ID: {response.data[0]['projectId']}")
                return response.data[0]['projectId']
            
            logger.error(f"Could not find project UUID for SQL ID {project_sql_id_param} or Global ID {global_project_id_config}")
            return None
        
        except Exception as e:
            logger.error(f"Error in get_project_by_sql_id_or_global_project_id: {str(e)}")
            return None
            
    # === Batch Operations and Queries ===
    
    def get_pending_documents(self, limit: int = 50) -> List[Dict]:
        """Get documents pending processing"""
        logger.info(f"Fetching up to {limit} pending documents")
        
        try:
            response = self.client.table('source_documents')\
                .select('*')\
                .eq('initial_processing_status', 'pending_intake')\
                .limit(limit)\
                .execute()
            
            logger.info(f"Found {len(response.data)} pending documents")
            return response.data
            
        except Exception as e:
            logger.error(f"Error fetching pending documents: {str(e)}")
            raise
    
    def get_documents_for_entity_extraction(self, limit: int = 20) -> List[Dict]:
        """Get documents for entity extraction using separate API calls (replaced RPC call)"""
        logger.info(f"Fetching documents for entity extraction")
        
        try:
            # Get documents ready for entity extraction using Supabase API
            docs_response = self.client.table('neo4j_documents')\
                .select('*')\
                .eq('processingStatus', 'pending_entities')\
                .limit(limit)\
                .execute()
            
            documents_with_chunks = []
            for doc in docs_response.data:
                # Get chunks for each document using separate API call
                chunks_response = self.client.table('neo4j_chunks')\
                    .select('*')\
                    .eq('document_id', doc['id'])\
                    .order('chunkIndex', desc=False)\
                    .execute()
                
                # Add chunks to document structure (matching original query format)
                doc['chunks'] = chunks_response.data
                documents_with_chunks.append(doc)
            
            logger.info(f"Found {len(documents_with_chunks)} documents for entity extraction")
            return documents_with_chunks
            
        except Exception as e:
            logger.error(f"Error fetching documents for entity extraction: {str(e)}")
            raise
    
    def update_processing_status(self, table: str, record_id: int, status: str) -> None:
        """Update processing status for any table"""
        logger.info(f"Updating {table} ID {record_id} status to: {status}")
        
        try:
            # Use the correct column name based on the table
            if table == 'neo4j_documents':
                status_field = 'processingStatus'  # Match schema field name
                update_data = {
                    status_field: status,
                    'updatedAt': datetime.now().isoformat()
                }
            elif table == 'neo4j_chunks':
                status_field = 'processingStatus'  # Match schema field name 
                update_data = {
                    status_field: status,
                    'updatedAt': datetime.now().isoformat()
                }
            else:  # source_documents or other tables
                status_field = 'initial_processing_status'  # Keep original name
                update_data = {
                    status_field: status
                }
            
            response = self.client.table(table).update(update_data).eq('id', record_id).execute()
            logger.info(f"Updated {table} ID {record_id} status to {status}")
            
        except Exception as e:
            logger.error(f"Error updating status: {str(e)}")
            raise
    
    # === Error Handling ===
    
    def log_processing_error(self, table: str, record_id: int, error_message: str) -> None:
        """Log processing error to database"""
        logger.error(f"Processing error for {table} ID {record_id}: {error_message}")
        
        try:
            # Use the correct column names based on the table
            update_data = {
                'error_message': error_message
            }
            
            if table == 'source_documents':
                update_data['initial_processing_status'] = 'error'
            elif table == 'neo4j_documents':
                update_data['processingStatus'] = 'error'  # Match schema field name
                update_data['updatedAt'] = datetime.now().isoformat()
            elif table == 'neo4j_chunks':
                update_data['processingStatus'] = 'error'  # Match schema field name
                update_data['updatedAt'] = datetime.now().isoformat()
            
            response = self.client.table(table).update(update_data).eq('id', record_id).execute()
            
        except Exception as e:
            logger.error(f"Failed to log error to database: {str(e)}")
    
    # === Additional Utility Methods ===
    
    def update_chunk_metadata(self, chunk_sql_id: int, metadata_json: Dict) -> bool:
        """
        Update the metadata of a chunk in the database.
        
        Args:
            chunk_sql_id: SQL ID of the chunk
            metadata_json: Metadata as a dictionary or JSON string
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Updating metadata for chunk {chunk_sql_id}")
        
        try:
            update_data = {
                'metadata_json': metadata_json if isinstance(metadata_json, str) else json.dumps(metadata_json),
                'updatedAt': datetime.now().isoformat()
            }
            
            response = self.client.table('neo4j_chunks').update(update_data).eq('id', chunk_sql_id).execute()
            
            if response.data:
                logger.info(f"Updated metadata for chunk {chunk_sql_id}")
                return True
            else:
                logger.warning(f"No chunk found with ID {chunk_sql_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating chunk metadata: {str(e)}")
            return False
    
    def get_document_by_id(self, doc_id: int) -> Optional[Dict]:
        """Get a single document by ID"""
        try:
            response = self.client.table('source_documents')\
                .select('*')\
                .eq('id', doc_id)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            logger.error(f"Error getting document by ID: {str(e)}")
            return None
    
    # === Textract Job Management ===
    
    def create_textract_job_entry(self, source_document_id: int, document_uuid: str, job_id: str,
                                 s3_input_bucket: str, s3_input_key: str,
                                 job_type: str = 'DetectDocumentText',
                                 feature_types: Optional[List[str]] = None,
                                 s3_output_bucket: Optional[str] = None,
                                 s3_output_key: Optional[str] = None,
                                 confidence_threshold: Optional[float] = None,
                                 client_request_token: Optional[str] = None,
                                 job_tag: Optional[str] = None,
                                 sns_topic_arn: Optional[str] = None) -> Optional[int]:
        """Creates an entry in the textract_jobs table."""
        from config import TEXTRACT_CONFIDENCE_THRESHOLD, TEXTRACT_SNS_TOPIC_ARN
        
        logger.info(f"Creating Textract job entry for source_doc_id: {source_document_id}, job_id: {job_id}")
        job_data = {
            'source_document_id': source_document_id,
            'document_uuid': document_uuid,
            'job_id': job_id,
            'job_type': job_type,
            's3_input_bucket': s3_input_bucket,
            's3_input_key': s3_input_key,
            'job_status': 'submitted',  # Initial status
            'confidence_threshold': confidence_threshold or TEXTRACT_CONFIDENCE_THRESHOLD,
            'client_request_token': client_request_token,
            'job_tag': job_tag,
            'sns_topic_arn': sns_topic_arn or TEXTRACT_SNS_TOPIC_ARN,
            'started_at': datetime.now().isoformat()  # Record submission time as started_at for now
        }
        if feature_types:
            job_data['feature_types'] = feature_types
        if s3_output_bucket:
            job_data['s3_output_bucket'] = s3_output_bucket
        if s3_output_key:
            job_data['s3_output_key'] = s3_output_key
        
        try:
            response = self.client.table('textract_jobs').insert(job_data).execute()
            if response.data:
                return response.data[0]['id']
            logger.error(f"Failed to insert Textract job entry, response: {response.error if response.error else 'No data returned'}")
            return None
        except Exception as e:
            logger.error(f"Error creating Textract job entry: {e}", exc_info=True)
            # Don't raise for now - database constraint issue
            logger.warning(f"Continuing despite Textract job table error: {e}")
            return None
    
    def update_textract_job_status(self, job_id: str, job_status: str,
                                   page_count: Optional[int] = None,
                                   processed_pages: Optional[int] = None,
                                   avg_confidence: Optional[float] = None,
                                   warnings_json: Optional[Dict] = None,
                                   error_message: Optional[str] = None,
                                   s3_output_key: Optional[str] = None,
                                   completed_at_override: Optional[datetime] = None) -> bool:
        """Updates an existing entry in the textract_jobs table."""
        # Map AWS status to database enum
        status_mapping = {
            'SUBMITTED': 'submitted',
            'IN_PROGRESS': 'in_progress',
            'SUCCEEDED': 'succeeded',
            'FAILED': 'failed',
            'PARTIAL_SUCCESS': 'partial_success'
        }
        
        # Normalize status
        normalized_status = status_mapping.get(job_status.upper(), job_status.lower())
        
        logger.info(f"Updating Textract job_id: {job_id} to status: {normalized_status}")
        update_data = {'job_status': normalized_status}
        if page_count is not None:
            update_data['page_count'] = page_count
        if processed_pages is not None:
            update_data['processed_pages'] = processed_pages
        if avg_confidence is not None:
            update_data['avg_confidence'] = avg_confidence
        if warnings_json:
            update_data['warnings'] = warnings_json  # Assumes JSONB column
        if error_message:
            update_data['error_message'] = error_message
        if s3_output_key:  # If Textract saves output to S3
            update_data['s3_output_key'] = s3_output_key
            
        if normalized_status in ['succeeded', 'failed', 'partial_success']:
            update_data['completed_at'] = (completed_at_override or datetime.now()).isoformat()

        try:
            response = self.client.table('textract_jobs').update(update_data).eq('job_id', job_id).execute()
            # Check if response indicates success (e.g., response.data is not empty or response.error is None)
            if response.data or not response.error:  # Supabase returns list of updated rows or empty list if no match
                logger.info(f"Textract job {job_id} updated successfully.")
                return True
            logger.warning(f"Failed to update Textract job {job_id} or job not found. Response error: {response.error}")
            return False
        except Exception as e:
            logger.error(f"Error updating Textract job entry for job_id {job_id}: {e}", exc_info=True)
            # Don't raise for now - database constraint issue
            logger.warning(f"Continuing despite Textract job table error: {e}")
            return False
    
    def get_textract_job_by_job_id(self, job_id: str) -> Optional[Dict]:
        """Retrieves a Textract job entry by its job_id."""
        try:
            response = self.client.table('textract_jobs').select('*').eq('job_id', job_id).maybe_single().execute()
            return response.data
        except Exception as e:
            logger.error(f"Error fetching Textract job by job_id {job_id}: {e}", exc_info=True)
            return None
    
    def update_source_document_with_textract_outcome(self, source_doc_sql_id: int,
                                                     textract_job_id: str,
                                                     textract_job_status: str,  # From the new field in source_documents
                                                     ocr_provider_enum: str = 'textract',  # Value for ocr_provider type
                                                     raw_text: Optional[str] = None,
                                                     ocr_metadata: Optional[Dict] = None,  # This is Textract's page-level metadata
                                                     textract_warnings_json: Optional[Dict] = None,
                                                     textract_confidence: Optional[float] = None,
                                                     textract_output_s3_key_val: Optional[str] = None,
                                                     job_started_at: Optional[datetime] = None,
                                                     job_completed_at: Optional[datetime] = None):
        """Updates source_documents table with results from Textract processing."""
        logger.info(f"Updating source_document {source_doc_sql_id} with Textract job ({textract_job_id}) outcome: {textract_job_status}")
        
        # Map AWS status to database enum
        status_mapping = {
            'SUBMITTED': 'submitted',
            'IN_PROGRESS': 'in_progress', 
            'SUCCEEDED': 'succeeded',
            'FAILED': 'failed',
            'PARTIAL_SUCCESS': 'partial_success'
        }
        
        # Normalize status
        normalized_status = status_mapping.get(textract_job_status.upper(), textract_job_status.lower())
        
        update_payload = {
            'textract_job_id': textract_job_id,
            'textract_job_status': normalized_status,
            'ocr_provider': ocr_provider_enum,
            'last_modified_at': datetime.now(timezone.utc).isoformat()  # Use timezone-aware datetime
        }
        if raw_text is not None:  # Only update if text was successfully extracted
            update_payload['raw_extracted_text'] = raw_text
            update_payload['initial_processing_status'] = 'ocr_complete_pending_doc_node'  # Assuming success if raw_text is present
        elif textract_job_status == 'failed':
            update_payload['initial_processing_status'] = 'extraction_failed'

        if ocr_metadata:
            update_payload['ocr_metadata_json'] = json.dumps(ocr_metadata)
        if textract_warnings_json:
            update_payload['textract_warnings'] = textract_warnings_json  # Assumes JSONB
        if textract_confidence is not None:
            update_payload['textract_confidence_avg'] = textract_confidence
        if textract_output_s3_key_val:
            update_payload['textract_output_s3_key'] = textract_output_s3_key_val
        
        if job_started_at:
            update_payload['textract_job_started_at'] = job_started_at.isoformat()
        if job_completed_at:
            update_payload['textract_job_completed_at'] = job_completed_at.isoformat()
            update_payload['ocr_completed_at'] = job_completed_at.isoformat()  # General OCR completion
            if job_started_at:  # Calculate duration if both are present
                try:
                    # Ensure both are timezone-aware
                    if job_started_at.tzinfo is None:
                        job_started_at = job_started_at.replace(tzinfo=timezone.utc)
                    if job_completed_at.tzinfo is None:
                        job_completed_at = job_completed_at.replace(tzinfo=timezone.utc)
                        
                    duration = (job_completed_at - job_started_at).total_seconds()
                    update_payload['ocr_processing_seconds'] = max(0, int(duration))
                except Exception as e:
                    # Handle timezone mismatch or other errors
                    logger.warning(f"Could not calculate duration: {e}")
        
        # Retry logic for transient database errors
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                self.client.table('source_documents').update(update_payload).eq('id', source_doc_sql_id).execute()
                logger.info(f"Source_document {source_doc_sql_id} updated with Textract info (attempt {attempt + 1})")
                return True
            except Exception as e:
                if 'record "new" has no field "status"' in str(e):
                    logger.error(f"Trigger error detected: {e}")
                    # Don't retry trigger errors
                    return False
                elif attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                    logger.warning(f"Retry {attempt + 1}/{max_retries} after error: {e}. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to update after {max_retries} attempts: {e}")
                    return False
    
    # === Database Cleanup Methods ===
    
    def cleanup_all_data(self, confirm: bool = False) -> Dict[str, int]:
        """
        Complete cleanup of all data in the database.
        
        WARNING: This will permanently delete ALL data from ALL tables!
        
        Args:
            confirm: Must be True to actually perform the deletion
            
        Returns:
            Dictionary with table names and number of rows deleted
        """
        if not confirm:
            raise ValueError("You must pass confirm=True to delete all data. This action cannot be undone!")
        
        logger.warning("Starting complete database cleanup - ALL DATA WILL BE DELETED!")
        
        deletion_counts = {}
        
        # Tables in correct deletion order (child tables first)
        tables_to_clean = [
            # Dependent tables first
            'neo4j_relationships_staging',
            'neo4j_entity_mentions',
            'neo4j_chunks',
            'neo4j_canonical_entities',
            'document_processing_history',
            'document_processing_queue',
            'textract_jobs',
            # Main document tables
            'neo4j_documents',
            'source_documents',
            # Parent table last
            'projects'
        ]
        
        for table in tables_to_clean:
            try:
                # Use service client for tables with RLS
                client = self.service_client if table in ['neo4j_relationships_staging'] else self.client
                
                # Get count before deletion
                count_result = client.table(table).select('*', count='exact').execute()
                initial_count = count_result.count if hasattr(count_result, 'count') else len(count_result.data)
                
                # Delete all rows
                if initial_count > 0:
                    # For large tables, delete in batches to avoid timeouts
                    if initial_count > 1000:
                        logger.info(f"Deleting {initial_count} rows from {table} in batches...")
                        deleted = 0
                        while deleted < initial_count:
                            # Get a batch of IDs
                            batch = client.table(table).select('id').limit(500).execute()
                            if not batch.data:
                                break
                            
                            batch_ids = [row['id'] for row in batch.data]
                            client.table(table).delete().in_('id', batch_ids).execute()
                            deleted += len(batch_ids)
                            logger.info(f"  Deleted {deleted}/{initial_count} from {table}")
                    else:
                        # Small table - delete all at once
                        client.table(table).delete().gte('id', 0).execute()
                    
                    deletion_counts[table] = initial_count
                    logger.info(f"✓ Deleted {initial_count} rows from {table}")
                else:
                    deletion_counts[table] = 0
                    logger.info(f"✓ {table} was already empty")
                    
            except Exception as e:
                logger.error(f"❌ Error cleaning {table}: {str(e)}")
                deletion_counts[table] = -1
        
        # Clear any Redis cache if available
        try:
            from redis_utils import get_redis_manager
            redis_mgr = get_redis_manager()
            if redis_mgr and redis_mgr.is_available():
                redis_mgr.redis_client.flushdb()
                logger.info("✓ Cleared Redis cache")
        except Exception as e:
            logger.warning(f"Could not clear Redis cache: {e}")
        
        total_deleted = sum(c for c in deletion_counts.values() if c > 0)
        logger.info(f"\nDatabase cleanup complete! Deleted {total_deleted} total rows across {len(tables_to_clean)} tables.")
        
        return deletion_counts
    
    def cleanup_project_data(self, project_id: str) -> Dict[str, int]:
        """
        Clean up all data for a specific project.
        
        Args:
            project_id: Project UUID to clean up
            
        Returns:
            Dictionary with table names and number of rows deleted
        """
        logger.info(f"Starting cleanup for project: {project_id}")
        
        deletion_counts = {}
        
        try:
            # First, get all document UUIDs for this project
            docs_result = self.client.table('source_documents').select('document_uuid').eq('project_uuid', project_id).execute()
            doc_uuids = [doc['document_uuid'] for doc in docs_result.data]
            
            if not doc_uuids:
                logger.info("No documents found for this project")
                return deletion_counts
            
            logger.info(f"Found {len(doc_uuids)} documents to clean up")
            
            # Get neo4j document IDs
            neo4j_docs = self.client.table('neo4j_documents').select('documentId').in_('documentId', doc_uuids).execute()
            neo4j_doc_uuids = [doc['documentId'] for doc in neo4j_docs.data]
            
            # Clean up in correct order
            # 1. Relationships
            if neo4j_doc_uuids:
                rel_result = self.service_client.table('neo4j_relationships_staging').delete().in_('fromNodeId', neo4j_doc_uuids).execute()
                deletion_counts['neo4j_relationships_staging'] = len(rel_result.data)
            
            # 2. Entity mentions (get chunk UUIDs first)
            if neo4j_doc_uuids:
                chunks_result = self.client.table('neo4j_chunks').select('chunkId').in_('document_uuid', doc_uuids).execute()
                chunk_uuids = [chunk['chunkId'] for chunk in chunks_result.data]
                
                if chunk_uuids:
                    mentions_result = self.client.table('neo4j_entity_mentions').delete().in_('chunk_uuid', chunk_uuids).execute()
                    deletion_counts['neo4j_entity_mentions'] = len(mentions_result.data)
            
            # 3. Chunks
            chunks_result = self.client.table('neo4j_chunks').delete().in_('document_uuid', doc_uuids).execute()
            deletion_counts['neo4j_chunks'] = len(chunks_result.data)
            
            # 4. Processing queue
            queue_result = self.client.table('document_processing_queue').delete().in_('document_id', doc_uuids).execute()
            deletion_counts['document_processing_queue'] = len(queue_result.data)
            
            # 5. Textract jobs
            textract_result = self.client.table('textract_jobs').delete().in_('document_uuid', doc_uuids).execute()
            deletion_counts['textract_jobs'] = len(textract_result.data)
            
            # 6. Neo4j documents
            neo4j_result = self.client.table('neo4j_documents').delete().in_('documentId', doc_uuids).execute()
            deletion_counts['neo4j_documents'] = len(neo4j_result.data)
            
            # 7. Source documents
            source_result = self.client.table('source_documents').delete().in_('document_uuid', doc_uuids).execute()
            deletion_counts['source_documents'] = len(source_result.data)
            
            # Note: We don't delete the project itself or canonical entities (they may be shared)
            
            total_deleted = sum(deletion_counts.values())
            logger.info(f"Project cleanup complete! Deleted {total_deleted} total rows.")
            
        except Exception as e:
            logger.error(f"Error during project cleanup: {e}")
            raise
        
        return deletion_counts
    
    # === Image Processing Helper Methods ===
    
    def update_image_processing_status(self, document_uuid: str, status: str, 
                                     confidence_score: float = None, 
                                     image_type: str = None,
                                     error_details: str = None) -> bool:
        """
        Update image processing status and metadata.
        
        Args:
            document_uuid: UUID of the document
            status: Processing status (image_queued, image_processing, image_completed, image_failed)
            confidence_score: Analysis confidence (0.0-1.0)
            image_type: Detected image type
            error_details: Error message if processing failed
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            update_data = {
                'celery_status': status,
                'last_modified_at': datetime.now().isoformat()
            }
            
            if confidence_score is not None:
                update_data['image_analysis_confidence'] = confidence_score
                
            if image_type is not None:
                update_data['image_type'] = image_type
                
            if error_details is not None:
                update_data['error_details'] = error_details
            
            response = self.client.table('source_documents').update(update_data).eq(
                'document_uuid', document_uuid
            ).execute()
            
            if response.data:
                logger.info(f"Updated image processing status for {document_uuid}: {status}")
                return True
            else:
                logger.warning(f"No document found with UUID {document_uuid}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to update image processing status: {e}")
            return False
    
    def store_image_processing_result(self, document_uuid: str, extracted_text: str,
                                    processing_metadata: Dict) -> bool:
        """
        Store complete image processing result in database.
        
        Args:
            document_uuid: UUID of the document
            extracted_text: Generated description from o4-mini
            processing_metadata: Complete processing metadata
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            update_data = {
                'extracted_text': extracted_text,
                'celery_status': 'image_completed',
                'initial_processing_status': 'image_completed',
                'image_analysis_confidence': processing_metadata.get('confidence_score', 0.0),
                'image_type': processing_metadata.get('image_type', 'unknown'),
                'o4_mini_tokens_used': processing_metadata.get('total_tokens', 0),
                'o4_mini_input_tokens': processing_metadata.get('input_tokens', 0),
                'o4_mini_output_tokens': processing_metadata.get('output_tokens', 0),
                'image_processing_cost': processing_metadata.get('estimated_cost', 0.0),
                'image_description_length': len(extracted_text),
                'last_modified_at': datetime.now().isoformat()
            }
            
            response = self.client.table('source_documents').update(update_data).eq(
                'document_uuid', document_uuid
            ).execute()
            
            if response.data:
                logger.info(f"Stored image processing result for {document_uuid}")
                return True
            else:
                logger.warning(f"No document found with UUID {document_uuid}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to store image processing result: {e}")
            return False
    
    def get_image_processing_costs(self, project_id: int = None, 
                                 start_date: datetime = None) -> Dict[str, float]:
        """
        Calculate image processing costs for o4-mini usage.
        
        Args:
            project_id: Optional project ID to filter by
            start_date: Optional start date to filter by
            
        Returns:
            dict: Cost breakdown and totals
        """
        try:
            query = self.client.table('source_documents').select(
                'image_processing_cost, o4_mini_tokens_used, o4_mini_input_tokens, o4_mini_output_tokens'
            ).eq('file_category', 'image').not_.is_('image_processing_cost', 'null')
            
            if project_id:
                query = query.eq('project_fk_id', project_id)
            
            if start_date:
                query = query.gte('created_at', start_date.isoformat())
                
            response = query.execute()
            
            total_cost = 0.0
            total_tokens = 0
            total_input_tokens = 0
            total_output_tokens = 0
            document_count = len(response.data)
            
            for doc in response.data:
                total_cost += doc.get('image_processing_cost', 0.0)
                total_tokens += doc.get('o4_mini_tokens_used', 0)
                total_input_tokens += doc.get('o4_mini_input_tokens', 0)
                total_output_tokens += doc.get('o4_mini_output_tokens', 0)
            
            return {
                'total_cost': round(total_cost, 6),
                'average_cost_per_image': round(total_cost / document_count, 6) if document_count > 0 else 0.0,
                'total_tokens': total_tokens,
                'total_input_tokens': total_input_tokens,
                'total_output_tokens': total_output_tokens,
                'document_count': document_count
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate image processing costs: {e}")
            return {
                'total_cost': 0.0,
                'average_cost_per_image': 0.0,
                'total_tokens': 0,
                'total_input_tokens': 0,
                'total_output_tokens': 0,
                'document_count': 0
            }
    
    def get_image_processing_stats(self) -> Dict[str, int]:
        """
        Get comprehensive image processing statistics.
        
        Returns:
            dict: Processing statistics by status
        """
        try:
            response = self.client.table('source_documents').select(
                'celery_status, file_category'
            ).eq('file_category', 'image').execute()
            
            stats = {
                'total_images': 0,
                'image_queued': 0,
                'image_processing': 0,
                'image_completed': 0,
                'image_failed': 0,
                'image_failed_with_fallback': 0,
                'other_status': 0
            }
            
            for doc in response.data:
                stats['total_images'] += 1
                status = doc.get('celery_status', 'unknown')
                
                if status in stats:
                    stats[status] += 1
                else:
                    stats['other_status'] += 1
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get image processing stats: {e}")
            return {
                'total_images': 0,
                'image_queued': 0,
                'image_processing': 0,
                'image_completed': 0,
                'image_failed': 0,
                'image_failed_with_fallback': 0,
                'other_status': 0
            }
    
    def get_failed_image_documents(self, limit: int = 50) -> List[Dict]:
        """
        Get list of documents that failed image processing.
        
        Args:
            limit: Maximum number of documents to return
            
        Returns:
            List of document records with failure details
        """
        try:
            response = self.client.table('source_documents').select(
                'id, document_uuid, original_file_name, celery_status, error_details, '
                'image_analysis_confidence, last_modified_at'
            ).eq('file_category', 'image').in_(
                'celery_status', ['image_failed', 'image_failed_with_fallback']
            ).order('last_modified_at', desc=True).limit(limit).execute()
            
            return response.data
            
        except Exception as e:
            logger.error(f"Failed to get failed image documents: {e}")
            return []

    # === Enhanced Batch Operations with Pydantic Models ===
    
    def get_pending_documents_as_models(self, limit: int = 50) -> List[SourceDocumentModel]:
        """
        Get documents pending processing as validated Pydantic models.
        
        Args:
            limit: Maximum number of documents to return
            
        Returns:
            List of SourceDocumentModel instances
        """
        logger.info(f"Fetching up to {limit} pending documents as models")
        
        try:
            response = self.client.table('source_documents')\
                .select('*')\
                .eq('initial_processing_status', 'pending_intake')\
                .limit(limit)\
                .execute()
            
            models = []
            for doc_data in response.data:
                try:
                    model = create_model_from_db(SourceDocumentModel, doc_data)
                    models.append(model)
                except ValidationError as e:
                    logger.warning(f"Validation error for document {doc_data.get('id')}: {e}")
                    # Continue processing other documents
                    continue
            
            logger.info(f"Successfully created {len(models)} validated document models")
            return models
            
        except Exception as e:
            logger.error(f"Error fetching pending documents as models: {str(e)}")
            raise
    
    def batch_create_chunks(self, chunks: List[ChunkModel]) -> List[ChunkModel]:
        """
        Create multiple chunks in a single batch operation with validation.
        
        Args:
            chunks: List of ChunkModel instances to create
            
        Returns:
            List of created ChunkModel instances with IDs
        """
        logger.info(f"Batch creating {len(chunks)} chunks")
        
        try:
            # Validate all chunks first
            chunk_dicts = []
            for chunk in chunks:
                chunk_dict = chunk.model_dump(by_alias=True, exclude={'id'})
                chunk_dicts.append(chunk_dict)
            
            # Batch insert
            response = self.client.table('neo4j_chunks').insert(chunk_dicts).execute()
            
            # Create models from returned data
            created_models = []
            for chunk_data in response.data:
                model = create_model_from_db(ChunkModel, chunk_data)
                created_models.append(model)
            
            logger.info(f"Successfully created {len(created_models)} chunks in batch")
            return created_models
            
        except Exception as e:
            logger.error(f"Error in batch chunk creation: {str(e)}")
            raise
    
    def batch_update_processing_status(self, table: str, updates: List[Tuple[int, str]]) -> int:
        """
        Update processing status for multiple records in batch.
        
        Args:
            table: Table name to update
            updates: List of (record_id, status) tuples
            
        Returns:
            Number of records updated
        """
        logger.info(f"Batch updating {len(updates)} records in {table}")
        
        try:
            updated_count = 0
            
            # Determine status field based on table
            if table == 'neo4j_documents':
                status_field = 'processingStatus'
            elif table == 'neo4j_chunks':
                status_field = 'processingStatus'
            else:
                status_field = 'initial_processing_status'
            
            # Process in smaller batches to avoid API limits
            batch_size = 100
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                
                for record_id, status in batch:
                    update_data = {
                        status_field: status,
                        'updatedAt': datetime.now(timezone.utc).isoformat()
                    }
                    
                    response = self.client.table(table).update(update_data).eq('id', record_id).execute()
                    if response.data:
                        updated_count += 1
            
            logger.info(f"Successfully updated {updated_count} records")
            return updated_count
            
        except Exception as e:
            logger.error(f"Error in batch status update: {str(e)}")
            raise
    
    def get_documents_with_chunks_as_models(self, limit: int = 20) -> List[Tuple[Neo4jDocumentModel, List[ChunkModel]]]:
        """
        Get documents ready for entity extraction with their chunks as validated models.
        
        Args:
            limit: Maximum number of documents to return
            
        Returns:
            List of (Neo4jDocumentModel, List[ChunkModel]) tuples
        """
        logger.info(f"Fetching documents with chunks as models for entity extraction")
        
        try:
            # Get documents ready for entity extraction
            docs_response = self.client.table('neo4j_documents')\
                .select('*')\
                .eq('processingStatus', 'pending_entities')\
                .limit(limit)\
                .execute()
            
            documents_with_chunks = []
            for doc_data in docs_response.data:
                try:
                    # Create document model
                    doc_model = create_model_from_db(Neo4jDocumentModel, doc_data)
                    
                    # Get chunks for this document
                    chunks_response = self.client.table('neo4j_chunks')\
                        .select('*')\
                        .eq('document_id', doc_model.id)\
                        .order('chunkIndex', desc=False)\
                        .execute()
                    
                    # Create chunk models
                    chunk_models = []
                    for chunk_data in chunks_response.data:
                        try:
                            chunk_model = create_model_from_db(ChunkModel, chunk_data)
                            chunk_models.append(chunk_model)
                        except ValidationError as e:
                            logger.warning(f"Validation error for chunk {chunk_data.get('id')}: {e}")
                            continue
                    
                    documents_with_chunks.append((doc_model, chunk_models))
                    
                except ValidationError as e:
                    logger.warning(f"Validation error for document {doc_data.get('id')}: {e}")
                    continue
            
            logger.info(f"Found {len(documents_with_chunks)} documents with validated models")
            return documents_with_chunks
            
        except Exception as e:
            logger.error(f"Error fetching documents with chunks as models: {str(e)}")
            raise