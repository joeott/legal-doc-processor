#!/usr/bin/env python3
# create_production_manifest.py

import json
import uuid
from pathlib import Path
from datetime import datetime

# Load discovered documents
try:
    with open('paul_michael_discovery_20250604_032359.json', 'r') as f:
        discovery = json.load(f)
    print(f"Loaded discovery data with {len(discovery['documents'])} documents")
except FileNotFoundError:
    print("Discovery file not found. Looking for alternative...")
    # Try alternative paths
    discovery_files = list(Path('.').glob('paul_michael_discovery_*.json'))
    if discovery_files:
        with open(discovery_files[0], 'r') as f:
            discovery = json.load(f)
        print(f"Loaded discovery data from {discovery_files[0]}")
    else:
        print("No discovery files found!")
        exit(1)

# Create processing manifest with all documents
manifest = {
    'id': f'production_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
    'name': 'Final Production Verification Test',
    'project_uuid': str(uuid.uuid4()),  # Generate a valid UUID for the project
    'documents': []
}

for doc in discovery['documents']:
    manifest['documents'].append({
        'document_uuid': str(uuid.uuid4()),
        'file_path': doc['absolute_path'],
        'project_uuid': manifest['project_uuid'],
        'metadata': {
            'original_filename': doc['filename'],
            'size_mb': doc['size_mb'],
            'sha256': doc['sha256_hash'],
            'category': doc.get('size_category', 'unknown')
        }
    })

# Save manifest
output_path = f'production_test_manifest_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
with open(output_path, 'w') as f:
    json.dump(manifest, f, indent=2)

print(f"Created manifest with {len(manifest['documents'])} documents")
print(f"Saved to: {output_path}")

# Print summary statistics
total_size_mb = sum(doc['size_mb'] for doc in discovery['documents'])
large_files = [doc for doc in discovery['documents'] if doc['size_mb'] > 500]

print(f"\nManifest Summary:")
print(f"- Total documents: {len(manifest['documents'])}")
print(f"- Total size: {total_size_mb:.1f} MB")
print(f"- Large files (>500MB): {len(large_files)}")
print(f"- Project UUID: {manifest['project_uuid']}")
print(f"- Manifest ID: {manifest['id']}")