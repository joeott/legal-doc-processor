#!/usr/bin/env python3
"""
Setup S3 buckets for document processing with appropriate policies.
This script creates the required S3 buckets and configures their policies.
"""

import boto3
import json
import os
from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
from config import S3_BUCKET_PRIVATE, S3_BUCKET_PUBLIC, S3_BUCKET_TEMP

def create_buckets():
    """Create the required S3 buckets if they don't exist"""
    s3_client = boto3.client(
        's3',
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    
    buckets_to_create = [
        S3_BUCKET_PRIVATE,
        S3_BUCKET_PUBLIC,
        S3_BUCKET_TEMP
    ]
    
    for bucket_name in buckets_to_create:
        try:
            # Check if bucket exists
            s3_client.head_bucket(Bucket=bucket_name)
            print(f"✓ Bucket '{bucket_name}' already exists")
        except:
            # Create bucket
            try:
                if AWS_DEFAULT_REGION == 'us-east-1':
                    # us-east-1 doesn't support LocationConstraint
                    s3_client.create_bucket(Bucket=bucket_name)
                else:
                    s3_client.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': AWS_DEFAULT_REGION}
                    )
                print(f"✓ Created bucket '{bucket_name}'")
            except Exception as e:
                print(f"✗ Failed to create bucket '{bucket_name}': {e}")
                raise

def set_public_bucket_policy():
    """Set the public read policy for the OCR bucket"""
    s3_client = boto3.client(
        's3',
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    
    # First try to disable block public access
    try:
        s3_client.put_public_access_block(
            Bucket=S3_BUCKET_PUBLIC,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': False,
                'IgnorePublicAcls': False,
                'BlockPublicPolicy': False,
                'RestrictPublicBuckets': False
            }
        )
        print(f"✓ Disabled block public access on '{S3_BUCKET_PUBLIC}'")
    except Exception as e:
        print(f"⚠️  Could not disable block public access: {e}")
        print("   This is fine - we'll use presigned URLs only")
        return  # Skip setting public policy
    
    # Public bucket policy for OCR access
    public_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicReadForOCR",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{S3_BUCKET_PUBLIC}/*"
            }
        ]
    }
    
    try:
        s3_client.put_bucket_policy(
            Bucket=S3_BUCKET_PUBLIC,
            Policy=json.dumps(public_policy)
        )
        print(f"✓ Set public read policy on '{S3_BUCKET_PUBLIC}'")
    except Exception as e:
        print(f"⚠️  Could not set public bucket policy: {e}")
        print("   This is fine - presigned URLs will work perfectly for Mistral OCR")
        print("   In fact, this is more secure!")

def set_lifecycle_policies():
    """Set lifecycle policies to automatically clean up old OCR files"""
    s3_client = boto3.client(
        's3',
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    
    # Lifecycle policy to delete OCR files after 7 days
    lifecycle_config = {
        'Rules': [
            {
                'ID': 'DeleteOldOCRFiles',
                'Status': 'Enabled',
                'Prefix': 'ocr-processing/',
                'Expiration': {
                    'Days': 7
                }
            }
        ]
    }
    
    try:
        s3_client.put_bucket_lifecycle_configuration(
            Bucket=S3_BUCKET_PUBLIC,
            LifecycleConfiguration=lifecycle_config
        )
        print(f"✓ Set lifecycle policy on '{S3_BUCKET_PUBLIC}' to delete OCR files after 7 days")
    except Exception as e:
        print(f"✗ Failed to set lifecycle policy on '{S3_BUCKET_PUBLIC}': {e}")
        raise
    
    # Similar policy for temp bucket
    try:
        s3_client.put_bucket_lifecycle_configuration(
            Bucket=S3_BUCKET_TEMP,
            LifecycleConfiguration=lifecycle_config
        )
        print(f"✓ Set lifecycle policy on '{S3_BUCKET_TEMP}' to delete files after 7 days")
    except Exception as e:
        print(f"✗ Failed to set lifecycle policy on '{S3_BUCKET_TEMP}': {e}")
        raise

def configure_cors():
    """Configure CORS for the public bucket to allow browser uploads"""
    s3_client = boto3.client(
        's3',
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    
    cors_configuration = {
        'CORSRules': [
            {
                'AllowedHeaders': ['*'],
                'AllowedMethods': ['GET', 'PUT', 'POST'],
                'AllowedOrigins': ['*'],
                'ExposeHeaders': ['ETag']
            }
        ]
    }
    
    try:
        s3_client.put_bucket_cors(
            Bucket=S3_BUCKET_PUBLIC,
            CORSConfiguration=cors_configuration
        )
        print(f"✓ Set CORS configuration on '{S3_BUCKET_PUBLIC}'")
    except Exception as e:
        print(f"✗ Failed to set CORS on '{S3_BUCKET_PUBLIC}': {e}")
        raise

def main():
    """Main setup function"""
    print("Setting up S3 buckets for document processing...")
    print(f"Region: {AWS_DEFAULT_REGION}")
    print(f"Private bucket: {S3_BUCKET_PRIVATE}")
    print(f"Public bucket: {S3_BUCKET_PUBLIC}")
    print(f"Temp bucket: {S3_BUCKET_TEMP}")
    print("")
    
    # Create buckets
    create_buckets()
    print("")
    
    # Set policies (non-critical - continue even if they fail)
    try:
        set_public_bucket_policy()
    except Exception as e:
        print(f"⚠️  Warning: {e}")
    
    try:
        set_lifecycle_policies()
    except Exception as e:
        print(f"⚠️  Warning: Could not set lifecycle policies: {e}")
    
    try:
        configure_cors()
    except Exception as e:
        print(f"⚠️  Warning: Could not set CORS: {e}")
    print("")
    
    print("✓ S3 bucket setup complete!")
    print("")
    print("Next steps:")
    print("1. Run the migration to add database indexes:")
    print("   psql $DATABASE_URL < frontend/migrations/00004_add_s3_indexes.sql")
    print("2. Test the S3 integration:")
    print("   python scripts/test_s3_integration.py")

if __name__ == "__main__":
    main()