#!/usr/bin/env python3
"""
Debug helper for investigating stuck or failed documents in Celery pipeline
"""
import os
import sys
import json
from datetime import datetime
from celery.result import AsyncResult

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager, CacheKeys
from scripts.celery_app import app

class CeleryDocumentDebugger:
    """Debug tools for Celery document processing"""
    
    def __init__(self):
        self.db = SupabaseManager()
        self.redis_mgr = get_redis_manager()
        self.redis_client = self.redis_mgr.get_client() if self.redis_mgr else None
    
    def debug_by_uuid(self, doc_uuid: str):
        """Debug document by UUID"""
        print(f"\n🔍 Debugging Document UUID: {doc_uuid}")
        print("=" * 80)
        
        # 1. Check source_documents
        print("\n📄 Source Document Status:")
        source_doc = self.db.client.table('source_documents')\
            .select('*')\
            .eq('document_uuid', doc_uuid)\
            .maybe_single()\
            .execute()
        
        if source_doc.data:
            self._print_important_fields(source_doc.data, [
                'id', 'celery_status', 'celery_task_id', 
                'initial_processing_status', 'error_message',
                'created_at', 'last_modified_at'
            ])
            
            # Check Celery task status if available
            if source_doc.data.get('celery_task_id'):
                self._check_celery_task(source_doc.data['celery_task_id'])
        else:
            print("  ❌ Document not found in source_documents")
            return
        
        # 2. Check Redis state
        print("\n💾 Redis State:")
        if self.redis_client:
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=doc_uuid)
            state_data = self.redis_client.hgetall(state_key)
            
            if state_data:
                for k, v in state_data.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    val = v.decode() if isinstance(v, bytes) else v
                    
                    # Try to parse JSON values
                    try:
                        val_parsed = json.loads(val)
                        print(f"  {key}:")
                        print(f"    {json.dumps(val_parsed, indent=4)}")
                    except:
                        print(f"  {key}: {val}")
            else:
                print("  No Redis state found")
        
        # 3. Check related tables
        self._check_related_tables(doc_uuid, source_doc.data.get('id'))
        
        # 4. Check Textract jobs if PDF
        if source_doc.data.get('detected_file_type') == 'pdf':
            self._check_textract_job(doc_uuid)
        
        # 5. Provide recommendations
        self._provide_recommendations(source_doc.data)
    
    def debug_by_file_name(self, file_name: str):
        """Debug document by file name"""
        print(f"\n🔍 Searching for file: {file_name}")
        
        docs = self.db.client.table('source_documents')\
            .select('document_uuid, original_file_name, celery_status')\
            .ilike('original_file_name', f'%{file_name}%')\
            .execute()
        
        if not docs.data:
            print("  ❌ No documents found with that file name")
            return
        
        if len(docs.data) == 1:
            self.debug_by_uuid(docs.data[0]['document_uuid'])
        else:
            print(f"\n  Found {len(docs.data)} matching documents:")
            for doc in docs.data:
                print(f"    - {doc['original_file_name']} (UUID: {doc['document_uuid'][:8]}..., Status: {doc['celery_status']})")
            print("\n  Please specify exact UUID to debug")
    
    def _check_celery_task(self, task_id: str):
        """Check Celery task status"""
        print(f"\n🎯 Celery Task Status (ID: {task_id[:8]}...):")
        try:
            result = AsyncResult(task_id, app=app)
            print(f"  State: {result.state}")
            print(f"  Ready: {result.ready()}")
            print(f"  Successful: {result.successful()}")
            print(f"  Failed: {result.failed()}")
            
            if result.info:
                print(f"  Info: {result.info}")
            
            if result.traceback:
                print(f"  Traceback:\n{result.traceback}")
                
        except Exception as e:
            print(f"  ❌ Error checking task: {e}")
    
    def _check_related_tables(self, doc_uuid: str, source_doc_id: int):
        """Check all related tables for document"""
        print("\n🔗 Related Database Records:")
        
        # Neo4j documents
        neo4j_doc = self.db.client.table('neo4j_documents')\
            .select('id, processingStatus, name')\
            .eq('sourceDocumentUuid', doc_uuid)\
            .maybe_single()\
            .execute()
        
        if neo4j_doc.data:
            print(f"\n  neo4j_documents:")
            print(f"    ID: {neo4j_doc.data['id']}")
            print(f"    Status: {neo4j_doc.data['processingStatus']}")
            print(f"    Name: {neo4j_doc.data['name']}")
            
            # Check chunks
            chunks = self.db.client.table('neo4j_chunks')\
                .select('id', count='exact')\
                .eq('document_id', neo4j_doc.data['id'])\
                .execute()
            
            print(f"\n  neo4j_chunks: {chunks.count} chunks")
            
            if chunks.count > 0:
                # Check entity mentions
                chunk_ids = [c['id'] for c in chunks.data[:10]]  # Sample first 10
                mentions = self.db.client.table('neo4j_entity_mentions')\
                    .select('id', count='exact')\
                    .in_('chunk_id', chunk_ids)\
                    .execute()
                
                print(f"  neo4j_entity_mentions: {mentions.count} mentions (sample)")
                
                # Check canonical entities
                canonicals = self.db.client.table('neo4j_canonical_entities')\
                    .select('id', count='exact')\
                    .eq('document_id', neo4j_doc.data['id'])\
                    .execute()
                
                print(f"  neo4j_canonical_entities: {canonicals.count} entities")
                
                # Check relationships
                rels = self.db.client.table('neo4j_relationship_staging')\
                    .select('id', count='exact')\
                    .eq('from_id', doc_uuid)\
                    .execute()
                
                print(f"  neo4j_relationship_staging: {rels.count} relationships")
        else:
            print("  ❌ No neo4j_documents record found")
    
    def _check_textract_job(self, doc_uuid: str):
        """Check Textract job status"""
        print("\n📄 Textract Job Status:")
        
        job = self.db.client.table('textract_jobs')\
            .select('*')\
            .eq('source_document_uuid', doc_uuid)\
            .order('created_at', desc=True)\
            .limit(1)\
            .maybe_single()\
            .execute()
        
        if job.data:
            self._print_important_fields(job.data, [
                'job_id', 'job_status', 'job_type',
                'error_message', 'created_at', 'updated_at'
            ])
        else:
            print("  No Textract job found")
    
    def _print_important_fields(self, data: dict, fields: list):
        """Print selected fields from a record"""
        for field in fields:
            if field in data and data[field] is not None:
                print(f"  {field}: {data[field]}")
    
    def _provide_recommendations(self, doc_data: dict):
        """Provide debugging recommendations based on status"""
        print("\n💡 Recommendations:")
        
        status = doc_data.get('celery_status', 'unknown')
        
        if status == 'pending':
            print("  - Document hasn't been picked up by Celery yet")
            print("  - Check if Celery workers are running: celery -A scripts.celery_app status")
            print("  - Try resubmitting: python scripts/celery_submission.py")
            
        elif status == 'ocr_processing':
            print("  - Document stuck in OCR stage")
            print("  - Check Textract job status above")
            print("  - Check AWS credentials and S3 permissions")
            print("  - Look for errors in Celery worker logs")
            
        elif status in ['ocr_failed', 'text_failed', 'entity_failed', 'resolution_failed', 'graph_failed']:
            print(f"  - Document failed at {status} stage")
            print(f"  - Error: {doc_data.get('error_message', 'No error message')}")
            print("  - Check Celery worker logs for full traceback")
            print("  - May need to manually reset status and retry")
            
        elif status == 'completed':
            print("  - Document processing completed successfully")
            print("  - Check related tables above for output verification")
            
        else:
            print(f"  - Document in unexpected status: {status}")
            print("  - Check Redis state for more details")
            print("  - Review Celery task chain implementation")
    
    def list_stuck_documents(self, minutes: int = 30):
        """List all documents stuck in processing"""
        print(f"\n📋 Documents stuck for more than {minutes} minutes:")
        print("=" * 80)
        
        from datetime import timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        
        stuck = self.db.client.table('source_documents')\
            .select('document_uuid, file_name, celery_status, last_modified_at')\
            .in_('celery_status', [
                'processing', 'ocr_processing', 'text_processing',
                'entity_extraction', 'entity_resolution', 'graph_building'
            ])\
            .lt('last_modified_at', cutoff.isoformat())\
            .execute()
        
        if stuck.data:
            for doc in stuck.data:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(
                    doc['last_modified_at'].replace('Z', '+00:00')
                )
                print(f"\n  📄 {doc['file_name']}")
                print(f"     UUID: {doc['document_uuid'][:8]}...")
                print(f"     Status: {doc['celery_status']}")
                print(f"     Stuck for: {age.total_seconds()/60:.1f} minutes")
        else:
            print("  ✅ No stuck documents found")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Debug Celery document processing')
    parser.add_argument('--uuid', help='Document UUID to debug')
    parser.add_argument('--file', help='File name to search for')
    parser.add_argument('--stuck', type=int, metavar='MINUTES',
                       help='List documents stuck for N minutes')
    
    args = parser.parse_args()
    
    debugger = CeleryDocumentDebugger()
    
    if args.uuid:
        debugger.debug_by_uuid(args.uuid)
    elif args.file:
        debugger.debug_by_file_name(args.file)
    elif args.stuck:
        debugger.list_stuck_documents(args.stuck)
    else:
        print("Usage:")
        print("  Debug by UUID:  python debug_celery_document.py --uuid DOC_UUID")
        print("  Debug by file:  python debug_celery_document.py --file filename.pdf")
        print("  List stuck:     python debug_celery_document.py --stuck 30")


if __name__ == "__main__":
    main()