#!/usr/bin/env python3
"""
Check complete status of all 10 documents from project_fk_id = 18 (Paul Michael Acuity Batch)
Shows document status, processing stages, errors, and completion summary
"""

import os
import sys
from datetime import datetime
from collections import defaultdict
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from sqlalchemy import text
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Pipeline stages in order
PIPELINE_STAGES = [
    'ocr_extraction',
    'text_chunking', 
    'entity_extraction',
    'entity_resolution',
    'relationship_extraction',
    'finalization'
]

# Stage display names
STAGE_NAMES = {
    'ocr_extraction': 'OCR Extraction',
    'text_chunking': 'Text Chunking',
    'entity_extraction': 'Entity Extraction', 
    'entity_resolution': 'Entity Resolution',
    'relationship_extraction': 'Relationship Extraction',
    'finalization': 'Finalization'
}

def check_batch_status():
    """Check status of all documents in project_fk_id = 18"""
    
    # Initialize database manager
    db = DatabaseManager()
    
    # Get session
    session_gen = db.get_session()
    session = next(session_gen)
    
    try:
        # 1. Get all source documents for project_fk_id = 18
        print("\n" + "="*80)
        print("PAUL MICHAEL ACUITY BATCH STATUS CHECK (Project ID: 18)")
        print("="*80)
        
        result = session.execute(text("""
            SELECT document_uuid, original_file_name, created_at, status, s3_key, 
                   s3_bucket, updated_at, file_path
            FROM source_documents 
            WHERE project_fk_id = 18
            ORDER BY created_at
        """))
        
        documents = result.fetchall()
        
        print(f"\nFound {len(documents)} documents in project")
        print("-" * 80)
        
        # Track overall statistics
        stats = {
            'total': len(documents),
            'completed': 0,
            'in_progress': 0,
            'failed': 0,
            'stuck': 0,
            'by_stage': defaultdict(lambda: {'completed': 0, 'failed': 0, 'in_progress': 0})
        }
        
        completed_docs = []
        stuck_docs = []
        failed_docs = []
        
        # 2. Check each document's status
        for idx, doc in enumerate(documents, 1):
            doc_uuid = doc[0]
            filename = doc[1]
            created_at = doc[2]
            status = doc[3]
            s3_key = doc[4]
            s3_bucket = doc[5]
            s3_location = f"s3://{s3_bucket}/{s3_key}" if s3_bucket and s3_key else "N/A"
            
            print(f"\n[{idx}] Document: {doc_uuid}")
            print(f"    Filename: {filename}")
            print(f"    Created: {created_at}")
            print(f"    Status: {status}")
            print(f"    S3 Location: {s3_location}")
            
            # 3. Check processing tasks for this document
            task_result = session.execute(text("""
                SELECT task_type, status, error_message, created_at, completed_at
                FROM processing_tasks 
                WHERE document_id = :doc_id
                ORDER BY created_at
            """), {"doc_id": doc_uuid})
            
            tasks = task_result.fetchall()
            
            if not tasks:
                print("    ⚠️  NO PROCESSING TASKS FOUND")
                stats['stuck'] += 1
                stuck_docs.append((doc_uuid, filename, "No processing started"))
                continue
            
            print(f"\n    Processing Tasks ({len(tasks)} total):")
            
            # Group tasks by stage
            stage_tasks = defaultdict(list)
            for task in tasks:
                task_type = task[0]
                stage_tasks[task_type].append(task)
            
            # Check each pipeline stage
            completed_stages = []
            last_stage = None
            has_error = False
            
            for stage in PIPELINE_STAGES:
                stage_name = STAGE_NAMES.get(stage, stage)
                if stage in stage_tasks:
                    # Get most recent task for this stage
                    stage_task = sorted(stage_tasks[stage], key=lambda x: x[3])[-1]
                    task_status = stage_task[1]
                    error_msg = stage_task[2]
                    task_created = stage_task[3]
                    task_completed = stage_task[4]
                    
                    status_icon = {
                        'completed': '✅',
                        'failed': '❌', 
                        'in_progress': '🔄',
                        'pending': '⏳'
                    }.get(task_status, '❓')
                    
                    print(f"    {status_icon} {stage_name}: {task_status}")
                    
                    # Show error if failed
                    if task_status == 'failed' and error_msg:
                        print(f"       Error: {error_msg[:100]}...")
                        has_error = True
                    
                    # Show timing
                    if task_completed:
                        duration = (task_completed - task_created).total_seconds()
                        print(f"       Duration: {duration:.1f}s")
                    
                    # Update stats
                    stats['by_stage'][stage][task_status] += 1
                    
                    if task_status == 'completed':
                        completed_stages.append(stage)
                        last_stage = stage
                    elif task_status == 'failed':
                        failed_docs.append((doc_uuid, filename, stage))
                        
                else:
                    print(f"    ⏸️  {stage_name}: Not started")
            
            # 4. Check additional data
            print("\n    Data Summary:")
            
            # Check chunks
            chunk_result = session.execute(text("""
                SELECT COUNT(*) FROM document_chunks 
                WHERE document_uuid = :doc_id
            """), {"doc_id": doc_uuid})
            chunk_count = chunk_result.scalar()
            print(f"    • Chunks: {chunk_count}")
            
            # Check entities
            entity_result = session.execute(text("""
                SELECT COUNT(*) FROM entity_mentions 
                WHERE document_uuid = :doc_id
            """), {"doc_id": doc_uuid})
            entity_count = entity_result.scalar()
            print(f"    • Entity Mentions: {entity_count}")
            
            # Check canonical entities
            canonical_result = session.execute(text("""
                SELECT COUNT(DISTINCT em.canonical_entity_uuid)
                FROM entity_mentions em
                WHERE em.document_uuid = :doc_id AND em.canonical_entity_uuid IS NOT NULL
            """), {"doc_id": doc_uuid})
            canonical_count = canonical_result.scalar()
            print(f"    • Canonical Entities: {canonical_count}")
            
            # Check relationships (through entity mentions)
            relationship_result = session.execute(text("""
                SELECT COUNT(DISTINCT rs.id) 
                FROM relationship_staging rs
                JOIN entity_mentions em_source ON rs.source_entity_uuid = em_source.canonical_entity_uuid
                WHERE em_source.document_uuid = :doc_id
            """), {"doc_id": doc_uuid})
            relationship_count = relationship_result.scalar() or 0
            print(f"    • Relationships: {relationship_count}")
            
            # 5. Determine overall status
            if len(completed_stages) == len(PIPELINE_STAGES):
                print("\n    ✅ FULLY COMPLETED")
                stats['completed'] += 1
                completed_docs.append((doc_uuid, filename))
            elif has_error:
                print("\n    ❌ FAILED")
                stats['failed'] += 1
            elif completed_stages:
                print(f"\n    🔄 IN PROGRESS (Last completed: {STAGE_NAMES.get(last_stage, last_stage)})")
                stats['in_progress'] += 1
                if last_stage and PIPELINE_STAGES.index(last_stage) < len(PIPELINE_STAGES) - 1:
                    next_stage = PIPELINE_STAGES[PIPELINE_STAGES.index(last_stage) + 1]
                    stuck_docs.append((doc_uuid, filename, f"Stuck after {STAGE_NAMES.get(last_stage, last_stage)}, before {STAGE_NAMES.get(next_stage, next_stage)}"))
            else:
                print("\n    ⚠️  STUCK (No processing started)")
                stats['stuck'] += 1
                stuck_docs.append((doc_uuid, filename, "No processing started"))
        
        # Print summary
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        
        print(f"\nTotal Documents: {stats['total']}")
        print(f"✅ Completed: {stats['completed']} ({stats['completed']/stats['total']*100:.1f}%)")
        print(f"🔄 In Progress: {stats['in_progress']} ({stats['in_progress']/stats['total']*100:.1f}%)")
        print(f"❌ Failed: {stats['failed']} ({stats['failed']/stats['total']*100:.1f}%)")
        print(f"⚠️  Stuck: {stats['stuck']} ({stats['stuck']/stats['total']*100:.1f}%)")
        
        print("\nStage-by-Stage Breakdown:")
        for stage in PIPELINE_STAGES:
            stage_stats = stats['by_stage'][stage]
            total_stage = sum(stage_stats.values())
            print(f"\n{STAGE_NAMES.get(stage, stage)}:")
            if total_stage > 0:
                print(f"  • Completed: {stage_stats['completed']} ({stage_stats['completed']/total_stage*100:.1f}%)")
                print(f"  • Failed: {stage_stats['failed']} ({stage_stats['failed']/total_stage*100:.1f}%)")
                print(f"  • In Progress: {stage_stats['in_progress']} ({stage_stats['in_progress']/total_stage*100:.1f}%)")
            else:
                print("  • Not reached")
        
        # List problematic documents
        if stuck_docs:
            print("\n" + "-"*80)
            print("STUCK DOCUMENTS:")
            for doc_uuid, filename, reason in stuck_docs:
                print(f"\n• {filename}")
                print(f"  UUID: {doc_uuid}")
                print(f"  Reason: {reason}")
        
        if failed_docs:
            print("\n" + "-"*80)
            print("FAILED DOCUMENTS:")
            for doc_uuid, filename, stage in failed_docs:
                print(f"\n• {filename}")
                print(f"  UUID: {doc_uuid}")
                print(f"  Failed at: {STAGE_NAMES.get(stage, stage)}")
        
        if completed_docs:
            print("\n" + "-"*80)
            print("COMPLETED DOCUMENTS:")
            for doc_uuid, filename in completed_docs:
                print(f"\n• {filename}")
                print(f"  UUID: {doc_uuid}")
        
        # Save detailed report
        report = {
            'timestamp': datetime.now().isoformat(),
            'project_id': 18,
            'summary': {
                'total': stats['total'],
                'completed': stats['completed'],
                'in_progress': stats['in_progress'],
                'failed': stats['failed'],
                'stuck': stats['stuck']
            },
            'documents': []
        }
        
        for doc in documents:
            doc_info = {
                'document_uuid': str(doc[0]),  # Convert UUID to string
                'filename': doc[1],
                'status': doc[3],
                'created_at': doc[2].isoformat() if doc[2] else None
            }
            report['documents'].append(doc_info)
        
        report_file = f"batch_status_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n\nDetailed report saved to: {report_file}")
    
    finally:
        session.close()

if __name__ == "__main__":
    try:
        check_batch_status()
    except Exception as e:
        logger.error(f"Error checking batch status: {e}", exc_info=True)
        sys.exit(1)