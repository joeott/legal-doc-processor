#!/bin/bash
# Enable public access for RDS instance (for development/setup only)

set -e

INSTANCE_ID="database1"
REGION="us-east-1"

echo "⚠️  WARNING: This will make your RDS instance publicly accessible!"
echo "This should only be used for initial setup and development."
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo "🔄 Enabling public accessibility for RDS instance: $INSTANCE_ID"

# Enable public access
aws rds modify-db-instance \
    --db-instance-identifier "$INSTANCE_ID" \
    --publicly-accessible \
    --apply-immediately \
    --region "$REGION"

echo "✅ Public access enabled. Changes may take a few minutes to apply."
echo ""
echo "⏳ Current status:"
aws rds describe-db-instances \
    --db-instance-identifier "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'DBInstances[0].[DBInstanceStatus,PubliclyAccessible]' \
    --output table

echo ""
echo "📋 Next steps:"
echo "1. Wait for instance status to become 'available'"
echo "2. Check status: aws rds describe-db-instances --db-instance-identifier $INSTANCE_ID --query 'DBInstances[0].DBInstanceStatus'"
echo "3. Once available, run: python scripts/test_rds_connection.py"
echo ""
echo "🔒 Security reminder: Disable public access after setup is complete:"
echo "aws rds modify-db-instance --db-instance-identifier $INSTANCE_ID --no-publicly-accessible --apply-immediately"