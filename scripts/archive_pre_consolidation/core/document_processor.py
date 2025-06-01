"""
Unified document processing logic.
Consolidates common patterns from multiple processing scripts.
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from supabase_utils import SupabaseManager
from redis_utils import get_redis_manager
from cache_keys import CacheKeys
from config import get_stage_info

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Centralized document processing functionality."""
    
    def __init__(self):
        self.db_manager = SupabaseManager()
        self.redis_manager = get_redis_manager()
        self.stage_info = get_stage_info()
    
    def get_document_by_uuid(self, document_uuid: str) -> Optional[Dict[str, Any]]:
        """Get document details by UUID."""
        try:
            response = self.db_manager.client.table('source_documents').select(
                '*'
            ).eq('document_uuid', document_uuid).execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching document {document_uuid}: {e}")
            return None
    
    def get_document_by_id(self, document_id: int) -> Optional[Dict[str, Any]]:
        """Get document details by SQL ID."""
        try:
            response = self.db_manager.client.table('source_documents').select(
                '*'
            ).eq('id', document_id).execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching document ID {document_id}: {e}")
            return None
    
    def update_document_status(self, document_uuid: str, status: str, 
                             error_message: Optional[str] = None,
                             additional_fields: Optional[Dict[str, Any]] = None) -> bool:
        """Update document processing status."""
        try:
            update_data = {
                'celery_status': status,
                'last_modified_at': datetime.now().isoformat()
            }
            
            if error_message:
                update_data['error_message'] = error_message[:500]  # Truncate long errors
                
            if additional_fields:
                update_data.update(additional_fields)
                
            self.db_manager.client.table('source_documents').update(
                update_data
            ).eq('document_uuid', document_uuid).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error updating document status: {e}")
            return False
    
    def get_pending_documents(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get documents pending processing."""
        try:
            response = self.db_manager.client.table('source_documents').select(
                'id', 'document_uuid', 'original_file_name', 'project_fk_id'
            ).eq('celery_status', 'pending').limit(limit).execute()
            
            return response.data
        except Exception as e:
            logger.error(f"Error fetching pending documents: {e}")
            return []
    
    def get_failed_documents(self, stage: Optional[str] = None, 
                           hours_back: int = 24) -> List[Dict[str, Any]]:
        """Get failed documents, optionally filtered by stage."""
        try:
            query = self.db_manager.client.table('source_documents').select(
                'id', 'document_uuid', 'original_file_name', 'celery_status', 
                'error_message', 'last_modified_at'
            )
            
            if stage:
                query = query.eq('celery_status', f'{stage}_failed')
            else:
                query = query.in_('celery_status', 
                               ['ocr_failed', 'text_failed', 'entity_failed', 'graph_failed'])
            
            # Add time filter
            from datetime import datetime, timedelta
            time_threshold = (datetime.now() - timedelta(hours=hours_back)).isoformat()
            query = query.gte('last_modified_at', time_threshold)
            
            response = query.execute()
            return response.data
        except Exception as e:
            logger.error(f"Error fetching failed documents: {e}")
            return []
    
    def get_stuck_documents(self, minutes: int = 30) -> List[Dict[str, Any]]:
        """Get documents stuck in processing state."""
        try:
            from datetime import datetime, timedelta
            time_threshold = (datetime.now() - timedelta(minutes=minutes)).isoformat()
            
            response = self.db_manager.client.table('source_documents').select(
                'id', 'document_uuid', 'original_file_name', 'celery_status', 
                'celery_task_id', 'last_modified_at'
            ).in_('celery_status', 
                ['processing', 'ocr_processing', 'text_processing', 
                 'entity_processing', 'graph_processing']
            ).lte('last_modified_at', time_threshold).execute()
            
            return response.data
        except Exception as e:
            logger.error(f"Error fetching stuck documents: {e}")
            return []
    
    def reset_document_status(self, document_uuid: str) -> bool:
        """Reset document to pending status for reprocessing."""
        try:
            self.db_manager.client.table('source_documents').update({
                'celery_status': 'pending',
                'celery_task_id': None,
                'error_message': None,
                'last_modified_at': datetime.now().isoformat()
            }).eq('document_uuid', document_uuid).execute()
            
            # Clear any cached data
            if self.redis_manager and self.redis_manager.is_available():
                patterns = [
                    CacheKeys.DOC_OCR_RESULT,
                    CacheKeys.DOC_CHUNKS_LIST,
                    CacheKeys.DOC_ENTITY_MENTIONS,
                    CacheKeys.DOC_RESOLVED_MENTIONS
                ]
                
                for pattern in patterns:
                    key = CacheKeys.format_key(pattern, document_uuid=document_uuid)
                    self.redis_manager.client.delete(key)
                    
            return True
        except Exception as e:
            logger.error(f"Error resetting document: {e}")
            return False
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get overall processing statistics."""
        try:
            # Get status counts
            response = self.db_manager.client.table('source_documents').select(
                'celery_status'
            ).execute()
            
            status_counts = {}
            for row in response.data:
                status = row.get('celery_status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            # Calculate percentages
            total = sum(status_counts.values())
            status_percentages = {}
            for status, count in status_counts.items():
                status_percentages[status] = (count / total * 100) if total > 0 else 0
                
            return {
                'total_documents': total,
                'status_counts': status_counts,
                'status_percentages': status_percentages,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting processing stats: {e}")
            return {}
    
    def validate_document_file(self, file_path: str) -> Dict[str, Any]:
        """Validate document file exists and is accessible."""
        result = {
            'valid': False,
            'exists': False,
            'readable': False,
            'size': 0,
            'error': None
        }
        
        try:
            if os.path.exists(file_path):
                result['exists'] = True
                
                if os.access(file_path, os.R_OK):
                    result['readable'] = True
                    result['size'] = os.path.getsize(file_path)
                    result['valid'] = True
                else:
                    result['error'] = "File is not readable"
            else:
                result['error'] = "File does not exist"
                
        except Exception as e:
            result['error'] = str(e)
            
        return result