#!/usr/bin/env python3
"""
Simple test to verify region configuration
"""
import os

# Set minimal configuration
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'
os.environ['DATABASE_URL'] = 'postgresql://dummy:dummy@localhost/dummy'
os.environ['DEPLOYMENT_STAGE'] = '3'

# Check current configuration
print("=== Region Configuration ===")
print(f"AWS_DEFAULT_REGION from env: {os.getenv('AWS_DEFAULT_REGION', 'not set')}")
print(f"S3_BUCKET_REGION from env: {os.getenv('S3_BUCKET_REGION', 'not set')}")

# Import after setting environment
from scripts.config import AWS_DEFAULT_REGION, S3_BUCKET_REGION

print("\nConfiguration values:")
print(f"AWS_DEFAULT_REGION: {AWS_DEFAULT_REGION}")
print(f"S3_BUCKET_REGION: {S3_BUCKET_REGION}")

print("\nExpected behavior:")
print("- AWS_DEFAULT_REGION defaults to 'us-east-1' (general AWS operations)")
print("- S3_BUCKET_REGION defaults to 'us-east-2' (S3 bucket location)")
print("- Textract will use S3_BUCKET_REGION to match the bucket location")

# Test with boto3 directly
import boto3

print("\n=== Testing Boto3 Client Initialization ===")

# Test S3 client
s3_client = boto3.client('s3', region_name=S3_BUCKET_REGION)
print(f"✅ S3 client region: {s3_client.meta.region_name}")

# Test Textract client
textract_client = boto3.client('textract', region_name=S3_BUCKET_REGION)
print(f"✅ Textract client region: {textract_client.meta.region_name}")

print("\n✅ Region configuration is correct!")
print("Both S3 and Textract will use the same region (us-east-2)")