"""
Celery Application Configuration for PDF Document Processing Pipeline
"""
from celery import Celery
from celery.signals import worker_process_init
import os
import resource
import logging
from scripts.config import (
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, REDIS_SSL,
    DEPLOYMENT_STAGE, STAGE_CLOUD_ONLY, get_redis_config_for_stage
)

logger = logging.getLogger(__name__)

# Memory limit configuration
WORKER_MAX_MEMORY_MB = 512  # 512MB per worker
WORKER_MEMORY_LIMIT = WORKER_MAX_MEMORY_MB * 1024 * 1024  # Convert to bytes

def set_memory_limit():
    """Set memory limit for worker process"""
    try:
        resource.setrlimit(resource.RLIMIT_AS, (WORKER_MEMORY_LIMIT, WORKER_MEMORY_LIMIT))
        logger.info(f"Set worker memory limit to {WORKER_MAX_MEMORY_MB}MB")
    except Exception as e:
        logger.warning(f"Could not set memory limit: {e}")

# Construct Redis URL from existing config
redis_config = get_redis_config_for_stage(DEPLOYMENT_STAGE)
redis_host = redis_config.get('host', REDIS_HOST)
redis_port = redis_config.get('port', REDIS_PORT)
redis_ssl = redis_config.get('ssl', REDIS_SSL)

# Build Redis URL with SSL support
from scripts.config import REDIS_USERNAME

if REDIS_PASSWORD:
    if REDIS_USERNAME:
        # Include username in URL (Redis Cloud requires this)
        redis_url = f"{'rediss' if redis_ssl else 'redis'}://{REDIS_USERNAME}:{REDIS_PASSWORD}@{redis_host}:{redis_port}/{REDIS_DB}"
    else:
        redis_url = f"{'rediss' if redis_ssl else 'redis'}://:{REDIS_PASSWORD}@{redis_host}:{redis_port}/{REDIS_DB}"
else:
    redis_url = f"{'rediss' if redis_ssl else 'redis'}://{redis_host}:{redis_port}/{REDIS_DB}"

# Create Celery app
app = Celery(
    'pdf_pipeline',
    broker=redis_url,
    backend=redis_url,
    include=[
        'scripts.pdf_tasks'  # Main task module
    ]
)

# Configure Celery
app.conf.update(
    # Serialization
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    
    # Timezone
    timezone='UTC',
    enable_utc=True,
    
    # Worker settings
    worker_prefetch_multiplier=1,  # Process one task at a time
    task_acks_late=True,           # Acknowledge after completion
    worker_max_tasks_per_child=50, # Restart worker after 50 tasks to prevent memory leaks
    worker_max_memory_per_child=200000,  # Restart worker after 200MB (in KB)
    
    # Task execution limits
    task_soft_time_limit=240,      # 4 minute soft limit
    task_time_limit=300,           # 5 minute hard limit
    
    # Result backend
    result_expires=3600 * 24 * 7,  # Keep results for 7 days
    result_persistent=True,         # Persist results
    
    # Task tracking
    task_track_started=True,
    task_send_sent_event=True,
    worker_send_task_events=True,
    
    # Retry configuration
    task_default_retry_delay=60,
    task_max_retry_delay=3600,
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_retry_jitter=True,
    
    # Queue configuration
    task_default_queue='default',
    task_create_missing_queues=True,
    
    # Define task routes for specialized workers
    task_routes={
        'scripts.pdf_tasks.extract_text_from_document': {'queue': 'ocr'},
        'scripts.pdf_tasks.chunk_document_text': {'queue': 'text'},
        'scripts.pdf_tasks.extract_entities_from_chunks': {'queue': 'entity'},
        'scripts.pdf_tasks.resolve_document_entities': {'queue': 'entity'},
        'scripts.resolution_task.resolve_entities_standalone': {'queue': 'entity'},
        'scripts.pdf_tasks.build_document_relationships': {'queue': 'graph'},
        'scripts.pdf_tasks.process_pdf_document': {'queue': 'default'},
        'scripts.pdf_tasks.cleanup_*': {'queue': 'cleanup'},
    },
    
    # Beat scheduler (for future periodic tasks)
    beat_scheduler='celery.beat:PersistentScheduler',
    beat_schedule_filename='celerybeat-schedule',
    
    # Security
    worker_hijack_root_logger=False,
    worker_log_color=True,
    
    # Performance optimizations
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    
    # Redis-specific optimizations
    redis_max_connections=100,
    redis_socket_keepalive=True,
    redis_socket_keepalive_options={
        1: 3,   # TCP_KEEPIDLE
        2: 3,   # TCP_KEEPINTVL
        3: 3,   # TCP_KEEPCNT
    },
    
    # Task publication
    task_publish_retry=True,
    task_publish_retry_policy={
        'max_retries': 3,
        'interval_start': 0.1,
        'interval_step': 0.2,
        'interval_max': 0.5,
    },
)

# Stage-specific configuration
if DEPLOYMENT_STAGE == STAGE_CLOUD_ONLY:
    # Cloud deployment optimizations
    app.conf.update(
        broker_transport_options={
            'visibility_timeout': 3600,  # 1 hour for long-running cloud tasks
            'fanout_prefix': True,
            'fanout_patterns': True,
        }
    )

# Task signatures for common patterns
app.signature_map = {
    'process_document': app.signature(
        'scripts.pdf_tasks.process_pdf_document',
        options={'queue': 'default'}
    ),
}

# Add worker initialization
@worker_process_init.connect
def setup_worker_process(**kwargs):
    """Initialize worker process with memory limits"""
    set_memory_limit()

if __name__ == '__main__':
    app.start()