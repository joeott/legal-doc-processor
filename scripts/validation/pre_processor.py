"""Pre-processing validation framework"""

import os
import boto3
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET, VALIDATED_REGION

logger = logging.getLogger(__name__)

@dataclass
class ValidationResult:
    """Result of a validation check"""
    check_name: str
    passed: bool
    message: str
    details: Optional[Dict] = None

class PreProcessingValidator:
    """Validate all prerequisites before document processing"""
    
    def __init__(self):
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.s3 = boto3.client('s3', region_name=VALIDATED_REGION)
        self.results: List[ValidationResult] = []
    
    def validate_document(self, document_uuid: str, file_path: str) -> Tuple[bool, List[ValidationResult]]:
        """Run all validation checks"""
        
        self.results = []
        
        # 1. Check document exists in database
        self._check_database_record(document_uuid)
        
        # 2. Check project association
        self._check_project_association(document_uuid)
        
        # 3. Check Redis metadata
        self._check_redis_metadata(document_uuid)
        
        # 4. Check S3 accessibility
        self._check_s3_access(file_path)
        
        # 5. Check file size
        self._check_file_size(file_path)
        
        # 6. Check system resources
        self._check_system_resources()
        
        # 7. Check Textract availability
        self._check_textract_availability()
        
        # Compile results
        all_passed = all(r.passed for r in self.results)
        return all_passed, self.results
    
    def _check_database_record(self, document_uuid: str):
        """Check if document exists in database"""
        try:
            session = next(self.db.get_session())
            from sqlalchemy import text
            
            result = session.execute(
                text("SELECT id, project_fk_id FROM source_documents WHERE document_uuid = :uuid"),
                {'uuid': document_uuid}
            )
            record = result.fetchone()
            session.close()
            
            if record:
                self.results.append(ValidationResult(
                    "database_record",
                    True,
                    f"Document found: ID={record.id}",
                    {"id": record.id, "project_fk_id": record.project_fk_id}
                ))
            else:
                self.results.append(ValidationResult(
                    "database_record",
                    False,
                    "Document not found in database",
                    None
                ))
        except Exception as e:
            self.results.append(ValidationResult(
                "database_record",
                False,
                f"Database error: {str(e)}",
                None
            ))
    
    def _check_project_association(self, document_uuid: str):
        """Check if document has valid project"""
        try:
            session = next(self.db.get_session())
            from sqlalchemy import text
            
            result = session.execute(
                text("""
                    SELECT p.id, p.project_id, p.name 
                    FROM source_documents d
                    JOIN projects p ON d.project_fk_id = p.id
                    WHERE d.document_uuid = :uuid AND p.active = true
                """),
                {'uuid': document_uuid}
            )
            project = result.fetchone()
            session.close()
            
            if project:
                self.results.append(ValidationResult(
                    "project_association",
                    True,
                    f"Valid project: {project.name}",
                    {"project_id": project.id, "project_uuid": str(project.project_id)}
                ))
            else:
                self.results.append(ValidationResult(
                    "project_association",
                    False,
                    "No valid project association",
                    None
                ))
        except Exception as e:
            self.results.append(ValidationResult(
                "project_association",
                False,
                f"Project check error: {str(e)}",
                None
            ))
    
    def _check_redis_metadata(self, document_uuid: str):
        """Check if Redis metadata exists"""
        try:
            metadata_key = f"doc:metadata:{document_uuid}"
            metadata = self.redis.get_dict(metadata_key)
            
            if metadata and 'project_uuid' in metadata:
                self.results.append(ValidationResult(
                    "redis_metadata",
                    True,
                    "Metadata found",
                    {"keys": list(metadata.keys())}
                ))
            else:
                self.results.append(ValidationResult(
                    "redis_metadata",
                    False,
                    "Metadata missing or incomplete",
                    {"found": metadata is not None}
                ))
        except Exception as e:
            self.results.append(ValidationResult(
                "redis_metadata",
                False,
                f"Redis error: {str(e)}",
                None
            ))
    
    def _check_s3_access(self, file_path: str):
        """Check if S3 file is accessible"""
        if not file_path.startswith('s3://'):
            self.results.append(ValidationResult(
                "s3_access",
                True,
                "Local file",
                None
            ))
            return
        
        try:
            from urllib.parse import urlparse
            parsed = urlparse(file_path)
            bucket = parsed.netloc
            key = parsed.path.lstrip('/')
            
            response = self.s3.head_object(Bucket=bucket, Key=key)
            size_mb = response['ContentLength'] / (1024 * 1024)
            
            self.results.append(ValidationResult(
                "s3_access",
                True,
                f"S3 file accessible: {size_mb:.1f}MB",
                {"bucket": bucket, "key": key, "size_mb": size_mb}
            ))
        except Exception as e:
            self.results.append(ValidationResult(
                "s3_access",
                False,
                f"S3 access error: {str(e)}",
                None
            ))
    
    def _check_file_size(self, file_path: str):
        """Check if file size is reasonable"""
        try:
            max_size_mb = 500
            size_mb = 0
            
            if file_path.startswith('s3://'):
                # Already checked in S3 access
                for r in self.results:
                    if r.check_name == "s3_access" and r.passed and r.details:
                        size_mb = r.details.get('size_mb', 0)
                        break
            else:
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
            
            if size_mb <= max_size_mb:
                self.results.append(ValidationResult(
                    "file_size",
                    True,
                    f"File size OK: {size_mb:.1f}MB",
                    {"size_mb": size_mb}
                ))
            else:
                self.results.append(ValidationResult(
                    "file_size",
                    False,
                    f"File too large: {size_mb:.1f}MB > {max_size_mb}MB",
                    {"size_mb": size_mb, "max_mb": max_size_mb}
                ))
        except Exception as e:
            self.results.append(ValidationResult(
                "file_size",
                False,
                f"Size check error: {str(e)}",
                None
            ))
    
    def _check_system_resources(self):
        """Check system memory and disk"""
        try:
            import psutil
            
            # Memory check
            memory = psutil.virtual_memory()
            memory_ok = memory.percent < 80
            
            # Disk check
            disk = psutil.disk_usage('/')
            disk_ok = disk.percent < 90
            
            if memory_ok and disk_ok:
                self.results.append(ValidationResult(
                    "system_resources",
                    True,
                    f"Resources OK: Memory {memory.percent:.1f}%, Disk {disk.percent:.1f}%",
                    {"memory_percent": memory.percent, "disk_percent": disk.percent}
                ))
            else:
                self.results.append(ValidationResult(
                    "system_resources",
                    False,
                    f"Resource constraint: Memory {memory.percent:.1f}%, Disk {disk.percent:.1f}%",
                    {"memory_percent": memory.percent, "disk_percent": disk.percent}
                ))
        except Exception as e:
            self.results.append(ValidationResult(
                "system_resources",
                True,  # Don't block on resource check failure
                f"Resource check skipped: {str(e)}",
                None
            ))
    
    def _check_textract_availability(self):
        """Check if Textract service is available"""
        try:
            import boto3
            from scripts.config import VALIDATED_REGION
            
            textract = boto3.client('textract', region_name=VALIDATED_REGION)
            
            # Try to describe a non-existent job (should fail gracefully)
            try:
                textract.get_document_text_detection(JobId='test-availability')
            except textract.exceptions.InvalidJobIdException:
                # This is expected - service is available
                pass
            
            self.results.append(ValidationResult(
                "textract_availability",
                True,
                f"Textract available in {VALIDATED_REGION}",
                {"region": VALIDATED_REGION}
            ))
        except Exception as e:
            self.results.append(ValidationResult(
                "textract_availability",
                False,
                f"Textract not available: {str(e)}",
                None
            ))

# Integration with pdf_tasks.py
def validate_before_processing(document_uuid: str, file_path: str) -> None:
    """Validate prerequisites before processing - raises on failure"""
    
    validator = PreProcessingValidator()
    passed, results = validator.validate_document(document_uuid, file_path)
    
    # Log all results
    for result in results:
        if result.passed:
            logger.info(f"✅ {result.check_name}: {result.message}")
        else:
            logger.error(f"❌ {result.check_name}: {result.message}")
    
    if not passed:
        failed_checks = [r.check_name for r in results if not r.passed]
        raise ValueError(f"Pre-processing validation failed: {', '.join(failed_checks)}")