#!/usr/bin/env python3
"""
Simple script to process a single document through the pipeline.
"""

import os
import sys
from pathlib import Path
import uuid
import logging

# Setup Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load environment
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

# Import pipeline modules
from scripts.pdf_tasks import process_pdf_document
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.s3_storage import S3StorageManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

def process_document(file_path: str):
    """Process a single document through the pipeline using CLI import."""
    
    # Validate file exists
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return
        
    logger.info(f"Processing document: {file_path}")
    
    try:
        # Import using the CLI module
        import importlib
        import_module = importlib.import_module('scripts.cli.import')
        TypeSafeImporter = import_module.TypeSafeImporter
        from scripts.core.processing_models import ImportFileModel
        
        importer = TypeSafeImporter()
        
        # Create a default project UUID for testing
        # First check if we have a test project, otherwise create one
        from scripts.rds_utils import execute_query
        
        # Look for existing test project
        projects = execute_query(
            "SELECT project_uuid FROM projects WHERE name = 'Test Legal Project' ORDER BY created_at DESC LIMIT 1"
        )
        
        if projects and len(projects) > 0:
            project_uuid = str(projects[0]['project_uuid'])
            logger.info(f"Using existing test project: {project_uuid}")
        else:
            # Create a new test project
            from scripts.tests.create_test_project import create_test_project
            project_uuid = create_test_project()
            if not project_uuid:
                raise Exception("Failed to create test project")
        
        # Create file info
        file_info = ImportFileModel(
            name=os.path.basename(file_path),
            path=os.path.basename(file_path),
            size=os.path.getsize(file_path),
            detected_type='pdf',
            mime_type='application/pdf',
            folder_category='documents'
        )
        
        # Import the document
        result = importer.import_document(
            file_info=file_info,
            session_uuid=str(uuid.uuid4()),  # Create a dummy session
            project_uuid=project_uuid,
            base_path=Path(file_path).parent
        )
        
        if result['success']:
            logger.info(f"Submitted to Celery. Task ID: {result['task_id']}")
            logger.info(f"Document UUID: {result['document_uuid']}")
            logger.info("Use the monitor to track progress:")
            logger.info(f"  python scripts/cli/monitor.py doc-status {result['document_uuid']}")
            return result['document_uuid']
        else:
            logger.error(f"Import failed: {result.get('error', 'Unknown error')}")
            return None
        
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python process_single_document.py <file_path>")
        sys.exit(1)
        
    file_path = sys.argv[1]
    doc_id = process_document(file_path)
    
    if doc_id:
        print(f"\nDocument submitted successfully!")
        print(f"Document ID: {doc_id}")
        print(f"\nMonitor progress with:")
        print(f"  PYTHONPATH=/opt/legal-doc-processor python3 scripts/cli/monitor.py doc-status {doc_id}")
    else:
        print("\nDocument processing failed!")
        sys.exit(1)