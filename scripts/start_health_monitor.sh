#!/bin/bash
# Start health monitor for legal document processor

# Set up environment
export PYTHONPATH="/opt/legal-doc-processor:$PYTHONPATH"

# Check if already running
if pgrep -f "health_monitor.py" > /dev/null; then
    echo "Health monitor is already running"
    exit 0
fi

echo "Starting health monitor..."

# Load environment variables
if [ -f /opt/legal-doc-processor/.env ]; then
    export $(grep -v '^#' /opt/legal-doc-processor/.env | xargs)
fi

# Start the monitor in the background
nohup python /opt/legal-doc-processor/scripts/monitoring/health_monitor.py > /opt/legal-doc-processor/health_monitor.log 2>&1 &

echo "Health monitor started. PID: $!"
echo "Logs: /opt/legal-doc-processor/health_monitor.log"