# Context 141: Photo & Image Document Handling Implementation

## Executive Summary

**Problem**: Photo files (.jpg, .heic, .png, .gif, .bmp, .tiff, .webp) are failing at OCR stage because they require visual analysis rather than text extraction. These documents need multimodal AI processing via OpenAI o4-mini-2025-04-16 to generate descriptive content.

**Solution**: Implement specialized photo processing pipeline that:
1. Detects image file types early in the pipeline
2. Routes images to OpenAI o4-mini-2025-04-16 instead of Textract
3. Generates structured descriptions with legal document context
4. Integrates descriptions into existing entity extraction and relationship building

## Current State Analysis

### Failing Documents Observed
From recent processing attempts, these photo formats are failing:
- `.jpg` - JPEG images (most common)
- `.heic` - iOS photo format
- `.png` - Portable Network Graphics
- Status: All showing `ocr_failed` in database

### Current Pipeline Flow Issues
```
Photo File → OCR Extraction → [FAILS] AWS Textract expects text documents
                            ↓
                     ocr_failed status
```

### Required New Flow
```
Photo File → Image Detection → OpenAI o4-mini-2025-04-16 → Description Text → Entity Extraction → Knowledge Graph
```

## Comprehensive Implementation Plan

### 1. File Type Detection Enhancement

#### Location: `scripts/ocr_extraction.py`
**Current Issue**: File type detection doesn't properly categorize images for special handling

**Required Changes**:
```python
# Add image file type constants
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.heif'}
DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', '.rtf', '.eml'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac'}

def detect_file_category(file_path: str) -> str:
    """Categorize file into image, document, or audio"""
    extension = Path(file_path).suffix.lower()
    
    if extension in IMAGE_EXTENSIONS:
        return 'image'
    elif extension in DOCUMENT_EXTENSIONS:
        return 'document'
    elif extension in AUDIO_EXTENSIONS:
        return 'audio'
    else:
        return 'unknown'
```

#### Database Schema Update
**New Migration Required**: `00018_add_file_category_field.sql`
```sql
ALTER TABLE source_documents 
ADD COLUMN file_category VARCHAR(20) DEFAULT 'document';

-- Update existing records
UPDATE source_documents 
SET file_category = CASE 
    WHEN LOWER(original_file_name) ~ '\.(jpg|jpeg|png|gif|bmp|tiff|tif|webp|heic|heif)$' THEN 'image'
    WHEN LOWER(original_file_name) ~ '\.(mp3|wav|m4a|aac|flac)$' THEN 'audio'
    ELSE 'document'
END;

-- Add index for performance
CREATE INDEX idx_source_documents_file_category ON source_documents(file_category);
```

### 2. OpenAI o4-mini Integration

#### New Module: `scripts/image_processing.py`
**Purpose**: Handle all image analysis using OpenAI o4-mini-2025-04-16

**Key Functions**:
```python
import base64
import requests
from pathlib import Path
from typing import Dict, Optional, Tuple
from scripts.config import get_config
from scripts.s3_storage import S3DocumentStorage

class ImageProcessor:
    """Process images using OpenAI o4-mini-2025-04-16"""
    
    def __init__(self):
        self.config = get_config()
        self.s3_storage = S3DocumentStorage()
        self.openai_api_key = self.config.get('OPENAI_API_KEY')
        
    def process_image(self, s3_key: str, file_name: str, project_context: str = None) -> Dict:
        """
        Process image using GPT-4 Vision to extract meaningful content
        
        Args:
            s3_key: S3 location of image
            file_name: Original filename for context
            project_context: Legal case context if available
            
        Returns:
            {
                'extracted_text': str,  # Generated description
                'confidence_score': float,  # Model confidence
                'image_type': str,  # Detected image type
                'entities_detected': List[str],  # Preliminary entity detection
                'processing_metadata': Dict
            }
        """
        
    def _download_image_from_s3(self, s3_key: str) -> bytes:
        """Download image from S3 for processing"""
        
    def _encode_image_base64(self, image_bytes: bytes) -> str:
        """Encode image as base64 for OpenAI API"""
        
    def _analyze_with_o4_mini(self, base64_image: str, context: str) -> Dict:
        """Send image to OpenAI o4-mini-2025-04-16 for analysis"""
        
    def _generate_legal_context_prompt(self, file_name: str, project_context: str = None) -> str:
        """Generate context-aware prompt for legal document analysis"""
```

#### Detailed o4-mini Vision Prompt Design
**Legal Document Context Prompt**:
```python
def _generate_legal_context_prompt(self, file_name: str, project_context: str = None) -> str:
    base_prompt = """
    You are analyzing an image from a legal case file. Please provide a detailed, structured description that would be useful for legal document processing and knowledge graph construction.

    Focus on:
    1. Document Type: What type of document/image is this? (photo, scan, diagram, screenshot, etc.)
    2. Text Content: Extract any visible text, including handwritten notes
    3. Legal Elements: Identify any legal forms, signatures, dates, case numbers, or legal terminology
    4. People: Names of individuals mentioned or visible
    5. Organizations: Company names, law firms, courts, or institutions
    6. Locations: Addresses, property descriptions, or geographic references
    7. Dates/Times: Any temporal information visible
    8. Physical Evidence: Description of any physical items, damage, or conditions shown
    9. Context Clues: What this image likely represents in a legal proceeding

    Format your response as structured text that can be processed for entity extraction.
    """
    
    if project_context:
        base_prompt += f"\n\nCase Context: {project_context}"
        
    base_prompt += f"\n\nFile Name: {file_name}"
    
    return base_prompt
```

### 3. Pipeline Integration Points

#### A. Celery Task Routing
**Location**: `scripts/celery_tasks/ocr_tasks.py`
**Current**: Single `process_ocr` task handles all files
**Required**: Split into specialized tasks

```python
# NEW TASK
@celery_app.task(bind=True, name='process_image')
def process_image(self, document_uuid: str, source_doc_sql_id: int, 
                 file_path: str, file_name: str, project_sql_id: int):
    """Process image files using OpenAI o4-mini-2025-04-16"""
    try:
        from scripts.image_processing import ImageProcessor
        processor = ImageProcessor()
        
        # Get project context
        project_context = self._get_project_context(project_sql_id)
        
        # Process image
        result = processor.process_image(file_path, file_name, project_context)
        
        # Update database with extracted content
        self._update_document_with_image_content(document_uuid, result)
        
        # Continue to text processing
        from scripts.celery_tasks.text_tasks import process_text_extraction
        process_text_extraction.delay(document_uuid, source_doc_sql_id, project_sql_id)
        
        return result
        
    except Exception as e:
        logger.error(f"Image processing failed for {document_uuid}: {e}")
        self._mark_document_failed(document_uuid, 'image_failed', str(e))
        raise

# MODIFIED TASK
@celery_app.task(bind=True, name='process_ocr')
def process_ocr(self, document_uuid: str, source_doc_sql_id: int, 
               file_path: str, file_name: str, detected_file_type: str, 
               project_sql_id: int):
    """Route to appropriate processing based on file type"""
    
    # Determine file category
    from scripts.ocr_extraction import detect_file_category
    file_category = detect_file_category(file_name)
    
    if file_category == 'image':
        # Route to image processing
        return process_image.delay(document_uuid, source_doc_sql_id, 
                                 file_path, file_name, project_sql_id)
    else:
        # Continue with existing text/document processing
        # ... existing logic ...
```

#### B. Document Submission Routing
**Location**: `scripts/celery_submission.py`
**Current**: All documents go to `process_ocr` task
**Required**: Route based on file category

```python
def submit_document_to_celery(
    document_id: int,
    document_uuid: str, 
    file_path: str,
    file_type: str,
    file_name: str,
    project_sql_id: int
) -> Tuple[str, bool]:
    """Submit document to appropriate Celery task based on file type"""
    
    try:
        # Determine file category
        from scripts.ocr_extraction import detect_file_category
        file_category = detect_file_category(file_name)
        
        # Update database with file category
        db = SupabaseManager()
        db.client.table('source_documents').update({
            'file_category': file_category
        }).eq('id', document_id).execute()
        
        # Route to appropriate task
        if file_category == 'image':
            from scripts.celery_tasks.ocr_tasks import process_image
            task = process_image.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=document_id,
                file_path=file_path,
                file_name=file_name,
                project_sql_id=project_sql_id
            )
            status = 'image_queued'
        else:
            # Existing logic for documents/audio
            from scripts.celery_tasks.ocr_tasks import process_ocr
            task = process_ocr.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=document_id,
                file_path=file_path,
                file_name=file_name,
                detected_file_type=file_type,
                project_sql_id=project_sql_id
            )
            status = 'ocr_queued'
        
        # Update with task ID
        db.client.table('source_documents').update({
            'celery_task_id': task.id,
            'celery_status': status,
            'initial_processing_status': status
        }).eq('id', document_id).execute()
        
        return task.id, True
        
    except Exception as e:
        logger.error(f"Failed to submit document to Celery: {e}")
        return None, False
```

### 4. Database Schema Enhancements

#### A. Status Field Updates
**Location**: `frontend/database/migrations/00018_add_image_processing_support.sql`

```sql
-- Add file category field
ALTER TABLE source_documents 
ADD COLUMN IF NOT EXISTS file_category VARCHAR(20) DEFAULT 'document';

-- Update status enums to include image processing
ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'image_queued';
ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'image_processing'; 
ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'image_completed';
ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'image_failed';

-- Add image processing metadata
ALTER TABLE source_documents 
ADD COLUMN IF NOT EXISTS image_analysis_confidence DECIMAL(3,2),
ADD COLUMN IF NOT EXISTS image_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS gpt4_vision_tokens_used INTEGER DEFAULT 0;

-- Create index for image processing queries
CREATE INDEX IF NOT EXISTS idx_source_documents_file_category ON source_documents(file_category);
CREATE INDEX IF NOT EXISTS idx_source_documents_image_status ON source_documents(celery_status) WHERE file_category = 'image';
```

#### B. Cost Tracking for o4-mini
**Location**: `scripts/config.py`
Add o4-mini-2025-04-16 pricing:

```python
# Add to STAGE_1_CONFIG
O4_MINI_VISION_PRICING = {
    'input_tokens_per_1k': 0.00015,  # $0.00015 per 1K input tokens
    'output_tokens_per_1k': 0.0006,  # $0.0006 per 1K output tokens  
    'image_base_cost': 0.00765,   # Base cost per image (standard vision pricing)
    'image_detail_high_cost': 0.01275,  # Additional cost for high detail
}
```

### 5. Testing Framework Updates

#### A. Image Processing Tests
**New File**: `tests/unit/test_image_processing.py`

```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from scripts.image_processing import ImageProcessor

class TestImageProcessor:
    
    @pytest.fixture
    def mock_s3_storage(self):
        with patch('scripts.image_processing.S3DocumentStorage') as mock:
            yield mock.return_value
    
    @pytest.fixture 
    def mock_openai_response(self):
        return {
            "choices": [{
                "message": {
                    "content": "This appears to be a scanned legal document..."
                }
            }],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200
            }
        }
    
    def test_process_image_success(self, mock_s3_storage, mock_openai_response):
        """Test successful image processing"""
        # Test implementation
        
    def test_process_image_with_legal_context(self):
        """Test image processing with legal case context"""
        # Test implementation
        
    def test_image_encoding(self):
        """Test base64 image encoding"""
        # Test implementation
```

#### B. Integration Tests
**New File**: `tests/integration/test_image_pipeline.py`

```python
class TestImagePipeline:
    
    def test_image_file_routing(self):
        """Test that image files are routed to correct processing"""
        
    def test_end_to_end_image_processing(self):
        """Test complete image processing pipeline"""
        
    def test_image_entity_extraction(self):
        """Test entity extraction from image descriptions"""
```

### 6. Monitoring & Debugging Enhancements

#### A. Pipeline Monitor Updates
**Location**: `scripts/standalone_pipeline_monitor.py`
Add image processing metrics:

```python
def _get_processing_stats(self):
    """Enhanced stats including image processing"""
    # Add image-specific queries
    image_stats = self.db_manager.client.table('source_documents')\
        .select('celery_status', count='exact')\
        .eq('file_category', 'image')\
        .execute()
    
    # Include in dashboard display
```

#### B. Cost Monitoring Updates
**Location**: `scripts/monitor_cache_performance.py`
Add GPT-4 Vision cost tracking:

```python
def _calculate_gpt4_vision_costs(self):
    """Calculate costs for GPT-4 Vision processing"""
    # Query gpt4_vision_tokens_used field
    # Apply pricing calculations
```

### 7. Error Handling & Recovery

#### A. Image Processing Failure Recovery
**Location**: `scripts/image_processing.py`

```python
class ImageProcessingError(Exception):
    """Custom exception for image processing failures"""
    pass

def handle_image_processing_failure(document_uuid: str, error: Exception):
    """Handle image processing failures with fallback options"""
    
    # Attempt fallback processing
    fallback_description = f"Image file: {file_name}. Processing failed with: {str(error)}"
    
    # Store minimal description to allow pipeline continuation
    db = SupabaseManager()
    db.client.table('source_documents').update({
        'extracted_text': fallback_description,
        'celery_status': 'image_failed_with_fallback',
        'error_details': str(error)
    }).eq('document_uuid', document_uuid).execute()
```

#### B. Retry Logic for Vision API
```python
def _call_o4_mini_with_retry(self, base64_image: str, prompt: str, max_retries: int = 3):
    """Call o4-mini-2025-04-16 with exponential backoff retry"""
    
    for attempt in range(max_retries):
        try:
            # Make API call
            return self._make_vision_api_call(base64_image, prompt)
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            else:
                raise ImageProcessingError(f"o4-mini-2025-04-16 failed after {max_retries} attempts: {e}")
```

## Implementation Priority & Timeline

### Phase 1: Core Image Processing (High Priority)
1. **Database migration** - Add file_category and image processing fields
2. **File type detection** - Enhance detection logic in ocr_extraction.py
3. **Basic o4-mini integration** - Create image_processing.py module
4. **Celery task routing** - Route images to new processing task

### Phase 2: Pipeline Integration (Medium Priority)  
1. **Update import script** - Ensure images are categorized correctly
2. **Cost tracking** - Add o4-mini cost calculations
3. **Status updates** - Update monitoring and status tracking
4. **Error handling** - Robust failure recovery

### Phase 3: Testing & Optimization (Lower Priority)
1. **Unit tests** - Comprehensive test coverage
2. **Integration tests** - End-to-end image processing tests
3. **Performance optimization** - Batch processing, caching
4. **Documentation** - User guides and troubleshooting

## Expected Outcomes

### Before Implementation
- Image files: `ocr_failed` status, no useful content extracted
- Pipeline stops at OCR stage for photos
- Manual intervention required for image-heavy legal cases

### After Implementation
- Image files: Processed with meaningful descriptions
- Legal entities extracted from image content (names, dates, locations)
- Photos integrated into knowledge graph with proper relationships
- Cost-effective processing using GPT-4 Vision

### Performance Metrics
- **Processing Success Rate**: Target 95%+ for image files
- **Entity Extraction Quality**: Should identify 80%+ of visible legal entities
- **Cost Efficiency**: Estimated $0.008-0.015 per image (significantly lower with o4-mini)
- **Processing Time**: 10-30 seconds per image vs. instant failure currently

## Testing Strategy

### Development Testing
1. **Single Image Test**: Process one image file through new pipeline
2. **Batch Image Test**: Process folder of mixed image types
3. **Integration Test**: Verify entity extraction and relationship building
4. **Cost Verification**: Confirm cost calculations are accurate

### Validation Criteria
1. ✅ Image files no longer show `ocr_failed` status
2. ✅ Meaningful descriptions extracted from legal document photos
3. ✅ Entity extraction identifies people, organizations, dates from images
4. ✅ Cost tracking accurately reflects o4-mini-2025-04-16 usage
5. ✅ Pipeline monitoring displays image processing metrics

## Files Requiring Modification

### Critical Files (Must Modify)
1. `scripts/ocr_extraction.py` - File type detection
2. `scripts/celery_tasks/ocr_tasks.py` - Task routing
3. `scripts/celery_submission.py` - Document submission routing
4. `frontend/database/migrations/00018_add_image_processing_support.sql` - Schema
5. `scripts/config.py` - o4-mini-2025-04-16 configuration

### New Files to Create
1. `scripts/image_processing.py` - Core image processing logic
2. `tests/unit/test_image_processing.py` - Unit tests
3. `tests/integration/test_image_pipeline.py` - Integration tests

### Supporting Files (Should Modify)
1. `scripts/standalone_pipeline_monitor.py` - Monitoring updates
2. `scripts/supabase_utils.py` - Database helpers for images
3. `scripts/import_from_manifest_fixed.py` - Import script updates

This comprehensive implementation will transform the pipeline from failing on image files to successfully processing them with meaningful legal content extraction, enabling full document coverage for legal case management.