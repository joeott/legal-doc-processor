"""Health monitoring and alerting system"""

import os
import time
import json
import boto3
import psutil
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager

logger = logging.getLogger(__name__)

class HealthMonitor:
    """Monitor system health and send alerts"""
    
    def __init__(self):
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.cloudwatch = boto3.client('cloudwatch')
        self.sns = boto3.client('sns')
        
        # Thresholds
        self.MEMORY_THRESHOLD = 80  # %
        self.DISK_THRESHOLD = 90    # %
        self.ERROR_RATE_THRESHOLD = 0.1  # 10%
        self.QUEUE_DEPTH_THRESHOLD = 100
        
        # State tracking
        self.error_counts = defaultdict(int)
        self.success_counts = defaultdict(int)
        
    def check_system_health(self) -> Dict[str, any]:
        """Comprehensive health check"""
        
        health = {
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'healthy',
            'checks': {}
        }
        
        # 1. Memory usage
        memory = psutil.virtual_memory()
        health['checks']['memory'] = {
            'percent': memory.percent,
            'available_mb': memory.available / (1024 * 1024),
            'status': 'ok' if memory.percent < self.MEMORY_THRESHOLD else 'critical'
        }
        
        # 2. Disk usage
        disk = psutil.disk_usage('/')
        health['checks']['disk'] = {
            'percent': disk.percent,
            'free_gb': disk.free / (1024**3),
            'status': 'ok' if disk.percent < self.DISK_THRESHOLD else 'warning'
        }
        
        # 3. Database connectivity
        try:
            session = next(self.db.get_session())
            from sqlalchemy import text
            result = session.execute(text("SELECT 1"))
            session.close()
            health['checks']['database'] = {'status': 'ok', 'response_time_ms': 0}
        except Exception as e:
            health['checks']['database'] = {'status': 'error', 'error': str(e)}
        
        # 4. Redis connectivity
        try:
            start = time.time()
            self.redis.ping()
            response_time = (time.time() - start) * 1000
            health['checks']['redis'] = {'status': 'ok', 'response_time_ms': response_time}
        except Exception as e:
            health['checks']['redis'] = {'status': 'error', 'error': str(e)}
        
        # 5. Celery queue depth
        try:
            queue_lengths = self._get_queue_lengths()
            total_pending = sum(queue_lengths.values())
            health['checks']['queues'] = {
                'status': 'ok' if total_pending < self.QUEUE_DEPTH_THRESHOLD else 'warning',
                'total_pending': total_pending,
                'by_queue': queue_lengths
            }
        except Exception as e:
            health['checks']['queues'] = {'status': 'error', 'error': str(e)}
        
        # 6. Error rates (last hour)
        error_rate = self._calculate_error_rate()
        health['checks']['error_rate'] = {
            'status': 'ok' if error_rate < self.ERROR_RATE_THRESHOLD else 'warning',
            'rate': error_rate,
            'errors_1h': sum(self.error_counts.values()),
            'success_1h': sum(self.success_counts.values())
        }
        
        # 7. Textract job status
        textract_health = self._check_textract_health()
        health['checks']['textract'] = textract_health
        
        # Overall status
        critical_checks = [c for c in health['checks'].values() if c.get('status') == 'critical']
        warning_checks = [c for c in health['checks'].values() if c.get('status') == 'warning']
        
        if critical_checks:
            health['status'] = 'critical'
        elif warning_checks:
            health['status'] = 'warning'
        
        return health
    
    def _get_queue_lengths(self) -> Dict[str, int]:
        """Get Celery queue lengths"""
        lengths = {}
        
        for queue in ['default', 'ocr', 'text', 'entity', 'graph']:
            key = f"celery-queue-{queue}"
            try:
                length = self.redis.client.llen(key)
                lengths[queue] = length
            except:
                lengths[queue] = 0
        
        return lengths
    
    def _calculate_error_rate(self) -> float:
        """Calculate error rate for last hour"""
        total_errors = sum(self.error_counts.values())
        total_success = sum(self.success_counts.values())
        total = total_errors + total_success
        
        if total == 0:
            return 0.0
        
        return total_errors / total
    
    def _check_textract_health(self) -> Dict:
        """Check Textract job health"""
        try:
            session = next(self.db.get_session())
            from sqlalchemy import text
            
            # Get jobs from last hour
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            
            result = session.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN job_status = 'succeeded' THEN 1 ELSE 0 END) as succeeded,
                    SUM(CASE WHEN job_status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN job_status = 'in_progress' THEN 1 ELSE 0 END) as in_progress
                FROM textract_jobs
                WHERE created_at > :since
            """), {'since': one_hour_ago})
            
            stats = result.fetchone()
            session.close()
            
            if stats.total > 0:
                success_rate = stats.succeeded / stats.total
                status = 'ok' if success_rate > 0.9 else 'warning'
            else:
                status = 'ok'  # No jobs is OK
            
            return {
                'status': status,
                'jobs_1h': stats.total,
                'succeeded': stats.succeeded,
                'failed': stats.failed,
                'in_progress': stats.in_progress,
                'success_rate': success_rate if stats.total > 0 else 1.0
            }
            
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def send_metrics_to_cloudwatch(self, health: Dict):
        """Send health metrics to CloudWatch"""
        try:
            namespace = 'LegalDocProcessor'
            timestamp = datetime.utcnow()
            
            metrics = []
            
            # Memory metric
            if 'memory' in health['checks']:
                metrics.append({
                    'MetricName': 'MemoryUsagePercent',
                    'Value': health['checks']['memory']['percent'],
                    'Unit': 'Percent',
                    'Timestamp': timestamp
                })
            
            # Queue depth metric
            if 'queues' in health['checks'] and 'total_pending' in health['checks']['queues']:
                metrics.append({
                    'MetricName': 'TotalQueueDepth',
                    'Value': health['checks']['queues']['total_pending'],
                    'Unit': 'Count',
                    'Timestamp': timestamp
                })
            
            # Error rate metric
            if 'error_rate' in health['checks']:
                metrics.append({
                    'MetricName': 'ErrorRate',
                    'Value': health['checks']['error_rate']['rate'] * 100,
                    'Unit': 'Percent',
                    'Timestamp': timestamp
                })
            
            # Send metrics
            if metrics:
                self.cloudwatch.put_metric_data(
                    Namespace=namespace,
                    MetricData=metrics
                )
                
        except Exception as e:
            logger.error(f"Failed to send CloudWatch metrics: {e}")
    
    def check_and_alert(self):
        """Check health and send alerts if needed"""
        
        health = self.check_system_health()
        
        # Send metrics
        self.send_metrics_to_cloudwatch(health)
        
        # Check for alerts
        if health['status'] == 'critical':
            self._send_alert('CRITICAL', health)
        elif health['status'] == 'warning':
            # Only alert on persistent warnings
            warning_key = 'health:warning:count'
            warning_count = self.redis.client.incr(warning_key)
            self.redis.client.expire(warning_key, 300)  # Reset after 5 minutes
            
            if warning_count >= 3:  # 3 consecutive warnings
                self._send_alert('WARNING', health)
    
    def _send_alert(self, severity: str, health: Dict):
        """Send alert via SNS"""
        try:
            topic_arn = os.getenv('SNS_ALERT_TOPIC_ARN')
            if not topic_arn:
                logger.warning("No SNS topic configured for alerts")
                return
            
            # Build alert message
            issues = []
            for check_name, check_data in health['checks'].items():
                if check_data.get('status') in ['critical', 'warning']:
                    issues.append(f"- {check_name}: {check_data.get('status')}")
            
            message = f"""
{severity} Alert - Legal Document Processor

Time: {health['timestamp']}
Status: {health['status']}

Issues:
{chr(10).join(issues)}

Details:
{json.dumps(health, indent=2)}

Please investigate immediately.
"""
            
            self.sns.publish(
                TopicArn=topic_arn,
                Subject=f"{severity}: Legal Doc Processor Health Alert",
                Message=message
            )
            
            logger.info(f"Sent {severity} alert via SNS")
            
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

def check_system_health():
    """Quick health check function"""
    monitor = HealthMonitor()
    return monitor.check_system_health()

# Create monitoring script
if __name__ == "__main__":
    monitor = HealthMonitor()
    
    print("Starting health monitoring...")
    
    while True:
        try:
            monitor.check_and_alert()
            
            # Also print to console
            health = monitor.check_system_health()
            print(f"\n[{health['timestamp']}] Status: {health['status']}")
            
            for check, data in health['checks'].items():
                status_icon = "✅" if data.get('status') == 'ok' else "⚠️" if data.get('status') == 'warning' else "❌"
                print(f"  {status_icon} {check}: {data.get('status')}")
            
        except KeyboardInterrupt:
            print("\nStopping monitor...")
            break
        except Exception as e:
            print(f"Monitor error: {e}")
        
        time.sleep(60)  # Check every minute