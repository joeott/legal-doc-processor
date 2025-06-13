#!/usr/bin/env python3
"""
Test script to process documents recursively with project assignment.

This script:
1. Processes all files in a directory recursively
2. Uses fuzzy matching to find projects based on filename patterns
3. Assigns projects to documents when submitting to the pipeline
4. Uses the existing database schema and main_pipeline.py
"""

import os
import sys
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher
import re

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.celery_submission import submit_document_to_celery
from scripts.config import PROJECT_ID_GLOBAL, S3_PRIMARY_DOCUMENT_BUCKET
from scripts.s3_storage import S3StorageManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Common legal patterns to search for in filenames
LEGAL_PATTERNS = [
    # Client names
    r'([A-Z][A-Za-z]+)\s+v[s\.]?\s+([A-Z][A-Za-z]+)',  # "Smith v. Jones"
    r'([A-Z][A-Za-z]+)\s+([A-Z]\.?\s+)?([A-Z][A-Za-z]+)(?:\s*[-–]\s*)?(?:Comprehensive|Report|Brief|Motion)',  # "John A. Smith - Report"
    r'([A-Z][A-Za-z]+),?\s+([A-Z][a-z]+)',  # "Smith, John"
    # Case numbers
    r'(\d{2,4}[-/]\w{2,}[-/]\d{2,})',  # "2023-CV-12345"
    r'Case\s*[:#]?\s*(\d+[-/]\w+)',  # "Case # 123-ABC"
    # Motion/Brief types
    r'(Motion|Brief|Petition|Reply|Response|Affidavit|Order)',
    # Court names
    r'(Circuit|District|Superior|Court|Appellate)',
]

class ProjectMatcher:
    """Handles fuzzy matching of filenames to projects."""
    
    def __init__(self, db_manager: SupabaseManager):
        self.db_manager = db_manager
        self.projects_cache = None
        self.refresh_projects_cache()
    
    def refresh_projects_cache(self):
        """Load all projects from database."""
        try:
            response = self.db_manager.client.table('projects').select('*').execute()
            self.projects_cache = response.data if response.data else []
            logger.info(f"Loaded {len(self.projects_cache)} projects from database")
            for proj in self.projects_cache:
                logger.debug(f"  Project: {proj['name']} (ID: {proj['projectId']})")
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            self.projects_cache = []
    
    def extract_key_terms(self, filename: str) -> List[str]:
        """Extract meaningful terms from filename."""
        # Remove extension
        base_name = os.path.splitext(filename)[0]
        
        # Extract patterns
        terms = []
        
        # Extract names from "v." patterns
        for match in re.finditer(r'([A-Z][A-Za-z]+)\s+v[s\.]?\s+([A-Z][A-Za-z]+)', base_name):
            terms.extend([match.group(1), match.group(2)])
        
        # Extract full names
        for match in re.finditer(r'([A-Z][A-Za-z]+)\s+([A-Z]\.?\s+)?([A-Z][A-Za-z]+)', base_name):
            full_name = ' '.join(filter(None, [match.group(1), match.group(2), match.group(3)]))
            terms.append(full_name.strip())
        
        # Extract case numbers
        for match in re.finditer(r'(\d{2,4}[-/]\w{2,}[-/]\d{2,})', base_name):
            terms.append(match.group(1))
        
        # Also split by common delimiters and filter
        words = re.split(r'[-_\s]+', base_name)
        meaningful_words = [w for w in words if len(w) > 2 and not w.isdigit()]
        terms.extend(meaningful_words)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_terms = []
        for term in terms:
            term_lower = term.lower()
            if term_lower not in seen:
                seen.add(term_lower)
                unique_terms.append(term)
        
        return unique_terms
    
    def fuzzy_match_score(self, str1: str, str2: str) -> float:
        """Calculate fuzzy match score between two strings."""
        # Direct substring match gets high score
        str1_lower = str1.lower()
        str2_lower = str2.lower()
        
        if str1_lower in str2_lower or str2_lower in str1_lower:
            return 0.9
        
        # Use SequenceMatcher for fuzzy matching
        return SequenceMatcher(None, str1_lower, str2_lower).ratio()
    
    def find_matching_project(self, filename: str, threshold: float = 0.6) -> Optional[Tuple[int, str, str]]:
        """
        Find best matching project for a filename.
        
        Returns:
            Tuple of (project_sql_id, project_uuid, project_name) or None
        """
        if not self.projects_cache:
            return None
        
        # Extract key terms from filename
        terms = self.extract_key_terms(filename)
        if not terms:
            logger.debug(f"No meaningful terms extracted from: {filename}")
            return None
        
        logger.debug(f"Extracted terms from '{filename}': {terms}")
        
        # Score each project
        best_match = None
        best_score = 0.0
        
        for project in self.projects_cache:
            project_name = project.get('name', '')
            project_id = project.get('projectId', '')
            
            # Calculate score for this project
            max_term_score = 0.0
            for term in terms:
                score = self.fuzzy_match_score(term, project_name)
                max_term_score = max(max_term_score, score)
            
            # Also check if any term matches the project ID
            for term in terms:
                if term.lower() in project_id.lower():
                    max_term_score = max(max_term_score, 0.8)
            
            if max_term_score > best_score:
                best_score = max_term_score
                best_match = project
        
        if best_match and best_score >= threshold:
            logger.info(f"Matched '{filename}' to project '{best_match['name']}' (score: {best_score:.2f})")
            return best_match['id'], best_match['projectId'], best_match['name']
        else:
            logger.debug(f"No project match found for '{filename}' (best score: {best_score:.2f})")
            return None
    
    def create_project_from_filename(self, filename: str) -> Tuple[int, str]:
        """Create a new project based on filename patterns."""
        terms = self.extract_key_terms(filename)
        
        # Try to create a meaningful project name
        project_name = "General Documents"
        
        # Look for case names (e.g., "Smith v. Jones")
        for match in re.finditer(r'([A-Z][A-Za-z]+)\s+v[s\.]?\s+([A-Z][A-Za-z]+)', filename):
            project_name = f"{match.group(1)} v. {match.group(2)}"
            break
        else:
            # Look for client names
            for match in re.finditer(r'([A-Z][A-Za-z]+)\s+([A-Z]\.?\s+)?([A-Z][A-Za-z]+)', filename):
                if match.group(2):  # Has middle initial
                    project_name = f"{match.group(1)} {match.group(2)} {match.group(3)}".strip()
                else:
                    project_name = f"{match.group(1)} {match.group(3)}"
                break
            else:
                # Use the most significant term
                if terms:
                    # Filter out common words
                    significant_terms = [t for t in terms if len(t) > 4 and t.lower() not in 
                                       ['report', 'brief', 'motion', 'order', 'comprehensive']]
                    if significant_terms:
                        project_name = significant_terms[0]
        
        logger.info(f"Creating new project: {project_name}")
        try:
            sql_id, uuid = self.db_manager.get_or_create_project(
                project_id=f"proj_{project_name.lower().replace(' ', '_').replace('.', '')}",
                name=project_name
            )
            # Refresh cache to include new project
            self.refresh_projects_cache()
            return sql_id, uuid
        except Exception as e:
            logger.error(f"Failed to create project: {e}")
            # Fall back to global project
            return self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL, "Default Project")

def process_directory_recursive(
    directory: str,
    db_manager: SupabaseManager,
    project_matcher: ProjectMatcher,
    auto_create_projects: bool = False,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Process all files in a directory recursively.
    
    Args:
        directory: Root directory to process
        db_manager: SupabaseManager instance
        project_matcher: ProjectMatcher instance
        auto_create_projects: Whether to create projects for unmatched files
        dry_run: If True, only show what would be done without processing
    
    Returns:
        Dictionary with processing statistics
    """
    stats = {
        'total_files': 0,
        'processed': 0,
        'matched_to_project': 0,
        'created_projects': 0,
        'failed': 0,
        'skipped': 0
    }
    
    # Supported file extensions
    supported_extensions = {'.pdf', '.docx', '.txt', '.rtf', '.eml', '.wav', '.mp3'}
    
    # Walk through directory
    for root, dirs, files in os.walk(directory):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for filename in files:
            # Skip hidden files
            if filename.startswith('.'):
                continue
            
            file_path = os.path.join(root, filename)
            file_ext = os.path.splitext(filename)[1].lower()
            
            # Check if file type is supported
            if file_ext not in supported_extensions:
                logger.debug(f"Skipping unsupported file type: {filename}")
                stats['skipped'] += 1
                continue
            
            stats['total_files'] += 1
            
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {filename}")
            logger.info(f"Path: {file_path}")
            
            if dry_run:
                logger.info("[DRY RUN] Would process this file")
                
                # Try to match project
                match_result = project_matcher.find_matching_project(filename)
                if match_result:
                    _, _, project_name = match_result
                    logger.info(f"[DRY RUN] Would assign to project: {project_name}")
                    stats['matched_to_project'] += 1
                elif auto_create_projects:
                    logger.info(f"[DRY RUN] Would create new project based on filename")
                    stats['created_projects'] += 1
                else:
                    logger.info(f"[DRY RUN] Would use default project")
                
                stats['processed'] += 1
                continue
            
            try:
                # Find or create project
                project_sql_id = None
                project_uuid = None
                
                # Try to match to existing project
                match_result = project_matcher.find_matching_project(filename)
                if match_result:
                    project_sql_id, project_uuid, project_name = match_result
                    logger.info(f"Matched to existing project: {project_name}")
                    stats['matched_to_project'] += 1
                elif auto_create_projects:
                    # Create new project based on filename
                    project_sql_id, project_uuid = project_matcher.create_project_from_filename(filename)
                    logger.info(f"Created new project for file")
                    stats['created_projects'] += 1
                else:
                    # Use default project
                    project_sql_id, project_uuid = db_manager.get_or_create_project(
                        PROJECT_ID_GLOBAL, "Default Project"
                    )
                    logger.info(f"Using default project")
                
                # Create source document entry
                src_doc_sql_id, src_doc_uuid = db_manager.create_source_document_entry(
                    project_fk_id=project_sql_id,
                    project_uuid=project_uuid,
                    original_file_path=file_path,
                    original_file_name=filename,
                    detected_file_type=file_ext
                )
                
                if not src_doc_sql_id:
                    logger.error(f"Failed to create source document entry for {filename}")
                    stats['failed'] += 1
                    continue
                
                logger.info(f"Created source document: ID={src_doc_sql_id}, UUID={src_doc_uuid}")
                
                # Upload to S3 if needed
                final_path = file_path
                if not file_path.startswith("s3://"):
                    s3_storage = S3StorageManager(bucket_name=S3_PRIMARY_DOCUMENT_BUCKET)
                    final_path = s3_storage.upload_document(
                        file_path=file_path,
                        original_filename=filename
                    )
                    logger.info(f"Uploaded to S3: {final_path}")
                
                # Submit to Celery for processing
                task_id, success = submit_document_to_celery(
                    document_id=src_doc_sql_id,
                    document_uuid=src_doc_uuid,
                    file_path=final_path,
                    file_type=file_ext,
                    file_name=filename,
                    project_sql_id=project_sql_id  # Use project SQL ID
                )
                
                if success:
                    logger.info(f"✅ Submitted to Celery. Task ID: {task_id}")
                    stats['processed'] += 1
                else:
                    logger.error(f"❌ Failed to submit to Celery")
                    db_manager.update_source_document_text(
                        src_doc_sql_id, None, status="error_celery_submission"
                    )
                    stats['failed'] += 1
                    
            except Exception as e:
                logger.error(f"Error processing {filename}: {e}")
                stats['failed'] += 1
    
    return stats

def main():
    parser = argparse.ArgumentParser(
        description="Process documents recursively with project assignment"
    )
    parser.add_argument(
        "directory",
        help="Directory to process recursively"
    )
    parser.add_argument(
        "--auto-create-projects",
        action="store_true",
        help="Automatically create projects for unmatched files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually processing"
    )
    parser.add_argument(
        "--refresh-projects",
        action="store_true",
        help="Refresh project cache before processing"
    )
    
    args = parser.parse_args()
    
    # Validate directory
    if not os.path.isdir(args.directory):
        logger.error(f"Directory not found: {args.directory}")
        sys.exit(1)
    
    # Initialize database manager
    db_manager = SupabaseManager()
    
    # Initialize project matcher
    project_matcher = ProjectMatcher(db_manager)
    
    if args.refresh_projects:
        logger.info("Refreshing project cache...")
        project_matcher.refresh_projects_cache()
    
    # Process directory
    logger.info(f"Starting recursive processing of: {args.directory}")
    if args.dry_run:
        logger.info("DRY RUN MODE - No actual processing will occur")
    
    stats = process_directory_recursive(
        directory=args.directory,
        db_manager=db_manager,
        project_matcher=project_matcher,
        auto_create_projects=args.auto_create_projects,
        dry_run=args.dry_run
    )
    
    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info("PROCESSING SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total files found: {stats['total_files']}")
    logger.info(f"Files processed: {stats['processed']}")
    logger.info(f"Files matched to projects: {stats['matched_to_project']}")
    logger.info(f"New projects created: {stats['created_projects']}")
    logger.info(f"Files failed: {stats['failed']}")
    logger.info(f"Files skipped: {stats['skipped']}")
    
    if stats['failed'] > 0:
        logger.warning(f"\n⚠️  {stats['failed']} files failed to process")
        sys.exit(1)
    else:
        logger.info("\n✅ All files processed successfully!")

if __name__ == "__main__":
    main()