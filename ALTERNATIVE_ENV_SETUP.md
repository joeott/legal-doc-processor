# Alternative Ways to Load Environment Variables

## Method 1: Direct Source Command
```bash
cd /opt/legal-doc-processor
source load_env.sh
```

If that doesn't work, try:

## Method 2: Using bash explicitly
```bash
cd /opt/legal-doc-processor
bash -c 'source load_env.sh && echo "Environment loaded"'
```

## Method 3: Manual environment loading
```bash
cd /opt/legal-doc-processor
set -a
source <(grep -v '^#' .env | grep '=')
set +a
```

## Method 4: Export key variables manually
```bash
cd /opt/legal-doc-processor

# Export the most critical variables manually
export DATABASE_URL="postgresql://app_user:LegalDoc2025%5C%21Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require"
export OPENAI_API_KEY="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"
export S3_PRIMARY_DOCUMENT_BUCKET="samu-docs-private-upload"
export S3_BUCKET_REGION="us-east-2"
export AWS_DEFAULT_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="AKIAVM4WAPVISLMXC24R"
export AWS_SECRET_ACCESS_KEY="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"
export REDIS_HOST="redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com"
export REDIS_PORT="12696"
export REDIS_PASSWORD="BHMbnJHyf&9!4TT"
export USE_MINIMAL_MODELS="true"
export SKIP_CONFORMANCE_CHECK="true"
export DEPLOYMENT_STAGE="1"
export PYTHONPATH="/opt/legal-doc-processor:$PYTHONPATH"
```

## Method 5: Python-based environment loading
Create a temporary Python script to load and verify environment:

```python
# save as test_env.py
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv('/opt/legal-doc-processor/.env')

# Verify key variables
print(f"DATABASE_URL set: {bool(os.getenv('DATABASE_URL'))}")
print(f"OPENAI_API_KEY set: {bool(os.getenv('OPENAI_API_KEY'))}")
print(f"S3_BUCKET_REGION: {os.getenv('S3_BUCKET_REGION', 'NOT SET')}")

# Now run your test
os.system('python3 /opt/legal-doc-processor/scripts/test_region_fix_complete.py')
```

## Checking Current Environment
To verify if environment variables are loaded:
```bash
# Check if critical variables are set
echo "DATABASE_URL is set: $([ ! -z "$DATABASE_URL" ] && echo "YES" || echo "NO")"
echo "OPENAI_API_KEY is set: $([ ! -z "$OPENAI_API_KEY" ] && echo "YES" || echo "NO")"
echo "S3_BUCKET_REGION: $S3_BUCKET_REGION"
```

## If load_env.sh has permission issues:
```bash
# Make it executable
chmod +x /opt/legal-doc-processor/load_env.sh

# Then try again
source /opt/legal-doc-processor/load_env.sh
```