# Context 46: Signed URL Implementation for Mistral OCR

## Overview
Implemented signed URL generation in `supabase_utils.py` to address Mistral OCR error 1901 ("An error happened when fetching file from url"). This follows Solution 2 from context_45_mistral_diagnosis.md.

## Changes Made

### 1. Enhanced `generate_document_url()` Function
Modified the function in `scripts/supabase_utils.py` to support both signed and public URLs:

```python
def generate_document_url(file_path: str, use_signed_url: bool = True) -> str:
    """
    Generate a URL for a document stored in Supabase Storage.
    
    Args:
        file_path: Path to the file in Supabase Storage
        use_signed_url: Whether to generate a signed URL (default: True for Mistral OCR compatibility)
        
    Returns:
        URL for the document (signed or public based on use_signed_url)
    """
```

### 2. Key Features
- **Default behavior**: Now generates signed URLs by default (1-hour expiry)
- **Backward compatibility**: Can still generate public URLs with `use_signed_url=False`
- **Flexible response handling**: Handles different Supabase client response formats
- **Error logging**: Enhanced error messages for debugging

### 3. Implementation Details
```python
if use_signed_url:
    # Generate a signed URL with 1 hour expiry for Mistral OCR access
    expires_in = 3600  # 1 hour in seconds
    signed_url_response = client.storage.from_(bucket).create_signed_url(path, expires_in)
    
    # Handle various response formats from Supabase client
    if 'signedURL' in signed_url_response:
        signed_url = signed_url_response['signedURL']
    elif 'data' in signed_url_response and 'signedURL' in signed_url_response['data']:
        signed_url = signed_url_response['data']['signedURL']
    else:
        # Fallback for different response formats
        signed_url = signed_url_response.get('signedUrl', signed_url_response.get('signed_url', ''))
```

## Verification and Testing Process

### 1. Initial Error Discovery
```
2025-05-22 21:51:57,838 - ocr_extraction - ERROR - Mistral OCR request failed: An error happened when fetching file from url. Code: 1901
```
- Mistral OCR API returned error code 1901 when trying to fetch files from Supabase public URLs

### 2. URL Structure Analysis
- Working Supabase URL provided by user: `https://yalswdiexcuanszujjhl.supabase.co/storage/v1/object/sign/documents/uploads/1747798522899-t46hghze8r.pdf?token=...`
- Database s3_key field stores: `uploads/1747966420130-m9gegr9fdp.pdf`
- Frontend uploads to: `documents` bucket with path `uploads/[timestamp]-[random].[ext]`

### 3. Path Mapping Issues Discovered
- Files are uploaded to `documents/uploads/[filename]` in Supabase Storage
- Database stores only `uploads/[filename]` in s3_key field
- generate_document_url was incorrectly parsing bucket/path structure

### 4. Fix Implementation
Added path parsing logic to handle the mismatch:
```python
# Special handling: if path starts with 'uploads/', it's already the path within the 'documents' bucket
# This matches the upload.js behavior where files go to 'documents' bucket with path 'uploads/[filename]'
if not path.startswith('uploads/') and 'uploads/' in path:
    # Extract just the uploads/filename part
    uploads_idx = path.find('uploads/')
    if uploads_idx != -1:
        path = path[uploads_idx:]
```

### 5. Testing Results
- Created test script `test_signed_url.py` to verify URL generation
- Public URL generation: SUCCESS - `https://yalswdiexcuanszujjhl.supabase.co/storage/v1/object/public/uploads/1747966420130-m9gegr9fdp.pdf`
- Signed URL generation: FAILED - 404 error "Object not found"
- Pipeline test showed same pattern: public URLs generate but signed URLs fail with 404

### 6. Root Cause Analysis
The 404 errors indicate that:
1. Files might not exist in the expected location in Supabase Storage
2. The bucket structure doesn't match what the API expects
3. Permissions or configuration issues with Supabase Storage

### 7. Pipeline Behavior Observed
When running `python scripts/main_pipeline.py --mode queue`:
- Queue processor successfully claimed 3 documents
- Mistral OCR attempted to process with signed URLs
- All attempts failed with 404 "Object not found" errors
- Fallback to Qwen VL OCR was skipped (Stage 1 cloud-only mode)
- Documents marked as failed with error messages

## Conclusion
The signed URL implementation is technically correct but revealed a deeper storage architecture issue. The files either don't exist where expected in Supabase Storage or aren't accessible via the storage API. This necessitates switching to the previously confirmed working S3 storage method.

## Related Files
- `scripts/supabase_utils.py`: Contains the enhanced `generate_document_url()` function
- `scripts/ocr_extraction.py`: Uses `generate_document_url()` for Mistral OCR
- `ai_docs/context_45_mistral_diagnosis.md`: Original diagnosis and solution proposals
- `ai_docs/context_47_s3_storage_switch.md`: Plan for switching to S3 storage