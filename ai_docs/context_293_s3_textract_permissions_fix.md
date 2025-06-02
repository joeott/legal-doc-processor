# S3-Textract Permissions Fix: Detailed Recommendations

## Date: 2025-06-02
## Purpose: Provide specific AWS CLI commands to fix S3-Textract access issue
## Status: CRITICAL BLOCKER - REQUIRES IMMEDIATE ACTION

## Problem Summary

AWS Textract cannot access documents in the S3 bucket `samu-docs-private-upload`, resulting in the error:
```
InvalidS3ObjectException: Unable to get object metadata from S3. 
Check object key, region and/or access permissions.
```

This blocks the entire document processing pipeline as no OCR can be performed.

## Root Cause Analysis

1. **Service Access**: Textract service doesn't have permission to read objects from the private S3 bucket
2. **IAM Role**: The execution role may lack the necessary S3 permissions
3. **Bucket Policy**: No bucket policy exists to allow Textract service access
4. **Region Mismatch**: Potential region inconsistency between S3 bucket and Textract service

## Solution Options

### Option 1: Add S3 Bucket Policy (RECOMMENDED)

This is the simplest and most direct solution. Add a bucket policy that allows Textract to read objects.

#### Step 1: Create the bucket policy file
```bash
cat > textract-bucket-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowTextractAccess",
            "Effect": "Allow",
            "Principal": {
                "Service": "textract.amazonaws.com"
            },
            "Action": [
                "s3:GetObject",
                "s3:GetObjectVersion"
            ],
            "Resource": "arn:aws:s3:::samu-docs-private-upload/*"
        }
    ]
}
EOF
```

#### Step 2: Apply the bucket policy
```bash
aws s3api put-bucket-policy \
    --bucket samu-docs-private-upload \
    --policy file://textract-bucket-policy.json
```

#### Step 3: Verify the policy was applied
```bash
aws s3api get-bucket-policy \
    --bucket samu-docs-private-upload \
    --query Policy \
    --output text | python -m json.tool
```

### Option 2: Update IAM Role Permissions

If using an IAM role for Textract execution, ensure it has S3 access permissions.

#### Step 1: Identify the Textract execution role
```bash
# List roles that might be used by Textract
aws iam list-roles --query "Roles[?contains(RoleName, 'textract') || contains(RoleName, 'Textract')].RoleName"
```

#### Step 2: Create S3 access policy
```bash
cat > textract-s3-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:GetObjectVersion",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::samu-docs-private-upload",
                "arn:aws:s3:::samu-docs-private-upload/*"
            ]
        }
    ]
}
EOF
```

#### Step 3: Attach policy to the role
```bash
# Replace YOUR-TEXTRACT-ROLE-NAME with actual role name
aws iam put-role-policy \
    --role-name YOUR-TEXTRACT-ROLE-NAME \
    --policy-name TextractS3Access \
    --policy-document file://textract-s3-policy.json
```

### Option 3: Cross-Service Bucket Policy with Conditions

For enhanced security, add conditions to restrict access to specific AWS accounts or roles.

```bash
cat > secure-textract-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowTextractWithConditions",
            "Effect": "Allow",
            "Principal": {
                "Service": "textract.amazonaws.com"
            },
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::samu-docs-private-upload/*",
            "Condition": {
                "StringEquals": {
                    "aws:SourceAccount": "YOUR-AWS-ACCOUNT-ID"
                },
                "StringLike": {
                    "aws:SourceArn": "arn:aws:textract:*:YOUR-AWS-ACCOUNT-ID:*"
                }
            }
        }
    ]
}
EOF
```

Replace `YOUR-AWS-ACCOUNT-ID` with your actual AWS account ID, then apply:
```bash
aws s3api put-bucket-policy \
    --bucket samu-docs-private-upload \
    --policy file://secure-textract-policy.json
```

## Verification Steps

### 1. Check Current Bucket Configuration
```bash
# Get bucket location
aws s3api get-bucket-location --bucket samu-docs-private-upload

# Check current bucket policy (if any)
aws s3api get-bucket-policy --bucket samu-docs-private-upload

# Check bucket ACL
aws s3api get-bucket-acl --bucket samu-docs-private-upload

# List bucket CORS configuration
aws s3api get-bucket-cors --bucket samu-docs-private-upload
```

### 2. Test Object Access
```bash
# Test if objects are accessible
aws s3 ls s3://samu-docs-private-upload/documents/ --recursive | head -5

# Check specific object permissions
aws s3api get-object-acl \
    --bucket samu-docs-private-upload \
    --key documents/SAMPLE-DOCUMENT-UUID.pdf
```

### 3. Verify Textract Can Access Objects
After applying the fix, test with a sample document:

```bash
# Start a test Textract job
aws textract start-document-text-detection \
    --document-location '{
        "S3Object": {
            "Bucket": "samu-docs-private-upload",
            "Name": "documents/TEST-DOCUMENT.pdf"
        }
    }' \
    --region us-east-1
```

## Region Considerations

Ensure S3 bucket and Textract are in the same region:

```bash
# Check bucket region
aws s3api get-bucket-location --bucket samu-docs-private-upload

# Ensure Textract calls use the same region
export AWS_DEFAULT_REGION=us-east-1  # or your bucket's region
```

## Additional Troubleshooting

### 1. Enable S3 Access Logging
```bash
# Create logging bucket if needed
aws s3 mb s3://samu-docs-private-upload-logs

# Enable access logging
aws s3api put-bucket-logging \
    --bucket samu-docs-private-upload \
    --bucket-logging-status '{
        "LoggingEnabled": {
            "TargetBucket": "samu-docs-private-upload-logs",
            "TargetPrefix": "access-logs/"
        }
    }'
```

### 2. Check IAM Permissions for Application
```bash
# Get current user/role ARN
aws sts get-caller-identity

# List attached policies
aws iam list-attached-role-policies --role-name YOUR-APP-ROLE-NAME
```

### 3. Test S3 Access Directly
```python
# Python test script
import boto3

s3 = boto3.client('s3')
textract = boto3.client('textract')

# Test S3 access
try:
    response = s3.head_object(
        Bucket='samu-docs-private-upload',
        Key='documents/YOUR-TEST-DOCUMENT.pdf'
    )
    print("✅ S3 object accessible")
except Exception as e:
    print(f"❌ S3 access failed: {e}")

# Test Textract
try:
    response = textract.start_document_text_detection(
        DocumentLocation={
            'S3Object': {
                'Bucket': 'samu-docs-private-upload',
                'Name': 'documents/YOUR-TEST-DOCUMENT.pdf'
            }
        }
    )
    print(f"✅ Textract job started: {response['JobId']}")
except Exception as e:
    print(f"❌ Textract failed: {e}")
```

## Implementation Checklist

1. [ ] Determine which option to implement (bucket policy recommended)
2. [ ] Create and save the policy JSON file
3. [ ] Apply the policy using AWS CLI
4. [ ] Verify the policy was applied correctly
5. [ ] Test with a sample document through Textract
6. [ ] Re-run the document import process
7. [ ] Monitor pipeline for successful OCR completion

## Expected Outcome

After implementing these changes:
1. Textract will successfully access documents in S3
2. OCR jobs will start and complete normally
3. The pipeline will automatically progress through all stages
4. Documents will complete processing end-to-end

## Security Notes

- The recommended bucket policy only grants read access to Textract
- No public access is granted to the bucket
- Consider using the conditional policy (Option 3) for production
- Regularly audit bucket policies and access logs
- Use AWS CloudTrail to monitor Textract API calls

## Rollback Plan

If issues occur after applying changes:
```bash
# Remove bucket policy
aws s3api delete-bucket-policy --bucket samu-docs-private-upload

# Or revert to previous policy
aws s3api put-bucket-policy \
    --bucket samu-docs-private-upload \
    --policy file://previous-policy-backup.json
```

This fix is the final step needed to achieve full pipeline functionality. Once implemented, the legal document processing system will be fully operational and ready for production use.