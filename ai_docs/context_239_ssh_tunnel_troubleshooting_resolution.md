# Context 239: SSH Tunnel Troubleshooting and Resolution

**Date**: 2025-05-30
**Type**: Infrastructure Resolution
**Status**: RESOLVED
**Component**: EC2 Bastion and RDS Database Access

## Issue Summary

The SSH tunnel for RDS database access was failing due to:
1. Region mismatch between .env configuration (us-east-2) and actual infrastructure (us-east-1)
2. Security group IP restriction outdated (108.210.14.204 vs current IP 35.129.252.203)
3. Scripts attempting direct connection instead of tunnel connection

## Infrastructure Verification

### EC2 Bastion Host (Confirmed Active)
- **Instance ID**: `i-0e431c454a7c3c6a1`
- **Instance Type**: `t3.medium`
- **Public IP**: `54.162.223.205`
- **Region**: `us-east-1`
- **State**: Running (as of 2025-05-30)
- **Launch Time**: 2025-05-30T03:45:16+00:00
- **Instance Name**: `legal-doc-bastion`

### RDS PostgreSQL Instance (Confirmed Active)
- **Instance ID**: `database1`
- **Endpoint**: `database1.cuviucyodbeg.us-east-1.rds.amazonaws.com`
- **Port**: `5432`
- **Engine**: PostgreSQL 17.2
- **Region**: `us-east-1`
- **Status**: Available

## Resolution Steps Taken

### 1. Region Correction
```bash
# Updated .env file
AWS_REGION=us-east-1        # Was: us-east-2
AWS_DEFAULT_REGION=us-east-1 # Was: us-east-2
```

### 2. Security Group Update
```bash
# Added current IP to security group
aws ec2 authorize-security-group-ingress \
    --region us-east-1 \
    --group-id sg-03ba8403ff7b45bf7 \
    --protocol tcp \
    --port 22 \
    --cidr 35.129.252.203/32
```

### 3. SSH Tunnel Establishment
```bash
# Successfully created tunnel
ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 \
    -i resources/aws/legal-doc-processor-bastion.pem \
    ubuntu@54.162.223.205
```

### 4. Connection Verification
```bash
# Direct psql test - SUCCESS
PGPASSWORD='LegalDoc2025!Secure' psql \
    -h localhost -p 5433 -U app_user \
    -d legal_doc_processing -c "SELECT version();"

# Python test - SUCCESS
DATABASE_URL='postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing' \
    python -c "from scripts.rds_utils import test_connection; print(test_connection())"
```

## Current Connection Status

### Database Health Check Results
```json
{
  "status": "healthy",
  "version": "PostgreSQL 17.2 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 12.4.0, 64-bit",
  "tables": {
    "projects": 0,
    "documents": 0,
    "chunks": 0,
    "entities": 0,
    "relationships": 0
  }
}
```

## Updated Connection Strings

### Local Development (via SSH Tunnel)
```
DATABASE_URL=postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing
```

### Production/EC2 (Direct Connection)
```
DATABASE_URL_DIRECT=postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require
```

## Lessons Learned

1. **Always verify AWS region** - Infrastructure may be in different regions than expected
2. **Check security group IPs** - Dynamic IPs require regular updates
3. **Test with AWS CLI first** - Helps identify infrastructure issues before application testing
4. **Document infrastructure details** - Instance IDs and endpoints should be readily available

## Monitoring Recommendations

1. Set up CloudWatch alarms for EC2/RDS availability
2. Implement IP change detection for security group updates
3. Add tunnel health checks to monitoring scripts
4. Consider using AWS Systems Manager Session Manager as backup access method

## Cost Optimization Notes

- EC2 t3.medium bastion: ~$30/month if running 24/7
- Consider stopping bastion when not in use
- RDS db.t3.medium: ~$43/month plus storage
- Enable RDS stop/start scheduling for development