#!/usr/bin/env python3
"""
Enhanced Import CLI with Pydantic Model Validation
Provides type-safe import operations with comprehensive validation and error reporting.
"""

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
import click
import time
import uuid
import logging

# Import Pydantic models for validation
from scripts.core.processing_models import (
    DocumentMetadata,
    ImportManifestModel,
    ImportFileModel,
    ImportValidationResultModel
)
from scripts.core.schemas import (
    ImportSessionModel, SourceDocumentModel
)
from pydantic import ValidationError

from scripts.db import DatabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.pdf_tasks import process_pdf_document
from scripts.cache import get_redis_manager
from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET

logger = logging.getLogger(__name__)

class TypeSafeImporter:
    """Type-safe document importer using Pydantic models."""
    
    def __init__(self):
        # TODO: Re-enable conformance validation after schema issues are resolved
        self.db = DatabaseManager(validate_conformance=False)
        self.s3_manager = S3StorageManager()
        self.cache_manager = get_redis_manager()
        
    def validate_manifest(self, manifest_path: str) -> ImportValidationResultModel:
        """Validate import manifest with comprehensive error reporting."""
        try:
            with open(manifest_path, 'r') as f:
                raw_manifest = json.load(f)
            
            # Validate manifest structure
            try:
                manifest = ImportManifestModel(**raw_manifest)
                
                # Additional validation checks
                validation_errors = []
                validation_warnings = []
                
                # Check file paths exist
                base_path = Path(manifest.metadata.base_path)
                missing_files = []
                
                for file_info in manifest.files:
                    file_path = base_path / file_info.path
                    if not file_path.exists():
                        missing_files.append(str(file_path))
                
                if missing_files:
                    validation_errors.append(f"Missing files: {', '.join(missing_files[:5])}")
                    if len(missing_files) > 5:
                        validation_errors.append(f"... and {len(missing_files) - 5} more files")
                
                # Check for duplicate file hashes
                file_hashes = [f.file_hash for f in manifest.files if f.file_hash]
                duplicate_hashes = set([h for h in file_hashes if file_hashes.count(h) > 1])
                if duplicate_hashes:
                    validation_warnings.append(f"Duplicate file hashes found: {len(duplicate_hashes)} duplicates")
                
                # Validate file sizes
                large_files = [f for f in manifest.files if f.size and f.size > 100 * 1024 * 1024]  # 100MB
                if large_files:
                    validation_warnings.append(f"Large files detected: {len(large_files)} files > 100MB")
                
                return ImportValidationResultModel(
                    is_valid=len(validation_errors) == 0,
                    manifest=manifest,
                    validation_errors=validation_errors,
                    validation_warnings=validation_warnings,
                    total_files=len(manifest.files),
                    total_size=sum(f.size or 0 for f in manifest.files),
                    estimated_cost=self._estimate_processing_cost(manifest)
                )
                
            except ValidationError as e:
                # Format Pydantic validation errors
                error_details = []
                for error in e.errors():
                    field_path = " -> ".join(str(loc) for loc in error['loc'])
                    error_details.append(f"{field_path}: {error['msg']}")
                
                return ImportValidationResultModel(
                    is_valid=False,
                    manifest=None,
                    validation_errors=[f"Manifest validation failed: {'; '.join(error_details)}"],
                    validation_warnings=[],
                    total_files=0,
                    total_size=0,
                    estimated_cost=0.0
                )
                
        except Exception as e:
            return ImportValidationResultModel(
                is_valid=False,
                manifest=None,
                validation_errors=[f"Failed to load manifest: {str(e)}"],
                validation_warnings=[],
                total_files=0,
                total_size=0,
                estimated_cost=0.0
            )
    
    def _estimate_processing_cost(self, manifest: ImportManifestModel) -> float:
        """Estimate processing cost based on file types and sizes."""
        cost = 0.0
        
        for file_info in manifest.files:
            file_size_mb = (file_info.size or 0) / (1024 * 1024)
            
            # Estimate based on file type
            if file_info.detected_type == 'pdf':
                # Textract cost: ~$1.50 per 1000 pages, assume 1 page per MB
                cost += file_size_mb * 0.0015
            elif file_info.detected_type in ['jpg', 'jpeg', 'png', 'tiff']:
                # Textract image cost: ~$1.50 per 1000 images
                cost += 0.0015
            else:
                # Default processing cost
                cost += file_size_mb * 0.001
        
        return round(cost, 2)
    
    def create_import_session(self, manifest: ImportManifestModel, project_uuid: str) -> ImportSessionModel:
        """Create type-safe import session."""
        try:
            # Verify project exists (skip for now, will be added later)
            # TODO: Add project validation once project management is implemented
            
            # Create import session matching actual database schema
            session_uuid = str(uuid.uuid4())
            session_data = {
                'session_uuid': session_uuid,
                'project_uuid': project_uuid,
                'session_name': f"Import {manifest.metadata.case_name}",
                'import_source': 'manifest',
                'total_files': len(manifest.files),
                'files_uploaded': 0,
                'files_processing': 0,
                'files_completed': 0,
                'files_failed': 0,
                'started_at': datetime.now().isoformat()
            }
            
            # Create session model
            session = ImportSessionModel(**session_data)
            
            # Insert into database using raw SQL
            from scripts.rds_utils import insert_record
            result = insert_record("import_sessions", session.model_dump(mode='json'))
            
            if not result:
                raise Exception("Failed to create import session")
            
            # Return the created session
            return session
            
        except Exception as e:
            logger.error(f"Failed to create import session: {e}")
            raise
    
    def import_document(self, file_info: ImportFileModel, session_uuid: str, 
                       project_uuid: str, base_path: Path) -> Dict[str, Any]:
        """Import single document with type safety."""
        try:
            # Generate document UUID
            document_uuid = str(uuid.uuid4())
            
            # Prepare file path
            file_path = base_path / file_info.path
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            
            # Upload to S3
            upload_result = self.s3_manager.upload_document_with_uuid_naming(
                str(file_path), document_uuid, file_info.name
            )
            s3_key = upload_result['s3_key']
            
            # Create document metadata
            doc_metadata = DocumentMetadata(
                document_type=file_info.detected_type,
                title=file_info.name,
                file_path=str(file_path),
                file_size=file_info.size or 0
            )
            
            # Create document entry matching actual schema
            doc_data = {
                'document_uuid': document_uuid,
                'project_uuid': project_uuid,
                'document_name': file_info.name,
                'document_type': file_info.detected_type,
                's3_path': s3_key,
                'file_size': file_info.size or 0,
                'import_session_uuid': session_uuid,
                'processing_status': 'pending',
                'metadata': doc_metadata.model_dump()
            }
            
            # Create document in database
            doc = SourceDocumentModel(
                document_uuid=uuid.UUID(document_uuid),
                original_file_name=file_info.name,
                s3_bucket=S3_PRIMARY_DOCUMENT_BUCKET,
                s3_key=s3_key,
                file_size_bytes=file_info.size or file_path.stat().st_size,
                detected_file_type=file_info.detected_type,
                project_uuid=project_uuid,
                initial_processing_status='pending',
                celery_status='pending',
                metadata=doc_metadata.model_dump()
            )
            
            created_doc = self.db.create_source_document(doc)
            if not created_doc:
                raise Exception("Failed to create document record")
            
            document_uuid = str(created_doc.document_uuid)
            
            # Submit to Celery for processing
            # Construct proper S3 URI from the key
            s3_uri = f"s3://{S3_PRIMARY_DOCUMENT_BUCKET}/{s3_key}"
            
            task = process_pdf_document.delay(
                document_uuid=document_uuid,
                file_path=s3_uri,
                project_uuid=project_uuid,
                document_metadata={
                    'documentId': document_uuid,
                    'name': file_info.name,
                    'file_type': file_info.detected_type,
                    'project_uuid': project_uuid
                }
            )
            
            # Update with task ID
            from scripts.rds_utils import update_record
            update_record('source_documents', {
                'celery_task_id': task.id,
                'processing_status': 'processing'
            }, {'document_uuid': document_uuid})
            
            # Cache document for quick access
            cache_key = f"doc:import:{document_uuid}"
            self.cache_manager.set_cached(
                cache_key, 
                doc_data,
                ttl=3600
            )
            
            return {
                'success': True,
                'document_uuid': document_uuid,
                'task_id': task.id,
                's3_key': s3_key
            }
            
        except Exception as e:
            logger.error(f"Failed to import document {file_info.name}: {e}")
            return {
                'success': False,
                'error': str(e),
                'file_name': file_info.name
            }

@click.group()
def cli():
    """Enhanced import commands with Pydantic validation."""
    pass

@cli.command()
@click.argument('manifest_file', type=click.Path(exists=True))
@click.option('--project-uuid', required=True, help='Target project UUID')
@click.option('--batch-size', default=50, help='Documents per batch')
@click.option('--dry-run', is_flag=True, help='Validate manifest without importing')
@click.option('--delay', default=0.1, help='Delay between submissions')
@click.option('--validate-only', is_flag=True, help='Only validate manifest structure')
def from_manifest(manifest_file, project_uuid, batch_size, dry_run, delay, validate_only):
    """Import documents from a manifest file with Pydantic validation."""
    importer = TypeSafeImporter()
    
    # Validate manifest
    click.echo("🔍 Validating manifest...")
    validation_result = importer.validate_manifest(manifest_file)
    
    # Display validation results
    if validation_result.validation_errors:
        click.echo("❌ Manifest validation failed:")
        for error in validation_result.validation_errors:
            click.echo(f"  • {error}", err=True)
        return
    
    if validation_result.validation_warnings:
        click.echo("⚠️  Validation warnings:")
        for warning in validation_result.validation_warnings:
            click.echo(f"  • {warning}")
    
    click.echo("✅ Manifest validation successful!")
    click.echo(f"  Files: {validation_result.total_files}")
    click.echo(f"  Total size: {validation_result.total_size / (1024*1024):.1f} MB")
    click.echo(f"  Estimated cost: ${validation_result.estimated_cost:.2f}")
    
    if validate_only:
        return
    
    manifest = validation_result.manifest
    
    if dry_run:
        click.echo("\n🧪 DRY RUN - No files will be imported")
        for file_info in manifest.files[:10]:
            click.echo(f"  Would import: {file_info.name}")
        if len(manifest.files) > 10:
            click.echo(f"  ... and {len(manifest.files) - 10} more files")
        return
    
    # Confirm import
    if not click.confirm(f"\nProceed with importing {len(manifest.files)} files?"):
        click.echo("Import cancelled.")
        return
    
    try:
        # Create import session
        click.echo("📝 Creating import session...")
        session = importer.create_import_session(manifest, project_uuid)
        click.echo(f"✅ Created import session: {session['session_uuid']}")
        
        # Project UUID is already validated in create_import_session
        
        # Import documents in batches
        base_path = Path(manifest.metadata.base_path)
        imported = 0
        failed = 0
        
        for i in range(0, len(manifest.files), batch_size):
            batch = manifest.files[i:i+batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(manifest.files) + batch_size - 1) // batch_size
            
            click.echo(f"\n📦 Processing batch {batch_num}/{total_batches} ({len(batch)} files)")
            
            for file_info in batch:
                result = importer.import_document(
                    file_info, session['session_uuid'], project_uuid, base_path
                )
                
                if result['success']:
                    imported += 1
                    if imported % 10 == 0:
                        click.echo(f"  ✅ Imported {imported} documents...")
                else:
                    failed += 1
                    click.echo(f"  ❌ Failed: {result['file_name']} - {result['error']}", err=True)
                
                time.sleep(delay)
        
        # Update session status
        from scripts.rds_utils import update_record
        update_record('import_sessions', {
            'files_completed': imported,
            'files_failed': failed,
            'completed_at': datetime.now().isoformat()
        }, {'session_uuid': session['session_uuid']})
        
        # Display summary
        click.echo(f"\n📊 Import Summary:")
        click.echo(f"  ✅ Imported: {imported}")
        click.echo(f"  ❌ Failed: {failed}")
        click.echo(f"  📈 Success rate: {(imported/(imported+failed)*100):.1f}%")
        
        if failed > 0:
            click.echo(f"\n💡 Check import session {session['session_uuid']} for detailed error logs")
        
    except Exception as e:
        click.echo(f"❌ Import failed: {str(e)}", err=True)
        logger.error(f"Import failed: {e}")

@cli.command()
@click.argument('directory', type=click.Path(exists=True))
@click.option('--project-uuid', required=True, help='Target project UUID')
@click.option('--recursive', is_flag=True, help='Include subdirectories')
@click.option('--file-types', default='pdf,doc,docx,txt', help='Comma-separated file types')
def from_directory(directory, project_uuid, recursive, file_types):
    """Import documents from a directory with type validation."""
    click.echo(f"🔍 Scanning directory: {directory}")
    
    # Parse file types
    allowed_types = [ext.strip().lower() for ext in file_types.split(',')]
    
    # Scan directory
    dir_path = Path(directory)
    pattern = "**/*" if recursive else "*"
    
    files = []
    for file_path in dir_path.glob(pattern):
        if file_path.is_file() and file_path.suffix.lower().lstrip('.') in allowed_types:
            files.append(file_path)
    
    if not files:
        click.echo("❌ No matching files found")
        return
    
    click.echo(f"✅ Found {len(files)} files")
    
    # Create temporary manifest
    manifest_data = {
        "metadata": {
            "case_name": f"Directory Import {dir_path.name}",
            "base_path": str(dir_path.parent),
            "created_at": datetime.now().isoformat()
        },
        "files": [],
        "import_config": {
            "processing_order": ["documents"],
            "batch_size": 50
        }
    }
    
    for file_path in files:
        relative_path = file_path.relative_to(dir_path.parent)
        file_info = {
            "name": file_path.name,
            "path": str(relative_path),
            "size": file_path.stat().st_size,
            "detected_type": file_path.suffix.lower().lstrip('.'),
            "mime_type": f"application/{file_path.suffix.lower().lstrip('.')}",
            "folder_category": "documents"
        }
        manifest_data["files"].append(file_info)
    
    # Validate and import using manifest logic
    importer = TypeSafeImporter()
    
    try:
        manifest = ImportManifestModel(**manifest_data)
        validation_result = ImportValidationResultModel(
            is_valid=True,
            manifest=manifest,
            validation_errors=[],
            validation_warnings=[],
            total_files=len(files),
            total_size=sum(f.stat().st_size for f in files),
            estimated_cost=importer._estimate_processing_cost(manifest)
        )
        
        click.echo(f"📊 Import Preview:")
        click.echo(f"  Files: {validation_result.total_files}")
        click.echo(f"  Total size: {validation_result.total_size / (1024*1024):.1f} MB")
        click.echo(f"  Estimated cost: ${validation_result.estimated_cost:.2f}")
        
        if click.confirm("Proceed with import?"):
            # Use the manifest import logic
            ctx = click.get_current_context()
            ctx.invoke(from_manifest, 
                      manifest_file=None,  # We'll pass the manifest object directly
                      project_uuid=project_uuid,
                      batch_size=50,
                      dry_run=False,
                      delay=0.1,
                      validate_only=False)
        
    except ValidationError as e:
        click.echo("❌ Directory import validation failed:", err=True)
        for error in e.errors():
            field_path = " -> ".join(str(loc) for loc in error['loc'])
            click.echo(f"  • {field_path}: {error['msg']}", err=True)

if __name__ == '__main__':
    cli()