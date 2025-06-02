#!/usr/bin/env python3
"""
Test Textract access to S3 bucket after permissions update
"""
import boto3
import sys
import os

# Set environment variables
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION

print("=== Testing S3-Textract Permissions ===")
print(f"Region: {AWS_DEFAULT_REGION}")
print(f"Bucket: samu-docs-private-upload")
print("-" * 50)

# Initialize clients
s3_client = boto3.client('s3',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

textract_client = boto3.client('textract',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# Test with an existing document from our previous uploads
test_keys = [
    "documents/519fd8c1-40fc-4671-b20b-12a3bb919634.pdf",
    "documents/b1588104-009f-44b7-9931-79b866d5ed79.pdf",
    "documents/849531b3-89e0-4187-9dd2-ea8779b4f069.pdf"
]

success_count = 0
for test_key in test_keys:
    print(f"\nTesting document: {test_key}")
    
    try:
        # First verify object exists
        response = s3_client.head_object(
            Bucket='samu-docs-private-upload',
            Key=test_key
        )
        print(f"  ✅ S3 object exists")
        print(f"     Size: {response['ContentLength']} bytes")
        print(f"     Last Modified: {response['LastModified']}")
        
        # Now test Textract access
        print(f"  🔄 Starting Textract job...")
        response = textract_client.start_document_text_detection(
            DocumentLocation={
                'S3Object': {
                    'Bucket': 'samu-docs-private-upload',
                    'Name': test_key
                }
            }
        )
        print(f"  ✅ Textract job started successfully!")
        print(f"     Job ID: {response['JobId']}")
        success_count += 1
        
        # Get job status
        job_status = textract_client.get_document_text_detection(JobId=response['JobId'])
        print(f"     Initial Status: {job_status['JobStatus']}")
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        if "InvalidS3ObjectException" in str(e):
            print("     → S3 permissions issue still exists")
        elif "Unable to get object metadata" in str(e):
            print("     → Textract cannot access the S3 object")
        else:
            print(f"     → Unexpected error type")

print("\n" + "="*50)
print(f"Summary: {success_count}/{len(test_keys)} documents tested successfully")

if success_count == len(test_keys):
    print("✅ S3-Textract permissions are correctly configured!")
    print("   The pipeline should now work end-to-end.")
    sys.exit(0)
else:
    print("❌ S3-Textract permissions issue persists.")
    print("   Please verify the bucket policy was applied correctly.")
    sys.exit(1)