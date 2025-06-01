#!/bin/bash
# Configure PostgreSQL 17 parameter group with proper units

set -e

REGION="us-east-1"
PARAM_GROUP="legal-doc-processing-pg17"
INSTANCE_ID="database1"

# Create parameter group for PostgreSQL 17
echo "⚙️  Creating parameter group for PostgreSQL 17..."
aws rds create-db-parameter-group \
    --db-parameter-group-name "$PARAM_GROUP" \
    --db-parameter-group-family "postgres17" \
    --description "Optimized settings for legal document processing (PG17)" \
    --region "$REGION" 2>/dev/null || {
    echo "⚠️  Parameter group may already exist"
}

# Configure parameters with proper units
echo "📝 Configuring parameters..."

# Note: shared_buffers uses 8kB units, so 256MB = 32768 * 8kB
# wal_buffers uses 8kB units, so 16MB = 2048 * 8kB
aws rds modify-db-parameter-group \
    --db-parameter-group-name "$PARAM_GROUP" \
    --region "$REGION" \
    --parameters \
        "ParameterName=shared_buffers,ParameterValue=32768,ApplyMethod=pending-reboot" \
        "ParameterName=max_connections,ParameterValue=200,ApplyMethod=pending-reboot" \
        "ParameterName=work_mem,ParameterValue=4096,ApplyMethod=immediate" \
        "ParameterName=maintenance_work_mem,ParameterValue=65536,ApplyMethod=immediate" \
        "ParameterName=effective_cache_size,ParameterValue=131072,ApplyMethod=immediate" \
        "ParameterName=checkpoint_completion_target,ParameterValue=0.9,ApplyMethod=immediate" \
        "ParameterName=wal_buffers,ParameterValue=2048,ApplyMethod=pending-reboot" \
        "ParameterName=random_page_cost,ParameterValue=1.1,ApplyMethod=immediate" \
        "ParameterName=log_statement,ParameterValue=mod,ApplyMethod=immediate" \
        "ParameterName=log_min_duration_statement,ParameterValue=1000,ApplyMethod=immediate"

echo "✅ Parameter group configured"

# Apply to instance
echo "🔄 Applying parameter group to instance..."
aws rds modify-db-instance \
    --db-instance-identifier "$INSTANCE_ID" \
    --db-parameter-group-name "$PARAM_GROUP" \
    --apply-immediately \
    --region "$REGION"

echo "✅ Parameter group applied. A reboot may be required for some parameters."
echo ""
echo "To reboot the instance (after backup completes):"
echo "aws rds reboot-db-instance --db-instance-identifier $INSTANCE_ID"