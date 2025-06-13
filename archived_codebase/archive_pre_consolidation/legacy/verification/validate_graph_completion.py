#!/usr/bin/env python3
"""Validate graph building completion for documents"""
import sys
import os
import logging
from typing import Dict, List, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GraphValidator:
    """Validates graph building completion for documents."""
    
    def __init__(self):
        self.db = SupabaseManager()
    
    def validate_document_graph(self, document_uuid: str) -> dict:
        """
        Validate that a document has all required relationships.
        
        Returns:
            dict with 'passed' (bool) and 'details' (dict)
        """
        results = {
            'passed': True,
            'document_uuid': document_uuid,
            'details': {
                'structural': {},
                'entities': {},
                'metrics': {},
                'errors': []
            }
        }
        
        try:
            # 1. Check document exists in neo4j_documents
            neo4j_doc = self.db.client.table('neo4j_documents').select(
                'id', 'documentId', 'status', 'project_id'
            ).eq('documentId', document_uuid).maybe_single().execute()
            
            if not neo4j_doc.data:
                results['passed'] = False
                results['details']['errors'].append('Document node missing in neo4j_documents')
                results['details']['structural']['document_node'] = 'MISSING'
                return results
            
            results['details']['structural']['document_node'] = 'EXISTS'
            project_uuid = neo4j_doc.data.get('project_id')
            
            # 2. Check chunks exist
            chunks = self.db.client.table('neo4j_chunks').select(
                'id', 'chunk_uuid', 'chunk_index'
            ).eq('document_uuid', document_uuid).order('chunk_index').execute()
            
            chunk_count = len(chunks.data)
            results['details']['metrics']['chunk_count'] = chunk_count
            
            if chunk_count == 0:
                results['passed'] = False
                results['details']['errors'].append('No chunks found')
                results['details']['structural']['chunks'] = 'MISSING'
                return results
            
            results['details']['structural']['chunks'] = f'EXISTS ({chunk_count})'
            
            # 3. Check relationships
            # Get all relationships involving this document or its chunks
            chunk_uuids = [c['chunk_uuid'] for c in chunks.data]
            all_node_ids = [document_uuid] + chunk_uuids
            
            # Check using the actual camelCase column names
            relationships = self.db.client.table('neo4j_relationships_staging').select(
                'fromNodeId', 'toNodeId', 'relationshipType'
            ).or_(
                f'fromNodeId.in.({",".join(all_node_ids)}),toNodeId.in.({",".join(all_node_ids)})'
            ).execute()
            
            # Categorize relationships
            rel_stats = self._analyze_relationships(
                relationships.data, 
                document_uuid, 
                project_uuid,
                chunk_uuids
            )
            
            # Validate structural relationships
            self._validate_structural_relationships(results, rel_stats, chunk_count)
            
            # 4. Check entities
            self._validate_entities(results, document_uuid, chunk_uuids)
            
            # 5. Calculate final score
            self._calculate_final_score(results)
            
        except Exception as e:
            logger.error(f"Error validating document {document_uuid}: {e}")
            results['passed'] = False
            results['details']['errors'].append(f"Validation error: {str(e)}")
        
        return results
    
    def _analyze_relationships(self, relationships: List[dict], 
                             document_uuid: str, 
                             project_uuid: str,
                             chunk_uuids: List[str]) -> dict:
        """Analyze and categorize relationships."""
        stats = {
            'doc_to_project': 0,
            'chunk_to_doc': 0,
            'sequential_chunks': 0,
            'mention_to_chunk': 0,
            'mention_to_canonical': 0,
            'total': len(relationships)
        }
        
        chunk_set = set(chunk_uuids)
        
        for rel in relationships:
            from_id = rel['fromNodeId']
            to_id = rel['toNodeId']
            rel_type = rel['relationshipType']
            
            # Document to project
            if from_id == document_uuid and to_id == project_uuid and rel_type == 'BELONGS_TO':
                stats['doc_to_project'] += 1
            
            # Chunk to document
            elif from_id in chunk_set and to_id == document_uuid and rel_type == 'BELONGS_TO':
                stats['chunk_to_doc'] += 1
            
            # Sequential chunks
            elif from_id in chunk_set and to_id in chunk_set and rel_type in ['NEXT_CHUNK', 'PREVIOUS_CHUNK']:
                stats['sequential_chunks'] += 1
            
            # Entity relationships
            elif rel_type == 'FOUND_IN':
                stats['mention_to_chunk'] += 1
            elif rel_type == 'MEMBER_OF_CLUSTER':
                stats['mention_to_canonical'] += 1
        
        return stats
    
    def _validate_structural_relationships(self, results: dict, rel_stats: dict, chunk_count: int):
        """Validate structural relationships meet requirements."""
        # Document to project
        if rel_stats['doc_to_project'] >= 1:
            results['details']['structural']['document_to_project'] = 'PASS'
        else:
            results['details']['structural']['document_to_project'] = f'FAIL (found {rel_stats["doc_to_project"]})'
            results['passed'] = False
            results['details']['errors'].append('Missing document-to-project relationship')
        
        # Chunks to document
        if rel_stats['chunk_to_doc'] >= chunk_count:
            results['details']['structural']['chunks_to_document'] = 'PASS'
        else:
            results['details']['structural']['chunks_to_document'] = f'FAIL (found {rel_stats["chunk_to_doc"]}/{chunk_count})'
            results['passed'] = False
            results['details']['errors'].append(f'Missing chunk-to-document relationships: {chunk_count - rel_stats["chunk_to_doc"]}')
        
        # Sequential chunks (should have 2*(chunk_count-1) for bidirectional)
        expected_sequential = 2 * (chunk_count - 1) if chunk_count > 1 else 0
        if rel_stats['sequential_chunks'] >= expected_sequential:
            results['details']['structural']['sequential_chunks'] = 'PASS'
        else:
            results['details']['structural']['sequential_chunks'] = f'WARN (found {rel_stats["sequential_chunks"]}/{expected_sequential})'
            # Don't fail on this, just warn
        
        results['details']['metrics']['relationship_stats'] = rel_stats
    
    def _validate_entities(self, results: dict, document_uuid: str, chunk_uuids: List[str]):
        """Validate entity extraction and relationships."""
        # Check entity mentions
        mentions = self.db.client.table('neo4j_entity_mentions').select(
            'id', 'mention_uuid', 'chunk_uuid', 'resolved_canonical_id'
        ).in_('chunk_uuid', chunk_uuids).execute()
        
        mention_count = len(mentions.data)
        results['details']['metrics']['entity_mention_count'] = mention_count
        
        # Check canonical entities
        canonical = self.db.client.table('neo4j_canonical_entities').select(
            'id', 'canonical_id', 'entity_type'
        ).eq('source_document_id', document_uuid).execute()
        
        canonical_count = len(canonical.data)
        results['details']['metrics']['canonical_entity_count'] = canonical_count
        
        # Validate entity requirements
        if canonical_count > 0:
            results['details']['entities']['canonical_entities'] = f'PASS ({canonical_count} found)'
        else:
            results['details']['entities']['canonical_entities'] = 'FAIL (0 found)'
            results['passed'] = False
            results['details']['errors'].append('No canonical entities found')
        
        # Check resolution rate
        if mention_count > 0:
            resolved_count = sum(1 for m in mentions.data if m.get('resolved_canonical_id'))
            resolution_rate = (resolved_count / mention_count) * 100
            results['details']['metrics']['entity_resolution_rate'] = f"{resolution_rate:.1f}%"
            
            if resolution_rate >= 70:
                results['details']['entities']['resolution_rate'] = f'PASS ({resolution_rate:.1f}%)'
            else:
                results['details']['entities']['resolution_rate'] = f'WARN ({resolution_rate:.1f}%)'
    
    def _calculate_final_score(self, results: dict):
        """Calculate final validation score."""
        # Count passes and fails
        pass_count = 0
        fail_count = 0
        
        for category in ['structural', 'entities']:
            for key, value in results['details'][category].items():
                if isinstance(value, str):
                    if value.startswith('PASS'):
                        pass_count += 1
                    elif value.startswith('FAIL'):
                        fail_count += 1
        
        total_checks = pass_count + fail_count
        if total_checks > 0:
            results['details']['metrics']['validation_score'] = f"{(pass_count / total_checks) * 100:.1f}%"
        
        # Add summary
        results['summary'] = {
            'total_checks': total_checks,
            'passed': pass_count,
            'failed': fail_count,
            'errors': len(results['details']['errors'])
        }
    
    def validate_batch(self, document_uuids: List[str]) -> dict:
        """Validate multiple documents and provide summary."""
        batch_results = {
            'total': len(document_uuids),
            'passed': 0,
            'failed': 0,
            'documents': []
        }
        
        for doc_uuid in document_uuids:
            result = self.validate_document_graph(doc_uuid)
            batch_results['documents'].append(result)
            
            if result['passed']:
                batch_results['passed'] += 1
            else:
                batch_results['failed'] += 1
        
        batch_results['success_rate'] = (batch_results['passed'] / batch_results['total'] * 100) if batch_results['total'] > 0 else 0
        
        return batch_results
    
    def print_validation_report(self, result: dict):
        """Print a formatted validation report."""
        print(f"\n{'='*80}")
        print(f"GRAPH VALIDATION REPORT - Document: {result['document_uuid'][:8]}...")
        print(f"{'='*80}")
        
        print(f"\nOVERALL: {'PASSED' if result['passed'] else 'FAILED'}")
        
        if result.get('summary'):
            print(f"\nSummary:")
            print(f"  Total Checks: {result['summary']['total_checks']}")
            print(f"  Passed: {result['summary']['passed']}")
            print(f"  Failed: {result['summary']['failed']}")
            print(f"  Errors: {result['summary']['errors']}")
        
        print(f"\nStructural Validation:")
        for key, value in result['details']['structural'].items():
            status_icon = "✓" if value.startswith('PASS') else "✗" if value.startswith('FAIL') else "⚠"
            print(f"  {status_icon} {key}: {value}")
        
        print(f"\nEntity Validation:")
        for key, value in result['details']['entities'].items():
            status_icon = "✓" if value.startswith('PASS') else "✗" if value.startswith('FAIL') else "⚠"
            print(f"  {status_icon} {key}: {value}")
        
        print(f"\nMetrics:")
        for key, value in result['details']['metrics'].items():
            print(f"  - {key}: {value}")
        
        if result['details']['errors']:
            print(f"\nErrors:")
            for error in result['details']['errors']:
                print(f"  ! {error}")
        
        print(f"\n{'='*80}")

def main():
    """Main function for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate graph building completion")
    parser.add_argument('document_uuid', nargs='?', help="Document UUID to validate")
    parser.add_argument('--batch', action='store_true', help="Validate all completed documents")
    parser.add_argument('--status', default='completed', help="Status to filter for batch validation")
    
    args = parser.parse_args()
    
    validator = GraphValidator()
    
    if args.batch:
        # Get all documents with specified status
        db = SupabaseManager()
        docs = db.client.table('source_documents').select(
            'document_uuid', 'original_file_name'
        ).eq('celery_status', args.status).execute()
        
        if not docs.data:
            print(f"No documents found with status '{args.status}'")
            return
        
        print(f"Validating {len(docs.data)} documents with status '{args.status}'...")
        
        doc_uuids = [d['document_uuid'] for d in docs.data]
        batch_results = validator.validate_batch(doc_uuids)
        
        print(f"\nBatch Validation Summary:")
        print(f"  Total: {batch_results['total']}")
        print(f"  Passed: {batch_results['passed']}")
        print(f"  Failed: {batch_results['failed']}")
        print(f"  Success Rate: {batch_results['success_rate']:.1f}%")
        
        # Show failed documents
        if batch_results['failed'] > 0:
            print(f"\nFailed Documents:")
            for doc in batch_results['documents']:
                if not doc['passed']:
                    print(f"  - {doc['document_uuid']}: {', '.join(doc['details']['errors'])}")
    
    elif args.document_uuid:
        # Validate single document
        result = validator.validate_document_graph(args.document_uuid)
        validator.print_validation_report(result)
    
    else:
        parser.print_help()

if __name__ == "__main__":
    main()