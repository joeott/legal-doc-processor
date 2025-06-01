#!/usr/bin/env python3
"""
Script to generate UUIDs for Airtable projects that don't have them,
and update both Airtable and Supabase with the same UUIDs.
"""

import os
import sys
import uuid
import logging
from typing import Dict, List, Optional
from pyairtable import Api

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager

# Get Airtable config from environment
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID')

if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
    raise ValueError("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in environment")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ProjectUUIDBackfiller:
    """Handles backfilling of UUIDs for projects missing them in Airtable"""
    
    def __init__(self):
        self.api = Api(AIRTABLE_API_KEY)
        self.base = self.api.base(AIRTABLE_BASE_ID)
        self.projects_table = self.base.table('Projects')
        self.db_manager = SupabaseManager()
        
    def get_projects_without_uuid(self) -> List[Dict]:
        """Get all projects from Airtable that don't have a projectid"""
        all_projects = []
        
        # Fetch all records with pagination
        for page in self.projects_table.iterate():
            for record in page:
                fields = record['fields']
                # Check if projectid is missing or empty
                if not fields.get('projectid'):
                    all_projects.append({
                        'airtable_id': record['id'],
                        'fields': fields,
                        'case_name': fields.get('Casename', 'Unknown'),
                        'dropbox_name': fields.get('DropBox File Name', ''),
                        'created_time': record.get('createdTime', '')
                    })
        
        return all_projects
    
    def generate_deterministic_uuid(self, airtable_id: str, case_name: str) -> str:
        """
        Generate a deterministic UUID based on Airtable record ID.
        This ensures the same UUID is generated if the script is run multiple times.
        """
        # Use namespace UUID5 with Airtable ID to ensure consistency
        namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # Standard namespace
        generated_uuid = uuid.uuid5(namespace, f"airtable:{AIRTABLE_BASE_ID}:{airtable_id}")
        return str(generated_uuid)
    
    def update_airtable_project(self, airtable_id: str, project_uuid: str) -> bool:
        """Update Airtable project with the generated UUID"""
        try:
            self.projects_table.update(airtable_id, {'projectid': project_uuid})
            logger.info(f"Updated Airtable record {airtable_id} with UUID {project_uuid}")
            return True
        except Exception as e:
            logger.error(f"Failed to update Airtable record {airtable_id}: {e}")
            return False
    
    def create_supabase_project(self, project: Dict, project_uuid: str) -> bool:
        """Create project in Supabase with the generated UUID"""
        try:
            # Check if project already exists
            existing = self.db_manager.client.table('projects').select('id').eq('projectId', project_uuid).execute()
            
            if existing.data:
                logger.info(f"Project {project_uuid} already exists in Supabase")
                return True
            
            # Prepare project data
            project_data = {
                'projectId': project_uuid,
                'name': project['case_name'],
                'airtable_id': project['airtable_id'],
                'metadata': {
                    'dropbox_file_name': project['dropbox_name'],
                    'attorney': project['fields'].get('Attorney', []),
                    'paralegal': project['fields'].get('Paralegal', ''),
                    'phase': project['fields'].get('Phase', []),
                    'project_type': project['fields'].get('Project Type', []),
                    'court_location': project['fields'].get('Court Location (from Metadata Import table)', ''),
                    'case_number': project['fields'].get('Case Number (from Metadata Import table)', ''),
                    'dropbox_url': project['fields'].get('Dropbox URL', ''),
                    'airtable_created': project['created_time'],
                    'raw_fields': project['fields']
                },
                'active': True,
                'createdAt': project['created_time'],
                'updatedAt': project['created_time']
            }
            
            # Insert into Supabase
            result = self.db_manager.client.table('projects').insert(project_data).execute()
            
            if result.data:
                logger.info(f"Created project {project_uuid} in Supabase: {project['case_name']}")
                return True
            else:
                logger.error(f"Failed to create project in Supabase: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error creating project in Supabase: {e}")
            return False
    
    def backfill_all_projects(self, dry_run: bool = False) -> Dict[str, int]:
        """
        Backfill UUIDs for all projects missing them.
        
        Args:
            dry_run: If True, only show what would be done without making changes
            
        Returns:
            Statistics dictionary
        """
        stats = {
            'found': 0,
            'updated_airtable': 0,
            'created_supabase': 0,
            'errors': 0
        }
        
        logger.info("Starting UUID backfill process...")
        
        # Get projects without UUIDs
        projects = self.get_projects_without_uuid()
        stats['found'] = len(projects)
        
        logger.info(f"Found {len(projects)} projects without UUIDs")
        
        if dry_run:
            logger.info("DRY RUN MODE - No changes will be made")
        
        for project in projects:
            try:
                # Generate deterministic UUID
                project_uuid = self.generate_deterministic_uuid(
                    project['airtable_id'],
                    project['case_name']
                )
                
                logger.info(f"\nProcessing: {project['case_name']}")
                logger.info(f"  Airtable ID: {project['airtable_id']}")
                logger.info(f"  Generated UUID: {project_uuid}")
                
                if not dry_run:
                    # Update Airtable first
                    if self.update_airtable_project(project['airtable_id'], project_uuid):
                        stats['updated_airtable'] += 1
                        
                        # Then create in Supabase
                        if self.create_supabase_project(project, project_uuid):
                            stats['created_supabase'] += 1
                    else:
                        stats['errors'] += 1
                else:
                    logger.info("  [DRY RUN] Would update Airtable and create in Supabase")
                    
            except Exception as e:
                logger.error(f"Error processing project {project['case_name']}: {e}")
                stats['errors'] += 1
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("BACKFILL SUMMARY")
        logger.info("="*60)
        logger.info(f"Projects found without UUID: {stats['found']}")
        logger.info(f"Airtable records updated: {stats['updated_airtable']}")
        logger.info(f"Supabase projects created: {stats['created_supabase']}")
        logger.info(f"Errors: {stats['errors']}")
        
        return stats
    
    def verify_consistency(self) -> None:
        """Verify that Airtable and Supabase have consistent UUIDs"""
        logger.info("\nVerifying UUID consistency...")
        
        # Get all Airtable projects with UUIDs
        airtable_projects = {}
        for page in self.projects_table.iterate():
            for record in page:
                if record['fields'].get('projectid'):
                    airtable_projects[record['fields']['projectid']] = {
                        'name': record['fields'].get('Casename', 'Unknown'),
                        'airtable_id': record['id']
                    }
        
        # Get all Supabase projects
        supabase_projects = self.db_manager.client.table('projects').select('projectId, name, airtable_id').execute()
        
        supabase_dict = {p['projectId']: p for p in supabase_projects.data}
        
        # Check for inconsistencies
        missing_in_supabase = set(airtable_projects.keys()) - set(supabase_dict.keys())
        missing_in_airtable = set(supabase_dict.keys()) - set(airtable_projects.keys())
        
        if missing_in_supabase:
            logger.warning(f"\nProjects in Airtable but not in Supabase: {len(missing_in_supabase)}")
            for uuid in list(missing_in_supabase)[:5]:
                logger.warning(f"  - {uuid}: {airtable_projects[uuid]['name']}")
        
        if missing_in_airtable:
            logger.warning(f"\nProjects in Supabase but not in Airtable: {len(missing_in_airtable)}")
            for uuid in list(missing_in_airtable)[:5]:
                logger.warning(f"  - {uuid}: {supabase_dict[uuid]['name']}")
        
        if not missing_in_supabase and not missing_in_airtable:
            logger.info("✅ All UUIDs are consistent between Airtable and Supabase!")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Backfill UUIDs for Airtable projects")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--verify", action="store_true", help="Verify consistency between Airtable and Supabase")
    
    args = parser.parse_args()
    
    backfiller = ProjectUUIDBackfiller()
    
    if args.verify:
        backfiller.verify_consistency()
    else:
        backfiller.backfill_all_projects(dry_run=args.dry_run)