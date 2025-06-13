#!/bin/bash
# Production-ready worker startup script based on Context 505 analysis
# This script starts all required Celery workers with optimal configuration

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Legal Document Processing Pipeline - Worker Startup${NC}"
echo "====================================================="
date

# Change to project directory
cd /opt/legal-doc-processor

# Load environment variables
if [ -f .env ]; then
    echo -e "${GREEN}Loading environment variables...${NC}"
    set -a
    source .env
    set +a
else
    echo -e "${RED}ERROR: .env file not found!${NC}"
    exit 1
fi

# Create log directory if it doesn't exist
LOG_DIR="/var/log/celery"
if [ ! -d "$LOG_DIR" ]; then
    echo -e "${YELLOW}Creating log directory: $LOG_DIR${NC}"
    sudo mkdir -p $LOG_DIR
    sudo chown $USER:$USER $LOG_DIR
fi

# Function to check if a worker is running
check_worker() {
    local worker_name=$1
    if ps aux | grep -v grep | grep -q "celery.*$worker_name"; then
        return 0
    else
        return 1
    fi
}

# Kill existing workers
echo -e "${YELLOW}Stopping existing workers...${NC}"
ps aux | grep "[c]elery.*worker" | awk '{print $2}' | xargs -r kill -9 2>/dev/null || true
sleep 3

# Start workers with optimal configuration
echo -e "${GREEN}Starting workers...${NC}"

# 1. OCR Worker - Memory intensive for Textract
echo -n "Starting OCR worker... "
celery -A scripts.celery_app worker \
    -Q ocr \
    -n worker.ocr@%h \
    --concurrency=1 \
    --max-memory-per-child=800000 \
    --loglevel=info \
    > $LOG_DIR/ocr_worker.log 2>&1 &
sleep 2
if check_worker "worker.ocr"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# 2. Text Processing Worker - Chunking operations
echo -n "Starting text processing worker... "
celery -A scripts.celery_app worker \
    -Q text \
    -n worker.text@%h \
    --concurrency=2 \
    --max-memory-per-child=400000 \
    --loglevel=info \
    > $LOG_DIR/text_worker.log 2>&1 &
sleep 2
if check_worker "worker.text"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# 3. Entity Worker - NLP/AI operations
echo -n "Starting entity worker... "
celery -A scripts.celery_app worker \
    -Q entity \
    -n worker.entity@%h \
    --concurrency=1 \
    --max-memory-per-child=600000 \
    --loglevel=info \
    > $LOG_DIR/entity_worker.log 2>&1 &
sleep 2
if check_worker "worker.entity"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# 4. Graph Worker - Relationship building
echo -n "Starting graph worker... "
celery -A scripts.celery_app worker \
    -Q graph \
    -n worker.graph@%h \
    --concurrency=1 \
    --max-memory-per-child=400000 \
    --loglevel=info \
    > $LOG_DIR/graph_worker.log 2>&1 &
sleep 2
if check_worker "worker.graph"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# 5. Default/Orchestration Worker
echo -n "Starting default worker... "
celery -A scripts.celery_app worker \
    -Q default,cleanup \
    -n worker.default@%h \
    --concurrency=1 \
    --max-memory-per-child=300000 \
    --loglevel=info \
    > $LOG_DIR/default_worker.log 2>&1 &
sleep 2
if check_worker "worker.default"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# 6. Batch Processing Workers - CRITICAL for batch operations
echo -e "${YELLOW}Starting batch processing workers...${NC}"

# High priority batch worker
echo -n "Starting high priority batch worker... "
celery -A scripts.celery_app worker \
    -Q batch.high \
    -n worker.batch.high@%h \
    --concurrency=2 \
    --max-memory-per-child=300000 \
    --loglevel=info \
    > $LOG_DIR/batch_high_worker.log 2>&1 &
sleep 2
if check_worker "worker.batch.high"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Normal priority batch worker
echo -n "Starting normal priority batch worker... "
celery -A scripts.celery_app worker \
    -Q batch.normal \
    -n worker.batch.normal@%h \
    --concurrency=1 \
    --max-memory-per-child=300000 \
    --loglevel=info \
    > $LOG_DIR/batch_normal_worker.log 2>&1 &
sleep 2
if check_worker "worker.batch.normal"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Low priority batch worker (combined with normal for efficiency)
echo -n "Starting low priority batch worker... "
celery -A scripts.celery_app worker \
    -Q batch.low \
    -n worker.batch.low@%h \
    --concurrency=1 \
    --max-memory-per-child=200000 \
    --loglevel=info \
    > $LOG_DIR/batch_low_worker.log 2>&1 &
sleep 2
if check_worker "worker.batch.low"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Final status check
echo -e "\n${GREEN}Worker Status Summary:${NC}"
echo "====================="

WORKER_COUNT=$(ps aux | grep "[c]elery.*worker" | wc -l)
echo -e "Total workers running: ${GREEN}$WORKER_COUNT${NC}"

# Show individual worker status
echo -e "\nWorker Details:"
ps aux | grep "[c]elery.*worker" | grep -v grep | awk '{print $2, $11, $12, $13, $14, $15}' | while read pid args; do
    echo "  PID $pid: $args"
done

# Show queue status
echo -e "\n${GREEN}Queue Status:${NC}"
echo "============="
if command -v redis-cli &> /dev/null; then
    for queue in default ocr text entity graph cleanup batch.high batch.normal batch.low; do
        LENGTH=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD --no-auth-warning llen $queue 2>/dev/null || echo "0")
        printf "  %-15s: %s messages\n" "$queue" "$LENGTH"
    done
else
    echo "  Redis CLI not available for queue status"
fi

# Memory usage summary
echo -e "\n${GREEN}Memory Usage:${NC}"
echo "============="
TOTAL_MEM=$(free -m | awk 'NR==2{printf "%.1f", $2/1024}')
USED_MEM=$(free -m | awk 'NR==2{printf "%.1f", $3/1024}')
FREE_MEM=$(free -m | awk 'NR==2{printf "%.1f", $4/1024}')
echo "  Total: ${TOTAL_MEM}GB | Used: ${USED_MEM}GB | Free: ${FREE_MEM}GB"

echo -e "\n${GREEN}Worker startup complete!${NC}"
echo "Logs available in: $LOG_DIR"
echo "Monitor with: tail -f $LOG_DIR/*.log"