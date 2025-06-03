#!/usr/bin/env python3
"""
Phase 4 Test 4.1: Monitor Polling Task Activity
Monitor logs for 30 seconds to verify polling tasks are running.
"""
import time
import subprocess
import sys
from datetime import datetime

def monitor_polling_activity(duration=30):
    """Monitor logs for polling activity"""
    print(f"=== Phase 4 Test 4.1: Polling Task Monitoring ===")
    print(f"Monitoring for {duration} seconds...")
    print(f"Start time: {datetime.now()}")
    print("-" * 60)
    
    # Check if polling task is registered
    try:
        result = subprocess.run(
            ["python3", "-c", """
from scripts.celery_app import app
tasks = list(app.tasks.keys())
polling_tasks = [t for t in tasks if 'poll' in t.lower()]
for task in polling_tasks:
    print(f'✅ Polling task registered: {task}')
if not polling_tasks:
    print('❌ No polling tasks found!')
"""],
            capture_output=True,
            text=True
        )
        print(result.stdout)
        if result.stderr:
            print(f"Error: {result.stderr}")
    except Exception as e:
        print(f"Error checking tasks: {e}")
    
    print("\nMonitoring worker logs...")
    
    # Monitor logs for polling activity
    start_time = time.time()
    polling_patterns = ["poll_textract_job", "Polling", "retry", "IN_PROGRESS"]
    found_patterns = set()
    
    # Start log monitoring
    try:
        # Use journalctl or check log files
        log_process = subprocess.Popen(
            ["tail", "-f", "/opt/legal-doc-processor/monitoring/logs/celery_worker.log"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        print("\nLog entries containing polling activity:")
        print("-" * 60)
        
        while time.time() - start_time < duration:
            # Check if there's output
            line = log_process.stdout.readline()
            if line:
                # Check for polling patterns
                for pattern in polling_patterns:
                    if pattern.lower() in line.lower():
                        found_patterns.add(pattern)
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        print(f"[{timestamp}] {line.strip()}")
            
            time.sleep(0.1)
        
        log_process.terminate()
        
    except FileNotFoundError:
        print("Log file not found, checking alternative sources...")
        
        # Try to get recent Celery logs another way
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True
            )
            if "celery" in result.stdout:
                print("✅ Celery worker process is running")
            else:
                print("⚠️ No Celery worker process found")
        except:
            pass
    
    except Exception as e:
        print(f"Error monitoring logs: {e}")
    
    print("\n" + "-" * 60)
    print(f"Monitoring complete. End time: {datetime.now()}")
    print(f"\nPatterns found: {', '.join(found_patterns) if found_patterns else 'None'}")
    
    # Summary
    print("\n=== Test 4.1 Results ===")
    if found_patterns:
        print(f"✅ Found polling activity patterns: {found_patterns}")
        return True
    else:
        print("⚠️ No polling activity detected in logs during monitoring period")
        print("This could mean:")
        print("- No documents are currently being processed")
        print("- Polling tasks are scheduled but not executing")
        print("- Log location is different than expected")
        return False

if __name__ == "__main__":
    success = monitor_polling_activity(30)
    sys.exit(0 if success else 1)