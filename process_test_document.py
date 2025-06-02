#!/usr/bin/env python3
"""Process a test document through the pipeline"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
import tempfile

# Set up Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment
from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Process a single test document"""
    
    # Document to process
    doc_path = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Amend Disclosure Stmt 9-23-24.pdf"
    
    if not os.path.exists(doc_path):
        logger.error(f"Document not found: {doc_path}")
        return 1
    
    # Create manifest
    manifest = {
        "metadata": {
            "case_name": "Paul, Michael (Acuity)",
            "base_path": "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)",
            "created_at": datetime.now().isoformat()
        },
        "files": [
            {
                "path": os.path.basename(doc_path),
                "name": os.path.basename(doc_path),
                "size": os.path.getsize(doc_path),
                "detected_type": "pdf",
                "mime_type": "application/pdf"
            }
        ]
    }
    
    # Write manifest to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(manifest, f)
        manifest_path = f.name
    
    logger.info(f"Created manifest: {manifest_path}")
    
    # First, create a project
    logger.info("Creating project...")
    project_cmd = ["python3", "scripts/tests/create_test_project.py"]
    import subprocess
    result = subprocess.run(project_cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        logger.error(f"Failed to create project: {result.stderr}")
        return 1
    
    # Extract project UUID from output
    import re
    match = re.search(r'Created project: ([a-f0-9-]+)', result.stdout)
    if match:
        project_uuid = match.group(1)
        logger.info(f"Using project UUID: {project_uuid}")
    else:
        logger.error("Could not extract project UUID")
        return 1
    
    # Import document using CLI
    logger.info("Importing document...")
    import_cmd = [
        "python3", "scripts/cli/import.py", 
        "from-manifest", manifest_path,
        "--project-uuid", project_uuid
    ]
    
    result = subprocess.run(import_cmd, capture_output=True, text=True)
    
    print("\n" + "="*60)
    print("IMPORT OUTPUT:")
    print("="*60)
    print(result.stdout)
    if result.stderr:
        print("\nERRORS:")
        print(result.stderr)
    print("="*60)
    
    # Clean up
    os.unlink(manifest_path)
    
    if result.returncode == 0:
        logger.info("\n✅ Document import successful!")
        logger.info("\nMonitor processing with:")
        logger.info("  python3 scripts/cli/monitor.py live")
        return 0
    else:
        logger.error("\n❌ Document import failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())