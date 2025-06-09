#!/usr/bin/env python3
"""Start a Celery worker with proper error handling"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add scripts to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # Import and print debug info
    logger.info("Importing Celery app...")
    from scripts.celery_app import app
    
    logger.info("Celery app imported successfully")
    logger.info(f"Registered tasks: {list(app.tasks.keys())}")
    
    # Start worker
    logger.info("Starting worker...")
    app.worker_main(['worker', '--loglevel=info', '--concurrency=1'])
    
except Exception as e:
    logger.error(f"Failed to start worker: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)