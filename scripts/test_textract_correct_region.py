#!/usr/bin/env python3
"""
Test Textract access with correct region (us-east-2)
"""
import boto3
import sys
import os

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

print("=== Testing S3-Textract with Correct Region ===")
print("S3 Bucket Region: us-east-2")
print("Using Textract in: us-east-2")
print("-" * 50)

# Initialize clients with CORRECT REGION
s3_client = boto3.client('s3',
    region_name='us-east-2',  # Bucket is in us-east-2
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

textract_client = boto3.client('textract',
    region_name='us-east-2',  # Use same region as bucket
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# Test with one document
test_key = "documents/519fd8c1-40fc-4671-b20b-12a3bb919634.pdf"

print(f"\nTesting document: {test_key}")

try:
    # Verify object exists
    response = s3_client.head_object(
        Bucket='samu-docs-private-upload',
        Key=test_key
    )
    print(f"✅ S3 object exists")
    print(f"   Size: {response['ContentLength']} bytes")
    
    # Test Textract access with correct region
    print(f"\n🔄 Starting Textract job in us-east-2...")
    response = textract_client.start_document_text_detection(
        DocumentLocation={
            'S3Object': {
                'Bucket': 'samu-docs-private-upload',
                'Name': test_key
            }
        }
    )
    print(f"✅ SUCCESS! Textract job started!")
    print(f"   Job ID: {response['JobId']}")
    
    # Check job status
    import time
    time.sleep(2)
    job_status = textract_client.get_document_text_detection(JobId=response['JobId'])
    print(f"   Status: {job_status['JobStatus']}")
    
    print("\n" + "="*50)
    print("✅ REGION FIX CONFIRMED!")
    print("The issue was a region mismatch. Solutions:")
    print("1. Update AWS_DEFAULT_REGION to 'us-east-2' in .env")
    print("2. Or ensure Textract uses 'us-east-2' region")
    
except Exception as e:
    print(f"❌ Error: {e}")
    print("\nDebugging info:")
    print(f"- S3 bucket is in: us-east-2")
    print(f"- Textract must use the same region")
    print(f"- Current AWS_DEFAULT_REGION in config: {os.environ.get('AWS_DEFAULT_REGION', 'not set')}")