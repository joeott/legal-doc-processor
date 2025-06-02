#!/bin/bash
#
# Fix Celery worker environment variables
#

echo "Fixing Celery worker environment..."

# Create environment file for supervisor
cat > /opt/legal-doc-processor/scripts/celery_environment.conf << 'EOF'
# Environment variables for Celery workers
# Source this in supervisor config

# Load from .env file
set -a
source /opt/legal-doc-processor/.env
set +a

# Export critical AWS variables
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export S3_BUCKET_REGION="${S3_BUCKET_REGION:-us-east-2}"
export S3_PRIMARY_DOCUMENT_BUCKET="${S3_PRIMARY_DOCUMENT_BUCKET:-samu-docs-private-upload}"

# Other critical variables
export OPENAI_API_KEY="${OPENAI_API_KEY}"
export REDIS_HOST="${REDIS_HOST}"
export REDIS_PORT="${REDIS_PORT}"
export REDIS_PASSWORD="${REDIS_PASSWORD}"
export DATABASE_URL="${DATABASE_URL}"
export USE_MINIMAL_MODELS="${USE_MINIMAL_MODELS:-true}"
export SKIP_CONFORMANCE_CHECK="${SKIP_CONFORMANCE_CHECK:-true}"
export DEPLOYMENT_STAGE="${DEPLOYMENT_STAGE:-1}"
export PYTHONPATH="/opt/legal-doc-processor:${PYTHONPATH}"

# Debug
echo "AWS_ACCESS_KEY_ID is set: $([ ! -z "$AWS_ACCESS_KEY_ID" ] && echo "YES" || echo "NO")"
echo "S3_BUCKET_REGION: ${S3_BUCKET_REGION}"
EOF

# Update supervisor config to include environment
echo "Updating supervisor configuration..."

# Check current supervisor config
if [ -f /etc/supervisor/conf.d/celery.conf ]; then
    echo "Found existing celery.conf, creating backup..."
    sudo cp /etc/supervisor/conf.d/celery.conf /etc/supervisor/conf.d/celery.conf.bak
fi

# Create new supervisor config with environment
sudo tee /etc/supervisor/conf.d/celery_with_env.conf > /dev/null << 'EOF'
[group:celery]
programs=celery-default,celery-ocr,celery-text,celery-entity,celery-graph

[program:celery-default]
command=bash -c 'source /opt/legal-doc-processor/.env && export S3_BUCKET_REGION=us-east-2 && celery -A scripts.celery_app worker -Q default -n default@%%h --loglevel=info'
directory=/opt/legal-doc-processor
user=ubuntu
numprocs=1
stdout_logfile=/var/log/celery/default.log
stderr_logfile=/var/log/celery/default.err
autostart=true
autorestart=true
startsecs=10

[program:celery-ocr]
command=bash -c 'source /opt/legal-doc-processor/.env && export S3_BUCKET_REGION=us-east-2 && celery -A scripts.celery_app worker -Q ocr -n ocr@%%h --loglevel=info'
directory=/opt/legal-doc-processor
user=ubuntu
numprocs=1
stdout_logfile=/var/log/celery/ocr.log
stderr_logfile=/var/log/celery/ocr.err
autostart=true
autorestart=true
startsecs=10

[program:celery-text]
command=bash -c 'source /opt/legal-doc-processor/.env && export S3_BUCKET_REGION=us-east-2 && celery -A scripts.celery_app worker -Q text -n text@%%h --loglevel=info'
directory=/opt/legal-doc-processor
user=ubuntu
numprocs=1
stdout_logfile=/var/log/celery/text.log
stderr_logfile=/var/log/celery/text.err
autostart=true
autorestart=true
startsecs=10

[program:celery-entity]
command=bash -c 'source /opt/legal-doc-processor/.env && export S3_BUCKET_REGION=us-east-2 && celery -A scripts.celery_app worker -Q entity -n entity@%%h --loglevel=info'
directory=/opt/legal-doc-processor
user=ubuntu
numprocs=1
stdout_logfile=/var/log/celery/entity.log
stderr_logfile=/var/log/celery/entity.err
autostart=true
autorestart=true
startsecs=10

[program:celery-graph]
command=bash -c 'source /opt/legal-doc-processor/.env && export S3_BUCKET_REGION=us-east-2 && celery -A scripts.celery_app worker -Q graph -n graph@%%h --loglevel=info'
directory=/opt/legal-doc-processor
user=ubuntu
numprocs=1
stdout_logfile=/var/log/celery/graph.log
stderr_logfile=/var/log/celery/graph.err
autostart=true
autorestart=true
startsecs=10
EOF

echo "Reloading supervisor configuration..."
sudo supervisorctl reread
sudo supervisorctl update

echo "Restarting Celery workers..."
sudo supervisorctl restart celery:*

echo "Waiting for workers to start..."
sleep 10

echo "Checking worker status..."
sudo supervisorctl status celery:*

echo "Done! Celery workers should now have AWS environment variables."