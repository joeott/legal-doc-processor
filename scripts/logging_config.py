"""
Enhanced Logging Configuration for Consolidated PDF Pipeline
Provides module-specific logging with structured output and performance tracking
"""
import logging
import logging.handlers
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import threading
from contextlib import contextmanager
import time

# Create logs directory structure
BASE_LOG_DIR = Path(__file__).parent.parent / "monitoring" / "logs"
LOG_DIRS = {
    'main': BASE_LOG_DIR,
    'cache': BASE_LOG_DIR / 'cache',
    'database': BASE_LOG_DIR / 'database',
    'entity': BASE_LOG_DIR / 'entity',
    'graph': BASE_LOG_DIR / 'graph',
    'pdf_tasks': BASE_LOG_DIR / 'pdf_tasks',
    'tests': BASE_LOG_DIR / 'tests',
    'celery': BASE_LOG_DIR / 'celery',
    'api': BASE_LOG_DIR / 'api'
}

# Create all directories with error handling
for dir_name, dir_path in LOG_DIRS.items():
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        # Verify directory was created
        if not dir_path.exists():
            print(f"WARNING: Failed to create log directory: {dir_path}")
    except Exception as e:
        print(f"ERROR: Failed to create log directory {dir_name}: {e}")

def setup_logging(name=None, log_level=logging.INFO, module_type=None):
    """
    Set up logging with both console and file handlers
    
    Args:
        name: Logger name (defaults to root logger)
        log_level: Logging level
        module_type: Type of module for log directory selection
        
    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers = []
    
    # Console handler with color support
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    # File handler - rotates daily and keeps 30 days of logs
    log_filename = datetime.now().strftime("pipeline_%Y%m%d.log")
    # Use the main log directory for all logs
    log_dir = LOG_DIRS.get(module_type or 'main', LOG_DIRS['main'])
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_dir / log_filename,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)  # Capture more detail in files
    
    # Error file handler - only ERROR and above
    error_filename = datetime.now().strftime("errors_%Y%m%d.log")
    error_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_dir / error_filename,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    
    # Detailed formatter for files
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Simpler formatter for console
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Apply formatters
    console_handler.setFormatter(console_formatter)
    file_handler.setFormatter(file_formatter)
    error_handler.setFormatter(file_formatter)
    
    # Add handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    
    # Log startup message
    if name:
        logger.info(f"Logger initialized for {name}")
    else:
        logger.info("Root logger initialized")
    logger.info(f"Logs directory: {log_dir}")
    logger.info(f"Main log file: {log_dir / log_filename}")
    logger.info(f"Error log file: {log_dir / error_filename}")
    
    return logger

def get_logger(name):
    """Get or create a logger with the standard configuration"""
    return setup_logging(name)


class StructuredLogger:
    """Enhanced logger with structured logging capabilities"""
    
    def __init__(self, name: str, module_type: Optional[str] = None):
        self.module_type = module_type or 'main'
        self.logger = setup_logging(name, module_type=self.module_type)
        self.context = threading.local()
        
    def _get_context(self) -> Dict[str, Any]:
        """Get thread-local context"""
        if not hasattr(self.context, 'data'):
            self.context.data = {}
        return self.context.data
    
    def set_context(self, **kwargs):
        """Set context values for structured logging"""
        self._get_context().update(kwargs)
    
    def clear_context(self):
        """Clear context values"""
        self._get_context().clear()
    
    def _format_message(self, message: str, extra: Dict[str, Any] = None) -> str:
        """Format message with context"""
        context = self._get_context()
        if extra:
            context = {**context, **extra}
        
        if context:
            # Create structured log entry
            structured_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'module': self.module_type,
                'message': message,
                'context': context
            }
            return f"{message} | {json.dumps(context, default=str)}"
        return message
    
    def debug(self, message: str, **kwargs):
        self.logger.debug(self._format_message(message, kwargs))
    
    def info(self, message: str, **kwargs):
        self.logger.info(self._format_message(message, kwargs))
    
    def warning(self, message: str, **kwargs):
        self.logger.warning(self._format_message(message, kwargs))
    
    def error(self, message: str, **kwargs):
        self.logger.error(self._format_message(message, kwargs))
    
    def critical(self, message: str, **kwargs):
        self.logger.critical(self._format_message(message, kwargs))
    
    @contextmanager
    def timer(self, operation: str):
        """Context manager for timing operations"""
        start_time = time.time()
        self.info(f"Starting {operation}")
        try:
            yield
        finally:
            elapsed = time.time() - start_time
            self.info(f"Completed {operation}", duration_seconds=elapsed)
    
    @contextmanager
    def operation_context(self, operation: str, **context):
        """Context manager for operation logging with context"""
        self.set_context(**context)
        try:
            with self.timer(operation):
                yield
        finally:
            self.clear_context()


# Module-specific logger factory
def get_module_logger(module_name: str, module_type: str = None) -> StructuredLogger:
    """
    Get a module-specific structured logger
    
    Args:
        module_name: Full module name (e.g., 'scripts.cache')
        module_type: Type of module ('cache', 'database', 'entity', etc.)
    
    Returns:
        StructuredLogger instance
    """
    if module_type is None:
        # Infer module type from name
        parts = module_name.split('.')
        if len(parts) > 1:
            module_type = parts[-1]
        else:
            module_type = 'main'
    
    return StructuredLogger(module_name, module_type)


# Performance tracking utilities
class PerformanceLogger:
    """Logger for tracking performance metrics"""
    
    def __init__(self, logger: StructuredLogger):
        self.logger = logger
        self.metrics = {}
    
    def record_metric(self, metric_name: str, value: float, unit: str = 'seconds'):
        """Record a performance metric"""
        self.metrics[metric_name] = {
            'value': value,
            'unit': unit,
            'timestamp': datetime.utcnow().isoformat()
        }
        self.logger.info(f"Performance metric recorded", 
                        metric=metric_name, 
                        value=value, 
                        unit=unit)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all recorded metrics"""
        return self.metrics.copy()
    
    def log_summary(self):
        """Log a summary of all metrics"""
        if self.metrics:
            self.logger.info("Performance summary", metrics=self.metrics)