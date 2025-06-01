#!/usr/bin/env python3
"""
Real-time log monitoring for the document processing pipeline.
Provides colored output and filtering capabilities for debugging.
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime
import argparse
import re
from typing import List, Optional

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'

def colorize_log_line(line: str) -> str:
    """Add colors to log lines based on content."""
    
    # Task execution patterns
    if "TASK START" in line:
        return f"{Colors.BOLD}{Colors.GREEN}{line}{Colors.RESET}"
    elif "TASK SUCCESS" in line:
        return f"{Colors.BOLD}{Colors.CYAN}{line}{Colors.RESET}"
    elif "TASK FAILED" in line:
        return f"{Colors.BOLD}{Colors.RED}{line}{Colors.RESET}"
    
    # Log levels
    elif "[ERROR]" in line or "ERROR" in line:
        return f"{Colors.RED}{line}{Colors.RESET}"
    elif "[WARNING]" in line or "WARNING" in line:
        return f"{Colors.YELLOW}{line}{Colors.RESET}"
    elif "[INFO]" in line or "INFO" in line:
        return f"{Colors.GREEN}{line}{Colors.RESET}"
    elif "[DEBUG]" in line or "DEBUG" in line:
        return f"{Colors.BLUE}{line}{Colors.RESET}"
    
    # Special patterns
    elif "Document:" in line or "document_uuid" in line:
        return f"{Colors.CYAN}{line}{Colors.RESET}"
    elif "Duration:" in line or "elapsed" in line:
        return f"{Colors.YELLOW}{line}{Colors.RESET}"
    elif "===" in line:
        return f"{Colors.BOLD}{line}{Colors.RESET}"
    
    return line

def find_log_files(log_dir: Path, pattern: str = "*") -> List[Path]:
    """Find log files matching pattern."""
    date_str = datetime.now().strftime("%Y%m%d")
    
    # Find all log files from today
    log_files = []
    
    # If pattern is specific file type
    if pattern in ['error', 'errors']:
        log_files.extend(log_dir.rglob(f"errors_{date_str}.log"))
    elif pattern in ['sql', 'database']:
        log_files.extend((log_dir / 'database').glob(f"*{date_str}.log"))
    elif pattern in ['redis', 'cache']:
        log_files.extend((log_dir / 'cache').glob(f"*{date_str}.log"))
    elif pattern in ['celery', 'tasks']:
        log_files.extend((log_dir / 'celery').glob(f"*{date_str}.log"))
        log_files.extend((log_dir / 'pdf_tasks').glob(f"*{date_str}.log"))
    else:
        # All logs
        log_files.extend(log_dir.rglob(f"*{date_str}.log"))
    
    return sorted(log_files)

def tail_logs(log_files: List[Path], follow: bool = True, lines: int = 50, 
              filter_pattern: Optional[str] = None, exclude_pattern: Optional[str] = None):
    """Tail multiple log files with optional filtering."""
    
    if not log_files:
        print(f"{Colors.RED}No log files found!{Colors.RESET}")
        return
    
    print(f"{Colors.HEADER}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}Monitoring {len(log_files)} log file(s):{Colors.RESET}")
    for f in log_files:
        print(f"  📄 {f}")
    print(f"{Colors.HEADER}{'='*60}{Colors.RESET}\n")
    
    # Build tail command
    cmd = ["tail"]
    if follow:
        cmd.append("-f")
    cmd.extend(["-n", str(lines)])
    cmd.extend([str(f) for f in log_files])
    
    # Run tail and process output
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    try:
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                # Apply filters
                if filter_pattern and filter_pattern not in line:
                    continue
                if exclude_pattern and exclude_pattern in line:
                    continue
                
                # Colorize and print
                print(colorize_log_line(line.rstrip()))
                
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Monitoring stopped by user{Colors.RESET}")
        process.terminate()

def monitor_document(log_dir: Path, document_uuid: str):
    """Monitor logs for a specific document."""
    
    print(f"{Colors.HEADER}Tracking document: {document_uuid}{Colors.RESET}\n")
    
    # Use grep to find all mentions
    cmd = ["grep", "-r", document_uuid, str(log_dir), "--include=*.log"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            # Sort by timestamp if possible
            for line in sorted(lines):
                print(colorize_log_line(line))
        else:
            print(f"{Colors.YELLOW}No logs found for document {document_uuid}{Colors.RESET}")
            
    except Exception as e:
        print(f"{Colors.RED}Error searching logs: {e}{Colors.RESET}")

def show_recent_errors(log_dir: Path, minutes: int = 10):
    """Show recent errors from all logs."""
    
    print(f"{Colors.HEADER}Recent errors (last {minutes} minutes):{Colors.RESET}\n")
    
    # Find all log files
    log_files = find_log_files(log_dir, "*")
    
    errors = []
    for log_file in log_files:
        # Use grep to find ERROR lines
        cmd = ["grep", "-n", "ERROR", str(log_file)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                errors.append(f"{log_file.name}: {line}")
    
    if errors:
        # Show last 50 errors
        for error in errors[-50:]:
            print(colorize_log_line(error))
    else:
        print(f"{Colors.GREEN}No errors found!{Colors.RESET}")

def main():
    parser = argparse.ArgumentParser(description="Monitor document processing logs")
    parser.add_argument('command', nargs='?', default='tail',
                       choices=['tail', 'document', 'errors', 'tasks'],
                       help='Command to run')
    parser.add_argument('-d', '--document', help='Document UUID to track')
    parser.add_argument('-f', '--filter', help='Filter pattern (include lines matching)')
    parser.add_argument('-x', '--exclude', help='Exclude pattern (exclude lines matching)')
    parser.add_argument('-n', '--lines', type=int, default=50, help='Number of lines to show initially')
    parser.add_argument('-t', '--type', default='all', 
                       choices=['all', 'error', 'sql', 'redis', 'celery', 'tasks'],
                       help='Type of logs to monitor')
    parser.add_argument('--no-follow', action='store_true', help="Don't follow logs (tail -f)")
    
    args = parser.parse_args()
    
    # Log directory
    log_dir = Path("/opt/legal-doc-processor/monitoring/logs")
    
    if not log_dir.exists():
        print(f"{Colors.RED}Error: Log directory does not exist: {log_dir}{Colors.RESET}")
        print(f"{Colors.YELLOW}Run 'python scripts/setup_logging.py' first!{Colors.RESET}")
        sys.exit(1)
    
    # Execute command
    if args.command == 'document' or args.document:
        if not args.document:
            print(f"{Colors.RED}Error: Document UUID required{Colors.RESET}")
            sys.exit(1)
        monitor_document(log_dir, args.document)
        
    elif args.command == 'errors':
        show_recent_errors(log_dir)
        
    elif args.command == 'tasks':
        # Monitor task execution
        log_files = find_log_files(log_dir, 'tasks')
        log_files.extend(find_log_files(log_dir, 'celery'))
        tail_logs(log_files, not args.no_follow, args.lines, 
                 filter_pattern="TASK", exclude_pattern=args.exclude)
        
    else:  # tail
        # Find log files based on type
        log_files = find_log_files(log_dir, args.type)
        tail_logs(log_files, not args.no_follow, args.lines, 
                 args.filter, args.exclude)

if __name__ == "__main__":
    main()