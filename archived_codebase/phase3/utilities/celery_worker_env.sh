#!/bin/bash
#
# Environment wrapper for Celery workers
# Ensures all required environment variables are available
#

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load environment variables from .env file
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Loading environment from $PROJECT_ROOT/.env" >&2
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
else
    echo "ERROR: .env file not found at $PROJECT_ROOT/.env" >&2
    exit 1
fi

# Force critical environment variables
export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH}"
export S3_BUCKET_REGION="us-east-2"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

# Log environment status for debugging
echo "Environment loaded at $(date)" >&2
echo "  AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:0:10}..." >&2
echo "  S3_BUCKET_REGION: $S3_BUCKET_REGION" >&2
echo "  AWS_DEFAULT_REGION: $AWS_DEFAULT_REGION" >&2
echo "  PYTHONPATH: $PYTHONPATH" >&2

# Verify critical variables
if [ -z "$AWS_ACCESS_KEY_ID" ]; then
    echo "ERROR: AWS_ACCESS_KEY_ID not set" >&2
    exit 1
fi

if [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "ERROR: AWS_SECRET_ACCESS_KEY not set" >&2
    exit 1
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY not set" >&2
    exit 1
fi

# Execute the command passed as arguments
exec "$@"