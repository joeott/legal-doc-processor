#!/usr/bin/env python3
"""Test database connection and import a document"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment
load_dotenv()

# Import after environment is loaded
from scripts.config import get_database_url, db_engine
from scripts.db import DatabaseManager
# Remove unused import
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_database_connection():
    """Test database connection"""
    logger.info("Testing database connection...")
    
    try:
        # Get effective database URL
        db_url = get_database_url()
        logger.info(f"Using database URL: {db_url[:50]}...")
        
        # Test connection using the shared engine
        from sqlalchemy import text
        with db_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            logger.info(f"✅ Database connected: {version}")
            
            # Check tables
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name
            """))
            tables = [row[0] for row in result]
            logger.info(f"Found {len(tables)} tables: {', '.join(tables[:5])}...")
            
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

def check_existing_data():
    """Check existing data in database"""
    try:
        db_manager = DatabaseManager()
        
        # Check documents
        from sqlalchemy import text
        docs = db_manager.session.execute(text("SELECT COUNT(*) FROM source_documents")).scalar()
        logger.info(f"Existing documents: {docs}")
        
        # Check projects
        projects = db_manager.session.execute(text("SELECT COUNT(*) FROM projects")).scalar()
        logger.info(f"Existing projects: {projects}")
        
        # Check tasks
        tasks = db_manager.session.execute(text("""
            SELECT status, COUNT(*) 
            FROM processing_tasks 
            GROUP BY status
        """)).fetchall()
        
        if tasks:
            logger.info("Task status:")
            for status, count in tasks:
                logger.info(f"  - {status}: {count}")
        else:
            logger.info("No processing tasks found")
            
        db_manager.close()
        return True
        
    except Exception as e:
        logger.error(f"Failed to check existing data: {e}")
        return False

def import_document(file_path: str):
    """Import a single document"""
    logger.info(f"Importing document: {file_path}")
    
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False
    
    try:
        # Create a simple import manifest
        import json
        import tempfile
        
        manifest = {
            "documents": [
                {
                    "file_path": file_path,
                    "document_type": "legal_filing",
                    "metadata": {
                        "source": "manual_import",
                        "case": "Paul, Michael (Acuity)"
                    }
                }
            ]
        }
        
        # Write manifest to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(manifest, f)
            manifest_path = f.name
        
        logger.info(f"Created manifest: {manifest_path}")
        
        # Import using CLI
        import subprocess
        
        cmd = ["python3", "scripts/cli/import.py", "--manifest", manifest_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        logger.info(f"Import stdout: {result.stdout}")
        if result.stderr:
            logger.error(f"Import stderr: {result.stderr}")
        
        # Clean up
        os.unlink(manifest_path)
        
        return result.returncode == 0
        
    except Exception as e:
        logger.error(f"Failed to import document: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    logger.info("=== Legal Document Processor - Single Document Test ===")
    
    # Test database connection
    if not test_database_connection():
        logger.error("Cannot proceed without database connection")
        return 1
    
    # Check existing data
    check_existing_data()
    
    # Import document
    doc_path = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Amend Disclosure Stmt 9-23-24.pdf"
    
    if os.path.exists(doc_path):
        logger.info(f"\n📄 Processing document: {os.path.basename(doc_path)}")
        logger.info(f"File size: {os.path.getsize(doc_path):,} bytes")
        
        if import_document(doc_path):
            logger.info("✅ Document import initiated successfully!")
            logger.info("\nNext steps:")
            logger.info("1. Monitor processing with: python scripts/cli/monitor.py live")
            logger.info("2. Check document status with: python scripts/cli/monitor.py doc-status <document_id>")
        else:
            logger.error("❌ Document import failed!")
            return 1
    else:
        logger.error(f"Document not found: {doc_path}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())