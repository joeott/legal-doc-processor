#!/usr/bin/env python3
# run_production_test.py

import json
import time
import os
from datetime import datetime
from scripts.pdf_tasks import process_pdf_batch, process_pdf_document
from scripts.celery_app import app as celery_app
from celery import group
import sys

# Load manifest
manifest_path = 'production_test_manifest_20250604_142117.json'
print(f"Loading manifest from: {manifest_path}")
with open(manifest_path, 'r') as f:
    manifest = json.load(f)

print(f"Loaded manifest with {len(manifest['documents'])} documents")
print(f"Manifest ID: {manifest['id']}")
print(f"Project: {manifest['project_uuid']}")

# Initialize monitoring data
start_time = time.time()
all_results = []
batch_size = 10  # Process 10 documents at a time

# Create batches
batches = []
for i in range(0, len(manifest['documents']), batch_size):
    batch = manifest['documents'][i:i+batch_size]
    batches.append(batch)

print(f"Processing {len(manifest['documents'])} documents in {len(batches)} batches")
print(f"Batch size: {batch_size} documents")
print(f"Concurrency: 5 workers per batch")
print("="*60)

# Process each batch
for i, batch in enumerate(batches):
    print(f"\n{'='*60}")
    print(f"Processing Batch {i+1}/{len(batches)} ({len(batch)} documents)")
    print(f"{'='*60}")
    
    batch_start = time.time()
    
    # Process batch with parallel workers
    try:
        # Create a group of tasks for parallel processing
        job = group([
            process_pdf_document.s(
                doc['document_uuid'],
                doc['file_path'],
                doc['project_uuid'],
                doc['metadata']
            ) for doc in batch
        ])
        
        # Execute the group and wait for results
        result = job.apply_async()
        batch_results = result.get(timeout=600)  # 10 minute timeout per batch
        
        all_results.extend(batch_results)
        
        # Calculate statistics
        elapsed = time.time() - batch_start
        docs_processed = (i + 1) * batch_size
        total_elapsed = time.time() - start_time
        rate = docs_processed / (total_elapsed / 3600) if total_elapsed > 0 else 0
        eta_hours = (len(manifest['documents']) - docs_processed) / rate if rate > 0 else 0
        
        # Count successes
        successful = sum(1 for r in all_results if r and r.get('status') == 'completed')
        failed = sum(1 for r in all_results if r and r.get('status') == 'failed')
        
        print(f"\nBatch {i+1} completed in {elapsed:.1f} seconds")
        print(f"Progress: {docs_processed}/{len(manifest['documents'])} documents")
        print(f"Success Rate: {(successful/len(all_results)*100) if all_results else 0:.1f}%")
        print(f"Throughput: {rate:.1f} documents/hour")
        print(f"ETA: {eta_hours:.1f} hours ({eta_hours*60:.1f} minutes)")
        
    except Exception as e:
        print(f"ERROR in batch {i+1}: {str(e)}")
        # Continue with next batch
        continue

# Final statistics
total_time = time.time() - start_time
successful = sum(1 for r in all_results if r and r.get('status') == 'completed')
failed = len(all_results) - successful

print(f"\n{'='*60}")
print(f"PRODUCTION TEST COMPLETE")
print(f"{'='*60}")
print(f"Total Documents: {len(manifest['documents'])}")
print(f"Successful: {successful} ({successful/len(manifest['documents'])*100:.1f}%)")
print(f"Failed: {failed}")
print(f"Total Time: {total_time/60:.1f} minutes")
print(f"Average Throughput: {len(manifest['documents'])/(total_time/3600):.1f} documents/hour")
print(f"{'='*60}")

# Save results
results_data = {
    'manifest_id': manifest['id'],
    'start_time': datetime.fromtimestamp(start_time).isoformat(),
    'end_time': datetime.now().isoformat(),
    'total_time_seconds': total_time,
    'statistics': {
        'total_documents': len(manifest['documents']),
        'successful': successful,
        'failed': failed,
        'success_rate': successful/len(manifest['documents'])*100 if manifest['documents'] else 0,
        'avg_throughput': len(manifest['documents'])/(total_time/3600) if total_time > 0 else 0
    },
    'batch_results': all_results
}

output_path = f'production_test_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
with open(output_path, 'w') as f:
    json.dump(results_data, f, indent=2)

print(f"\nResults saved to: {output_path}")

# Check if we met success criteria
if results_data['statistics']['success_rate'] >= 99:
    print("\n✅ SUCCESS: Achieved ≥99% success rate!")
else:
    print(f"\n❌ FAILED: Only achieved {results_data['statistics']['success_rate']:.1f}% success rate")

if total_time < 900:  # 15 minutes
    print("✅ SUCCESS: Completed in under 15 minutes!")
else:
    print(f"❌ FAILED: Took {total_time/60:.1f} minutes (target: <15 minutes)")