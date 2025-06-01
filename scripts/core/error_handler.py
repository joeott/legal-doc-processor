"""
Unified error handling and recovery for the document pipeline.
Provides error analysis, recovery strategies, and monitoring.
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import traceback
import json

logger = logging.getLogger(__name__)


class ErrorHandler:
    """Centralized error handling and recovery functionality."""
    
    # Common error patterns and their recovery strategies
    ERROR_PATTERNS = {
        'rate_limit': {
            'patterns': ['rate limit', '429', 'too many requests'],
            'retry_delay': 300,  # 5 minutes
            'max_retries': 5,
            'strategy': 'exponential_backoff'
        },
        'auth_error': {
            'patterns': ['401', 'unauthorized', 'invalid api key', 'authentication'],
            'retry_delay': 0,
            'max_retries': 0,
            'strategy': 'manual_intervention'
        },
        'network_error': {
            'patterns': ['connection', 'timeout', 'network', 'unreachable'],
            'retry_delay': 60,
            'max_retries': 3,
            'strategy': 'linear_backoff'
        },
        'file_not_found': {
            'patterns': ['file not found', 'no such file', 'does not exist'],
            'retry_delay': 0,
            'max_retries': 0,
            'strategy': 'skip_document'
        },
        'memory_error': {
            'patterns': ['memory', 'out of memory', 'memoryerror'],
            'retry_delay': 120,
            'max_retries': 2,
            'strategy': 'reduce_batch_size'
        },
        'format_error': {
            'patterns': ['unsupported format', 'invalid format', 'cannot decode'],
            'retry_delay': 0,
            'max_retries': 0,
            'strategy': 'alternative_processor'
        }
    }
    
    def __init__(self, db_manager=None):
        self.db_manager = db_manager
        
    def analyze_error(self, error: Exception, context: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze an error and suggest recovery strategy."""
        error_str = str(error).lower()
        error_type = type(error).__name__
        
        # Check against known patterns
        for error_name, config in self.ERROR_PATTERNS.items():
            if any(pattern in error_str for pattern in config['patterns']):
                return {
                    'error_category': error_name,
                    'error_type': error_type,
                    'error_message': str(error),
                    'retry_strategy': config['strategy'],
                    'retry_delay': config['retry_delay'],
                    'max_retries': config['max_retries'],
                    'context': context,
                    'stacktrace': traceback.format_exc()
                }
        
        # Unknown error
        return {
            'error_category': 'unknown',
            'error_type': error_type,
            'error_message': str(error),
            'retry_strategy': 'linear_backoff',
            'retry_delay': 60,
            'max_retries': 2,
            'context': context,
            'stacktrace': traceback.format_exc()
        }
    
    def log_error(self, document_uuid: str, stage: str, error: Exception,
                  context: Optional[Dict[str, Any]] = None) -> bool:
        """Log error to document processing history."""
        if not self.db_manager:
            logger.warning("No database manager available for error logging")
            return False
            
        try:
            error_analysis = self.analyze_error(error, context or {})
            
            # Get document SQL ID
            doc_response = self.db_manager.client.table('source_documents').select(
                'id'
            ).eq('document_uuid', document_uuid).execute()
            
            if not doc_response.data:
                logger.error(f"Document {document_uuid} not found")
                return False
                
            doc_id = doc_response.data[0]['id']
            
            # Log to processing history
            self.db_manager.client.table('document_processing_history').insert({
                'document_id': doc_id,
                'stage': stage,
                'status': 'failed',
                'error_details': json.dumps(error_analysis),
                'metadata': json.dumps({
                    'error_category': error_analysis['error_category'],
                    'retry_strategy': error_analysis['retry_strategy'],
                    'timestamp': datetime.now().isoformat()
                }),
                'created_at': datetime.now().isoformat()
            }).execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to log error: {e}")
            return False
    
    def get_error_summary(self, hours_back: int = 24) -> Dict[str, Any]:
        """Get summary of recent errors."""
        if not self.db_manager:
            logger.warning("No database manager available for error summary")
            return {}
            
        try:
            time_threshold = (datetime.now() - timedelta(hours=hours_back)).isoformat()
            
            # Get recent failures
            response = self.db_manager.client.table('document_processing_history').select(
                'stage', 'error_details', 'created_at'
            ).eq('status', 'failed').gte('created_at', time_threshold).execute()
            
            if not response.data:
                return {
                    'total_errors': 0,
                    'errors_by_stage': {},
                    'errors_by_category': {},
                    'time_range_hours': hours_back
                }
            
            # Analyze errors
            errors_by_stage = {}
            errors_by_category = {}
            
            for record in response.data:
                stage = record['stage']
                errors_by_stage[stage] = errors_by_stage.get(stage, 0) + 1
                
                try:
                    error_details = json.loads(record['error_details'])
                    category = error_details.get('error_category', 'unknown')
                    errors_by_category[category] = errors_by_category.get(category, 0) + 1
                except:
                    errors_by_category['unknown'] = errors_by_category.get('unknown', 0) + 1
                    
            return {
                'total_errors': len(response.data),
                'errors_by_stage': errors_by_stage,
                'errors_by_category': errors_by_category,
                'time_range_hours': hours_back,
                'most_recent_error': response.data[0]['created_at'] if response.data else None
            }
            
        except Exception as e:
            logger.error(f"Error getting error summary: {e}")
            return {}
    
    def get_recovery_candidates(self, error_category: Optional[str] = None,
                              limit: int = 100) -> List[Dict[str, Any]]:
        """Get documents that are candidates for retry based on error type."""
        if not self.db_manager:
            logger.warning("No database manager available for getting recovery candidates")
            return []
            
        try:
            # Get failed documents
            query = self.db_manager.client.table('source_documents').select(
                'id', 'document_uuid', 'original_file_name', 'celery_status',
                'error_message', 'last_modified_at'
            ).in_('celery_status', ['ocr_failed', 'text_failed', 'entity_failed', 'graph_failed'])
            
            response = query.limit(limit).execute()
            
            candidates = []
            for doc in response.data:
                # Analyze the error
                if doc.get('error_message'):
                    error_analysis = self.analyze_error(
                        Exception(doc['error_message']), 
                        {'document_uuid': doc['document_uuid']}
                    )
                    
                    # Filter by category if specified
                    if error_category and error_analysis['error_category'] != error_category:
                        continue
                        
                    # Check if retry is recommended
                    if error_analysis['max_retries'] > 0:
                        candidates.append({
                            'document_uuid': doc['document_uuid'],
                            'filename': doc['original_file_name'],
                            'error_category': error_analysis['error_category'],
                            'retry_strategy': error_analysis['retry_strategy'],
                            'retry_delay': error_analysis['retry_delay']
                        })
                        
            return candidates
            
        except Exception as e:
            logger.error(f"Error getting recovery candidates: {e}")
            return []
    
    def create_error_report(self, output_format: str = 'json') -> Optional[str]:
        """Create comprehensive error report."""
        try:
            # Get error summary
            summary = self.get_error_summary(hours_back=24)
            
            # Get detailed errors by category
            detailed_errors = {}
            for category in summary.get('errors_by_category', {}).keys():
                candidates = self.get_recovery_candidates(error_category=category, limit=10)
                detailed_errors[category] = {
                    'count': summary['errors_by_category'][category],
                    'examples': candidates[:5],
                    'recovery_strategy': self.ERROR_PATTERNS.get(
                        category, {}
                    ).get('strategy', 'unknown')
                }
            
            report = {
                'generated_at': datetime.now().isoformat(),
                'summary': summary,
                'detailed_errors': detailed_errors,
                'recommendations': self._generate_recommendations(summary, detailed_errors)
            }
            
            if output_format == 'json':
                return json.dumps(report, indent=2, default=str)
            elif output_format == 'text':
                return self._format_text_report(report)
            else:
                raise ValueError(f"Unsupported format: {output_format}")
                
        except Exception as e:
            logger.error(f"Error creating error report: {e}")
            return None
    
    def _generate_recommendations(self, summary: Dict[str, Any], 
                                detailed_errors: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on error patterns."""
        recommendations = []
        
        # Check for auth errors
        if detailed_errors.get('auth_error', {}).get('count', 0) > 0:
            recommendations.append("Check API credentials - authentication errors detected")
            
        # Check for rate limits
        if detailed_errors.get('rate_limit', {}).get('count', 0) > 0:
            recommendations.append("Implement rate limiting or increase API quotas")
            
        # Check for network errors
        network_errors = detailed_errors.get('network_error', {}).get('count', 0)
        if network_errors > 10:
            recommendations.append("Network connectivity issues detected - check infrastructure")
            
        # Check for file errors
        if detailed_errors.get('file_not_found', {}).get('count', 0) > 0:
            recommendations.append("Verify file paths and S3 bucket permissions")
            
        return recommendations
    
    def _format_text_report(self, report: Dict[str, Any]) -> str:
        """Format report as readable text."""
        lines = []
        lines.append("Document Processing Error Report")
        lines.append("=" * 50)
        lines.append(f"Generated: {report['generated_at']}")
        lines.append("")
        
        summary = report['summary']
        lines.append(f"Total Errors (24h): {summary['total_errors']}")
        lines.append("")
        
        lines.append("Errors by Stage:")
        for stage, count in summary.get('errors_by_stage', {}).items():
            lines.append(f"  {stage}: {count}")
        lines.append("")
        
        lines.append("Errors by Category:")
        for category, details in report.get('detailed_errors', {}).items():
            lines.append(f"  {category}: {details['count']} errors")
            lines.append(f"    Strategy: {details['recovery_strategy']}")
            
        lines.append("")
        lines.append("Recommendations:")
        for rec in report.get('recommendations', []):
            lines.append(f"  • {rec}")
            
        return "\n".join(lines)