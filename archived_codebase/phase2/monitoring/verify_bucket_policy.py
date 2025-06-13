#!/usr/bin/env python3
"""
Verify S3 bucket policy and configuration
"""
import boto3
import json
import os

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION

print("=== S3 Bucket Policy Verification ===")
print(f"Bucket: samu-docs-private-upload")
print(f"Region: {AWS_DEFAULT_REGION}")
print("-" * 50)

s3_client = boto3.client('s3',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# 1. Check bucket location
try:
    location = s3_client.get_bucket_location(Bucket='samu-docs-private-upload')
    bucket_region = location.get('LocationConstraint') or 'us-east-1'
    print(f"✅ Bucket Region: {bucket_region}")
except Exception as e:
    print(f"❌ Error getting bucket location: {e}")

# 2. Get current bucket policy
try:
    response = s3_client.get_bucket_policy(Bucket='samu-docs-private-upload')
    policy = json.loads(response['Policy'])
    print("\n✅ Current Bucket Policy:")
    print(json.dumps(policy, indent=2))
    
    # Check if Textract is in the policy
    textract_found = False
    for statement in policy.get('Statement', []):
        principal = statement.get('Principal', {})
        if isinstance(principal, dict) and principal.get('Service') == 'textract.amazonaws.com':
            textract_found = True
            print("\n✅ Textract service principal found in policy")
            print(f"   Actions: {statement.get('Action')}")
            print(f"   Resource: {statement.get('Resource')}")
            break
    
    if not textract_found:
        print("\n⚠️ Textract service principal NOT found in policy!")
        
except s3_client.exceptions.NoSuchBucketPolicy:
    print("\n❌ No bucket policy found!")
    print("   You need to apply the Textract bucket policy.")
except Exception as e:
    print(f"\n❌ Error getting bucket policy: {e}")

# 3. Check bucket ACL
try:
    acl = s3_client.get_bucket_acl(Bucket='samu-docs-private-upload')
    print(f"\n✅ Bucket Owner: {acl['Owner']['DisplayName']}")
    print(f"   Owner ID: {acl['Owner']['ID']}")
except Exception as e:
    print(f"\n❌ Error getting bucket ACL: {e}")

# 4. Get account ID for policy recommendations
try:
    sts = boto3.client('sts',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    identity = sts.get_caller_identity()
    account_id = identity['Account']
    print(f"\n✅ AWS Account ID: {account_id}")
    
    # Provide recommended policy
    print("\n📋 RECOMMENDED BUCKET POLICY:")
    print("Copy and apply this policy using AWS CLI or Console:")
    print("-" * 50)
    
    recommended_policy = {
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
                "Resource": "arn:aws:s3:::samu-docs-private-upload/*",
                "Condition": {
                    "StringEquals": {
                        "aws:SourceAccount": account_id
                    }
                }
            }
        ]
    }
    
    print(json.dumps(recommended_policy, indent=2))
    
    # Save to file for easy application
    with open('/opt/legal-doc-processor/textract-bucket-policy.json', 'w') as f:
        json.dump(recommended_policy, f, indent=2)
    
    print("\n✅ Policy saved to: /opt/legal-doc-processor/textract-bucket-policy.json")
    print("\nTo apply this policy, run:")
    print("aws s3api put-bucket-policy --bucket samu-docs-private-upload --policy file:///opt/legal-doc-processor/textract-bucket-policy.json")
    
except Exception as e:
    print(f"\n❌ Error getting account info: {e}")

# 5. Test a specific object's permissions
test_key = "documents/519fd8c1-40fc-4671-b20b-12a3bb919634.pdf"
try:
    obj_acl = s3_client.get_object_acl(Bucket='samu-docs-private-upload', Key=test_key)
    print(f"\n✅ Sample object ACL for: {test_key}")
    print(f"   Owner: {obj_acl['Owner']['DisplayName']}")
    for grant in obj_acl.get('Grants', []):
        grantee = grant.get('Grantee', {})
        print(f"   Grant: {grant.get('Permission')} to {grantee.get('Type')}")
except Exception as e:
    print(f"\n❌ Error checking object ACL: {e}")