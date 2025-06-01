#!/usr/bin/env python3
"""
List all projects in the database.
"""

import os
import sys
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def list_projects():
    """List all projects in the database."""
    db_manager = SupabaseManager()
    
    try:
        # Get all projects
        response = db_manager.client.table('projects').select('*').order('createdAt', desc=True).execute()
        projects = response.data if response.data else []
        
        if not projects:
            logger.info("No projects found in database")
            return
        
        logger.info(f"\nFound {len(projects)} projects:\n")
        logger.info(f"{'='*100}")
        logger.info(f"{'ID':>4} | {'Name':<40} | {'Project UUID':<40} | {'Created':<20}")
        logger.info(f"{'='*100}")
        
        for proj in projects:
            created_at = proj.get('createdAt', '')
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    created_at = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            logger.info(
                f"{proj['id']:>4} | "
                f"{proj['name'][:40]:<40} | "
                f"{proj['projectId'][:40]:<40} | "
                f"{created_at:<20}"
            )
        
        logger.info(f"{'='*100}")
        
        # Show document counts per project
        logger.info("\nDocument counts per project:")
        logger.info(f"{'='*60}")
        logger.info(f"{'Project':<40} | {'Documents':>10}")
        logger.info(f"{'='*60}")
        
        for proj in projects:
            # Count documents for this project
            doc_response = db_manager.client.table('source_documents').select(
                'id', count='exact'
            ).eq('project_id', proj['id']).execute()
            
            doc_count = doc_response.count if hasattr(doc_response, 'count') else len(doc_response.data)
            
            logger.info(f"{proj['name'][:40]:<40} | {doc_count:>10}")
        
        logger.info(f"{'='*60}")
        
    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        sys.exit(1)

def main():
    list_projects()

if __name__ == "__main__":
    main()