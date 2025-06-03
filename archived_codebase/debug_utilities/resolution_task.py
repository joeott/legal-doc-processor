#!/usr/bin/env python3
"""
Standalone entity resolution task that doesn't inherit from PDFTask
Handles entity resolution and persistence without EntityService complications
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from celery import Task
from scripts.celery_app import app
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.entity_resolution_fixes import (
    resolve_entities_simple,
    save_canonical_entities_to_db,
    update_entity_mentions_with_canonical
)
from sqlalchemy import text as sql_text
import uuid

logger = logging.getLogger(__name__)


def update_document_state(document_uuid: str, stage: str, status: str, metadata: Dict[str, Any] = None):
    """Update document processing state in Redis"""
    redis_manager = get_redis_manager()
    state_key = CacheKeys.DOC_STATE.format(document_uuid=document_uuid)
    
    state_data = redis_manager.get_dict(state_key) or {}
    
    enhanced_metadata = metadata or {}
    enhanced_metadata['updated_at'] = datetime.utcnow().isoformat()
    enhanced_metadata['stage'] = stage
    
    state_data[stage] = {
        'status': status,
        'timestamp': datetime.utcnow().isoformat(),
        'metadata': enhanced_metadata
    }
    
    state_data['last_update'] = {
        'stage': stage,
        'status': status,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    redis_manager.store_dict(state_key, state_data, ttl=86400)
    logger.info(f"Updated state for document {document_uuid}: {stage} -> {status}")


class SimpleResolutionTask(Task):
    """Simple task class without EntityService complications"""
    _db_manager = None
    
    @property
    def db_manager(self):
        if self._db_manager is None:
            self._db_manager = DatabaseManager(validate_conformance=False)
        return self._db_manager


@app.task(bind=True, base=SimpleResolutionTask, max_retries=3, default_retry_delay=60, queue='entity')
def resolve_entities_standalone(self, document_uuid: str, entity_mentions: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Standalone entity resolution task that:
    1. Takes entity mentions from parameters or cache
    2. Saves entity mentions to database if not already saved
    3. Performs entity resolution
    4. Saves canonical entities to database
    5. Updates entity mentions with canonical UUIDs
    6. Triggers relationship building
    
    Args:
        document_uuid: UUID of the document
        entity_mentions: Optional list of entity mention dicts (if not provided, loads from cache)
        
    Returns:
        Dict containing resolution results
    """
    logger.info(f"Starting standalone entity resolution for document {document_uuid}")
    update_document_state(document_uuid, "entity_resolution", "in_progress", {"task_id": self.request.id})
    
    try:
        redis_manager = get_redis_manager()
        
        # 1. Get entity mentions from parameters or cache
        if not entity_mentions:
            logger.info("Loading entity mentions from cache...")
            mentions_key = CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=document_uuid)
            mentions_data = redis_manager.get_dict(mentions_key)
            if mentions_data:
                entity_mentions = mentions_data.get('mentions', [])
            else:
                # Try to load from database
                logger.info("Cache miss, loading from database...")
                session = next(self.db_manager.get_session())
                try:
                    result = session.execute(
                        sql_text("""
                            SELECT mention_uuid, chunk_uuid, document_uuid, entity_text,
                                   entity_type, start_char, end_char, confidence_score
                            FROM entity_mentions
                            WHERE document_uuid = :doc_uuid
                        """),
                        {'doc_uuid': str(document_uuid)}
                    )
                    entity_mentions = []
                    for row in result:
                        entity_mentions.append({
                            'mention_uuid': str(row.mention_uuid),
                            'chunk_uuid': str(row.chunk_uuid),
                            'document_uuid': str(row.document_uuid),
                            'entity_text': row.entity_text,
                            'entity_type': row.entity_type,
                            'start_char': row.start_char,
                            'end_char': row.end_char,
                            'confidence_score': row.confidence_score
                        })
                finally:
                    session.close()
        
        if not entity_mentions:
            logger.warning(f"No entity mentions found for document {document_uuid}")
            update_document_state(document_uuid, "entity_resolution", "completed", {
                "resolved_count": 0,
                "canonical_count": 0,
                "message": "No entity mentions to resolve"
            })
            return {'status': 'skipped', 'message': 'No entity mentions to resolve'}
        
        logger.info(f"Processing {len(entity_mentions)} entity mentions")
        
        # 2. Check if mentions are already in database, if not save them
        session = next(self.db_manager.get_session())
        try:
            # Check if mentions exist
            check_query = sql_text("""
                SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :doc_uuid
            """)
            existing_count = session.execute(check_query, {'doc_uuid': str(document_uuid)}).scalar()
            
            if existing_count == 0:
                logger.info("Entity mentions not in database, saving them...")
                # Save entity mentions to database
                for mention in entity_mentions:
                    insert_query = sql_text("""
                        INSERT INTO entity_mentions (
                            mention_uuid, chunk_uuid, document_uuid, entity_text,
                            entity_type, start_char, end_char, confidence_score, created_at
                        ) VALUES (
                            :mention_uuid, :chunk_uuid, :document_uuid, :entity_text,
                            :entity_type, :start_char, :end_char, :confidence_score, NOW()
                        )
                        ON CONFLICT (mention_uuid) DO NOTHING
                    """)
                    
                    session.execute(insert_query, {
                        'mention_uuid': mention.get('mention_uuid', str(uuid.uuid4())),
                        'chunk_uuid': mention['chunk_uuid'],
                        'document_uuid': mention.get('document_uuid', document_uuid),
                        'entity_text': mention['entity_text'],
                        'entity_type': mention['entity_type'],
                        'start_char': mention.get('start_char', 0),
                        'end_char': mention.get('end_char', 0),
                        'confidence_score': mention.get('confidence_score', 0.0)
                    })
                session.commit()
                logger.info(f"Saved {len(entity_mentions)} entity mentions to database")
            else:
                logger.info(f"Found {existing_count} existing entity mentions in database")
        finally:
            session.close()
        
        # 3. Perform entity resolution
        logger.info("Performing entity resolution...")
        resolution_result = resolve_entities_simple(
            entity_mentions=entity_mentions,
            document_uuid=document_uuid,
            threshold=0.8
        )
        
        logger.info(f"Resolution complete: {resolution_result['total_canonical']} canonical entities from {resolution_result['total_mentions']} mentions")
        
        # 4. Save canonical entities to database
        if resolution_result['canonical_entities']:
            logger.info(f"Saving {len(resolution_result['canonical_entities'])} canonical entities...")
            saved_count = save_canonical_entities_to_db(
                canonical_entities=resolution_result['canonical_entities'],
                document_uuid=document_uuid,
                db_manager=self.db_manager
            )
            logger.info(f"Successfully saved {saved_count} canonical entities")
        else:
            logger.warning("No canonical entities to save")
            saved_count = 0
        
        # 5. Update entity mentions with canonical UUIDs
        if resolution_result['mention_to_canonical']:
            logger.info(f"Updating {len(resolution_result['mention_to_canonical'])} entity mentions with canonical UUIDs...")
            updated_count = update_entity_mentions_with_canonical(
                mention_to_canonical=resolution_result['mention_to_canonical'],
                document_uuid=document_uuid,
                db_manager=self.db_manager
            )
            logger.info(f"Successfully updated {updated_count} entity mentions")
        else:
            updated_count = 0
        
        # 6. Update cache with resolved entities
        entities_key = CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=document_uuid)
        redis_manager.store_dict(entities_key, {
            'entities': resolution_result['canonical_entities']
        }, ttl=86400)
        
        # 7. Update document state
        update_document_state(document_uuid, "entity_resolution", "completed", {
            "resolved_count": updated_count,
            "canonical_count": len(resolution_result['canonical_entities']),
            "deduplication_rate": resolution_result['deduplication_rate']
        })
        
        # 8. Prepare data for relationship building
        # Get metadata and chunks for relationship building
        metadata_key = f"doc:metadata:{document_uuid}"
        stored_metadata = redis_manager.get_dict(metadata_key) or {}
        project_uuid = stored_metadata.get('project_uuid')
        document_metadata = stored_metadata.get('document_metadata', {})
        
        # Ensure document_uuid is in metadata
        if 'document_uuid' not in document_metadata:
            document_metadata['document_uuid'] = document_uuid
        
        # Get chunks from cache or database
        chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
        chunks_data = redis_manager.get_dict(chunks_key) or {}
        chunks = chunks_data.get('chunks', [])
        
        if not chunks:
            logger.info("Loading chunks from database...")
            session = next(self.db_manager.get_session())
            try:
                chunk_query = sql_text("""
                    SELECT chunk_uuid, text, chunk_index, char_start_index, char_end_index
                    FROM document_chunks
                    WHERE document_uuid = :doc_uuid
                    ORDER BY chunk_index
                """)
                chunk_results = session.execute(chunk_query, {'doc_uuid': str(document_uuid)})
                chunks = []
                for row in chunk_results:
                    chunks.append({
                        'chunk_uuid': str(row.chunk_uuid),
                        'chunk_text': row.text,
                        'chunk_index': row.chunk_index,
                        'start_char': row.char_start_index,
                        'end_char': row.char_end_index
                    })
            finally:
                session.close()
        
        # Get updated entity mentions from database
        session = next(self.db_manager.get_session())
        try:
            mentions_query = sql_text("""
                SELECT em.*, ce.canonical_name
                FROM entity_mentions em
                LEFT JOIN canonical_entities ce ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                WHERE em.document_uuid = :doc_uuid
            """)
            
            mentions_results = session.execute(mentions_query, {'doc_uuid': str(document_uuid)}).fetchall()
            
            entity_mentions_list = []
            for row in mentions_results:
                entity_mentions_list.append({
                    'mention_uuid': str(row.mention_uuid),
                    'chunk_uuid': str(row.chunk_uuid),
                    'document_uuid': str(row.document_uuid),
                    'entity_text': row.entity_text,
                    'entity_type': row.entity_type,
                    'start_char': row.start_char,
                    'end_char': row.end_char,
                    'confidence_score': row.confidence_score,
                    'canonical_entity_uuid': str(row.canonical_entity_uuid) if row.canonical_entity_uuid else None,
                    'canonical_name': row.canonical_name
                })
        finally:
            session.close()
        
        # 9. Trigger relationship building
        if project_uuid and chunks and resolution_result['canonical_entities']:
            logger.info(f"Triggering relationship building with {len(resolution_result['canonical_entities'])} canonical entities")
            
            # Import here to avoid circular imports
            from scripts.pdf_tasks import build_document_relationships
            
            build_document_relationships.apply_async(
                args=[
                    document_uuid,
                    document_metadata,
                    project_uuid,
                    chunks,
                    entity_mentions_list,
                    resolution_result['canonical_entities']
                ]
            )
        else:
            logger.warning(f"Skipping relationship building - missing data: project_uuid={bool(project_uuid)}, chunks={len(chunks)}, entities={len(resolution_result['canonical_entities'])}")
        
        return {
            'status': 'success',
            'canonical_entities': resolution_result['canonical_entities'],
            'total_resolved': updated_count,
            'deduplication_rate': resolution_result['deduplication_rate']
        }
        
    except Exception as e:
        logger.error(f"Entity resolution failed for {document_uuid}: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        update_document_state(document_uuid, "entity_resolution", "failed", {"error": str(e)})
        raise