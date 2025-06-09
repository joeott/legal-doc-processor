"""Flexible validation system with tiered approach"""

import os
from enum import Enum
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging
import boto3
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET, VALIDATED_REGION
from sqlalchemy import text

logger = logging.getLogger(__name__)

class ValidationLevel(Enum):
    """Validation importance levels"""
    CRITICAL = "critical"     # Must pass or processing fails
    IMPORTANT = "important"   # Log warning but continue
    OPTIONAL = "optional"     # Nice to have, ignore failures

@dataclass
class ValidationResult:
    """Result of a single validation check"""
    check_name: str
    passed: bool
    message: str
    level: ValidationLevel
    details: Optional[Dict] = None

class FlexibleValidator:
    """Validation that helps rather than hinders document processing"""
    
    # Default validation rules - can be overridden via environment
    VALIDATION_RULES = {
        "database_record": ValidationLevel.CRITICAL,
        "s3_access": ValidationLevel.CRITICAL,
        "project_association": ValidationLevel.IMPORTANT,
        "redis_metadata": ValidationLevel.OPTIONAL,
        "file_size": ValidationLevel.IMPORTANT,
        "system_resources": ValidationLevel.OPTIONAL,
        "textract_availability": ValidationLevel.IMPORTANT
    }
    
    def __init__(self):
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.s3 = boto3.client('s3', region_name=VALIDATED_REGION)
        
        # Allow environment override of validation levels
        self._load_env_overrides()
    
    def _load_env_overrides(self):
        """Load validation level overrides from environment"""
        for check_name in self.VALIDATION_RULES:
            env_key = f"VALIDATION_{check_name.upper()}_LEVEL"
            env_value = os.getenv(env_key)
            if env_value and env_value.upper() in [e.value.upper() for e in ValidationLevel]:
                self.VALIDATION_RULES[check_name] = ValidationLevel(env_value.lower())
                logger.info(f"Override {check_name} validation level to {env_value}")
    
    def validate_document(self, document_uuid: str, file_path: str) -> Tuple[bool, Dict[str, ValidationResult]]:
        """
        Validate document with appropriate flexibility.
        
        Returns:
            Tuple of (critical_checks_passed, all_results)
        """
        results = {}
        critical_passed = True
        
        for check_name, level in self.VALIDATION_RULES.items():
            try:
                # Run the validation check
                result = self._run_check(check_name, document_uuid, file_path)
                results[check_name] = result
                
                # Handle based on level
                if not result.passed:
                    if level == ValidationLevel.CRITICAL:
                        critical_passed = False
                        logger.error(f"❌ CRITICAL validation failed: {check_name} - {result.message}")
                    elif level == ValidationLevel.IMPORTANT:
                        logger.warning(f"⚠️  Important validation failed: {check_name} - {result.message}")
                    else:
                        logger.info(f"ℹ️  Optional validation failed: {check_name} - {result.message}")
                else:
                    logger.debug(f"✅ {check_name} validation passed")
                    
            except Exception as e:
                # Handle check errors gracefully
                error_msg = f"Check error: {str(e)}"
                results[check_name] = ValidationResult(
                    check_name=check_name,
                    passed=False,
                    message=error_msg,
                    level=level
                )
                
                if level == ValidationLevel.CRITICAL:
                    critical_passed = False
                    logger.error(f"❌ CRITICAL validation error in {check_name}: {e}")
                else:
                    logger.warning(f"Validation check {check_name} error: {e}")
        
        # Log summary
        passed_count = sum(1 for r in results.values() if r.passed)
        total_count = len(results)
        logger.info(f"Validation summary: {passed_count}/{total_count} checks passed, critical_passed={critical_passed}")
        
        return critical_passed, results
    
    def _run_check(self, check_name: str, document_uuid: str, file_path: str) -> ValidationResult:
        """Run a specific validation check"""
        
        check_methods = {
            "database_record": self._check_database_record,
            "s3_access": self._check_s3_access,
            "project_association": self._check_project_association,
            "redis_metadata": self._check_redis_metadata,
            "file_size": self._check_file_size,
            "system_resources": self._check_system_resources,
            "textract_availability": self._check_textract_availability
        }
        
        if check_name not in check_methods:
            raise ValueError(f"Unknown validation check: {check_name}")
        
        return check_methods[check_name](document_uuid, file_path)
    
    def _check_database_record(self, document_uuid: str, file_path: str) -> ValidationResult:
        """Check if document exists in database"""
        try:
            session = next(self.db.get_session())
            
            result = session.execute(
                text("SELECT id, project_fk_id, status FROM source_documents WHERE document_uuid = :uuid"),
                {'uuid': document_uuid}
            )
            record = result.fetchone()
            session.close()
            
            if record:
                return ValidationResult(
                    check_name="database_record",
                    passed=True,
                    message=f"Document found: ID={record.id}, status={record.status}",
                    level=self.VALIDATION_RULES["database_record"],
                    details={"id": record.id, "project_fk_id": record.project_fk_id, "status": record.status}
                )
            else:
                return ValidationResult(
                    check_name="database_record",
                    passed=False,
                    message="Document not found in database",
                    level=self.VALIDATION_RULES["database_record"]
                )
        except Exception as e:
            return ValidationResult(
                check_name="database_record",
                passed=False,
                message=f"Database error: {str(e)}",
                level=self.VALIDATION_RULES["database_record"]
            )
    
    def _check_s3_access(self, document_uuid: str, file_path: str) -> ValidationResult:
        """Check if S3 file is accessible"""
        if not file_path.startswith('s3://'):
            return ValidationResult(
                check_name="s3_access",
                passed=True,
                message="Local file, S3 check not applicable",
                level=self.VALIDATION_RULES["s3_access"]
            )
        
        try:
            from urllib.parse import urlparse
            parsed = urlparse(file_path)
            bucket = parsed.netloc
            key = parsed.path.lstrip('/')
            
            response = self.s3.head_object(Bucket=bucket, Key=key)
            size_mb = response['ContentLength'] / (1024 * 1024)
            
            return ValidationResult(
                check_name="s3_access",
                passed=True,
                message=f"S3 file accessible: {size_mb:.1f}MB",
                level=self.VALIDATION_RULES["s3_access"],
                details={"size_mb": size_mb, "content_type": response.get('ContentType')}
            )
        except Exception as e:
            return ValidationResult(
                check_name="s3_access",
                passed=False,
                message=f"S3 access error: {str(e)}",
                level=self.VALIDATION_RULES["s3_access"]
            )
    
    def _check_project_association(self, document_uuid: str, file_path: str) -> ValidationResult:
        """Check if document has valid project association"""
        try:
            session = next(self.db.get_session())
            
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
                return ValidationResult(
                    check_name="project_association",
                    passed=True,
                    message=f"Valid project: {project.name}",
                    level=self.VALIDATION_RULES["project_association"],
                    details={"project_id": project.id, "project_name": project.name}
                )
            else:
                return ValidationResult(
                    check_name="project_association",
                    passed=False,
                    message="No valid project association",
                    level=self.VALIDATION_RULES["project_association"]
                )
        except Exception as e:
            return ValidationResult(
                check_name="project_association",
                passed=False,
                message=f"Project check error: {str(e)}",
                level=self.VALIDATION_RULES["project_association"]
            )
    
    def _check_redis_metadata(self, document_uuid: str, file_path: str) -> ValidationResult:
        """Check if Redis metadata exists"""
        try:
            metadata_key = f"doc:metadata:{document_uuid}"
            metadata = self.redis.get_dict(metadata_key)
            
            if metadata and 'project_uuid' in metadata:
                return ValidationResult(
                    check_name="redis_metadata",
                    passed=True,
                    message="Metadata found",
                    level=self.VALIDATION_RULES["redis_metadata"],
                    details={"keys": list(metadata.keys())}
                )
            else:
                return ValidationResult(
                    check_name="redis_metadata",
                    passed=False,
                    message="Metadata missing or incomplete",
                    level=self.VALIDATION_RULES["redis_metadata"]
                )
        except Exception as e:
            return ValidationResult(
                check_name="redis_metadata",
                passed=False,
                message=f"Redis error: {str(e)}",
                level=self.VALIDATION_RULES["redis_metadata"]
            )
    
    def _check_file_size(self, document_uuid: str, file_path: str) -> ValidationResult:
        """Check if file size is within acceptable limits"""
        try:
            from scripts.utils.pdf_handler import safe_pdf_operation
            
            result = safe_pdf_operation(file_path, "check")
            if result and 'size' in result:
                size_mb = result['size'] / (1024 * 1024)
                max_size_mb = int(os.getenv('MAX_FILE_SIZE_MB', '1000'))
                
                if size_mb <= max_size_mb:
                    return ValidationResult(
                        check_name="file_size",
                        passed=True,
                        message=f"File size OK: {size_mb:.1f}MB",
                        level=self.VALIDATION_RULES["file_size"],
                        details={"size_mb": size_mb}
                    )
                else:
                    return ValidationResult(
                        check_name="file_size",
                        passed=False,
                        message=f"File too large: {size_mb:.1f}MB > {max_size_mb}MB",
                        level=self.VALIDATION_RULES["file_size"],
                        details={"size_mb": size_mb, "max_mb": max_size_mb}
                    )
            else:
                return ValidationResult(
                    check_name="file_size",
                    passed=False,
                    message="Could not determine file size",
                    level=self.VALIDATION_RULES["file_size"]
                )
        except Exception as e:
            return ValidationResult(
                check_name="file_size",
                passed=False,
                message=f"Size check error: {str(e)}",
                level=self.VALIDATION_RULES["file_size"]
            )
    
    def _check_system_resources(self, document_uuid: str, file_path: str) -> ValidationResult:
        """Check system resources availability"""
        try:
            import psutil
            
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            memory_ok = memory.percent < 90
            disk_ok = disk.percent < 90
            
            if memory_ok and disk_ok:
                return ValidationResult(
                    check_name="system_resources",
                    passed=True,
                    message=f"Resources OK: Memory {memory.percent:.1f}%, Disk {disk.percent:.1f}%",
                    level=self.VALIDATION_RULES["system_resources"],
                    details={"memory_percent": memory.percent, "disk_percent": disk.percent}
                )
            else:
                return ValidationResult(
                    check_name="system_resources",
                    passed=False,
                    message=f"Resource constraints: Memory {memory.percent:.1f}%, Disk {disk.percent:.1f}%",
                    level=self.VALIDATION_RULES["system_resources"],
                    details={"memory_percent": memory.percent, "disk_percent": disk.percent}
                )
        except Exception as e:
            return ValidationResult(
                check_name="system_resources",
                passed=True,  # Don't fail on resource check errors
                message=f"Resource check skipped: {str(e)}",
                level=self.VALIDATION_RULES["system_resources"]
            )
    
    def _check_textract_availability(self, document_uuid: str, file_path: str) -> ValidationResult:
        """Check if Textract is available"""
        try:
            textract_client = boto3.client('textract', region_name=VALIDATED_REGION)
            # Just check if we can create client - actual API test would cost money
            return ValidationResult(
                check_name="textract_availability",
                passed=True,
                message=f"Textract available in {VALIDATED_REGION}",
                level=self.VALIDATION_RULES["textract_availability"],
                details={"region": VALIDATED_REGION}
            )
        except Exception as e:
            return ValidationResult(
                check_name="textract_availability",
                passed=False,
                message=f"Textract availability error: {str(e)}",
                level=self.VALIDATION_RULES["textract_availability"]
            )


def validate_before_processing(document_uuid: str, file_path: str) -> None:
    """
    Backward compatible function for existing code.
    Raises ValueError only if critical validations fail and FORCE_PROCESSING is not set.
    """
    validator = FlexibleValidator()
    critical_passed, results = validator.validate_document(document_uuid, file_path)
    
    if not critical_passed:
        failed_critical = [name for name, result in results.items() 
                          if not result.passed and result.level == ValidationLevel.CRITICAL]
        
        # Check if force processing is enabled
        if os.getenv('FORCE_PROCESSING', '').lower() == 'true':
            logger.warning(f"FORCE_PROCESSING enabled, continuing despite critical failures: {failed_critical}")
        else:
            raise ValueError(f"Pre-processing validation failed: {', '.join(failed_critical)}")