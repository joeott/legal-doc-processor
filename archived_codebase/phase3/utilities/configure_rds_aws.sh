#!/bin/bash
# Configure RDS PostgreSQL instance for Legal Document Processing

set -e

# Configuration
RDS_ENDPOINT="database1.cuviucyodbeg.us-east-1.rds.amazonaws.com"
CURRENT_IP=$(curl -s https://api.ipify.org)
REGION="us-east-1"

echo "🔧 Configuring RDS instance at: $RDS_ENDPOINT"
echo "📍 Your current IP: $CURRENT_IP"

# Function to get RDS instance details from endpoint
get_instance_id() {
    # Extract instance identifier from endpoint
    echo "$RDS_ENDPOINT" | cut -d'.' -f1
}

INSTANCE_ID=$(get_instance_id)
echo "🔍 RDS Instance ID: $INSTANCE_ID"

# Try to get instance details
echo "📊 Getting RDS instance information..."
aws rds describe-db-instances --db-instance-identifier "$INSTANCE_ID" --region "$REGION" 2>/dev/null || {
    echo "⚠️  Could not find instance with ID: $INSTANCE_ID"
    echo "📋 Listing all RDS instances..."
    aws rds describe-db-instances --region "$REGION" --query 'DBInstances[*].[DBInstanceIdentifier,Endpoint.Address,DBInstanceStatus]' --output table
    exit 1
}

# Get security group
SECURITY_GROUP=$(aws rds describe-db-instances \
    --db-instance-identifier "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' \
    --output text)

echo "🔒 Security Group: $SECURITY_GROUP"

# Add current IP to security group
echo "🔓 Adding your IP ($CURRENT_IP) to security group..."
aws ec2 authorize-security-group-ingress \
    --group-id "$SECURITY_GROUP" \
    --protocol tcp \
    --port 5432 \
    --cidr "$CURRENT_IP/32" \
    --region "$REGION" 2>/dev/null || {
    echo "⚠️  Rule may already exist or failed to add"
}

# Get VPC ID for internal access
VPC_ID=$(aws rds describe-db-instances \
    --db-instance-identifier "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'DBInstances[0].DBSubnetGroup.VpcId' \
    --output text)

echo "🌐 VPC ID: $VPC_ID"

# Get VPC CIDR for internal access
VPC_CIDR=$(aws ec2 describe-vpcs \
    --vpc-ids "$VPC_ID" \
    --region "$REGION" \
    --query 'Vpcs[0].CidrBlock' \
    --output text)

echo "🔗 VPC CIDR: $VPC_CIDR"

# Add VPC CIDR to security group for internal access
echo "🔓 Adding VPC CIDR to security group for internal access..."
aws ec2 authorize-security-group-ingress \
    --group-id "$SECURITY_GROUP" \
    --protocol tcp \
    --port 5432 \
    --cidr "$VPC_CIDR" \
    --region "$REGION" 2>/dev/null || {
    echo "⚠️  VPC rule may already exist"
}

# Create custom parameter group
echo "⚙️  Creating custom parameter group..."
aws rds create-db-parameter-group \
    --db-parameter-group-name "legal-doc-processing-pg15" \
    --db-parameter-group-family "postgres15" \
    --description "Optimized settings for legal document processing" \
    --region "$REGION" 2>/dev/null || {
    echo "⚠️  Parameter group may already exist"
}

# Set parameter group values
echo "📝 Configuring parameter group..."
aws rds modify-db-parameter-group \
    --db-parameter-group-name "legal-doc-processing-pg15" \
    --region "$REGION" \
    --parameters \
        "ParameterName=shared_buffers,ParameterValue=256MB,ApplyMethod=pending-reboot" \
        "ParameterName=max_connections,ParameterValue=200,ApplyMethod=pending-reboot" \
        "ParameterName=work_mem,ParameterValue=4MB,ApplyMethod=immediate" \
        "ParameterName=maintenance_work_mem,ParameterValue=64MB,ApplyMethod=immediate" \
        "ParameterName=effective_cache_size,ParameterValue=1GB,ApplyMethod=immediate" \
        "ParameterName=checkpoint_completion_target,ParameterValue=0.9,ApplyMethod=immediate" \
        "ParameterName=wal_buffers,ParameterValue=16MB,ApplyMethod=pending-reboot" \
        "ParameterName=random_page_cost,ParameterValue=1.1,ApplyMethod=immediate" \
        "ParameterName=log_statement,ParameterValue=mod,ApplyMethod=immediate" \
        "ParameterName=log_min_duration_statement,ParameterValue=1000,ApplyMethod=immediate"

# Apply parameter group to instance
echo "🔄 Applying parameter group to instance..."
aws rds modify-db-instance \
    --db-instance-identifier "$INSTANCE_ID" \
    --db-parameter-group-name "legal-doc-processing-pg15" \
    --apply-immediately \
    --region "$REGION"

# Enable Performance Insights
echo "📊 Enabling Performance Insights..."
aws rds modify-db-instance \
    --db-instance-identifier "$INSTANCE_ID" \
    --enable-performance-insights \
    --performance-insights-retention-period 7 \
    --apply-immediately \
    --region "$REGION" 2>/dev/null || {
    echo "⚠️  Performance Insights may already be enabled"
}

# Create CloudWatch alarms
echo "🚨 Setting up CloudWatch alarms..."

# CPU Utilization alarm
aws cloudwatch put-metric-alarm \
    --alarm-name "RDS-$INSTANCE_ID-High-CPU" \
    --alarm-description "Alert when RDS CPU exceeds 80%" \
    --metric-name CPUUtilization \
    --namespace AWS/RDS \
    --statistic Average \
    --period 300 \
    --threshold 80 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --dimensions Name=DBInstanceIdentifier,Value="$INSTANCE_ID" \
    --region "$REGION" 2>/dev/null || echo "⚠️  CPU alarm may already exist"

# Database connections alarm
aws cloudwatch put-metric-alarm \
    --alarm-name "RDS-$INSTANCE_ID-High-Connections" \
    --alarm-description "Alert when connections exceed 150" \
    --metric-name DatabaseConnections \
    --namespace AWS/RDS \
    --statistic Average \
    --period 300 \
    --threshold 150 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --dimensions Name=DBInstanceIdentifier,Value="$INSTANCE_ID" \
    --region "$REGION" 2>/dev/null || echo "⚠️  Connections alarm may already exist"

# Free storage alarm
aws cloudwatch put-metric-alarm \
    --alarm-name "RDS-$INSTANCE_ID-Low-Storage" \
    --alarm-description "Alert when free storage below 10GB" \
    --metric-name FreeStorageSpace \
    --namespace AWS/RDS \
    --statistic Average \
    --period 300 \
    --threshold 10737418240 \
    --comparison-operator LessThanThreshold \
    --evaluation-periods 1 \
    --dimensions Name=DBInstanceIdentifier,Value="$INSTANCE_ID" \
    --region "$REGION" 2>/dev/null || echo "⚠️  Storage alarm may already exist"

echo "✅ AWS configuration complete!"
echo ""
echo "📋 Summary:"
echo "  - Instance: $INSTANCE_ID"
echo "  - Endpoint: $RDS_ENDPOINT"
echo "  - Security Group: $SECURITY_GROUP"
echo "  - Your IP ($CURRENT_IP) has been added for access"
echo "  - VPC CIDR ($VPC_CIDR) has been added for internal access"
echo "  - Custom parameter group applied"
echo "  - Performance Insights enabled"
echo "  - CloudWatch alarms configured"
echo ""
echo "🚀 Next steps:"
echo "  1. Wait 1-2 minutes for security group changes to propagate"
echo "  2. Get master password for RDS instance"
echo "  3. Run: export RDS_MASTER_PASSWORD='your-password'"
echo "  4. Run: python scripts/test_rds_connection.py"
echo "  5. Run: psql -h $RDS_ENDPOINT -U app_user -d legal_doc_processing -f scripts/create_schema.sql"