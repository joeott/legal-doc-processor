# AWS Textract Refactor Elements

## Executive Summary

This document provides a comprehensive analysis of replacing the current Mistral OCR implementation with AWS Textract in the legal document processing pipeline. The refactor is necessitated by critical access limitations with Mistral OCR that prevent secure document processing. This analysis serves as a detailed specification for implementing AWS Textract as the primary OCR solution.

## Problem Statement

### Current OCR Implementation Issues

1. **Mistral OCR Access Limitations**
   - Mistral OCR API cannot access Supabase Storage URLs due to authentication header requirements
   - Requires public S3 bucket access, not just presigned URLs with authentication parameters
   - Consistently returns error 1901 "invalid_file" when attempting to fetch from presigned URLs
   - AWS account-level security policies (BlockPublicPolicy) prevent making buckets public
   - The Mistral API endpoint expects to fetch documents via simple HTTP GET without authentication
   - Testing confirmed that presigned URLs return HTTP 307 redirects that Mistral cannot follow
   - Error occurs at the document fetch stage, before any OCR processing begins

2. **Security Concerns**
   - Making S3 buckets public poses significant security risks for legal documents
   - No control over who accesses sensitive documents during OCR processing window
   - Limited ability to restrict access by IP range (Mistral uses Cloudflare CDN with dynamic IPs)
   - Potential for data exposure if cleanup fails or is delayed
   - Legal documents may contain PII, privileged information, or confidential data
   - Public bucket policies conflict with compliance requirements (HIPAA, SOC2, etc.)
   - No audit trail of who accessed documents from public bucket

3. **Operational Complexity**
   - Multiple bucket management required (samu-docs-private-upload, samu-docs-public-ocr, samu-docs-temp-ocr)
   - File copying between buckets adds 2-5 seconds latency per document
   - Manual cleanup required after OCR processing to prevent data exposure
   - Complex error handling for multi-step process (upload → copy → OCR → cleanup)
   - Race conditions possible if cleanup fails while document is being accessed
   - Bucket lifecycle policies add another layer of configuration complexity
   - Monitoring required across multiple buckets for security and cost control

4. **Cost Implications**
   - Mistral OCR: $1 per 1000 pages (base OCR cost)
   - Additional S3 storage costs for three separate buckets
   - S3 transfer costs for copying between buckets (approximately $0.09/GB)
   - Redundant storage during processing (same file in 2-3 locations)
   - Increased CloudWatch monitoring costs for multiple buckets
   - Potential egress charges if public bucket is accessed externally
   - Hidden costs from failed cleanups leading to storage accumulation

## Why AWS Textract is the Right Solution

### 1. **Native AWS Integration**
   - Direct access to S3 buckets without any public exposure using IAM service roles
   - Uses IAM roles and policies for secure, auditable access control
   - No need for public buckets, presigned URLs, or complex URL generation
   - Seamless integration with existing AWS infrastructure (S3, CloudWatch, SNS)
   - Textract service directly reads from private S3 buckets using AWS internal network
   - Supports S3 object versioning for document history tracking
   - Can leverage S3 encryption (SSE-S3, SSE-KMS) transparently

### 2. **Security Advantages**
   - Documents remain completely private throughout entire processing lifecycle
   - Fine-grained access control via IAM policies with least-privilege principles
   - Automatic encryption at rest (S3) and in transit (TLS 1.2+)
   - Full compliance with HIPAA, PCI-DSS, SOC 1/2/3, ISO 27001, and FedRAMP
   - Complete audit trail via AWS CloudTrail for all API calls and access
   - No external internet exposure of sensitive legal documents
   - Service-to-service authentication eliminates credential management
   - VPC endpoint support for network isolation if required

### 3. **Superior Document Intelligence**
   - Extracts text, tables, forms, and key-value pairs with structural understanding
   - Identifies document structure, hierarchies, and semantic relationships
   - Built-in entity detection and classification for legal documents
   - Support for handwriting recognition (critical for signatures and annotations)
   - Multi-page document processing with maintained page relationships
   - Preserves reading order and document flow across columns and sections
   - Specialized models for legal document types (contracts, pleadings, discovery)
   - Confidence scores for each extracted element enabling quality filtering
   - Bounding box coordinates for spatial analysis and redaction

### 4. **Cost Efficiency**
   - Pay-per-use pricing model with no base charges
   - No minimum fees or upfront commitments required
   - Textract pricing: $1.50 per 1000 pages for DetectDocumentText (comparable to Mistral)
   - Advanced features available: $15/1000 pages for tables, $50/1000 for forms
   - Eliminates need for multiple S3 buckets (saves ~$0.023/GB/month × 3)
   - Reduces storage and transfer costs by eliminating inter-bucket copying
   - No egress charges since processing happens within AWS
   - Bulk pricing discounts available for high-volume processing
   - Cost predictability through AWS Cost Explorer and budgets

### 5. **Operational Simplicity**
   - Single API call for document processing (StartDocumentTextDetection)
   - Asynchronous processing for large documents with job status tracking
   - Built-in retry logic and error handling with exponential backoff
   - No file movement between buckets required - works with single private bucket
   - Automatic scaling to handle thousands of concurrent documents
   - SNS notifications for job completion (eliminates polling)
   - Batch processing support for multiple documents
   - No manual cleanup required - documents stay in original location
   - Simplified monitoring through single CloudWatch dashboard

### 6. **Advanced Features for Legal Document Processing**
   - **AnalyzeDocument**: Extract forms, tables, and structured data from legal documents
   - **DetectDocumentText**: High-accuracy OCR for text extraction
   - **AnalyzeExpense**: Process invoices and expense documents in discovery
   - **AnalyzeID**: Extract data from identity documents for verification
   - **StartDocumentAnalysis**: Asynchronous processing for large case files
   - **Queries Feature**: Ask natural language questions about document content
   - **Layout Analysis**: Understand document structure (headers, footers, paragraphs)
   - **Signature Detection**: Identify signature blocks in contracts
   - **Custom Queries**: Extract specific legal entities (case numbers, party names)

## Impacted Scripts and Line Numbers

### 1. **scripts/ocr_extraction.py**
   - **Lines 211-288**: `extract_text_from_pdf_mistral_ocr()` function to be completely replaced with `extract_text_from_pdf_textract()`
   - **Line 21**: Import statement for `mistral_utils` to be replaced with `textract_utils`
   - **Lines 296-310**: Main PDF processing logic in `process_single_document()` needs update
   - **New function needed**: `extract_text_from_pdf_textract()` with async job handling
   - **New imports needed**: `boto3`, `time`, AWS Textract-specific imports

### 2. **scripts/mistral_utils.py**
   - **Entire file**: Would be deleted and replaced with new `textract_utils.py`
   - **Key functions to implement in textract_utils.py**:
     - `start_document_text_detection()`: Initiate async Textract job
     - `get_document_text_detection()`: Poll for job results
     - `process_textract_blocks()`: Convert blocks to formatted text
     - `extract_tables_from_blocks()`: Parse table structures
     - `calculate_reading_order()`: Maintain document flow

### 3. **scripts/config.py**
   - **Lines 132-137**: Remove all Mistral OCR configuration variables
   - **Lines 117-128**: Simplify S3 bucket configuration to single private bucket
   - **Lines 123-125**: Remove S3_BUCKET_PUBLIC and S3_BUCKET_TEMP
   - **New additions required**:
     - `TEXTRACT_FEATURE_TYPES`: Configure which Textract features to use
     - `TEXTRACT_CONFIDENCE_THRESHOLD`: Minimum confidence for text acceptance
     - `TEXTRACT_USE_ASYNC`: Whether to use async processing
     - `TEXTRACT_SNS_TOPIC_ARN`: Optional SNS topic for job notifications
     - `TEXTRACT_MAX_POLLING_TIME`: Maximum time to wait for job completion

### 4. **scripts/main_pipeline.py**
   - **Line 21**: Update import from `extract_text_from_pdf_mistral_ocr` to `extract_text_from_pdf_textract`
   - **Lines 109-115**: Remove OCR method selection logic (USE_MISTRAL_FOR_OCR check)
   - **Line 111**: Replace call to `extract_text_from_pdf_mistral_ocr()` with `extract_text_from_pdf_textract()`
   - **Remove**: Fallback logic to Qwen VL OCR (lines 113-115)
   - **Update**: Error handling for Textract-specific exceptions
   - **Add**: Progress logging for async Textract jobs

### 5. **scripts/s3_storage.py**
   - **Lines 78-96**: Delete `copy_to_public_bucket()` - no longer needed with Textract
   - **Lines 98-114**: Delete `generate_presigned_url_for_ocr()` - Textract uses IAM roles
   - **Lines 116-124**: Delete `cleanup_ocr_file()` - no cleanup needed
   - **Lines 34-76**: Simplify `upload_document_with_uuid_naming()` - only needs private bucket
   - **Remove**: All references to S3_BUCKET_PUBLIC and S3_BUCKET_TEMP
   - **Add**: Method to generate S3 object reference for Textract API
   - **Simplify**: Error handling to remove public bucket-specific errors

### 6. **scripts/queue_processor.py**
   - **Lines 102-125**: Simplify file path handling - no need for public bucket logic
   - **Lines 143-196**: Simplify `migrate_existing_file_to_s3()` - single bucket only
   - **Remove**: Logic for copying between buckets
   - **Update**: S3 path construction to use only private bucket
   - **Add**: Textract job ID tracking in queue for async processing
   - **Add**: Status updates for long-running Textract jobs

## Textract API Field Definitions

### Input Parameters

#### StartDocumentTextDetection (Async) - Primary Method for PDFs
```python
{
    'DocumentLocation': {
        'S3Object': {
            'Bucket': str,  # S3 bucket name (e.g., 'samu-docs-private-upload')
            'Name': str,    # S3 object key (e.g., 'documents/uuid.pdf')
            'Version': str  # Optional: S3 object version for versioned buckets
        }
    },
    'ClientRequestToken': str,  # Optional: Idempotency token (use document UUID)
    'JobTag': str,             # Optional: Job identifier for tracking
    'NotificationChannel': {    # Optional: SNS notification for completion
        'SNSTopicArn': str,     # ARN of SNS topic for notifications
        'RoleArn': str          # IAM role ARN with SNS publish permissions
    },
    'OutputConfig': {          # Optional: Save results directly to S3
        'S3Bucket': str,        # Bucket for output (can be same as input)
        'S3Prefix': str         # Prefix for output files (e.g., 'textract-output/')
    },
    'KMSKeyId': str            # Optional: KMS key for encryption
}
```

#### AnalyzeDocument (Sync) - For Advanced Features
```python
{
    'Document': {
        'S3Object': {
            'Bucket': str,      # S3 bucket name
            'Name': str,        # S3 object key
            'Version': str      # Optional: specific version
        }
    },
    'FeatureTypes': [           # Required: at least one feature
        'TABLES',               # Extract tables with structure
        'FORMS',                # Extract key-value pairs from forms
        'SIGNATURES',           # Detect signature locations
        'LAYOUT'                # Analyze document layout and reading order
    ],
    'HumanLoopConfig': {        # Optional: Human-in-the-loop review
        'HumanLoopName': str,   # Unique name for the human loop
        'FlowDefinitionArn': str # ARN of the flow definition
    },
    'QueriesConfig': {          # Optional: Natural language queries
        'Queries': [
            {
                'Text': str,     # Query text (e.g., "What is the case number?")
                'Alias': str     # Optional alias for the query
            }
        ]
    }
}
```

### Output Response Structure

#### GetDocumentTextDetection Response - Complete Structure
```python
{
    'DocumentMetadata': {
        'Pages': int  # Number of pages processed
    },
    'JobStatus': str,  # IN_PROGRESS, SUCCEEDED, FAILED, PARTIAL_SUCCESS
    'NextToken': str,  # Pagination token
    'Blocks': [
        {
            'BlockType': str,  # PAGE, LINE, WORD, TABLE, CELL, KEY_VALUE_SET
            'Confidence': float,  # 0-100
            'Text': str,
            'Geometry': {
                'BoundingBox': {
                    'Width': float,
                    'Height': float,
                    'Left': float,
                    'Top': float
                },
                'Polygon': [
                    {'X': float, 'Y': float}
                ]
            },
            'Id': str,
            'Relationships': [
                {
                    'Type': str,  # CHILD, VALUE, COMPLEX_FEATURES
                    'Ids': [str]
                }
            ],
            'Page': int,
            'RowIndex': int,     # For table cells
            'ColumnIndex': int,  # For table cells
            'RowSpan': int,      # For merged cells
            'ColumnSpan': int    # For merged cells
        }
    ],
    'Warnings': [
        {
            'ErrorCode': str,
            'Pages': [int]
        }
    ],
    'StatusMessage': str
}
```

### Key Block Types - Detailed Descriptions

1. **PAGE**: Container for all content on a page
   - Contains all other blocks for that page
   - Provides page-level bounding box
   - Includes page number reference

2. **LINE**: A line of text
   - Contains multiple WORD blocks
   - Preserves reading order
   - Includes full line text and confidence

3. **WORD**: Individual word
   - Atomic text unit
   - Highest granularity for confidence scores
   - Used for precise text location

4. **TABLE**: Table structure
   - Contains CELL blocks
   - Preserves row/column relationships
   - Includes table-level confidence

5. **CELL**: Table cell
   - Contains text content of cell
   - Includes row/column indices
   - Supports merged cells (rowSpan/columnSpan)

6. **KEY_VALUE_SET**: Form field and value
   - Links form labels to values
   - Critical for legal forms processing
   - Maintains field relationships

7. **SELECTION_ELEMENT**: Checkbox or radio button
   - Indicates selected/unselected state
   - Common in legal forms
   - Includes confidence for selection state

### Confidence Scores - Interpretation and Usage

- **Score Range**: 0-100 (float values with decimal precision)
- **Production Threshold**: 80+ recommended for legal documents
- **Interpretation by Block Type**:
  - **WORD**: Confidence in character recognition accuracy
  - **LINE**: Average confidence of contained words
  - **TABLE**: Confidence in table structure detection
  - **CELL**: Confidence in cell boundary detection
  - **KEY_VALUE_SET**: Confidence in field-value association
- **Configurable Thresholds**:
  - High-quality scans: 85+ threshold
  - Poor quality/handwritten: 70+ threshold
  - Critical legal terms: 95+ threshold
- **Usage Pattern**:
  ```python
  if block['Confidence'] >= TEXTRACT_CONFIDENCE_THRESHOLD:
      # Process block
  else:
      # Flag for manual review
  ```

### Error Handling - Comprehensive Guide

#### Common Error Codes and Resolution
- **ProvisionedThroughputExceededException**: 
  - Cause: Rate limit exceeded (5 TPS for async, 1 TPS for sync)
  - Resolution: Implement exponential backoff, use SQS for rate limiting
  
- **InvalidS3ObjectException**: 
  - Cause: Cannot access S3 object due to permissions or non-existence
  - Resolution: Verify IAM role permissions, check S3 object exists
  
- **UnsupportedDocumentException**: 
  - Cause: File format not supported (only PDF, PNG, JPG, TIFF)
  - Resolution: Convert documents to supported format before processing
  
- **DocumentTooLargeException**: 
  - Cause: File exceeds size limit (500MB for async, 5MB for sync)
  - Resolution: Split large documents or compress images
  
- **BadDocumentException**: 
  - Cause: Corrupted, encrypted, or password-protected document
  - Resolution: Validate document integrity, remove encryption

#### Error Handling Strategy
```python
try:
    response = textract.start_document_text_detection(...)
except ClientError as e:
    error_code = e.response['Error']['Code']
    if error_code == 'ProvisionedThroughputExceededException':
        # Implement exponential backoff
        time.sleep(2 ** retry_count)
    elif error_code == 'InvalidS3ObjectException':
        # Log and skip document
        logger.error(f"Cannot access S3 object: {e}")
```

### Integration Considerations

1. **Asynchronous Processing - Detailed Implementation**
   - **When to use**: PDFs > 1 page or batch processing
   - **Start job**: `start_document_text_detection()` returns JobId
   - **Poll for results**: Call `get_document_text_detection()` with JobId
   - **Polling strategy**:
     ```python
     def poll_textract_job(job_id, max_attempts=60, initial_delay=5):
         delay = initial_delay
         for attempt in range(max_attempts):
             response = textract.get_document_text_detection(JobId=job_id)
             if response['JobStatus'] in ['SUCCEEDED', 'FAILED']:
                 return response
             time.sleep(delay)
             delay = min(delay * 1.5, 60)  # Exponential backoff, max 60s
     ```
   - **SNS Alternative**: Configure SNS topic for completion notifications

2. **Synchronous Processing - When Appropriate**
   - **Use cases**: Single-page documents, real-time requirements
   - **Limitations**: Maximum 1 page, 5MB file size
   - **Response time**: Typically 1-3 seconds
   - **Implementation**: Direct call to `detect_document_text()`

3. **Cost Optimization Strategies**
   - **Base OCR**: $1.50/1000 pages (DetectDocumentText)
   - **Tables**: $15/1000 pages (AnalyzeDocument with TABLES)
   - **Forms**: $50/1000 pages (AnalyzeDocument with FORMS)
   - **Optimization approaches**:
     - Use DetectDocumentText for simple text extraction
     - Enable TABLES only for documents with tabular data
     - Enable FORMS only for fillable forms
     - Batch process similar document types
     - Cache results to avoid reprocessing

4. **Output Processing - Block to Text Conversion**
   - **Reading order algorithm**:
     ```python
     def extract_text_from_blocks(blocks):
         # Group blocks by page
         pages = defaultdict(list)
         for block in blocks:
             if block['BlockType'] == 'LINE':
                 pages[block['Page']].append(block)
         
         # Sort by vertical position (top to bottom)
         for page_blocks in pages.values():
             page_blocks.sort(key=lambda b: b['Geometry']['BoundingBox']['Top'])
         
         # Extract text maintaining structure
         full_text = []
         for page_num in sorted(pages.keys()):
             page_text = '\n'.join([block['Text'] for block in pages[page_num]])
             full_text.append(page_text)
         
         return '\n\n'.join(full_text)
     ```
   - **Table extraction**: Parse CELL blocks using RowIndex/ColumnIndex
   - **Form extraction**: Match KEY blocks with VALUE blocks
   - **Maintain formatting**: Preserve line breaks and spacing

### Configuration Requirements - Complete Settings

```python
# New config.py additions - Replace Mistral configuration
# AWS Textract Configuration
AWS_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-2')

# Feature selection (comma-separated list)
TEXTRACT_FEATURE_TYPES = os.getenv('TEXTRACT_FEATURES', 'TABLES,FORMS').split(',')

# Confidence threshold for text acceptance (0-100)
TEXTRACT_CONFIDENCE_THRESHOLD = float(os.getenv('TEXTRACT_CONFIDENCE', '80'))

# Maximum results per page (for pagination)
TEXTRACT_MAX_RESULTS = int(os.getenv('TEXTRACT_MAX_RESULTS', '1000'))

# Use async processing for multi-page documents
TEXTRACT_USE_ASYNC = os.getenv('TEXTRACT_USE_ASYNC', 'true').lower() == 'true'

# Async job configuration
TEXTRACT_MAX_POLLING_TIME = int(os.getenv('TEXTRACT_MAX_POLLING_TIME', '300'))  # 5 minutes
TEXTRACT_POLLING_INTERVAL = int(os.getenv('TEXTRACT_POLLING_INTERVAL', '5'))   # 5 seconds

# SNS configuration for job notifications (optional)
TEXTRACT_SNS_TOPIC_ARN = os.getenv('TEXTRACT_SNS_TOPIC_ARN', '')
TEXTRACT_SNS_ROLE_ARN = os.getenv('TEXTRACT_SNS_ROLE_ARN', '')

# Cost control settings
TEXTRACT_ENABLE_TABLES = os.getenv('TEXTRACT_ENABLE_TABLES', 'true').lower() == 'true'
TEXTRACT_ENABLE_FORMS = os.getenv('TEXTRACT_ENABLE_FORMS', 'false').lower() == 'true'

# Output configuration
TEXTRACT_SAVE_RAW_RESPONSE = os.getenv('TEXTRACT_SAVE_RAW_RESPONSE', 'false').lower() == 'true'
TEXTRACT_OUTPUT_FORMAT = os.getenv('TEXTRACT_OUTPUT_FORMAT', 'text')  # text, json, or both

# Remove Mistral-specific configuration
# DELETE: MISTRAL_API_KEY, USE_MISTRAL_FOR_OCR, MISTRAL_OCR_MODEL, etc.
```

### Migration Path - Direct Replacement Strategy

1. **Phase 1**: Implement Textract and Remove Mistral
   - Create `textract_utils.py` with all necessary functions
   - Replace `extract_text_from_pdf_mistral_ocr()` with `extract_text_from_pdf_textract()`
   - Update all imports and function calls
   - Remove Mistral configuration variables
   - Delete `mistral_utils.py`
   - Test with sample documents

2. **Phase 2**: Simplify S3 Infrastructure
   - Remove public and temp bucket references
   - Update S3StorageManager to use single private bucket
   - Remove copy_to_public_bucket() and cleanup functions
   - Update queue processor for simplified flow

3. **Phase 3**: Production Deployment
   - Update environment variables
   - Apply configuration changes
   - Deploy updated code
   - Monitor for errors and performance

### IAM Policy Requirements for Textract

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "textract:StartDocumentTextDetection",
        "textract:GetDocumentTextDetection",
        "textract:AnalyzeDocument",
        "textract:DetectDocumentText"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion"
      ],
      "Resource": "arn:aws:s3:::samu-docs-private-upload/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sns:Publish"
      ],
      "Resource": "arn:aws:sns:*:*:textract-*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-2"
        }
      }
    }
  ]
}
```

### Summary of Benefits

This refactor would:
- **Eliminate** the need for public S3 buckets completely
- **Improve** security by keeping all documents private
- **Reduce** operational complexity from 3 buckets to 1
- **Provide** superior document intelligence capabilities
- **Maintain** compatibility with existing pipeline structure
- **Enable** advanced features like table and form extraction
- **Ensure** compliance with security standards
- **Simplify** error handling and monitoring
- **Reduce** overall infrastructure costs

The implementation is straightforward as Textract is designed as a drop-in replacement for OCR services, with the added benefit of structured data extraction capabilities that will enhance the legal document processing pipeline's effectiveness.