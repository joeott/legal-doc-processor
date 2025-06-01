#!/bin/bash
# Real-time monitoring dashboard for document processing tests

while true; do
    clear
    echo "=== DOCUMENT PROCESSING TEST MONITOR ==="
    echo "Time: $(date)"
    echo ""
    
    echo "=== Worker Status ==="
    sudo supervisorctl status | grep celery || echo "Workers not managed by Supervisor"
    
    echo -e "\n=== Queue Depths ==="
    cd /opt/legal-doc-processor
    source venv/bin/activate
    
    python -c "
import redis
from scripts.config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_USERNAME, REDIS_SSL

try:
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        username=REDIS_USERNAME,
        ssl=REDIS_SSL,
        decode_responses=True
    )
    
    queues = ['ocr', 'text', 'entity', 'graph', 'default', 'cleanup']
    for queue in queues:
        try:
            length = client.llen(f'celery:queue:{queue}')
            print(f'{queue:10} queue: {length} tasks')
        except:
            print(f'{queue:10} queue: Error')
except Exception as e:
    print(f'Redis connection error: {e}')
"
    
    echo -e "\n=== Recent Errors ==="
    if [ -f "/opt/legal-doc-processor/monitoring/logs/all_logs_20250531.log" ]; then
        grep ERROR /opt/legal-doc-processor/monitoring/logs/all_logs_*.log 2>/dev/null | tail -3 || echo "No errors found"
    else
        echo "Log file not found"
    fi
    
    echo -e "\n=== Active Tasks ==="
    if [ -f "/opt/legal-doc-processor/monitoring/logs/all_logs_20250531.log" ]; then
        grep "TASK START" /opt/legal-doc-processor/monitoring/logs/all_logs_*.log 2>/dev/null | tail -3 || echo "No active tasks"
    fi
    
    echo -e "\n=== Database Activity ==="
    cd /opt/legal-doc-processor
    source venv/bin/activate
    python -c "
from scripts.rds_utils import execute_query
try:
    result = execute_query(
        '''SELECT 
            (SELECT COUNT(*) FROM documents) as docs,
            (SELECT COUNT(*) FROM chunks) as chunks,
            (SELECT COUNT(*) FROM entities) as entities,
            (SELECT COUNT(*) FROM relationships) as rels
        '''
    )
    if result:
        r = result[0]
        print(f'Documents: {r[\"docs\"]}, Chunks: {r[\"chunks\"]}, Entities: {r[\"entities\"]}, Relationships: {r[\"rels\"]}')
except Exception as e:
    print(f'Database query error: {e}')
" 2>/dev/null || echo "Database connection error"
    
    sleep 5
done