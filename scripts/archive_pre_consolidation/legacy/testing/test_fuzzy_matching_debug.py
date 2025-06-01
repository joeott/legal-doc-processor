#!/usr/bin/env python3
"""Debug fuzzy matching to understand why all matches get score 130."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airtable.fuzzy_matcher import FuzzyMatcher
import logging

# Set up logging with DEBUG level
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Test document
test_file = "Jessica Zwicky Ott Law Firm Retainer personal injury - signed.pdf"
test_path = "input/Zwicky, Jessica/Client Docs/Jessica Zwicky Ott Law Firm Retainer personal injury - signed.pdf"

print(f"Testing file: {test_file}")
print(f"Full path: {test_path}")
print("\n" + "="*80 + "\n")

# Initialize matcher
matcher = FuzzyMatcher()

# Get all projects and show matches
projects = matcher.airtable_mgr.get_all_projects()
print(f"Total projects: {len(projects)}")

# Look for Zwicky project specifically
zwicky_projects = [p for p in projects if 'zwicky' in p.get('project_name', '').lower()]
print(f"\nProjects with 'Zwicky' in name: {len(zwicky_projects)}")
for proj in zwicky_projects:
    print(f"  - {proj['project_name']} (UUID: {proj['project_id']})")
    print(f"    Case name: {proj.get('case_name', 'N/A')}")
    print(f"    Dropbox name: {proj.get('dropbox_file_name', 'N/A')}")
    print(f"    File patterns: {proj.get('file_patterns', [])}")
    print(f"    Folder patterns: {proj.get('folder_patterns', [])}")

print("\n" + "="*80 + "\n")

# Test matching with different thresholds
for threshold in [130, 100, 80, 50]:
    print(f"\nTesting with threshold: {threshold}")
    match = matcher.find_matching_project(
        file_name=test_file,
        file_path=test_path,
        threshold=threshold
    )
    if match:
        print(f"  ✅ Matched: {match['project_name']} (score: {match.get('score', 'N/A')})")
    else:
        print(f"  ❌ No match found")