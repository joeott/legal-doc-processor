#!/usr/bin/env python3
"""
Enhanced logging setup for testing the document processing pipeline.
Run this before testing to ensure proper logging configuration.
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

def setup_test_logging():
    """Enhanced logging setup for testing phase."""
    
    print("🔧 Setting up enhanced logging for testing...")
    
    # 1. Create all log directories
    base_dir = Path("/opt/legal-doc-processor/monitoring/logs")
    subdirs = ['cache', 'database', 'entity', 'graph', 'pdf_tasks', 'tests', 'celery', 'api']
    
    # Create base directory
    base_dir.mkdir(parents=True, exist_ok=True)
    print(f"✅ Created base log directory: {base_dir}")
    
    # Create subdirectories
    for subdir in subdirs:
        subdir_path = base_dir / subdir
        subdir_path.mkdir(exist_ok=True)
        print(f"  📁 Created: {subdir_path}")
    
    # 2. Configure root logger for DEBUG level
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 3. Add enhanced console handler with colors
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    
    # Color codes for different log levels
    class ColoredFormatter(logging.Formatter):
        COLORS = {
            'DEBUG': '\033[36m',    # Cyan
            'INFO': '\033[32m',     # Green
            'WARNING': '\033[33m',  # Yellow
            'ERROR': '\033[31m',    # Red
            'CRITICAL': '\033[35m', # Magenta
        }
        RESET = '\033[0m'
        
        def format(self, record):
            log_color = self.COLORS.get(record.levelname, self.RESET)
            record.levelname = f"{log_color}{record.levelname:8s}{self.RESET}"
            return super().format(record)
    
    formatter = ColoredFormatter(
        '%(asctime)s [%(levelname)s] %(name)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console.setFormatter(formatter)
    root_logger.addHandler(console)
    
    # 4. Add file handler for all logs
    log_file = base_dir / f"all_logs_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # 5. Enable specific module logging
    
    # SQLAlchemy logging
    sqlalchemy_logger = logging.getLogger('sqlalchemy.engine')
    sqlalchemy_logger.setLevel(logging.INFO)
    sql_handler = logging.FileHandler(base_dir / 'database' / f"sql_{datetime.now().strftime('%Y%m%d')}.log")
    sql_handler.setFormatter(file_formatter)
    sqlalchemy_logger.addHandler(sql_handler)
    print("✅ Enabled SQL query logging")
    
    # Redis logging
    redis_logger = logging.getLogger('redis')
    redis_logger.setLevel(logging.DEBUG)
    redis_handler = logging.FileHandler(base_dir / 'cache' / f"redis_{datetime.now().strftime('%Y%m%d')}.log")
    redis_handler.setFormatter(file_formatter)
    redis_logger.addHandler(redis_handler)
    print("✅ Enabled Redis command logging")
    
    # Celery logging
    celery_logger = logging.getLogger('celery')
    celery_logger.setLevel(logging.DEBUG)
    celery_handler = logging.FileHandler(base_dir / 'celery' / f"celery_{datetime.now().strftime('%Y%m%d')}.log")
    celery_handler.setFormatter(file_formatter)
    celery_logger.addHandler(celery_handler)
    print("✅ Enabled Celery task logging")
    
    # API/HTTP logging
    urllib3_logger = logging.getLogger('urllib3')
    urllib3_logger.setLevel(logging.DEBUG)
    api_handler = logging.FileHandler(base_dir / 'api' / f"api_calls_{datetime.now().strftime('%Y%m%d')}.log")
    api_handler.setFormatter(file_formatter)
    urllib3_logger.addHandler(api_handler)
    print("✅ Enabled API call logging")
    
    # 6. Create test log entry
    test_logger = logging.getLogger('setup_logging')
    test_logger.debug("Debug message test")
    test_logger.info("Info message test")
    test_logger.warning("Warning message test")
    test_logger.error("Error message test")
    
    print(f"\n📊 Logging Summary:")
    print(f"  • Root log level: DEBUG")
    print(f"  • Console output: ENABLED with colors")
    print(f"  • File logging: {log_file}")
    print(f"  • SQL queries: {base_dir / 'database'}")
    print(f"  • Redis commands: {base_dir / 'cache'}")
    print(f"  • Celery tasks: {base_dir / 'celery'}")
    print(f"  • API calls: {base_dir / 'api'}")
    
    # 7. Create helper scripts
    create_helper_scripts(base_dir)
    
    print("\n✅ Logging setup complete!")
    print("\n💡 Quick commands:")
    print("  • View all errors: tail -f monitoring/logs/all_logs_*.log | grep ERROR")
    print("  • Monitor in real-time: python scripts/monitor_logs.py")
    print("  • Check specific document: grep -r 'YOUR_UUID' monitoring/logs/")

def create_helper_scripts(base_dir):
    """Create helper scripts for log monitoring."""
    
    # Create quick error viewer
    error_script = base_dir / "show_errors.sh"
    error_script.write_text("""#!/bin/bash
# Show recent errors from all log files

echo "🔍 Recent errors from all logs:"
echo "================================"
find /opt/legal-doc-processor/monitoring/logs -name "*.log" -type f -exec grep -H "ERROR" {} \\; | tail -50
""")
    error_script.chmod(0o755)
    
    # Create document tracker
    doc_script = base_dir / "track_document.sh"
    doc_script.write_text("""#!/bin/bash
# Track a specific document through the pipeline

if [ -z "$1" ]; then
    echo "Usage: $0 <document_uuid>"
    exit 1
fi

echo "📄 Tracking document: $1"
echo "================================"
grep -r "$1" /opt/legal-doc-processor/monitoring/logs/ | sort -k1
""")
    doc_script.chmod(0o755)
    
    print("✅ Created helper scripts:")
    print(f"  • {error_script}")
    print(f"  • {doc_script}")

def configure_env_logging():
    """Set environment variables for enhanced logging."""
    
    # Set environment variables
    os.environ['LOG_LEVEL'] = 'DEBUG'
    os.environ['LOG_TO_CONSOLE'] = 'true'
    os.environ['LOG_SQL_QUERIES'] = 'true'
    os.environ['LOG_REDIS_COMMANDS'] = 'true'
    os.environ['LOG_API_CALLS'] = 'true'
    os.environ['ENABLE_PERFORMANCE_LOGGING'] = 'true'
    
    print("\n🔧 Set environment variables for testing:")
    for key, value in os.environ.items():
        if key.startswith('LOG_') or key.startswith('ENABLE_'):
            print(f"  • {key}={value}")

if __name__ == "__main__":
    # Run setup
    setup_test_logging()
    configure_env_logging()
    
    # Test import to ensure scripts directory is in path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    print("\n🎯 Next steps:")
    print("1. Run a test document through the pipeline")
    print("2. Monitor logs with: python scripts/monitor_logs.py")
    print("3. Check for errors with: monitoring/logs/show_errors.sh")