#!/usr/bin/env python3
"""
Diagnose why Textract job submission is failing
"""

import os
import sys
import boto3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app

@app.task
def check_celery_aws_environment():
    """Check AWS environment from within Celery worker"""
    import os
    import boto3
    
    env_vars = {
        'AWS_ACCESS_KEY_ID': bool(os.getenv('AWS_ACCESS_KEY_ID')),
        'AWS_SECRET_ACCESS_KEY': bool(os.getenv('AWS_SECRET_ACCESS_KEY')),
        'AWS_DEFAULT_REGION': os.getenv('AWS_DEFAULT_REGION'),
        'S3_BUCKET_REGION': os.getenv('S3_BUCKET_REGION'),
        'S3_PRIMARY_DOCUMENT_BUCKET': os.getenv('S3_PRIMARY_DOCUMENT_BUCKET')
    }
    
    # Try to create Textract client
    textract_test = {'client_created': False, 'error': None}
    try:
        textract = boto3.client('textract', region_name='us-east-2')
        textract_test['client_created'] = True
        # Try to list jobs (won't return anything but tests credentials)
        response = textract.list_document_text_detection_jobs(MaxResults=1)
        textract_test['can_list_jobs'] = True
    except Exception as e:
        textract_test['error'] = str(e)
    
    # Try to access S3
    s3_test = {'client_created': False, 'error': None}
    try:
        s3 = boto3.client('s3', region_name='us-east-2')
        s3_test['client_created'] = True
        bucket = os.getenv('S3_PRIMARY_DOCUMENT_BUCKET', 'samu-docs-private-upload')
        # Try to head bucket
        s3.head_bucket(Bucket=bucket)
        s3_test['bucket_accessible'] = True
        s3_test['bucket'] = bucket
    except Exception as e:
        s3_test['error'] = str(e)
    
    return {
        'environment': env_vars,
        'textract': textract_test,
        's3': s3_test
    }


def diagnose_textract_locally():
    """Run diagnostics in local environment"""
    print("=" * 70)
    print("TEXTRACT DIAGNOSTICS")
    print("=" * 70)
    
    # 1. Check local environment
    print("\n1. Local Environment Variables:")
    env_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_DEFAULT_REGION', 
                'S3_BUCKET_REGION', 'S3_PRIMARY_DOCUMENT_BUCKET']
    for var in env_vars:
        value = os.getenv(var)
        if var.endswith('KEY') and value:
            value = value[:10] + '...'  # Hide sensitive data
        print(f"   {var}: {value}")
    
    # 2. Test Textract client locally
    print("\n2. Local Textract Client Test:")
    try:
        textract = boto3.client('textract', region_name='us-east-2')
        print("   ✅ Textract client created successfully")
        
        # Check if we can make API calls
        response = textract.list_document_text_detection_jobs(MaxResults=1)
        print("   ✅ Can call Textract API")
    except Exception as e:
        print(f"   ❌ Textract error: {e}")
    
    # 3. Check S3 access
    print("\n3. S3 Access Test:")
    try:
        s3 = boto3.client('s3', region_name='us-east-2')
        bucket = os.getenv('S3_PRIMARY_DOCUMENT_BUCKET', 'samu-docs-private-upload')
        
        # Check bucket exists and is accessible
        s3.head_bucket(Bucket=bucket)
        print(f"   ✅ Bucket '{bucket}' is accessible")
        
        # Check bucket location
        location = s3.get_bucket_location(Bucket=bucket)
        region = location.get('LocationConstraint', 'us-east-1')
        print(f"   ✅ Bucket region: {region}")
        
    except Exception as e:
        print(f"   ❌ S3 error: {e}")
    
    # 4. Check Textract permissions on bucket
    print("\n4. Textract Bucket Permissions:")
    try:
        # Get bucket policy
        policy_response = s3.get_bucket_policy(Bucket=bucket)
        print("   ✅ Bucket has policy configured")
        
        # Check if Textract service is mentioned
        policy_text = policy_response['Policy']
        if 'textract.amazonaws.com' in policy_text:
            print("   ✅ Textract service principal found in policy")
        else:
            print("   ⚠️  Textract service principal NOT found in policy")
            
    except s3.exceptions.NoSuchBucketPolicy:
        print("   ❌ No bucket policy found - Textract needs bucket access")
    except Exception as e:
        print(f"   ❌ Policy check error: {e}")
    
    # 5. Test from Celery
    print("\n5. Celery Worker Environment Test:")
    try:
        result = check_celery_aws_environment.apply_async()
        celery_result = result.get(timeout=10)
        
        print("   Environment in Celery:")
        for key, value in celery_result['environment'].items():
            print(f"     {key}: {value}")
            
        print("\n   Textract in Celery:")
        for key, value in celery_result['textract'].items():
            print(f"     {key}: {value}")
            
        print("\n   S3 in Celery:")
        for key, value in celery_result['s3'].items():
            print(f"     {key}: {value}")
            
    except Exception as e:
        print(f"   ❌ Celery test failed: {e}")
    
    print("\n" + "=" * 70)
    
    # 6. Check actual Textract error from last document
    print("\n6. Recent Textract Errors:")
    from scripts.db import DatabaseManager
    from sqlalchemy import text
    
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    errors = session.execute(
        text("""SELECT document_uuid, error_message, created_at 
                FROM source_documents 
                WHERE error_message IS NOT NULL 
                AND error_message LIKE '%Textract%'
                ORDER BY created_at DESC 
                LIMIT 5""")
    ).fetchall()
    
    if errors:
        for err in errors:
            print(f"\n   Document: {err[0]}")
            print(f"   Time: {err[2]}")
            print(f"   Error: {err[1]}")
    else:
        print("   No recent Textract errors found")
    
    session.close()


if __name__ == "__main__":
    diagnose_textract_locally()