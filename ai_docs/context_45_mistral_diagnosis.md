# Context 45: Mistral OCR URL Access Diagnosis

## Problem Summary

Mistral OCR API is returning error code 1901: "An error happened when fetching file from URL". The URL being sent is:
```
https://yalswdiexcuanszujjhl.supabase.co/storage/v1/object/public/uploads/1747966420130-m9gegr9fdp.pdf
```

## Root Cause Analysis

### 1. URL Generation Process
The current flow:
1. File path: `uploads/1747966420130-m9gegr9fdp.pdf`
2. `generate_document_url()` creates: `https://yalswdiexcuanszujjhl.supabase.co/storage/v1/object/public/uploads/1747966420130-m9gegr9fdp.pdf`
3. We already fixed the trailing `?` issue in context_43

### 2. Potential Issues

#### Issue 1: File Not Public
The URL path includes `/public/` but the file might not actually be publicly accessible. Supabase Storage buckets can be:
- **Public**: Files accessible without authentication
- **Private**: Files require authentication tokens

#### Issue 2: File Doesn't Exist at Path
The file might not exist at the expected location in Supabase Storage. The path `uploads/1747966420130-m9gegr9fdp.pdf` assumes:
- Bucket name: `uploads`
- File key: `1747966420130-m9gegr9fdp.pdf`

#### Issue 3: Mistral Can't Access Supabase URLs
Based on context_12 and context_13, the original implementation plan suggested:
1. Uploading files to S3 temporarily
2. Generating presigned URLs
3. Passing those to Mistral

The current implementation skips this and tries to use Supabase URLs directly.

## Evidence from Previous Context

From **context_12_mistral_refactor_ocr.md**:
```python
# Upload the file to S3 temporarily to get a URL
s3_bucket = os.getenv("S3_BUCKET", "preprocessv2")
s3_key = f"temp_ocr/{uuid.uuid4()}/{file_name}"

# Generate presigned URL (valid for 1 hour)
url = s3_client.generate_presigned_url(
    'get_object',
    Params={'Bucket': s3_bucket, 'Key': s3_key},
    ExpiresIn=3600
)
```

From **context_13_mistral_update.md**:
The implementation suggested using Supabase Storage with a `generate_temp_url()` function, but this isn't what's being used in the current code.

## Diagnosis

### Current Implementation Issues:

1. **No Public Access Verification**: The code assumes the file is publicly accessible but doesn't verify this
2. **Direct URL Usage**: Using Supabase public URLs directly without authentication
3. **Missing S3 Fallback**: The original plan included S3 as a temporary storage solution

### Why Mistral Can't Access the File:

1. **Authentication Required**: Supabase public URLs might still require certain headers or cookies
2. **CORS/Referrer Restrictions**: Supabase might have restrictions on external API access
3. **File Not Actually Public**: The bucket might not be configured as public despite the URL path

## Proposed Solutions

### Solution 1: Verify and Fix Supabase Public Access (Quick Fix)

1. **Check bucket permissions**:
```sql
-- Check if uploads bucket is public
SELECT name, public 
FROM storage.buckets 
WHERE name = 'uploads';
```

2. **Make bucket public if needed**:
```sql
UPDATE storage.buckets 
SET public = true 
WHERE name = 'uploads';
```

3. **Add RLS policy for public read**:
```sql
CREATE POLICY "Public Access" ON storage.objects
FOR SELECT USING (bucket_id = 'uploads');
```

### Solution 2: Use Signed URLs (Recommended)

Modify `generate_document_url()` to create signed URLs:

```python
def generate_document_url(file_path: str) -> str:
    """Generate a signed URL for temporary access"""
    client = get_supabase_client()
    
    # Extract bucket and path
    parts = file_path.split('/')
    bucket = 'uploads'
    path = file_path
    
    if len(parts) > 1 and parts[0] in ['documents', 'uploads']:
        bucket = parts[0]
        path = '/'.join(parts[1:])
    
    try:
        # Create a signed URL valid for 1 hour
        signed_url = client.storage.from_(bucket).create_signed_url(
            path, 
            expires_in=3600  # 1 hour
        )
        
        if signed_url and 'signedURL' in signed_url:
            url = signed_url['signedURL']
            logger.info(f"Generated signed URL: {url}")
            return url
        else:
            # Fallback to public URL
            public_url = client.storage.from_(bucket).get_public_url(path)
            # Remove trailing ? if present
            if public_url.endswith('?'):
                public_url = public_url[:-1]
            return public_url
            
    except Exception as e:
        logger.error(f"Error generating signed URL: {e}")
        # Fallback to public URL
        return client.storage.from_(bucket).get_public_url(path)
```

### Solution 3: Implement S3 Temporary Storage (Most Robust)

As originally planned in context_12, upload files to S3 temporarily:

```python
def generate_s3_presigned_url(file_path: str) -> str:
    """Upload file to S3 and generate presigned URL"""
    import boto3
    import uuid
    
    s3_client = boto3.client('s3')
    bucket = os.getenv("S3_BUCKET_TEMP", "mistral-ocr-temp")
    key = f"temp/{uuid.uuid4()}/{os.path.basename(file_path)}"
    
    # Upload file
    with open(file_path, 'rb') as f:
        s3_client.upload_fileobj(f, bucket, key)
    
    # Generate presigned URL
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=3600
    )
    
    return url
```

### Solution 4: Direct File Upload to Mistral (Alternative)

Check if Mistral API supports direct file upload instead of URL:

```python
def extract_text_from_file(file_path: str) -> Dict[str, Any]:
    """Upload file directly to Mistral API"""
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}"
    }
    
    with open(file_path, 'rb') as f:
        files = {'document': (os.path.basename(file_path), f, 'application/pdf')}
        response = requests.post(
            "https://api.mistral.ai/v1/ocr",
            headers=headers,
            files=files,
            data={'model': MISTRAL_OCR_MODEL}
        )
    
    return response.json()
```

## Implementation Priority

1. **Immediate**: Try Solution 2 (Signed URLs) - Minimal code change
2. **If that fails**: Implement Solution 3 (S3 temporary storage) - Most reliable
3. **Verify**: Check Supabase bucket permissions (Solution 1)
4. **Research**: Check if Mistral supports direct upload (Solution 4)

## Testing Strategy

1. **Test URL accessibility**:
```bash
# Test if URL is publicly accessible
curl -I "https://yalswdiexcuanszujjhl.supabase.co/storage/v1/object/public/uploads/1747966420130-m9gegr9fdp.pdf"
```

2. **Test with signed URL**:
```python
# Generate signed URL and test with curl
signed_url = generate_signed_url(file_path)
print(f"Test this URL: {signed_url}")
```

3. **Test Mistral API directly**:
```python
# Use a known working public PDF URL
test_url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
result = extract_text_from_url(test_url, "test.pdf")
```

## Conclusion

The Mistral OCR failure is likely due to:
1. Supabase URLs not being truly public or accessible to external APIs
2. Missing authentication/signed URL implementation
3. Deviation from the original S3-based implementation plan

The recommended fix is to implement signed URLs (Solution 2) first, then fall back to S3 temporary storage (Solution 3) if needed.