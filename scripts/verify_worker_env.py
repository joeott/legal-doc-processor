#!/usr/bin/env python3
"""
Verify Celery workers have proper environment variables
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
import boto3

@app.task(name='verify_worker_environment')
def verify_worker_environment():
    """Check environment variables and AWS access in worker"""
    result = {
        'environment': {},
        'aws_test': {},
        'textract_test': {},
        'endpoint_info': {}
    }
    
    # Check environment variables
    env_vars = [
        'AWS_ACCESS_KEY_ID', 
        'AWS_SECRET_ACCESS_KEY', 
        'AWS_DEFAULT_REGION',
        'S3_BUCKET_REGION', 
        'S3_PRIMARY_DOCUMENT_BUCKET',
        'OPENAI_API_KEY',
        'DATABASE_URL',
        'REDIS_HOST',
        'PYTHONPATH'
    ]
    
    for var in env_vars:
        value = os.getenv(var)
        if var in ['AWS_SECRET_ACCESS_KEY', 'OPENAI_API_KEY', 'DATABASE_URL'] and value:
            # Mask sensitive data
            result['environment'][var] = f"{value[:10]}...{value[-4:]}" if len(value) > 14 else "***"
        else:
            result['environment'][var] = value
    
    # Test AWS credentials
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        result['aws_test']['credentials_available'] = credentials is not None
        
        # Test S3 access
        s3 = boto3.client('s3', region_name='us-east-2')
        bucket = os.getenv('S3_PRIMARY_DOCUMENT_BUCKET', 'samu-docs-private-upload')
        s3.head_bucket(Bucket=bucket)
        result['aws_test']['s3_access'] = True
        result['aws_test']['bucket'] = bucket
    except Exception as e:
        result['aws_test']['error'] = str(e)
    
    # Test Textract client creation and endpoint
    try:
        textract = boto3.client('textract', region_name='us-east-2')
        result['textract_test']['client_created'] = True
        
        # Get endpoint information
        result['endpoint_info']['region'] = textract.meta.region_name
        result['endpoint_info']['endpoint_url'] = textract.meta.endpoint_url
        
        # Try a simple API call to verify credentials work
        try:
            # This just lists jobs, won't return anything but tests auth
            response = textract.describe_document_text_detection(JobId='test')
        except textract.exceptions.InvalidJobIdException:
            # This is expected - it means auth worked but job doesn't exist
            result['textract_test']['auth_works'] = True
        except Exception as e:
            result['textract_test']['auth_error'] = str(e)
            
    except Exception as e:
        result['textract_test']['error'] = str(e)
    
    return result


def test_worker_environment():
    """Run the test"""
    print("Testing Celery worker environment...")
    print("=" * 70)
    
    try:
        # Submit task
        task = verify_worker_environment.apply_async()
        result = task.get(timeout=10)
        
        # Display results
        print("\n1. Environment Variables:")
        for key, value in result['environment'].items():
            status = "✓" if value else "✗"
            print(f"   {status} {key}: {value}")
        
        print("\n2. AWS Access Test:")
        for key, value in result['aws_test'].items():
            print(f"   {key}: {value}")
            
        print("\n3. Textract Test:")
        for key, value in result['textract_test'].items():
            print(f"   {key}: {value}")
            
        print("\n4. Endpoint Info:")
        for key, value in result['endpoint_info'].items():
            print(f"   {key}: {value}")
            
        # Overall status
        has_creds = all([
            result['environment'].get('AWS_ACCESS_KEY_ID'),
            result['environment'].get('AWS_SECRET_ACCESS_KEY'),
            result['environment'].get('S3_BUCKET_REGION') == 'us-east-2'
        ])
        
        s3_works = result['aws_test'].get('s3_access', False)
        textract_works = result['textract_test'].get('client_created', False)
        
        print("\n" + "=" * 70)
        if has_creds and s3_works and textract_works:
            print("✅ WORKER ENVIRONMENT IS PROPERLY CONFIGURED!")
        else:
            print("❌ WORKER ENVIRONMENT ISSUES DETECTED")
            
    except Exception as e:
        print(f"❌ Error testing worker environment: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_worker_environment()