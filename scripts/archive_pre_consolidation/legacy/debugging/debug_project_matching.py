#!/usr/bin/env python3
"""Debug specific projects to see why they're matching."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airtable.airtable_client import AirtableProjectManager

# Initialize
mgr = AirtableProjectManager()
projects = mgr.get_all_projects()

# Check specific problematic projects
problem_projects = [
    "In re Tez Louiz Entertainment, LLC",
    "Rebecca Dee v. New Town at St. Charles Pool",
    "Jessica Zwicky MVA"
]

for name in problem_projects:
    proj = next((p for p in projects if p['project_name'] == name), None)
    if proj:
        print(f"\nProject: {name}")
        print(f"  UUID: {proj.get('project_id', 'N/A')}")
        print(f"  Dropbox name: '{proj.get('dropbox_file_name', '')}'")
        print(f"  Case name: '{proj.get('case_name', '')}'")
        print(f"  Client name: '{proj.get('client_name', '')}'")
        print(f"  File patterns: {proj.get('file_patterns', [])}")
        print(f"  Folder patterns: {proj.get('folder_patterns', [])}")
        
# Also check for projects with empty dropbox names
empty_dropbox = [p for p in projects if not p.get('dropbox_file_name', '').strip()]
print(f"\n\nProjects with empty Dropbox names: {len(empty_dropbox)}")

# Projects with very short dropbox names that might match anything
short_dropbox = [p for p in projects if 0 < len(p.get('dropbox_file_name', '').strip()) < 3]
print(f"Projects with very short Dropbox names: {len(short_dropbox)}")
for proj in short_dropbox[:5]:
    print(f"  - {proj['project_name']}: '{proj.get('dropbox_file_name', '')}'")