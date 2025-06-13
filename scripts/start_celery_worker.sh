#!/bin/bash

# Load environment variables
source /opt/legal-doc-processor/load_env.sh

# Memory monitoring configuration
MAX_MEMORY_MB=512

# Function to check memory usage
check_memory() {
    local pid=$1
    local mem_kb=$(ps -o rss= -p $pid 2>/dev/null || echo 0)
    local mem_mb=$((mem_kb / 1024))
    
    if [ $mem_mb -gt $MAX_MEMORY_MB ]; then
        echo "Worker $pid using ${mem_mb}MB > ${MAX_MEMORY_MB}MB limit"
        kill -TERM $pid
        sleep 2
        kill -KILL $pid 2>/dev/null
    fi
}

# Start worker with memory limits
cd /opt/legal-doc-processor
celery -A scripts.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --max-memory-per-child=200000 \
    --queues=default,ocr,text,entity,graph &

WORKER_PID=$!

# Monitor memory usage
while true; do
    if ! kill -0 $WORKER_PID 2>/dev/null; then
        echo "Worker died, restarting..."
        exec $0
    fi
    
    check_memory $WORKER_PID
    
    # Check child processes
    for child in $(pgrep -P $WORKER_PID); do
        check_memory $child
    done
    
    sleep 10
done