# Context 238: AWS CLI Database Operations Guide for AI Assistants

**Date**: 2025-05-30
**Type**: AI Assistant Operations Guide
**Status**: ACTIVE
**Component**: AWS CLI Controls for RDS, EC2, and SSH Tunnel Management

## Overview for AI Assistants

This guide provides comprehensive AWS CLI commands and operations required to manage the RDS PostgreSQL database infrastructure. As an AI assistant, you should use these commands to diagnose issues, manage resources, and maintain database connectivity.

## Prerequisites Check

Before executing any commands, verify these prerequisites:

```bash
# Check AWS CLI is installed
aws --version

# Check if credentials are configured
aws sts get-caller-identity

# Verify PEM file exists and has correct permissions
ls -la resources/aws/legal-doc-processor-bastion.pem
# Should show: -r-------- (400 permissions)
```

## EC2 Bastion Host Management

### 1. Check Bastion Instance Status

```bash
# Get current status and IP
aws ec2 describe-instances \
    --instance-ids i-0e431c454a7c3c6a1 \
    --query 'Reservations[0].Instances[0].{State:State.Name,PublicIP:PublicIpAddress,PrivateIP:PrivateIpAddress}' \
    --output json
```

### 2. Start Stopped Bastion

```bash
# Start the instance if stopped
aws ec2 start-instances --instance-ids i-0e431c454a7c3c6a1

# Wait for instance to be running
aws ec2 wait instance-running --instance-ids i-0e431c454a7c3c6a1

# Get new public IP after start
aws ec2 describe-instances \
    --instance-ids i-0e431c454a7c3c6a1 \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text
```

### 3. Stop Bastion (Cost Savings)

```bash
# Stop instance when not in use
aws ec2 stop-instances --instance-ids i-0e431c454a7c3c6a1

# Verify stopped
aws ec2 wait instance-stopped --instance-ids i-0e431c454a7c3c6a1
```

### 4. Update Security Group for New IP

```bash
# Get current security group
SECURITY_GROUP_ID=$(aws ec2 describe-instances \
    --instance-ids i-0e431c454a7c3c6a1 \
    --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' \
    --output text)

# Get your current public IP
MY_IP=$(curl -s ifconfig.me)

# Update security group to allow your IP
aws ec2 authorize-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol tcp \
    --port 22 \
    --cidr ${MY_IP}/32 \
    --group-rule-description "SSH access for $(whoami)"

# Remove old IP rule (if needed)
aws ec2 revoke-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol tcp \
    --port 22 \
    --cidr 108.210.14.204/32
```

## RDS Database Management

### 1. Check RDS Instance Status

```bash
# Get RDS instance details
aws rds describe-db-instances \
    --db-instance-identifier database1 \
    --query 'DBInstances[0].{Status:DBInstanceStatus,Endpoint:Endpoint.Address,Port:Endpoint.Port,Engine:Engine,EngineVersion:EngineVersion}' \
    --output json
```

### 2. Start/Stop RDS Instance

```bash
# Stop RDS instance (cost savings)
aws rds stop-db-instance \
    --db-instance-identifier database1

# Start RDS instance
aws rds start-db-instance \
    --db-instance-identifier database1

# Wait for available state
aws rds wait db-instance-available \
    --db-instance-identifier database1
```

### 3. Modify RDS Instance

```bash
# Enable automated backups
aws rds modify-db-instance \
    --db-instance-identifier database1 \
    --backup-retention-period 7 \
    --preferred-backup-window "03:00-04:00" \
    --apply-immediately

# Modify instance size (if needed)
aws rds modify-db-instance \
    --db-instance-identifier database1 \
    --db-instance-class db.t3.medium \
    --apply-immediately
```

### 4. Create Database Snapshot

```bash
# Create manual snapshot
aws rds create-db-snapshot \
    --db-instance-identifier database1 \
    --db-snapshot-identifier legal-docs-snapshot-$(date +%Y%m%d-%H%M%S)

# List snapshots
aws rds describe-db-snapshots \
    --db-instance-identifier database1 \
    --query 'DBSnapshots[*].{SnapshotId:DBSnapshotIdentifier,Status:Status,Created:SnapshotCreateTime}' \
    --output table
```

## SSH Tunnel Management

### 1. Automated Tunnel Creation Function

```bash
# Function to create SSH tunnel with error handling
create_rds_tunnel() {
    # Get bastion public IP
    BASTION_IP=$(aws ec2 describe-instances \
        --instance-ids i-0e431c454a7c3c6a1 \
        --query 'Reservations[0].Instances[0].PublicIpAddress' \
        --output text)
    
    if [ "$BASTION_IP" = "None" ] || [ -z "$BASTION_IP" ]; then
        echo "Error: Bastion host not running or no public IP"
        return 1
    fi
    
    # Kill existing tunnel
    lsof -ti:5433 | xargs kill -9 2>/dev/null
    
    # Create new tunnel
    ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 \
        -i resources/aws/legal-doc-processor-bastion.pem \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        ubuntu@$BASTION_IP
    
    echo "Tunnel created via bastion at $BASTION_IP"
}
```

### 2. Test Database Connection

```bash
# Test connection through tunnel
test_rds_connection() {
    PGPASSWORD='LegalDoc2025!Secure' psql \
        -h localhost \
        -p 5433 \
        -U app_user \
        -d legal_doc_processing \
        -c "SELECT version();" \
        2>&1
}
```

## Complete Workflow Scripts

### 1. Start Everything Script

```bash
#!/bin/bash
# start_database_environment.sh

echo "Starting database environment..."

# 1. Start EC2 bastion if needed
STATE=$(aws ec2 describe-instances \
    --instance-ids i-0e431c454a7c3c6a1 \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text)

if [ "$STATE" != "running" ]; then
    echo "Starting bastion host..."
    aws ec2 start-instances --instance-ids i-0e431c454a7c3c6a1
    aws ec2 wait instance-running --instance-ids i-0e431c454a7c3c6a1
fi

# 2. Get bastion IP
BASTION_IP=$(aws ec2 describe-instances \
    --instance-ids i-0e431c454a7c3c6a1 \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo "Bastion IP: $BASTION_IP"

# 3. Check RDS status
RDS_STATUS=$(aws rds describe-db-instances \
    --db-instance-identifier database1 \
    --query 'DBInstances[0].DBInstanceStatus' \
    --output text)

if [ "$RDS_STATUS" = "stopped" ]; then
    echo "Starting RDS instance..."
    aws rds start-db-instance --db-instance-identifier database1
    aws rds wait db-instance-available --db-instance-identifier database1
fi

# 4. Create SSH tunnel
echo "Creating SSH tunnel..."
lsof -ti:5433 | xargs kill -9 2>/dev/null
ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 \
    -i resources/aws/legal-doc-processor-bastion.pem \
    ubuntu@$BASTION_IP

echo "Database environment ready!"
```

### 2. Stop Everything Script

```bash
#!/bin/bash
# stop_database_environment.sh

echo "Stopping database environment..."

# 1. Kill SSH tunnel
lsof -ti:5433 | xargs kill -9 2>/dev/null
echo "SSH tunnel stopped"

# 2. Stop bastion (optional - uncomment to save costs)
# aws ec2 stop-instances --instance-ids i-0e431c454a7c3c6a1
# echo "Bastion host stopped"

# 3. Stop RDS (optional - uncomment to save costs)
# aws rds stop-db-instance --db-instance-identifier database1
# echo "RDS instance stopped"

echo "Database environment stopped"
```

## Monitoring and Diagnostics

### 1. Check All Resources Status

```bash
# Function to check all resources
check_database_infrastructure() {
    echo "=== EC2 Bastion Status ==="
    aws ec2 describe-instances \
        --instance-ids i-0e431c454a7c3c6a1 \
        --query 'Reservations[0].Instances[0].{State:State.Name,PublicIP:PublicIpAddress}' \
        --output json
    
    echo -e "\n=== RDS Instance Status ==="
    aws rds describe-db-instances \
        --db-instance-identifier database1 \
        --query 'DBInstances[0].{Status:DBInstanceStatus,Endpoint:Endpoint.Address}' \
        --output json
    
    echo -e "\n=== SSH Tunnel Status ==="
    if lsof -ti:5433 > /dev/null 2>&1; then
        echo "SSH tunnel is ACTIVE on port 5433"
    else
        echo "SSH tunnel is NOT ACTIVE"
    fi
}
```

### 2. CloudWatch Metrics

```bash
# Get RDS CPU utilization
aws cloudwatch get-metric-statistics \
    --namespace AWS/RDS \
    --metric-name CPUUtilization \
    --dimensions Name=DBInstanceIdentifier,Value=database1 \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Average \
    --output table

# Get RDS connection count
aws cloudwatch get-metric-statistics \
    --namespace AWS/RDS \
    --metric-name DatabaseConnections \
    --dimensions Name=DBInstanceIdentifier,Value=database1 \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Average \
    --output table
```

## Cost Optimization Commands

### 1. Check Running Resources

```bash
# Function to estimate daily costs
check_running_costs() {
    echo "=== Running Resources ==="
    
    # Check EC2
    EC2_STATE=$(aws ec2 describe-instances \
        --instance-ids i-0e431c454a7c3c6a1 \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text)
    
    if [ "$EC2_STATE" = "running" ]; then
        echo "EC2 Bastion (t3.medium): ~$1.00/day"
    fi
    
    # Check RDS
    RDS_STATUS=$(aws rds describe-db-instances \
        --db-instance-identifier database1 \
        --query 'DBInstances[0].DBInstanceStatus' \
        --output text)
    
    if [ "$RDS_STATUS" = "available" ]; then
        echo "RDS PostgreSQL (db.t3.medium): ~$1.44/day"
    fi
    
    echo -e "\nTo reduce costs, stop resources when not in use"
}
```

### 2. Schedule Start/Stop

```bash
# Create tags for automated scheduling (using AWS Instance Scheduler)
aws ec2 create-tags \
    --resources i-0e431c454a7c3c6a1 \
    --tags Key=Schedule,Value=business-hours

aws rds add-tags-to-resource \
    --resource-name arn:aws:rds:us-east-1:$(aws sts get-caller-identity --query Account --output text):db:database1 \
    --tags Key=Schedule,Value=business-hours
```

## Troubleshooting Commands

### 1. Debug Connection Issues

```bash
# Check security groups
aws ec2 describe-security-groups \
    --group-ids $(aws ec2 describe-instances --instance-ids i-0e431c454a7c3c6a1 --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text) \
    --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`]'

# Check RDS security
aws rds describe-db-instances \
    --db-instance-identifier database1 \
    --query 'DBInstances[0].VpcSecurityGroups'
```

### 2. View Recent Errors

```bash
# RDS error logs
aws rds describe-events \
    --source-identifier database1 \
    --source-type db-instance \
    --duration 1440 \
    --query 'Events[?EventCategories[0]==`failure`]' \
    --output table
```

## Environment Variables for Scripts

```bash
# Export commonly used values
export RDS_INSTANCE_ID="database1"
export BASTION_INSTANCE_ID="i-0e431c454a7c3c6a1"
export RDS_ENDPOINT="database1.cuviucyodbeg.us-east-1.rds.amazonaws.com"
export RDS_PORT="5432"
export TUNNEL_PORT="5433"
export PEM_KEY="resources/aws/legal-doc-processor-bastion.pem"
```

## Important Notes for AI Assistants

1. **Always check instance states** before attempting connections
2. **Update security groups** when IP addresses change
3. **Use cost optimization** by stopping resources when not in use
4. **Monitor CloudWatch** for performance issues
5. **Create snapshots** before major changes
6. **Test connections** after any infrastructure changes
7. **Document IP changes** in environment configuration

This guide should enable any AI assistant to effectively manage the database infrastructure using AWS CLI commands.