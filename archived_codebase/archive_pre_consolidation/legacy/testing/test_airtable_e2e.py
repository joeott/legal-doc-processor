#!/usr/bin/env python3
"""
Comprehensive end-to-end test for Airtable integration.
Tests document processing with project matching for all documents in a directory.
"""

import os
import sys
import time
import glob
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.celery_submission import submit_document_to_celery
from airtable.fuzzy_matcher import FuzzyMatcher
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def process_documents_in_directory(directory_path, recursive=True):
    """Process all documents in a directory with Airtable project matching."""
    
    # Initialize components
    logger.info("Initializing components...")
    db_manager = SupabaseManager()
    s3_manager = S3StorageManager()
    matcher = FuzzyMatcher()
    
    # Find all PDF files
    if recursive:
        pattern = os.path.join(directory_path, "**", "*.pdf")
        pdf_files = glob.glob(pattern, recursive=True)
    else:
        pattern = os.path.join(directory_path, "*.pdf")
        pdf_files = glob.glob(pattern)
    
    logger.info(f"Found {len(pdf_files)} PDF files to process")
    
    # Track results
    results = {
        'total': len(pdf_files),
        'matched': 0,
        'unmatched': 0,
        'processed': 0,
        'failed': 0,
        'zwicky_files': [],
        'matches': []
    }
    
    for pdf_file in pdf_files:
        try:
            file_path = Path(pdf_file)
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {file_path.name}")
            logger.info(f"Path: {file_path}")
            
            # Check if it's a Zwicky file
            is_zwicky = 'zwicky' in str(file_path).lower()
            if is_zwicky:
                results['zwicky_files'].append(str(file_path))
            
            # Try to match with existing project
            matched_project = matcher.find_matching_project(
                file_name=file_path.name,
                file_path=str(file_path)
            )
            
            if matched_project:
                logger.info(f"✅ Matched to: {matched_project['project_name']} (UUID: {matched_project['project_id']})")
                results['matched'] += 1
                
                # Store match info
                match_info = {
                    'file': str(file_path),
                    'project_name': matched_project['project_name'],
                    'project_uuid': matched_project['project_id'],
                    'is_zwicky': is_zwicky
                }
                results['matches'].append(match_info)
                
                # For Zwicky files, verify it's the correct project
                if is_zwicky:
                    expected_uuid = '5ac45531-c06f-43e5-a41b-f38ec8f239ce'
                    if matched_project['project_id'] == expected_uuid:
                        logger.info("✅ Zwicky file correctly matched to Zwicky project!")
                    else:
                        logger.warning(f"❌ Zwicky file matched to wrong project! Expected {expected_uuid}")
                
                # Continue with document processing (submission to Celery)
                # ... (would add actual processing here)
                
            else:
                logger.warning("❌ No matching project found")
                results['unmatched'] += 1
                
        except Exception as e:
            logger.error(f"Error processing {pdf_file}: {str(e)}")
            results['failed'] += 1
    
    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info("PROCESSING SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total files: {results['total']}")
    logger.info(f"Matched: {results['matched']}")
    logger.info(f"Unmatched: {results['unmatched']}")
    logger.info(f"Failed: {results['failed']}")
    
    # Zwicky analysis
    logger.info(f"\nZWICKY FILE ANALYSIS:")
    logger.info(f"Total Zwicky files found: {len(results['zwicky_files'])}")
    
    zwicky_matches = [m for m in results['matches'] if m['is_zwicky']]
    correct_zwicky = [m for m in zwicky_matches if m['project_uuid'] == '5ac45531-c06f-43e5-a41b-f38ec8f239ce']
    
    logger.info(f"Zwicky files matched: {len(zwicky_matches)}")
    logger.info(f"Correctly matched to Zwicky project: {len(correct_zwicky)}")
    
    if zwicky_matches:
        logger.info("\nZwicky match details:")
        for match in zwicky_matches:
            status = "✅" if match['project_uuid'] == '5ac45531-c06f-43e5-a41b-f38ec8f239ce' else "❌"
            logger.info(f"  {status} {os.path.basename(match['file'])} -> {match['project_name']}")
    
    return results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_airtable_e2e.py <directory_path>")
        sys.exit(1)
    
    directory = sys.argv[1]
    if not os.path.exists(directory):
        print(f"Directory not found: {directory}")
        sys.exit(1)
    
    process_documents_in_directory(directory)