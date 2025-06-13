#!/bin/bash
# Celery Worker Status Check Script

echo "=== Celery Worker Status ==="
sudo supervisorctl status | grep celery

echo -e "\n=== Redis Queue Depths ==="
cd /opt/legal-doc-processor
source venv/bin/activate

python -c "
import redis
from scripts.config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_USERNAME, REDIS_SSL

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
    except Exception as e:
        print(f'{queue:10} queue: Error - {e}')
"

echo -e "\n=== Recent Errors ==="
if [ -d "/opt/legal-doc-processor/monitoring/logs/celery" ]; then
    grep -h ERROR /opt/legal-doc-processor/monitoring/logs/celery/*.log 2>/dev/null | tail -5 || echo "No errors found"
else
    echo "Log directory not found"
fi

echo -e "\n=== Worker Memory Usage ==="
ps aux | grep celery | grep -v grep | awk '{sum+=$6} END {if(sum>0) print "Total RSS: " sum/1024 " MB"; else print "No workers running"}'