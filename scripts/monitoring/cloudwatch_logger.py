"""CloudWatch logging integration for AWS Textract operations."""

import boto3
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class CloudWatchLogger:
    """Enhanced logging to CloudWatch for Textract operations."""
    
    def __init__(self, log_group_name: str = "/aws/textract/document-processing", 
                 region_name: str = "us-east-2"):
        """Initialize CloudWatch logger."""
        self.log_group_name = log_group_name
        self.region_name = region_name
        self.client = boto3.client('logs', region_name=region_name)
        self.log_stream_name = None
        self.sequence_token = None
        
        # Create log stream with timestamp
        self._create_log_stream()
    
    def _create_log_stream(self):
        """Create a new log stream for this session."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        hostname = "celery-worker"
        self.log_stream_name = f"{hostname}-{timestamp}"
        
        try:
            self.client.create_log_stream(
                logGroupName=self.log_group_name,
                logStreamName=self.log_stream_name
            )
            logger.info(f"Created CloudWatch log stream: {self.log_stream_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceAlreadyExistsException':
                logger.debug(f"Log stream already exists: {self.log_stream_name}")
            else:
                logger.error(f"Error creating log stream: {e}")
                raise
    
    def log_textract_event(self, event_type: str, document_uuid: str, 
                          job_id: Optional[str] = None, 
                          metadata: Optional[Dict[str, Any]] = None,
                          error: Optional[str] = None,
                          level: str = "INFO"):
        """Log a structured Textract event to CloudWatch."""
        
        # Build structured log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "event_type": event_type,
            "document_uuid": document_uuid,
            "service": "textract",
            "region": self.region_name
        }
        
        if job_id:
            log_entry["job_id"] = job_id
            
        if metadata:
            log_entry["metadata"] = metadata
            
        if error:
            log_entry["error"] = error
            log_entry["level"] = "ERROR"
        
        # Send to CloudWatch
        self._put_log_event(log_entry)
        
        # Also log locally
        log_message = f"[TEXTRACT-{event_type}] Document: {document_uuid}"
        if job_id:
            log_message += f", Job: {job_id}"
        if error:
            logger.error(f"{log_message} - Error: {error}")
        else:
            logger.info(log_message)
    
    def _put_log_event(self, log_entry: Dict[str, Any]):
        """Send log event to CloudWatch."""
        try:
            params = {
                'logGroupName': self.log_group_name,
                'logStreamName': self.log_stream_name,
                'logEvents': [{
                    'timestamp': int(time.time() * 1000),
                    'message': json.dumps(log_entry)
                }]
            }
            
            # Include sequence token if we have one
            if self.sequence_token:
                params['sequenceToken'] = self.sequence_token
            
            response = self.client.put_log_events(**params)
            
            # Update sequence token for next call
            self.sequence_token = response.get('nextSequenceToken')
            
        except ClientError as e:
            # Handle sequence token mismatch
            if e.response['Error']['Code'] == 'InvalidSequenceTokenException':
                # Extract the expected token from error message
                import re
                match = re.search(r'expected sequence token is: (\S+)', str(e))
                if match:
                    self.sequence_token = match.group(1)
                    # Retry with correct token
                    self._put_log_event(log_entry)
            else:
                logger.error(f"Error sending log to CloudWatch: {e}")
    
    def log_api_call(self, api_method: str, request_params: Dict[str, Any],
                     response: Optional[Dict[str, Any]] = None,
                     error: Optional[str] = None):
        """Log Textract API calls with request/response details."""
        
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": "DEBUG" if not error else "ERROR",
            "event_type": "api_call",
            "api_method": api_method,
            "request_params": self._sanitize_params(request_params),
            "service": "textract"
        }
        
        if response:
            # Don't log full response (too large), just key metadata
            log_entry["response_metadata"] = {
                "job_id": response.get("JobId"),
                "status": response.get("JobStatus"),
                "status_message": response.get("StatusMessage")
            }
            
        if error:
            log_entry["error"] = error
            
        self._put_log_event(log_entry)
    
    def _sanitize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive data from parameters before logging."""
        sanitized = params.copy()
        
        # Remove any potential sensitive fields
        sensitive_fields = ['ClientRequestToken', 'NotificationChannel']
        for field in sensitive_fields:
            sanitized.pop(field, None)
            
        return sanitized
    
    def log_processing_metrics(self, document_uuid: str, metrics: Dict[str, Any]):
        """Log processing performance metrics."""
        
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": "INFO",
            "event_type": "processing_metrics",
            "document_uuid": document_uuid,
            "metrics": metrics,
            "service": "textract"
        }
        
        self._put_log_event(log_entry)


# Singleton instance
_cloudwatch_logger = None

def get_cloudwatch_logger() -> CloudWatchLogger:
    """Get or create CloudWatch logger instance."""
    global _cloudwatch_logger
    if _cloudwatch_logger is None:
        _cloudwatch_logger = CloudWatchLogger()
    return _cloudwatch_logger