#!/usr/bin/env python3
"""
Test that the region fix works correctly
"""
import os
import sys

# Enable minimal models for testing
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.config import AWS_DEFAULT_REGION, S3_BUCKET_REGION, S3_PRIMARY_DOCUMENT_BUCKET
from scripts.textract_job_manager import TextractJobManager
from scripts.textract_utils import TextractProcessor
from scripts.s3_storage import S3StorageManager
from scripts.db import DatabaseManager

print("=== Testing Region Configuration ===")
print(f"AWS_DEFAULT_REGION: {AWS_DEFAULT_REGION}")
print(f"S3_BUCKET_REGION: {S3_BUCKET_REGION}")
print(f"S3_PRIMARY_DOCUMENT_BUCKET: {S3_PRIMARY_DOCUMENT_BUCKET}")
print("-" * 50)

# Test 1: Check TextractJobManager initialization
print("\n1. Testing TextractJobManager initialization...")
try:
    job_manager = TextractJobManager()
    print(f"✅ TextractJobManager initialized successfully")
    print(f"   Using region: {job_manager.textract_client.meta.region_name}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 2: Check TextractProcessor initialization
print("\n2. Testing TextractProcessor initialization...")
try:
    db_manager = DatabaseManager(validate_conformance=False)
    textract_processor = TextractProcessor(db_manager)
    print(f"✅ TextractProcessor initialized successfully")
    print(f"   Using region: {textract_processor.client.meta.region_name}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 3: Check S3StorageManager initialization
print("\n3. Testing S3StorageManager initialization...")
try:
    s3_manager = S3StorageManager()
    print(f"✅ S3StorageManager initialized successfully")
    print(f"   Using region: {s3_manager.s3_client.meta.region_name}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 4: Verify bucket location
print("\n4. Verifying S3 bucket location...")
try:
    s3_manager = S3StorageManager()
    response = s3_manager.s3_client.get_bucket_location(Bucket=S3_PRIMARY_DOCUMENT_BUCKET)
    bucket_region = response.get('LocationConstraint') or 'us-east-1'
    print(f"✅ Bucket '{S3_PRIMARY_DOCUMENT_BUCKET}' is in region: {bucket_region}")
    
    if bucket_region != S3_BUCKET_REGION:
        print(f"⚠️  WARNING: Bucket region ({bucket_region}) doesn't match S3_BUCKET_REGION ({S3_BUCKET_REGION})")
    else:
        print(f"✅ Bucket region matches S3_BUCKET_REGION configuration")
except Exception as e:
    print(f"❌ Error checking bucket location: {e}")

print("\n" + "="*50)
print("Summary:")
print(f"- All AWS services (S3, Textract) should use region: {S3_BUCKET_REGION}")
print(f"- This ensures Textract can access the S3 bucket in the same region")
print(f"- To change the region, set S3_BUCKET_REGION in your .env file")