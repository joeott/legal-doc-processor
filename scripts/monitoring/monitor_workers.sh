#!/bin/bash
# Worker monitoring script - checks health and queue status
# Can be run manually or via cron for continuous monitoring

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
EXPECTED_WORKERS=8
WARNING_QUEUE_DEPTH=50
CRITICAL_QUEUE_DEPTH=100

echo -e "${BLUE}Worker Health Monitor - $(date)${NC}"
echo "================================================"

# Load environment
cd /opt/legal-doc-processor
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Check worker processes
echo -e "\n${BLUE}Worker Process Status:${NC}"
echo "---------------------"

WORKERS=(
    "worker.ocr:OCR Processing"
    "worker.text:Text Chunking"
    "worker.entity:Entity Extraction"
    "worker.graph:Graph Building"
    "worker.default:Orchestration"
    "worker.batch.high:Batch High Priority"
    "worker.batch.normal:Batch Normal Priority"
    "worker.batch.low:Batch Low Priority"
)

RUNNING_COUNT=0
for worker_info in "${WORKERS[@]}"; do
    IFS=':' read -r worker_name display_name <<< "$worker_info"
    
    if ps aux | grep -v grep | grep -q "celery.*$worker_name"; then
        PID=$(ps aux | grep -v grep | grep "celery.*$worker_name" | awk '{print $2}' | head -1)
        MEM=$(ps aux | grep -v grep | grep "celery.*$worker_name" | awk '{print $4}' | head -1)
        echo -e "  ${GREEN}✓${NC} $display_name (PID: $PID, MEM: ${MEM}%)"
        ((RUNNING_COUNT++))
    else
        echo -e "  ${RED}✗${NC} $display_name - NOT RUNNING"
    fi
done

echo -e "\nTotal: $RUNNING_COUNT/$EXPECTED_WORKERS workers running"

if [ $RUNNING_COUNT -lt $EXPECTED_WORKERS ]; then
    echo -e "${RED}WARNING: Missing workers detected!${NC}"
fi

# Check queue depths
echo -e "\n${BLUE}Queue Status:${NC}"
echo "-------------"

QUEUES=(
    "default:Orchestration"
    "ocr:OCR Processing"
    "text:Text Processing"
    "entity:Entity Extraction"
    "graph:Graph Building"
    "cleanup:Cleanup Tasks"
    "batch.high:High Priority Batch"
    "batch.normal:Normal Priority Batch"
    "batch.low:Low Priority Batch"
)

TOTAL_MESSAGES=0
HAS_WARNINGS=false

for queue_info in "${QUEUES[@]}"; do
    IFS=':' read -r queue_name display_name <<< "$queue_info"
    
    LENGTH=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD --no-auth-warning llen $queue_name 2>/dev/null || echo "0")
    
    # Color code based on queue depth
    if [ "$LENGTH" -gt "$CRITICAL_QUEUE_DEPTH" ]; then
        echo -e "  ${RED}● $display_name: $LENGTH messages (CRITICAL)${NC}"
        HAS_WARNINGS=true
    elif [ "$LENGTH" -gt "$WARNING_QUEUE_DEPTH" ]; then
        echo -e "  ${YELLOW}● $display_name: $LENGTH messages (WARNING)${NC}"
        HAS_WARNINGS=true
    else
        echo -e "  ${GREEN}● $display_name: $LENGTH messages${NC}"
    fi
    
    TOTAL_MESSAGES=$((TOTAL_MESSAGES + LENGTH))
done

echo -e "\nTotal messages in queues: $TOTAL_MESSAGES"

# Check memory usage
echo -e "\n${BLUE}System Resources:${NC}"
echo "-----------------"

# Memory
MEM_TOTAL=$(free -m | awk 'NR==2{print $2}')
MEM_USED=$(free -m | awk 'NR==2{print $3}')
MEM_PERCENT=$((MEM_USED * 100 / MEM_TOTAL))

if [ $MEM_PERCENT -gt 90 ]; then
    echo -e "  Memory: ${RED}${MEM_PERCENT}% used ($MEM_USED/$MEM_TOTAL MB) - CRITICAL${NC}"
elif [ $MEM_PERCENT -gt 80 ]; then
    echo -e "  Memory: ${YELLOW}${MEM_PERCENT}% used ($MEM_USED/$MEM_TOTAL MB) - WARNING${NC}"
else
    echo -e "  Memory: ${GREEN}${MEM_PERCENT}% used ($MEM_USED/$MEM_TOTAL MB)${NC}"
fi

# CPU
CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1}' | cut -d'.' -f1)
if [ -n "$CPU_USAGE" ]; then
    if [ $CPU_USAGE -gt 90 ]; then
        echo -e "  CPU: ${RED}${CPU_USAGE}% - CRITICAL${NC}"
    elif [ $CPU_USAGE -gt 70 ]; then
        echo -e "  CPU: ${YELLOW}${CPU_USAGE}% - WARNING${NC}"
    else
        echo -e "  CPU: ${GREEN}${CPU_USAGE}%${NC}"
    fi
fi

# Check recent errors
echo -e "\n${BLUE}Recent Errors (last 5 minutes):${NC}"
echo "-------------------------------"

ERROR_LOG="/opt/legal-doc-processor/monitoring/logs/errors_$(date +%Y%m%d).log"
if [ -f "$ERROR_LOG" ]; then
    RECENT_ERRORS=$(find "$ERROR_LOG" -mmin -5 -exec grep -c "ERROR" {} \; 2>/dev/null || echo "0")
    if [ "$RECENT_ERRORS" -gt "0" ]; then
        echo -e "  ${RED}Found $RECENT_ERRORS errors in last 5 minutes${NC}"
        echo "  Recent error messages:"
        tail -n 20 "$ERROR_LOG" | grep "ERROR" | tail -5 | while read line; do
            echo "    $line"
        done
    else
        echo -e "  ${GREEN}No recent errors${NC}"
    fi
else
    echo "  Error log not found"
fi

# Check Redis connection
echo -e "\n${BLUE}Redis Status:${NC}"
echo "-------------"
if redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD --no-auth-warning ping > /dev/null 2>&1; then
    REDIS_INFO=$(redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD --no-auth-warning info server | grep uptime_in_days | cut -d':' -f2 | tr -d '\r')
    echo -e "  ${GREEN}✓ Connected (uptime: ${REDIS_INFO} days)${NC}"
else
    echo -e "  ${RED}✗ Connection failed${NC}"
fi

# Summary and recommendations
echo -e "\n${BLUE}Summary:${NC}"
echo "--------"

if [ $RUNNING_COUNT -eq $EXPECTED_WORKERS ] && [ "$HAS_WARNINGS" = false ] && [ $MEM_PERCENT -lt 80 ]; then
    echo -e "${GREEN}✓ All systems operational${NC}"
else
    echo -e "${YELLOW}⚠ Issues detected:${NC}"
    
    if [ $RUNNING_COUNT -lt $EXPECTED_WORKERS ]; then
        echo -e "  - Missing workers: Run ${GREEN}./start_all_workers.sh${NC} to restart"
    fi
    
    if [ "$HAS_WARNINGS" = true ]; then
        echo -e "  - High queue depths detected: Check processing bottlenecks"
    fi
    
    if [ $MEM_PERCENT -gt 80 ]; then
        echo -e "  - High memory usage: Consider restarting workers or scaling up"
    fi
fi

# Optional: Send alerts if critical issues found
if [ $RUNNING_COUNT -lt $((EXPECTED_WORKERS / 2)) ] || [ $MEM_PERCENT -gt 95 ]; then
    echo -e "\n${RED}CRITICAL: System requires immediate attention!${NC}"
    # Add alerting logic here (email, Slack, etc.)
fi