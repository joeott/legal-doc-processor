"""Processing state management for document pipeline"""
from enum import Enum
from typing import Optional, Dict, Any
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ProcessingStage(Enum):
    """Ordered processing stages"""
    PENDING = "pending"
    OCR_PROCESSING = "ocr_processing"
    OCR_COMPLETE = "ocr_complete"
    TEXT_PROCESSING = "text_processing"
    TEXT_COMPLETE = "text_complete"
    ENTITY_EXTRACTION = "entity_extraction"
    ENTITY_COMPLETE = "entity_complete"
    ENTITY_RESOLUTION = "entity_resolution"
    RESOLUTION_COMPLETE = "resolution_complete"
    GRAPH_BUILDING = "graph_building"
    COMPLETED = "completed"
    
    @property
    def next_stage(self) -> Optional['ProcessingStage']:
        """Get the next stage in sequence"""
        stages = list(ProcessingStage)
        current_idx = stages.index(self)
        if current_idx < len(stages) - 1:
            return stages[current_idx + 1]
        return None
    
    def can_transition_to(self, target: 'ProcessingStage') -> bool:
        """Check if transition to target stage is valid"""
        # Define allowed transitions
        allowed_transitions = {
            ProcessingStage.PENDING: [ProcessingStage.OCR_PROCESSING],
            ProcessingStage.OCR_PROCESSING: [ProcessingStage.OCR_COMPLETE, ProcessingStage.PENDING],
            ProcessingStage.OCR_COMPLETE: [ProcessingStage.TEXT_PROCESSING],
            ProcessingStage.TEXT_PROCESSING: [ProcessingStage.TEXT_COMPLETE],
            ProcessingStage.TEXT_COMPLETE: [ProcessingStage.ENTITY_EXTRACTION],
            ProcessingStage.ENTITY_EXTRACTION: [ProcessingStage.ENTITY_COMPLETE],
            ProcessingStage.ENTITY_COMPLETE: [ProcessingStage.ENTITY_RESOLUTION],
            ProcessingStage.ENTITY_RESOLUTION: [ProcessingStage.RESOLUTION_COMPLETE],
            ProcessingStage.RESOLUTION_COMPLETE: [ProcessingStage.GRAPH_BUILDING],
            ProcessingStage.GRAPH_BUILDING: [ProcessingStage.COMPLETED]
        }
        return target in allowed_transitions.get(self, [])

class ProcessingStateManager:
    """Manages document processing state with Redis and database"""
    
    def __init__(self, db_manager, redis_manager):
        self.db = db_manager
        self.redis = redis_manager
        
    def get_processing_checkpoint(self, document_uuid: str) -> Dict[str, Any]:
        """Get the current processing checkpoint for a document"""
        # Check Redis first for active processing
        state_key = f"doc_state:{document_uuid}"
        redis_state = {}
        
        if self.redis:
            try:
                redis_client = self.redis.get_client()
                raw_state = redis_client.hgetall(state_key)
                # Decode bytes if needed
                for k, v in raw_state.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    val = v.decode() if isinstance(v, bytes) else v
                    redis_state[key] = val
            except Exception as e:
                logger.warning(f"Error reading Redis state: {e}")
        
        # Get database state
        try:
            doc = self.db.client.table('source_documents').select(
                'celery_status', 'last_successful_stage', 'processing_version'
            ).eq('document_uuid', document_uuid).single().execute()
            
            return {
                'current_stage': doc.data.get('celery_status'),
                'last_successful': doc.data.get('last_successful_stage'),
                'version': doc.data.get('processing_version', 1),
                'redis_state': redis_state
            }
        except Exception as e:
            logger.error(f"Error getting checkpoint: {e}")
            return {
                'current_stage': None,
                'last_successful': None,
                'version': 1,
                'redis_state': redis_state
            }
    
    def should_skip_stage(self, document_uuid: str, stage: ProcessingStage, 
                         force_reprocess: bool = False) -> bool:
        """Determine if a stage should be skipped"""
        if force_reprocess:
            return False
            
        checkpoint = self.get_processing_checkpoint(document_uuid)
        last_successful = checkpoint.get('last_successful')
        
        if not last_successful:
            return False
            
        # Skip if this stage was already completed successfully
        try:
            last_stage = ProcessingStage(last_successful)
            current_stage_idx = list(ProcessingStage).index(stage)
            last_stage_idx = list(ProcessingStage).index(last_stage)
            return current_stage_idx <= last_stage_idx
        except ValueError:
            return False
    
    def update_stage_status(self, document_uuid: str, stage: ProcessingStage, 
                          status: str = "processing") -> None:
        """Update the current processing stage"""
        try:
            # Update database
            self.db.client.table('source_documents').update({
                'celery_status': stage.value,
                'processing_attempts': self.db.client.rpc('increment', {'x': 1})
            }).eq('document_uuid', document_uuid).execute()
            
            # Update Redis if available
            if self.redis:
                state_key = f"doc_state:{document_uuid}"
                redis_client = self.redis.get_client()
                redis_client.hset(state_key, f"{stage.value}_status", status)
                redis_client.hset(state_key, f"{stage.value}_timestamp", datetime.now().isoformat())
                redis_client.expire(state_key, 7 * 24 * 3600)  # 7 days
                
        except Exception as e:
            logger.error(f"Error updating stage status: {e}")
    
    def mark_stage_complete(self, document_uuid: str, stage: ProcessingStage) -> None:
        """Mark a stage as successfully completed"""
        try:
            self.db.client.table('source_documents').update({
                'last_successful_stage': stage.value
            }).eq('document_uuid', document_uuid).execute()
            
            logger.info(f"Marked stage {stage.value} as complete for {document_uuid}")
        except Exception as e:
            logger.error(f"Error marking stage complete: {e}")