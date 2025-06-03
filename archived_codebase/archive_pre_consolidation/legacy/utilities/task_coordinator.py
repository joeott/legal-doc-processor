# task_coordinator.py
"""Distributed task coordination using Redis for the document processing pipeline."""

import json
import logging
import socket
import time
import uuid
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from enum import Enum

from redis_utils import get_redis_manager
from cache_keys import CacheKeys

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Types of tasks in the processing pipeline."""
    OCR = "ocr"
    CLEANING = "cleaning"
    CHUNKING = "chunking"
    ENTITY_EXTRACTION = "entity_extraction"
    ENTITY_RESOLUTION = "entity_resolution"
    RELATIONSHIP_BUILDING = "relationship_building"


class TaskStatus(Enum):
    """Status of a task."""
    PENDING = "pending"
    CLAIMED = "claimed"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class TaskCoordinator:
    """Coordinate distributed processing tasks using Redis."""
    
    def __init__(self, worker_type: str = "general", capabilities: Optional[List[str]] = None):
        """
        Initialize task coordinator.
        
        Args:
            worker_type: Type of worker (e.g., 'ocr', 'entity', 'general')
            capabilities: List of task types this worker can handle
        """
        self.redis_mgr = get_redis_manager()
        if not self.redis_mgr.is_available():
            raise RuntimeError("Redis is required for task coordination")
            
        self.worker_id = f"worker:{worker_type}:{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        self.worker_type = worker_type
        self.capabilities = capabilities or [t.value for t in TaskType]
        self._last_heartbeat = 0
        
        # Register worker
        self.register_worker()
        
    def register_worker(self):
        """Register this worker with its capabilities."""
        try:
            client = self.redis_mgr.get_client()
            
            worker_data = {
                'id': self.worker_id,
                'type': self.worker_type,
                'capabilities': ','.join(self.capabilities),
                'status': 'active',
                'started_at': datetime.now().isoformat(),
                'last_heartbeat': time.time(),
                'tasks_completed': 0,
                'tasks_failed': 0,
                'hostname': socket.gethostname()
            }
            
            # Store worker info
            worker_key = f"workers:{self.worker_id}"
            client.hset(worker_key, mapping=worker_data)
            client.expire(worker_key, 300)  # 5 minute TTL
            
            # Add to active workers set
            client.sadd("workers:active", self.worker_id)
            
            logger.info(f"Registered worker {self.worker_id} with capabilities: {self.capabilities}")
            
        except Exception as e:
            logger.error(f"Failed to register worker: {e}")
            raise
    
    def heartbeat(self):
        """Update worker heartbeat."""
        try:
            current_time = time.time()
            
            # Only send heartbeat every 30 seconds
            if current_time - self._last_heartbeat < 30:
                return
                
            client = self.redis_mgr.get_client()
            worker_key = f"workers:{self.worker_id}"
            
            # Update heartbeat
            client.hset(worker_key, 'last_heartbeat', current_time)
            client.hset(worker_key, 'status', 'active')
            client.expire(worker_key, 300)  # Reset TTL
            
            # Ensure we're in active set
            client.sadd("workers:active", self.worker_id)
            
            self._last_heartbeat = current_time
            logger.debug(f"Worker {self.worker_id} heartbeat sent")
            
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
    
    def submit_task(self, task_type: TaskType, task_data: Dict[str, Any]) -> Optional[str]:
        """
        Submit a task to the queue.
        
        Args:
            task_type: Type of task
            task_data: Task data/payload
            
        Returns:
            Task ID if successful
        """
        try:
            task_id = f"task:{uuid.uuid4().hex}"
            
            task = {
                'id': task_id,
                'type': task_type.value,
                'status': TaskStatus.PENDING.value,
                'data': json.dumps(task_data),
                'submitted_at': datetime.now().isoformat(),
                'submitted_by': self.worker_id,
                'attempts': 0
            }
            
            client = self.redis_mgr.get_client()
            
            # Store task data
            task_key = f"tasks:{task_id}"
            client.hset(task_key, mapping=task)
            client.expire(task_key, 86400)  # 24 hour TTL
            
            # Add to task queue
            queue_key = f"tasks:queue:{task_type.value}"
            client.lpush(queue_key, task_id)
            
            # Update metrics
            client.hincrby("tasks:metrics", f"submitted:{task_type.value}", 1)
            
            logger.info(f"Submitted task {task_id} of type {task_type.value}")
            return task_id
            
        except Exception as e:
            logger.error(f"Failed to submit task: {e}")
            return None
    
    def claim_task(self, task_type: Optional[TaskType] = None, timeout: int = 5) -> Optional[Dict]:
        """
        Atomically claim a task from the queue.
        
        Args:
            task_type: Specific task type to claim (None for any)
            timeout: Timeout for blocking pop in seconds
            
        Returns:
            Task data if claimed, None otherwise
        """
        try:
            self.heartbeat()  # Update heartbeat before claiming
            
            client = self.redis_mgr.get_client()
            
            # Determine which queues to check
            if task_type:
                queues = [f"tasks:queue:{task_type.value}"]
            else:
                # Check all queues for capabilities
                queues = [f"tasks:queue:{cap}" for cap in self.capabilities]
            
            # Try to claim from queues
            for queue in queues:
                result = client.brpop(queue, timeout=timeout)
                
                if result:
                    _, task_id = result
                    
                    # Get task data
                    task_key = f"tasks:{task_id}"
                    task_data = client.hgetall(task_key)
                    
                    if not task_data:
                        logger.warning(f"Task {task_id} not found in storage")
                        continue
                    
                    # Update task status
                    client.hset(task_key, mapping={
                        'status': TaskStatus.CLAIMED.value,
                        'claimed_by': self.worker_id,
                        'claimed_at': datetime.now().isoformat()
                    })
                    
                    # Record assignment
                    assignment_key = f"task:assignments:{task_id}"
                    client.hset(assignment_key, mapping={
                        'worker_id': self.worker_id,
                        'started_at': time.time(),
                        'task_type': task_data.get('type', 'unknown')
                    })
                    
                    # Parse task data
                    task_data['data'] = json.loads(task_data.get('data', '{}'))
                    
                    logger.info(f"Worker {self.worker_id} claimed task {task_id}")
                    return task_data
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to claim task: {e}")
            return None
    
    def complete_task(self, task_id: str, result: Optional[Dict] = None):
        """
        Mark task as completed.
        
        Args:
            task_id: Task ID
            result: Optional result data
        """
        try:
            client = self.redis_mgr.get_client()
            
            # Update task status
            task_key = f"tasks:{task_id}"
            client.hset(task_key, mapping={
                'status': TaskStatus.COMPLETED.value,
                'completed_at': datetime.now().isoformat(),
                'completed_by': self.worker_id
            })
            
            if result:
                client.hset(task_key, 'result', json.dumps(result))
            
            # Update assignment
            assignment_key = f"task:assignments:{task_id}"
            client.hset(assignment_key, mapping={
                'completed_at': time.time(),
                'status': 'completed'
            })
            
            # Update worker stats
            worker_key = f"workers:{self.worker_id}"
            client.hincrby(worker_key, 'tasks_completed', 1)
            
            # Update metrics
            task_data = client.hget(task_key, 'type')
            if task_data:
                client.hincrby("tasks:metrics", f"completed:{task_data}", 1)
            
            logger.info(f"Task {task_id} completed by {self.worker_id}")
            
        except Exception as e:
            logger.error(f"Failed to complete task {task_id}: {e}")
    
    def fail_task(self, task_id: str, error: str, retry: bool = True):
        """
        Mark task as failed.
        
        Args:
            task_id: Task ID
            error: Error message
            retry: Whether to retry the task
        """
        try:
            client = self.redis_mgr.get_client()
            
            task_key = f"tasks:{task_id}"
            task_data = client.hgetall(task_key)
            
            if not task_data:
                logger.error(f"Task {task_id} not found")
                return
            
            attempts = int(task_data.get('attempts', 0)) + 1
            max_attempts = 3
            
            if retry and attempts < max_attempts:
                # Put back in queue for retry
                status = TaskStatus.RETRYING.value
                task_type = task_data.get('type')
                queue_key = f"tasks:queue:{task_type}"
                
                # Add back to queue with delay
                client.lpush(queue_key, task_id)
            else:
                # Max retries reached or retry disabled
                status = TaskStatus.FAILED.value
            
            # Update task
            client.hset(task_key, mapping={
                'status': status,
                'failed_at': datetime.now().isoformat(),
                'failed_by': self.worker_id,
                'error': error,
                'attempts': attempts
            })
            
            # Update assignment
            assignment_key = f"task:assignments:{task_id}"
            client.hset(assignment_key, mapping={
                'failed_at': time.time(),
                'status': 'failed',
                'error': error
            })
            
            # Update worker stats
            worker_key = f"workers:{self.worker_id}"
            client.hincrby(worker_key, 'tasks_failed', 1)
            
            # Update metrics
            if task_data.get('type'):
                client.hincrby("tasks:metrics", f"failed:{task_data['type']}", 1)
            
            logger.error(f"Task {task_id} failed: {error} (attempt {attempts}/{max_attempts})")
            
        except Exception as e:
            logger.error(f"Failed to mark task {task_id} as failed: {e}")
    
    def get_worker_stats(self) -> Dict:
        """Get statistics for this worker."""
        try:
            client = self.redis_mgr.get_client()
            worker_key = f"workers:{self.worker_id}"
            
            stats = client.hgetall(worker_key)
            
            # Add uptime
            if stats.get('started_at'):
                started = datetime.fromisoformat(stats['started_at'])
                uptime = datetime.now() - started
                stats['uptime_seconds'] = uptime.total_seconds()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get worker stats: {e}")
            return {}
    
    def get_cluster_stats(self) -> Dict:
        """Get statistics for the entire worker cluster."""
        try:
            client = self.redis_mgr.get_client()
            
            # Get active workers
            active_workers = client.smembers("workers:active")
            
            stats = {
                'active_workers': len(active_workers),
                'workers': [],
                'queue_sizes': {},
                'metrics': {}
            }
            
            # Get worker details
            for worker_id in active_workers:
                worker_data = client.hgetall(f"workers:{worker_id}")
                if worker_data:
                    # Check if worker is still alive (heartbeat within 2 minutes)
                    last_heartbeat = float(worker_data.get('last_heartbeat', 0))
                    if time.time() - last_heartbeat < 120:
                        stats['workers'].append(worker_data)
                    else:
                        # Remove stale worker
                        client.srem("workers:active", worker_id)
            
            # Get queue sizes
            for task_type in TaskType:
                queue_key = f"tasks:queue:{task_type.value}"
                size = client.llen(queue_key)
                stats['queue_sizes'][task_type.value] = size
            
            # Get metrics
            metrics = client.hgetall("tasks:metrics")
            stats['metrics'] = {k: int(v) for k, v in metrics.items()}
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get cluster stats: {e}")
            return {}
    
    def cleanup(self):
        """Clean up worker registration on shutdown."""
        try:
            client = self.redis_mgr.get_client()
            
            # Remove from active workers
            client.srem("workers:active", self.worker_id)
            
            # Update worker status
            worker_key = f"workers:{self.worker_id}"
            client.hset(worker_key, 'status', 'stopped')
            client.hset(worker_key, 'stopped_at', datetime.now().isoformat())
            
            logger.info(f"Worker {self.worker_id} cleaned up")
            
        except Exception as e:
            logger.error(f"Failed to cleanup worker: {e}")


class TaskWorker:
    """Base class for task workers."""
    
    def __init__(self, worker_type: str, capabilities: List[str]):
        self.coordinator = TaskCoordinator(worker_type, capabilities)
        self.running = False
        
    def process_task(self, task: Dict) -> Dict:
        """
        Process a task. Override in subclasses.
        
        Args:
            task: Task data
            
        Returns:
            Result dictionary
        """
        raise NotImplementedError("Subclasses must implement process_task")
    
    def run(self, max_tasks: Optional[int] = None):
        """
        Run the worker loop.
        
        Args:
            max_tasks: Maximum number of tasks to process (None for infinite)
        """
        self.running = True
        tasks_processed = 0
        
        logger.info(f"Starting worker {self.coordinator.worker_id}")
        
        try:
            while self.running:
                # Check task limit
                if max_tasks and tasks_processed >= max_tasks:
                    logger.info(f"Reached task limit of {max_tasks}")
                    break
                
                # Try to claim a task
                task = self.coordinator.claim_task(timeout=5)
                
                if not task:
                    # No tasks available, send heartbeat and continue
                    self.coordinator.heartbeat()
                    continue
                
                task_id = task['id']
                
                try:
                    # Process the task
                    logger.info(f"Processing task {task_id}")
                    result = self.process_task(task)
                    
                    # Mark as completed
                    self.coordinator.complete_task(task_id, result)
                    tasks_processed += 1
                    
                except Exception as e:
                    # Mark as failed
                    logger.error(f"Task {task_id} failed: {e}")
                    self.coordinator.fail_task(task_id, str(e))
                    
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the worker."""
        self.running = False
        self.coordinator.cleanup()
        logger.info(f"Worker {self.coordinator.worker_id} stopped")


if __name__ == "__main__":
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description="Task coordinator utilities")
    parser.add_argument('command', choices=['stats', 'submit', 'monitor'],
                        help='Command to run')
    parser.add_argument('--task-type', help='Task type for submit command')
    parser.add_argument('--task-data', help='Task data JSON for submit command')
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    coordinator = TaskCoordinator()
    
    if args.command == 'stats':
        stats = coordinator.get_cluster_stats()
        print(json.dumps(stats, indent=2))
        
    elif args.command == 'submit':
        if not args.task_type or not args.task_data:
            print("Error: --task-type and --task-data required for submit")
        else:
            task_type = TaskType(args.task_type)
            task_data = json.loads(args.task_data)
            task_id = coordinator.submit_task(task_type, task_data)
            print(f"Submitted task: {task_id}")
            
    elif args.command == 'monitor':
        print("Monitoring cluster stats (Ctrl+C to stop)...")
        try:
            while True:
                stats = coordinator.get_cluster_stats()
                print(f"\nActive workers: {stats['active_workers']}")
                print("Queue sizes:", stats['queue_sizes'])
                print("Metrics:", stats['metrics'])
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nMonitoring stopped")