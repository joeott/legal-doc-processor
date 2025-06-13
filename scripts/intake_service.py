"""
Document Intake Service - Systematic document discovery and preparation for processing.

This service handles:
- Recursive directory scanning with file metadata capture
- Document deduplication based on content hash
- File integrity validation (corruption detection)
- Automatic S3 upload with organized key structure
- Processing priority assignment based on size/complexity
"""

import os
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
import logging

from scripts.config import (
    S3_PRIMARY_DOCUMENT_BUCKET, 
    AWS_DEFAULT_REGION,
    DOCUMENT_SIZE_LIMIT_MB
)
from scripts.logging_config import get_logger

logger = get_logger(__name__)

# Default project ID from migration
DEFAULT_PROJECT_ID = 1  # From migration above

def create_document_with_validation(
    document_uuid: str,
    filename: str,
    s3_bucket: str,
    s3_key: str,
    project_id: int = DEFAULT_PROJECT_ID
) -> Dict[str, Any]:
    """Create document with proper validation and FK references"""
    
    from scripts.db import DatabaseManager
    from sqlalchemy import text
    
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    try:
        # 1. Verify project exists
        project_check = session.execute(
            text("SELECT id FROM projects WHERE id = :id AND active = true"),
            {'id': project_id}
        )
        if not project_check.scalar():
            raise ValueError(f"Project {project_id} not found or inactive")
        
        # 2. Create document record
        insert_query = text("""
            INSERT INTO source_documents (
                document_uuid, project_fk_id, original_file_name, file_name,
                s3_bucket, s3_key, status, created_at
            ) VALUES (
                :doc_uuid, :project_id, :filename, :filename,
                :s3_bucket, :s3_key, 'pending', NOW()
            )
            RETURNING id
        """)
        
        result = session.execute(insert_query, {
            'doc_uuid': document_uuid,
            'project_id': project_id,
            'filename': filename,
            's3_bucket': s3_bucket,
            's3_key': s3_key
        })
        
        doc_id = result.scalar()
        session.commit()
        
        # 3. Create Redis metadata
        from scripts.cache import get_redis_manager
        redis_mgr = get_redis_manager()
        
        metadata_key = f"doc:metadata:{document_uuid}"
        metadata = {
            'document_uuid': document_uuid,
            'project_id': project_id,
            'project_uuid': str(session.execute(
                text("SELECT project_id FROM projects WHERE id = :id"),
                {'id': project_id}
            ).scalar()),
            'filename': filename,
            's3_bucket': s3_bucket,
            's3_key': s3_key,
            'created_at': datetime.now().isoformat(),
            'status': 'ready_for_processing'
        }
        
        redis_mgr.store_dict(metadata_key, metadata)
        logger.info(f"✅ Created document {document_uuid} with metadata")
        
        return {
            'document_id': doc_id,
            'document_uuid': document_uuid,
            'project_id': project_id,
            'metadata_stored': True
        }
        
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create document: {e}")
        raise
    finally:
        session.close()


@dataclass
class DocumentManifest:
    """Manifest for a discovered document."""
    local_path: str
    filename: str
    file_size_mb: float
    content_hash: str
    mime_type: str
    created_at: str
    modified_at: str
    s3_key: Optional[str] = None
    s3_bucket: Optional[str] = None
    priority: str = "normal"  # low, normal, high, urgent
    processing_complexity: str = "standard"  # simple, standard, complex
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ValidationResult:
    """Result of document integrity validation."""
    is_valid: bool
    file_exists: bool
    is_readable: bool
    mime_type_valid: bool
    size_within_limits: bool
    corruption_detected: bool
    error_message: Optional[str] = None


@dataclass
class S3Location:
    """S3 location information."""
    bucket: str
    key: str
    url: str
    upload_timestamp: str
    file_size_bytes: int


class DocumentIntakeService:
    """Service for discovering and preparing documents for processing."""
    
    def __init__(self):
        self.s3_client = boto3.client('s3', region_name=AWS_DEFAULT_REGION)
        self.supported_types = {
            'application/pdf',
            'image/png', 
            'image/jpeg',
            'image/tiff',
            'text/plain',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        
    def discover_documents(self, input_path: str, recursive: bool = True) -> List[DocumentManifest]:
        """
        Systematically catalog documents in a directory.
        
        Args:
            input_path: Path to scan for documents
            recursive: Whether to scan subdirectories
            
        Returns:
            List of DocumentManifest objects
        """
        logger.info(f"Starting document discovery in: {input_path}")
        
        if not os.path.exists(input_path):
            logger.error(f"Input path does not exist: {input_path}")
            return []
            
        documents = []
        path_obj = Path(input_path)
        
        # Get all files based on recursive flag
        if recursive:
            file_pattern = "**/*"
        else:
            file_pattern = "*"
            
        for file_path in path_obj.glob(file_pattern):
            if file_path.is_file():
                try:
                    manifest = self._create_document_manifest(str(file_path))
                    if manifest:
                        documents.append(manifest)
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
                    
        logger.info(f"Discovered {len(documents)} documents")
        return documents
    
    def _create_document_manifest(self, file_path: str) -> Optional[DocumentManifest]:
        """Create a manifest for a single document."""
        try:
            # Get file stats
            stat = os.stat(file_path)
            file_size_mb = stat.st_size / (1024 * 1024)
            
            # Calculate content hash
            content_hash = self._calculate_file_hash(file_path)
            
            # Get MIME type
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = 'application/octet-stream'
                
            # Skip unsupported file types
            if mime_type not in self.supported_types:
                logger.debug(f"Skipping unsupported file type {mime_type}: {file_path}")
                return None
                
            # Create manifest
            manifest = DocumentManifest(
                local_path=file_path,
                filename=os.path.basename(file_path),
                file_size_mb=file_size_mb,
                content_hash=content_hash,
                mime_type=mime_type,
                created_at=datetime.fromtimestamp(stat.st_ctime).isoformat(),
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                priority=self._determine_priority(file_size_mb, mime_type),
                processing_complexity=self._determine_complexity(file_size_mb, mime_type)
            )
            
            return manifest
            
        except Exception as e:
            logger.error(f"Error creating manifest for {file_path}: {e}")
            return None
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file content."""
        hash_sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating hash for {file_path}: {e}")
            return ""
    
    def _determine_priority(self, file_size_mb: float, mime_type: str) -> str:
        """Determine processing priority based on file characteristics."""
        # Small files get higher priority for quick wins
        if file_size_mb < 1.0:
            return "high"
        elif file_size_mb < 5.0:
            return "normal"
        elif file_size_mb < 20.0:
            return "normal"
        else:
            return "low"
    
    def _determine_complexity(self, file_size_mb: float, mime_type: str) -> str:
        """Determine processing complexity based on file characteristics."""
        if mime_type == 'text/plain':
            return "simple"
        elif mime_type == 'application/pdf':
            if file_size_mb < 5.0:
                return "standard"
            else:
                return "complex"
        elif mime_type.startswith('image/'):
            return "standard"
        else:
            return "complex"
    
    def create_processing_batches(self, documents: List[DocumentManifest], 
                                batch_strategy: str = "balanced") -> List[Dict[str, Any]]:
        """
        Organize documents into optimal processing batches.
        
        Args:
            documents: List of document manifests
            batch_strategy: "balanced", "size_optimized", "priority_first"
            
        Returns:
            List of processing batch configurations
        """
        logger.info(f"Creating processing batches for {len(documents)} documents using {batch_strategy} strategy")
        
        if not documents:
            return []
            
        # Remove duplicates based on content hash
        unique_docs = self._deduplicate_documents(documents)
        logger.info(f"After deduplication: {len(unique_docs)} unique documents")
        
        if batch_strategy == "priority_first":
            batches = self._create_priority_batches(unique_docs)
        elif batch_strategy == "size_optimized":
            batches = self._create_size_optimized_batches(unique_docs)
        else:  # balanced
            batches = self._create_balanced_batches(unique_docs)
            
        logger.info(f"Created {len(batches)} processing batches")
        return batches
    
    def _deduplicate_documents(self, documents: List[DocumentManifest]) -> List[DocumentManifest]:
        """Remove duplicate documents based on content hash."""
        seen_hashes = set()
        unique_docs = []
        
        for doc in documents:
            if doc.content_hash not in seen_hashes:
                seen_hashes.add(doc.content_hash)
                unique_docs.append(doc)
            else:
                logger.debug(f"Skipping duplicate document: {doc.filename}")
                
        return unique_docs
    
    def _create_balanced_batches(self, documents: List[DocumentManifest]) -> List[Dict[str, Any]]:
        """Create balanced batches mixing different document types and sizes."""
        batches = []
        current_batch = []
        current_size = 0.0
        batch_id = 1
        
        # Target batch sizes (in MB)
        small_batch_limit = 10.0
        medium_batch_limit = 100.0
        
        # Sort by priority first, then by size
        sorted_docs = sorted(documents, key=lambda x: (
            {'urgent': 0, 'high': 1, 'normal': 2, 'low': 3}[x.priority],
            x.file_size_mb
        ))
        
        for doc in sorted_docs:
            # Check if adding this document would exceed batch limits
            if current_batch and (
                current_size + doc.file_size_mb > medium_batch_limit or
                len(current_batch) >= 25
            ):
                # Create batch
                batch_type = self._determine_batch_type(current_size, len(current_batch))
                batches.append({
                    'batch_id': f"batch_{batch_id:03d}",
                    'batch_type': batch_type,
                    'document_count': len(current_batch),
                    'total_size_mb': round(current_size, 2),
                    'documents': [doc.to_dict() for doc in current_batch],
                    'priority': self._determine_batch_priority(current_batch),
                    'estimated_processing_time_minutes': self._estimate_processing_time(current_batch)
                })
                
                # Reset for next batch
                current_batch = []
                current_size = 0.0
                batch_id += 1
            
            current_batch.append(doc)
            current_size += doc.file_size_mb
        
        # Handle remaining documents
        if current_batch:
            batch_type = self._determine_batch_type(current_size, len(current_batch))
            batches.append({
                'batch_id': f"batch_{batch_id:03d}",
                'batch_type': batch_type,
                'document_count': len(current_batch),
                'total_size_mb': round(current_size, 2),
                'documents': [doc.to_dict() for doc in current_batch],
                'priority': self._determine_batch_priority(current_batch),
                'estimated_processing_time_minutes': self._estimate_processing_time(current_batch)
            })
        
        return batches
    
    def _create_priority_batches(self, documents: List[DocumentManifest]) -> List[Dict[str, Any]]:
        """Create batches prioritizing high-priority documents."""
        # Group by priority
        priority_groups = {'urgent': [], 'high': [], 'normal': [], 'low': []}
        for doc in documents:
            priority_groups[doc.priority].append(doc)
        
        batches = []
        batch_id = 1
        
        # Process each priority group
        for priority in ['urgent', 'high', 'normal', 'low']:
            if priority_groups[priority]:
                priority_batches = self._create_balanced_batches(priority_groups[priority])
                for batch in priority_batches:
                    batch['batch_id'] = f"batch_{batch_id:03d}"
                    batch['priority_focused'] = priority
                    batches.append(batch)
                    batch_id += 1
        
        return batches
    
    def _create_size_optimized_batches(self, documents: List[DocumentManifest]) -> List[Dict[str, Any]]:
        """Create batches optimized for consistent processing times."""
        # Sort by file size
        sorted_docs = sorted(documents, key=lambda x: x.file_size_mb)
        
        batches = []
        current_batch = []
        batch_id = 1
        
        for doc in sorted_docs:
            # Keep batches size-consistent
            if current_batch and len(current_batch) >= 20:
                batch_type = self._determine_batch_type(
                    sum(d.file_size_mb for d in current_batch), 
                    len(current_batch)
                )
                batches.append({
                    'batch_id': f"batch_{batch_id:03d}",
                    'batch_type': batch_type,
                    'document_count': len(current_batch),
                    'total_size_mb': round(sum(d.file_size_mb for d in current_batch), 2),
                    'documents': [doc.to_dict() for doc in current_batch],
                    'priority': self._determine_batch_priority(current_batch),
                    'estimated_processing_time_minutes': self._estimate_processing_time(current_batch)
                })
                
                current_batch = []
                batch_id += 1
            
            current_batch.append(doc)
        
        # Handle remaining documents
        if current_batch:
            batch_type = self._determine_batch_type(
                sum(d.file_size_mb for d in current_batch), 
                len(current_batch)
            )
            batches.append({
                'batch_id': f"batch_{batch_id:03d}",
                'batch_type': batch_type,
                'document_count': len(current_batch),
                'total_size_mb': round(sum(d.file_size_mb for d in current_batch), 2),
                'documents': [doc.to_dict() for doc in current_batch],
                'priority': self._determine_batch_priority(current_batch),
                'estimated_processing_time_minutes': self._estimate_processing_time(current_batch)
            })
        
        return batches
    
    def _determine_batch_type(self, total_size_mb: float, doc_count: int) -> str:
        """Determine batch type based on size and document count."""
        if total_size_mb < 10.0 or doc_count <= 5:
            return "small"
        elif total_size_mb < 100.0 or doc_count <= 25:
            return "medium"
        else:
            return "large"
    
    def _determine_batch_priority(self, documents: List[DocumentManifest]) -> str:
        """Determine overall batch priority based on document priorities."""
        priorities = [doc.priority for doc in documents]
        
        if any(p == 'urgent' for p in priorities):
            return 'urgent'
        elif any(p == 'high' for p in priorities):
            return 'high'
        elif all(p == 'low' for p in priorities):
            return 'low'
        else:
            return 'normal'
    
    def _estimate_processing_time(self, documents: List[DocumentManifest]) -> int:
        """Estimate processing time in minutes for a batch."""
        total_time = 0
        
        for doc in documents:
            # Base time estimates by complexity and size
            if doc.processing_complexity == "simple":
                base_time = 1  # 1 minute for simple docs
            elif doc.processing_complexity == "standard":
                base_time = 3  # 3 minutes for standard docs
            else:  # complex
                base_time = 8  # 8 minutes for complex docs
            
            # Adjust for file size
            size_multiplier = max(1.0, doc.file_size_mb / 5.0)
            total_time += base_time * size_multiplier
        
        return max(5, int(total_time))  # Minimum 5 minutes
    
    def validate_document_integrity(self, doc_path: str) -> ValidationResult:
        """
        Validate document integrity and suitability for processing.
        
        Args:
            doc_path: Path to document file
            
        Returns:
            ValidationResult with comprehensive validation status
        """
        result = ValidationResult(
            is_valid=False,
            file_exists=False,
            is_readable=False,
            mime_type_valid=False,
            size_within_limits=False,
            corruption_detected=False
        )
        
        try:
            # Check file existence
            if not os.path.exists(doc_path):
                result.error_message = "File does not exist"
                return result
            result.file_exists = True
            
            # Check readability
            try:
                with open(doc_path, 'rb') as f:
                    f.read(1024)  # Try to read first 1KB
                result.is_readable = True
            except Exception as e:
                result.error_message = f"File not readable: {e}"
                return result
            
            # Check MIME type
            mime_type, _ = mimetypes.guess_type(doc_path)
            if mime_type in self.supported_types:
                result.mime_type_valid = True
            else:
                result.error_message = f"Unsupported MIME type: {mime_type}"
                return result
            
            # Check file size
            file_size_mb = os.path.getsize(doc_path) / (1024 * 1024)
            if file_size_mb <= DOCUMENT_SIZE_LIMIT_MB:
                result.size_within_limits = True
            else:
                result.error_message = f"File size {file_size_mb:.1f}MB exceeds limit of {DOCUMENT_SIZE_LIMIT_MB}MB"
                return result
            
            # Basic corruption check for PDFs
            if mime_type == 'application/pdf':
                try:
                    with open(doc_path, 'rb') as f:
                        header = f.read(8)
                        if not header.startswith(b'%PDF-'):
                            result.corruption_detected = True
                            result.error_message = "PDF file appears corrupted (invalid header)"
                            return result
                except Exception:
                    result.corruption_detected = True
                    result.error_message = "Unable to validate PDF integrity"
                    return result
            
            # If we get here, all validations passed
            result.is_valid = True
            
        except Exception as e:
            result.error_message = f"Validation error: {e}"
            
        return result
    
    def upload_to_s3_with_metadata(self, local_path: str, metadata: Dict[str, Any]) -> Optional[S3Location]:
        """
        Upload document to S3 with organized key structure and metadata.
        
        Args:
            local_path: Local file path
            metadata: Document metadata to attach
            
        Returns:
            S3Location if successful, None if failed
        """
        try:
            # Generate organized S3 key
            filename = os.path.basename(local_path)
            date_prefix = datetime.now().strftime("%Y/%m/%d")
            content_hash = metadata.get('content_hash', '')
            s3_key = f"documents/{date_prefix}/{content_hash[:8]}_{filename}"
            
            # Prepare S3 metadata (limited to 2KB)
            s3_metadata = {
                'original-filename': filename,
                'content-hash': content_hash[:32],  # Truncate for metadata limits
                'file-size-mb': str(metadata.get('file_size_mb', 0)),
                'mime-type': metadata.get('mime_type', ''),
                'upload-timestamp': datetime.now().isoformat(),
                'processing-priority': metadata.get('priority', 'normal'),
                'processing-complexity': metadata.get('processing_complexity', 'standard')
            }
            
            # Upload file
            with open(local_path, 'rb') as f:
                self.s3_client.upload_fileobj(
                    f,
                    S3_PRIMARY_DOCUMENT_BUCKET,
                    s3_key,
                    ExtraArgs={
                        'Metadata': s3_metadata,
                        'ContentType': metadata.get('mime_type', 'application/octet-stream')
                    }
                )
            
            # Get file size for response
            file_size_bytes = os.path.getsize(local_path)
            
            # Create S3 location
            s3_location = S3Location(
                bucket=S3_PRIMARY_DOCUMENT_BUCKET,
                key=s3_key,
                url=f"s3://{S3_PRIMARY_DOCUMENT_BUCKET}/{s3_key}",
                upload_timestamp=datetime.now().isoformat(),
                file_size_bytes=file_size_bytes
            )
            
            logger.info(f"Successfully uploaded {filename} to S3: {s3_key}")
            return s3_location
            
        except ClientError as e:
            logger.error(f"S3 upload failed for {local_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Upload error for {local_path}: {e}")
            return None
    
    def create_intake_manifest(self, input_path: str, output_path: str, 
                             batch_strategy: str = "balanced") -> str:
        """
        Create a complete intake manifest for a directory.
        
        Args:
            input_path: Directory to scan
            output_path: Where to save the manifest
            batch_strategy: Batching strategy to use
            
        Returns:
            Path to created manifest file
        """
        logger.info(f"Creating intake manifest for {input_path}")
        
        # Discover documents
        documents = self.discover_documents(input_path)
        
        # Validate documents
        valid_documents = []
        invalid_documents = []
        
        for doc in documents:
            validation = self.validate_document_integrity(doc.local_path)
            if validation.is_valid:
                valid_documents.append(doc)
            else:
                invalid_documents.append({
                    'document': doc.to_dict(),
                    'validation_error': validation.error_message
                })
        
        # Create processing batches
        batches = self.create_processing_batches(valid_documents, batch_strategy)
        
        # Create manifest
        manifest = {
            'created_at': datetime.now().isoformat(),
            'input_path': input_path,
            'batch_strategy': batch_strategy,
            'summary': {
                'total_documents_discovered': len(documents),
                'valid_documents': len(valid_documents),
                'invalid_documents': len(invalid_documents),
                'total_batches': len(batches),
                'total_size_mb': round(sum(doc.file_size_mb for doc in valid_documents), 2),
                'estimated_total_processing_time_minutes': sum(batch.get('estimated_processing_time_minutes', 0) for batch in batches)
            },
            'batches': batches,
            'invalid_documents': invalid_documents
        }
        
        # Save manifest
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        logger.info(f"Intake manifest created: {output_path}")
        logger.info(f"Summary: {manifest['summary']}")
        
        return output_path