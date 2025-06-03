#!/usr/bin/env python3
"""
Create a test project for document processing.
"""

import os
import sys
import uuid
from pathlib import Path

# Setup Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load environment
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

from scripts.rds_utils import insert_record
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_test_project():
    """Create a test project in the database."""
    
    project_uuid = str(uuid.uuid4())
    
    project_data = {
        'project_uuid': project_uuid,
        'name': 'Test Legal Project',  # Use 'name' not 'project_name'
        'client_name': 'Test Client',
        'matter_type': 'litigation',
        'data_layer': 'production',
        'active': True,
        'metadata': {
            'description': 'Test project for legal document processing',
            'created_for': 'Testing',
            'project_type': 'litigation',
            'status': 'active'
        }
    }
    
    try:
        logger.info(f"Creating test project: {project_data['name']}")
        result = insert_record('projects', project_data)
        
        if result:
            logger.info(f"Successfully created project with UUID: {project_uuid}")
            return project_uuid
        else:
            logger.error("Failed to create project")
            return None
            
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        return None

if __name__ == "__main__":
    project_uuid = create_test_project()
    if project_uuid:
        print(f"\nTest project created successfully!")
        print(f"Project UUID: {project_uuid}")
        print(f"\nYou can now process documents with this project UUID")
    else:
        print("\nFailed to create test project!")
        sys.exit(1)