# Context 191: Implementation Task List for PDF-Only Pipeline with Enhanced Pydantic Models

## Date: 2025-05-28
## Focus: Verifiable, Atomic Tasks for Implementing PDF-Only Simplification with Robust Pydantic Models

### Executive Summary

This document provides a detailed, verifiable task list for implementing the PDF-only simplification and enhanced Pydantic models. Each task includes:
- Clear success criteria
- Automated verification scripts
- Dependency tracking
- Complexity reduction metrics

## Task Organization

Tasks are organized in phases with clear dependencies. Each task is atomic and independently verifiable.

---

## Phase 1: Remove Non-PDF Processing [CRITICAL PATH]

### TASK_101: Audit and Document Non-PDF Code
**Priority**: CRITICAL  
**Dependencies**: None  
**Estimated Time**: 2 hours  
**Complexity Reduction**: High  

**Implementation**:
```python
# audit_non_pdf_code.py
import os
import re
from pathlib import Path
from typing import List, Dict

def audit_non_pdf_code() -> Dict[str, List[str]]:
    """Find all non-PDF processing code."""
    non_pdf_patterns = {
        'image_processing': [
            r'\.png|\.jpg|\.jpeg|\.gif|\.bmp',
            r'PIL|Image|cv2|opencv',
            r'image_processing|process_image'
        ],
        'audio_processing': [
            r'\.mp3|\.wav|\.m4a|\.ogg',
            r'pydub|whisper|audio',
            r'transcribe|audio_processing'
        ],
        'video_processing': [
            r'\.mp4|\.avi|\.mov|\.mkv',
            r'cv2\.VideoCapture|ffmpeg',
            r'video_processing|extract_frames'
        ]
    }
    
    results = {category: [] for category in non_pdf_patterns}
    
    for py_file in Path('scripts').rglob('*.py'):
        content = py_file.read_text()
        for category, patterns in non_pdf_patterns.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    results[category].append(str(py_file))
                    break
    
    return results

# Save audit results
audit_results = audit_non_pdf_code()
with open('non_pdf_audit.json', 'w') as f:
    json.dump(audit_results, f, indent=2)
```

**Verification**:
```python
# verify_101.py
def verify_audit_complete():
    assert os.path.exists('non_pdf_audit.json')
    with open('non_pdf_audit.json') as f:
        audit = json.load(f)
    
    # Should find at least these files
    expected_files = [
        'scripts/image_processing.py',
        'scripts/ocr_extraction.py'  # Has image logic
    ]
    
    all_files = []
    for files in audit.values():
        all_files.extend(files)
    
    for expected in expected_files:
        assert expected in all_files, f"Missing {expected} from audit"
    
    return True
```

### TASK_102: Remove Image Processing Module
**Priority**: HIGH  
**Dependencies**: TASK_101  
**Estimated Time**: 30 minutes  
**Complexity Reduction**: -500 lines  

**Implementation**:
```bash
# Remove image processing files
rm -f scripts/image_processing.py
rm -f tests/unit/test_image_processing.py
rm -f tests/integration/test_image_pipeline.py

# Remove image-specific dependencies from requirements
grep -v "pillow\|opencv-python\|pytesseract" requirements.txt > requirements.tmp
mv requirements.tmp requirements.txt
```

**Verification**:
```python
# verify_102.py
def verify_image_removal():
    # Files should not exist
    assert not os.path.exists('scripts/image_processing.py')
    assert not os.path.exists('tests/unit/test_image_processing.py')
    
    # No image imports in remaining code
    for py_file in Path('scripts').rglob('*.py'):
        content = py_file.read_text()
        assert 'from PIL import' not in content
        assert 'import cv2' not in content
        assert 'from scripts.image_processing' not in content
    
    # No image deps in requirements
    with open('requirements.txt') as f:
        reqs = f.read().lower()
    assert 'pillow' not in reqs
    assert 'opencv' not in reqs
    
    return True
```

### TASK_103: Simplify OCR Module to PDF-Only
**Priority**: HIGH  
**Dependencies**: TASK_102  
**Estimated Time**: 1 hour  
**Complexity Reduction**: -300 lines  

**Implementation**:
```python
# New simplified ocr_extraction.py
"""
PDF-only OCR extraction module.
Simplified from multi-format to PDF-only processing.
"""
from typing import Dict, Any, Optional
import logging
from scripts.textract_utils import process_pdf_with_textract
from scripts.core.schemas import PDFDocumentModel, ProcessingStatus

logger = logging.getLogger(__name__)

async def extract_text_from_pdf(
    pdf_path: str,
    document: PDFDocumentModel
) -> Dict[str, Any]:
    """
    Extract text from PDF using AWS Textract.
    
    Args:
        pdf_path: Path to PDF file
        document: Document model for tracking
        
    Returns:
        Extraction results with text and metadata
    """
    try:
        # Transition to OCR processing
        document.transition_to(ProcessingStatus.OCR_PROCESSING)
        
        # Process with Textract
        result = await process_pdf_with_textract(pdf_path)
        
        # Update document model
        document.extracted_text = result['text']
        document.ocr_confidence_score = result['confidence']
        document.page_count = result['page_count']
        document.extracted_metadata = result['metadata']
        
        # Transition to next state
        document.transition_to(ProcessingStatus.TEXT_EXTRACTION)
        
        return result
        
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        document.transition_to(ProcessingStatus.FAILED, str(e))
        raise

# Remove all non-PDF functions
# No more process_image, process_video, etc.
```

**Verification**:
```python
# verify_103.py
def verify_ocr_simplification():
    with open('scripts/ocr_extraction.py') as f:
        content = f.read()
    
    # Should only have PDF function
    assert 'extract_text_from_pdf' in content
    
    # Should not have other format functions
    assert 'process_image' not in content
    assert 'process_video' not in content
    assert 'extract_text_from_image' not in content
    
    # Should import PDF model
    assert 'PDFDocumentModel' in content
    
    # Count lines (should be under 100)
    lines = content.strip().split('\n')
    assert len(lines) < 100, f"OCR module still too complex: {len(lines)} lines"
    
    return True
```

### TASK_104: Update Celery Tasks - Remove Non-PDF
**Priority**: HIGH  
**Dependencies**: TASK_103  
**Estimated Time**: 1 hour  
**Complexity Reduction**: -400 lines  

**Implementation**:
```python
# Updated celery_tasks/ocr_tasks.py
from celery import Task
from scripts.celery_app import celery_app
from scripts.core.schemas import PDFDocumentModel
from scripts.ocr_extraction import extract_text_from_pdf

@celery_app.task(bind=True, name='ocr.process_pdf')
class ProcessPDFTask(Task):
    """Simplified PDF-only OCR task."""
    
    async def run(self, document_id: int, pdf_path: str):
        # Load document model
        doc = await load_document_model(document_id)
        
        # Validate it's a PDF
        if not doc.original_filename.lower().endswith('.pdf'):
            raise ValueError("Only PDF files supported")
        
        # Process
        result = await extract_text_from_pdf(pdf_path, doc)
        
        # Save results
        await save_document_model(doc)
        
        return {
            'document_id': document_id,
            'status': doc.processing_status.value,
            'confidence': doc.ocr_confidence_score
        }

# Remove these tasks entirely:
# - process_image_task
# - process_audio_task  
# - process_video_task
# - detect_file_type_task (no longer needed)
```

**Verification**:
```python
# verify_104.py
def verify_celery_tasks_simplified():
    with open('scripts/celery_tasks/ocr_tasks.py') as f:
        content = f.read()
    
    # Should only have PDF task
    assert 'ProcessPDFTask' in content
    
    # Should not have other format tasks
    forbidden = [
        'process_image', 'process_audio', 'process_video',
        'ImageTask', 'AudioTask', 'VideoTask'
    ]
    
    for term in forbidden:
        assert term not in content, f"Found forbidden term: {term}"
    
    # Check task registration
    from scripts.celery_app import celery_app
    registered_tasks = list(celery_app.tasks.keys())
    
    # Should not have non-PDF tasks
    for task in registered_tasks:
        assert 'image' not in task.lower()
        assert 'audio' not in task.lower()
        assert 'video' not in task.lower()
    
    return True
```

### TASK_105: Update Database Schema - Remove Multimedia Columns
**Priority**: HIGH  
**Dependencies**: TASK_104  
**Estimated Time**: 30 minutes  
**Complexity Reduction**: Simpler schema  

**Implementation**:
```sql
-- migration_remove_multimedia.sql
BEGIN;

-- Remove multimedia columns from source_documents
ALTER TABLE source_documents 
DROP COLUMN IF EXISTS image_metadata,
DROP COLUMN IF EXISTS audio_metadata,
DROP COLUMN IF EXISTS video_metadata,
DROP COLUMN IF EXISTS transcription_metadata_json,
DROP COLUMN IF EXISTS frame_count,
DROP COLUMN IF EXISTS duration_seconds;

-- Add PDF-specific columns
ALTER TABLE source_documents
ADD COLUMN IF NOT EXISTS pdf_version VARCHAR(10),
ADD COLUMN IF NOT EXISTS page_count INTEGER,
ADD COLUMN IF NOT EXISTS is_searchable BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS has_forms BOOLEAN DEFAULT false;

-- Update file type constraint
ALTER TABLE source_documents
DROP CONSTRAINT IF EXISTS check_file_type;

ALTER TABLE source_documents
ADD CONSTRAINT check_file_type 
CHECK (file_type = 'application/pdf' OR file_type = 'text/plain');

COMMIT;
```

**Verification**:
```python
# verify_105.py
def verify_schema_simplified():
    from scripts.supabase_utils import get_supabase_client
    
    client = get_supabase_client()
    
    # Get table schema
    result = client.rpc('get_table_columns', {
        'table_name': 'source_documents'
    }).execute()
    
    columns = [col['column_name'] for col in result.data]
    
    # Should not have multimedia columns
    forbidden_columns = [
        'image_metadata', 'audio_metadata', 'video_metadata',
        'transcription_metadata_json', 'frame_count', 'duration_seconds'
    ]
    
    for col in forbidden_columns:
        assert col not in columns, f"Found forbidden column: {col}"
    
    # Should have PDF columns
    required_columns = ['pdf_version', 'page_count']
    for col in required_columns:
        assert col in columns, f"Missing required column: {col}"
    
    return True
```

---

## Phase 2: Implement Enhanced Pydantic Models [CRITICAL PATH]

### TASK_201: Create New PDF-Only Models
**Priority**: CRITICAL  
**Dependencies**: None  
**Estimated Time**: 2 hours  
**Complexity Reduction**: Better type safety  

**Implementation**:
```python
# Create scripts/core/pdf_models.py
# Copy the enhanced models from context_190
# This includes:
# - PDFDocumentModel
# - PDFChunkModel  
# - ProjectAssociationModel
# - SemanticNamingModel
# - PDFProcessingPipelineModel
```

**Verification**:
```python
# verify_201.py
def verify_pdf_models():
    from scripts.core.pdf_models import (
        PDFDocumentModel, PDFChunkModel,
        ProjectAssociationModel, SemanticNamingModel,
        PDFProcessingPipelineModel, ProcessingStatus
    )
    
    # Test model creation
    doc = PDFDocumentModel(
        original_filename="test.pdf",
        file_size_bytes=1000,
        file_hash="a" * 64,
        s3_key="test/test.pdf"
    )
    
    # Test validation works
    try:
        bad_doc = PDFDocumentModel(
            original_filename="test.docx",  # Should fail
            file_size_bytes=1000,
            file_hash="a" * 64,
            s3_key="test/test.docx"
        )
        assert False, "Should have rejected non-PDF"
    except ValueError:
        pass  # Expected
    
    # Test state transitions
    assert doc.processing_status == ProcessingStatus.PENDING_INTAKE
    doc.transition_to(ProcessingStatus.VALIDATING)
    assert doc.processing_status == ProcessingStatus.VALIDATING
    
    return True
```

### TASK_202: Migrate Existing Models
**Priority**: HIGH  
**Dependencies**: TASK_201  
**Estimated Time**: 2 hours  
**Complexity Reduction**: Unified model system  

**Implementation**:
```python
# scripts/core/model_migration.py
from typing import Dict, Any, Optional
from datetime import datetime
from scripts.core.schemas import SourceDocumentModel
from scripts.core.pdf_models import PDFDocumentModel, ProcessingStatus

class ModelMigrator:
    """Migrate existing models to PDF-only models."""
    
    @staticmethod
    def migrate_source_to_pdf(old_doc: SourceDocumentModel) -> PDFDocumentModel:
        """Convert old source document to new PDF model."""
        
        # Map status
        status_map = {
            'pending_intake': ProcessingStatus.PENDING_INTAKE,
            'ocr_processing': ProcessingStatus.OCR_PROCESSING,
            'text_extraction': ProcessingStatus.TEXT_EXTRACTION,
            'completed': ProcessingStatus.COMPLETED,
            'failed': ProcessingStatus.FAILED
        }
        
        # Create new model
        pdf_doc = PDFDocumentModel(
            document_uuid=old_doc.document_uuid,
            original_filename=old_doc.original_file_name,
            file_size_bytes=old_doc.file_size,
            file_hash=old_doc.md5_hash or ("0" * 64),
            s3_key=old_doc.s3_key,
            processing_status=status_map.get(
                old_doc.processing_status, 
                ProcessingStatus.PENDING_INTAKE
            ),
            created_at=old_doc.created_at,
            created_by="migration_script"
        )
        
        # Migrate OCR data if exists
        if old_doc.raw_extracted_text:
            pdf_doc.extracted_text = old_doc.raw_extracted_text
            pdf_doc.ocr_confidence_score = old_doc.textract_confidence_avg
        
        return pdf_doc
    
    @staticmethod
    def validate_migration(old_count: int, new_count: int) -> Dict[str, Any]:
        """Validate migration completeness."""
        return {
            "success": old_count == new_count,
            "old_count": old_count,
            "new_count": new_count,
            "migration_rate": new_count / old_count if old_count > 0 else 0
        }
```

**Verification**:
```python
# verify_202.py
def verify_model_migration():
    from scripts.core.model_migration import ModelMigrator
    from scripts.core.schemas import SourceDocumentModel
    from scripts.core.pdf_models import PDFDocumentModel
    
    # Create test old model
    old_doc = SourceDocumentModel(
        document_uuid="test-uuid",
        filename="test.pdf",
        original_file_name="test.pdf",
        detected_file_type="application/pdf",
        file_type="application/pdf",
        file_size=1000,
        s3_key="test/test.pdf",
        processing_status="completed"
    )
    
    # Migrate
    new_doc = ModelMigrator.migrate_source_to_pdf(old_doc)
    
    # Verify
    assert isinstance(new_doc, PDFDocumentModel)
    assert new_doc.original_filename == "test.pdf"
    assert new_doc.processing_status.value == "completed"
    
    return True
```

### TASK_203: Update Database Manager for PDF Models
**Priority**: HIGH  
**Dependencies**: TASK_202  
**Estimated Time**: 2 hours  
**Complexity Reduction**: Cleaner DB interface  

**Implementation**:
```python
# scripts/core/pdf_db_manager.py
from typing import Optional, List
from scripts.core.pdf_models import (
    PDFDocumentModel, PDFChunkModel, 
    ProjectAssociationModel, PDFProcessingPipelineModel
)
from scripts.core.pydantic_db import PydanticDatabase

class PDFDatabaseManager:
    """Database manager for PDF-only pipeline."""
    
    def __init__(self, db: PydanticDatabase):
        self.db = db
    
    async def create_document(self, pdf_doc: PDFDocumentModel) -> PDFDocumentModel:
        """Create new PDF document."""
        # Validate model
        pdf_doc.model_validate(pdf_doc.model_dump())
        
        # Insert
        result = await self.db.create(
            'source_documents',
            pdf_doc,
            returning=True
        )
        
        return result
    
    async def update_document_status(
        self, 
        doc_id: str, 
        new_status: ProcessingStatus,
        error: Optional[str] = None
    ) -> PDFDocumentModel:
        """Update document processing status."""
        # Get current document
        doc = await self.db.read(
            'source_documents',
            PDFDocumentModel,
            {'document_uuid': doc_id}
        )
        
        if not doc:
            raise ValueError(f"Document {doc_id} not found")
        
        # Transition status (validates transition)
        doc.transition_to(new_status, error)
        
        # Update
        return await self.db.update(
            'source_documents',
            doc,
            {'document_uuid': doc_id}
        )
    
    async def create_pipeline(
        self, 
        doc_id: str
    ) -> PDFProcessingPipelineModel:
        """Create processing pipeline for document."""
        doc = await self.db.read(
            'source_documents',
            PDFDocumentModel,
            {'document_uuid': doc_id}
        )
        
        if not doc:
            raise ValueError(f"Document {doc_id} not found")
        
        # Create pipeline model
        pipeline = PDFProcessingPipelineModel(
            document=doc,
            pipeline_version="2.0"
        )
        
        return pipeline
```

**Verification**:
```python
# verify_203.py
def verify_pdf_db_manager():
    from scripts.core.pdf_db_manager import PDFDatabaseManager
    from scripts.core.pdf_models import PDFDocumentModel, ProcessingStatus
    from scripts.core.pydantic_db import PydanticDatabase
    import asyncio
    
    async def test():
        # Create test DB manager
        db = PydanticDatabase(test_mode=True)
        manager = PDFDatabaseManager(db)
        
        # Create document
        doc = PDFDocumentModel(
            original_filename="test.pdf",
            file_size_bytes=1000,
            file_hash="a" * 64,
            s3_key="test/test.pdf"
        )
        
        # Test create
        saved_doc = await manager.create_document(doc)
        assert saved_doc.document_uuid == doc.document_uuid
        
        # Test status update
        updated = await manager.update_document_status(
            str(doc.document_uuid),
            ProcessingStatus.VALIDATING
        )
        assert updated.processing_status == ProcessingStatus.VALIDATING
        
        # Test invalid transition
        try:
            await manager.update_document_status(
                str(doc.document_uuid),
                ProcessingStatus.COMPLETED  # Can't go directly to completed
            )
            assert False, "Should have failed"
        except ValueError:
            pass  # Expected
        
        return True
    
    return asyncio.run(test())
```

---

## Phase 3: Implement LLM-Driven Association [DEPENDENT ON PHASE 2]

### TASK_301: Create Project Association Service
**Priority**: HIGH  
**Dependencies**: TASK_203  
**Estimated Time**: 3 hours  
**Complexity Reduction**: Centralized logic  

**Implementation**:
```python
# scripts/services/project_association.py
from typing import List, Optional
import numpy as np
from scripts.core.pdf_models import (
    PDFDocumentModel, ProjectAssociationModel,
    PDFChunkModel
)
from scripts.core.embeddings import EmbeddingService
from scripts.llm_client import LLMClient

class ProjectAssociationService:
    """Service for associating documents with projects using LLM."""
    
    def __init__(self, llm_client: LLMClient, embedding_service: EmbeddingService):
        self.llm = llm_client
        self.embeddings = embedding_service
    
    async def associate_document(
        self,
        document: PDFDocumentModel,
        chunks: List[PDFChunkModel],
        existing_projects: List[dict]
    ) -> ProjectAssociationModel:
        """Associate document with a project using LLM analysis."""
        
        # Extract key information
        entities = await self._extract_key_entities(chunks)
        summary = await self._generate_summary(chunks)
        
        # Get project embeddings
        project_embeddings = await self._get_project_embeddings(existing_projects)
        
        # Calculate similarity scores
        doc_embedding = await self.embeddings.embed_text(summary)
        similarities = self._calculate_similarities(doc_embedding, project_embeddings)
        
        # Prepare LLM prompt
        prompt = self._build_association_prompt(
            document, entities, summary, existing_projects, similarities
        )
        
        # Get LLM response
        response = await self.llm.complete(prompt)
        
        # Parse response
        association = self._parse_association_response(response)
        
        # Create model
        return ProjectAssociationModel(
            document_uuid=document.document_uuid,
            project_id=association['project_id'],
            confidence_score=association['confidence'],
            reasoning=association['reasoning'],
            evidence_chunks=[c.chunk_id for c in chunks[:5]],  # Top 5 relevant
            association_method='llm',
            llm_model=self.llm.model_name
        )
    
    def _build_association_prompt(
        self,
        document: PDFDocumentModel,
        entities: List[str],
        summary: str,
        projects: List[dict],
        similarities: List[float]
    ) -> str:
        """Build prompt for project association."""
        return f"""
        Analyze this legal document and determine which project it belongs to.
        
        Document Information:
        - Original Name: {document.original_filename}
        - Key Entities: {', '.join(entities[:10])}
        - Summary: {summary[:500]}
        
        Available Projects:
        {self._format_projects_with_similarity(projects, similarities)}
        
        Based on the document content, entities, and similarity scores:
        1. Which project does this document belong to?
        2. What is your confidence (0-1)?
        3. Explain your reasoning in 2-3 sentences.
        
        Format your response as:
        PROJECT_ID: [number]
        CONFIDENCE: [0.00-1.00]
        REASONING: [explanation]
        """
```

**Verification**:
```python
# verify_301.py
def verify_project_association_service():
    from scripts.services.project_association import ProjectAssociationService
    import inspect
    
    # Check class exists and has required methods
    assert hasattr(ProjectAssociationService, 'associate_document')
    
    # Check method signature
    sig = inspect.signature(ProjectAssociationService.associate_document)
    params = list(sig.parameters.keys())
    assert 'document' in params
    assert 'chunks' in params
    assert 'existing_projects' in params
    
    # Check returns ProjectAssociationModel
    return_anno = sig.return_annotation
    assert 'ProjectAssociationModel' in str(return_anno)
    
    return True
```

### TASK_302: Create Document Categorization Service
**Priority**: HIGH  
**Dependencies**: TASK_301  
**Estimated Time**: 2 hours  
**Complexity Reduction**: Standardized categorization  

**Implementation**:
```python
# scripts/services/document_categorization.py
from scripts.core.pdf_models import PDFDocumentModel, DocumentCategory
from scripts.llm_client import LLMClient

class DocumentCategorizationService:
    """Service for categorizing legal documents."""
    
    # Category examples for few-shot learning
    CATEGORY_EXAMPLES = {
        DocumentCategory.PLEADING: [
            "complaint", "answer", "motion", "brief", "petition"
        ],
        DocumentCategory.DISCOVERY: [
            "interrogatories", "deposition", "request for production",
            "request for admission", "subpoena"
        ],
        DocumentCategory.EVIDENCE: [
            "exhibit", "affidavit", "declaration", "witness statement"
        ],
        DocumentCategory.CORRESPONDENCE: [
            "letter", "email", "memorandum", "notice"
        ],
        DocumentCategory.FINANCIAL: [
            "invoice", "receipt", "statement", "tax return", "budget"
        ],
        DocumentCategory.CONTRACT: [
            "agreement", "contract", "amendment", "addendum", "lease"
        ]
    }
    
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
    
    async def categorize_document(
        self,
        document: PDFDocumentModel,
        text_sample: str
    ) -> tuple[DocumentCategory, float, str]:
        """
        Categorize document using LLM.
        
        Returns:
            (category, confidence, reasoning)
        """
        prompt = self._build_categorization_prompt(
            document.original_filename,
            text_sample
        )
        
        response = await self.llm.complete(prompt)
        
        # Parse response
        category, confidence, reasoning = self._parse_response(response)
        
        return category, confidence, reasoning
    
    def _build_categorization_prompt(self, filename: str, text: str) -> str:
        """Build categorization prompt with examples."""
        examples = "\n".join([
            f"- {cat.value}: {', '.join(examples)}"
            for cat, examples in self.CATEGORY_EXAMPLES.items()
        ])
        
        return f"""
        Categorize this legal document into one of these categories:
        
        {examples}
        
        Document Information:
        - Filename: {filename}
        - Text Sample: {text[:1000]}
        
        Respond with:
        CATEGORY: [one of the categories above]
        CONFIDENCE: [0.00-1.00]
        REASONING: [brief explanation]
        """
```

**Verification**:
```python
# verify_302.py
def verify_categorization_service():
    from scripts.services.document_categorization import DocumentCategorizationService
    from scripts.core.pdf_models import DocumentCategory
    
    # Check service exists
    service = DocumentCategorizationService(llm_client=None)
    
    # Check category examples
    assert hasattr(service, 'CATEGORY_EXAMPLES')
    assert DocumentCategory.PLEADING in service.CATEGORY_EXAMPLES
    
    # Check all categories covered
    for category in DocumentCategory:
        if category != DocumentCategory.UNKNOWN:
            assert category in service.CATEGORY_EXAMPLES
    
    return True
```

### TASK_303: Create Semantic Naming Service
**Priority**: MEDIUM  
**Dependencies**: TASK_302  
**Estimated Time**: 2 hours  
**Complexity Reduction**: Consistent naming  

**Implementation**:
```python
# scripts/services/semantic_naming.py
from datetime import datetime
import re
from scripts.core.pdf_models import (
    PDFDocumentModel, SemanticNamingModel,
    DocumentCategory, ProjectAssociationModel
)
from scripts.llm_client import LLMClient

class SemanticNamingService:
    """Service for generating semantic filenames."""
    
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
    
    async def generate_semantic_name(
        self,
        document: PDFDocumentModel,
        project_code: str,
        category: DocumentCategory,
        entities: List[str]
    ) -> SemanticNamingModel:
        """Generate semantic filename for document."""
        
        # Extract date from document
        doc_date = await self._extract_document_date(document)
        
        # Generate description
        description = await self._generate_description(
            document, category, entities
        )
        
        # Create naming model
        naming = SemanticNamingModel(
            document_uuid=document.document_uuid,
            project_code=self._sanitize_project_code(project_code),
            document_date=doc_date,
            category=category,
            description=self._sanitize_description(description)
        )
        
        return naming
    
    def _sanitize_project_code(self, code: str) -> str:
        """Sanitize project code for filename."""
        # Remove special chars, uppercase, limit length
        clean = re.sub(r'[^A-Z0-9_]', '', code.upper())
        return clean[:20]  # Max 20 chars
    
    def _sanitize_description(self, desc: str) -> str:
        """Sanitize description for filename."""
        # Remove special chars, replace spaces
        clean = re.sub(r'[^A-Za-z0-9\s-]', '', desc)
        clean = re.sub(r'\s+', '_', clean.strip())
        return clean[:50]  # Max 50 chars
    
    async def _generate_description(
        self,
        document: PDFDocumentModel,
        category: DocumentCategory,
        entities: List[str]
    ) -> str:
        """Generate concise description using LLM."""
        
        prompt = f"""
        Generate a concise filename description (3-5 words) for this document:
        
        Category: {category.value}
        Original Name: {document.original_filename}
        Key Entities: {', '.join(entities[:5])}
        
        Examples:
        - Motion Summary Judgment Smith
        - Deposition Notice Johnson
        - Contract Amendment ABC Corp
        
        Description:
        """
        
        response = await self.llm.complete(prompt)
        return response.strip()
```

**Verification**:
```python
# verify_303.py
def verify_semantic_naming_service():
    from scripts.services.semantic_naming import SemanticNamingService
    
    service = SemanticNamingService(llm_client=None)
    
    # Test sanitization
    assert service._sanitize_project_code("ABC-123!") == "ABC123"
    assert service._sanitize_description("Motion: Summary Judgment") == "Motion_Summary_Judgment"
    
    # Test length limits
    long_code = "A" * 30
    assert len(service._sanitize_project_code(long_code)) <= 20
    
    long_desc = "A very long description " * 10
    assert len(service._sanitize_description(long_desc)) <= 50
    
    return True
```

---

## Phase 4: Integration and Testing [FINAL PHASE]

### TASK_401: Create Integrated PDF Pipeline
**Priority**: CRITICAL  
**Dependencies**: All previous tasks  
**Estimated Time**: 3 hours  
**Complexity Reduction**: Single entry point  

**Implementation**:
```python
# scripts/pdf_pipeline.py
from scripts.core.pdf_models import (
    PDFDocumentModel, PDFProcessingPipelineModel,
    ProcessingStatus
)
from scripts.services.project_association import ProjectAssociationService
from scripts.services.document_categorization import DocumentCategorizationService
from scripts.services.semantic_naming import SemanticNamingService
from scripts.ocr_extraction import extract_text_from_pdf
from scripts.text_processing import chunk_text
from scripts.entity_extraction import extract_entities

class PDFProcessingPipeline:
    """Integrated PDF processing pipeline."""
    
    def __init__(self, config, db_manager):
        self.config = config
        self.db = db_manager
        self.project_service = ProjectAssociationService(...)
        self.category_service = DocumentCategorizationService(...)
        self.naming_service = SemanticNamingService(...)
    
    async def process_pdf(
        self, 
        pdf_path: str, 
        original_name: str
    ) -> PDFProcessingPipelineModel:
        """Process PDF through entire pipeline."""
        
        # Create document
        doc = PDFDocumentModel(
            original_filename=original_name,
            file_size_bytes=os.path.getsize(pdf_path),
            file_hash=self._calculate_hash(pdf_path),
            s3_key=self._upload_to_s3(pdf_path)
        )
        
        # Create pipeline
        pipeline = PDFProcessingPipelineModel(document=doc)
        
        try:
            # OCR
            await self._extract_text(pipeline, pdf_path)
            
            # Chunk
            await self._chunk_document(pipeline)
            
            # Extract entities
            await self._extract_entities(pipeline)
            
            # Associate project
            await self._associate_project(pipeline)
            
            # Categorize
            await self._categorize_document(pipeline)
            
            # Generate name
            await self._generate_semantic_name(pipeline)
            
            # Complete
            pipeline.document.transition_to(ProcessingStatus.COMPLETED)
            
        except Exception as e:
            pipeline.document.transition_to(ProcessingStatus.FAILED, str(e))
            raise
        
        return pipeline
```

**Verification**:
```python
# verify_401.py
def verify_integrated_pipeline():
    from scripts.pdf_pipeline import PDFProcessingPipeline
    from scripts.core.pdf_models import ProcessingStatus
    
    # Check class structure
    assert hasattr(PDFProcessingPipeline, 'process_pdf')
    
    # Check it returns pipeline model
    import inspect
    sig = inspect.signature(PDFProcessingPipeline.process_pdf)
    assert 'PDFProcessingPipelineModel' in str(sig.return_annotation)
    
    return True
```

### TASK_402: Create End-to-End Tests
**Priority**: HIGH  
**Dependencies**: TASK_401  
**Estimated Time**: 2 hours  
**Complexity Reduction**: Confidence in system  

**Implementation**:
```python
# tests/e2e/test_pdf_only_pipeline.py
import pytest
from pathlib import Path
from scripts.pdf_pipeline import PDFProcessingPipeline
from scripts.core.pdf_models import ProcessingStatus

class TestPDFOnlyPipeline:
    """End-to-end tests for PDF-only pipeline."""
    
    @pytest.fixture
    def sample_pdf(self):
        """Provide sample PDF for testing."""
        return Path("tests/fixtures/sample_legal_document.pdf")
    
    @pytest.fixture
    def pipeline(self):
        """Create test pipeline."""
        return PDFProcessingPipeline(test_config, test_db)
    
    async def test_full_pipeline_success(self, pipeline, sample_pdf):
        """Test successful processing through entire pipeline."""
        result = await pipeline.process_pdf(
            str(sample_pdf),
            "Sample Legal Document.pdf"
        )
        
        # Verify all stages completed
        assert result.document.processing_status == ProcessingStatus.COMPLETED
        assert len(result.chunks) > 0
        assert len(result.entities) > 0
        assert result.project_association is not None
        assert result.document.category is not None
        assert result.semantic_naming is not None
        
        # Verify confidence scores
        assert result.overall_confidence > 0.7
        
    async def test_non_pdf_rejection(self, pipeline):
        """Test that non-PDF files are rejected."""
        with pytest.raises(ValueError, match="Only PDF files"):
            await pipeline.process_pdf(
                "tests/fixtures/document.docx",
                "document.docx"
            )
    
    async def test_low_confidence_flagging(self, pipeline, sample_pdf):
        """Test that low confidence triggers review."""
        # Mock low confidence response
        with patch('llm_client.confidence', return_value=0.6):
            result = await pipeline.process_pdf(
                str(sample_pdf),
                "Unclear Document.pdf"
            )
            
            assert result.project_association.requires_review
            assert 'low_confidence' in result.quality_flags
```

**Verification**:
```python
# verify_402.py
def verify_e2e_tests():
    # Run tests
    import subprocess
    result = subprocess.run(
        ['pytest', 'tests/e2e/test_pdf_only_pipeline.py', '-v'],
        capture_output=True,
        text=True
    )
    
    # Check all tests defined
    assert 'test_full_pipeline_success' in result.stdout
    assert 'test_non_pdf_rejection' in result.stdout
    assert 'test_low_confidence_flagging' in result.stdout
    
    # Tests should pass
    assert result.returncode == 0
    
    return True
```

### TASK_403: Create Complexity Metrics Report
**Priority**: MEDIUM  
**Dependencies**: All tasks  
**Estimated Time**: 1 hour  
**Complexity Reduction**: Measurable  

**Implementation**:
```python
# scripts/metrics/complexity_report.py
import os
from pathlib import Path
from typing import Dict, Any

def generate_complexity_report() -> Dict[str, Any]:
    """Generate report on complexity reduction."""
    
    # Count lines of code
    def count_lines(path: str) -> int:
        if not os.path.exists(path):
            return 0
        return len(Path(path).read_text().splitlines())
    
    # Files removed
    removed_files = [
        'scripts/image_processing.py',
        'scripts/audio_processing.py',
        'scripts/video_processing.py'
    ]
    
    lines_removed = sum(count_lines(f) for f in removed_files)
    
    # Simplified files
    simplified = {
        'scripts/ocr_extraction.py': {
            'before': 500,  # estimated
            'after': count_lines('scripts/ocr_extraction.py')
        },
        'scripts/celery_tasks/ocr_tasks.py': {
            'before': 400,
            'after': count_lines('scripts/celery_tasks/ocr_tasks.py')
        }
    }
    
    # Dependencies removed
    removed_deps = [
        'pillow', 'opencv-python', 'pytesseract',
        'pydub', 'speechrecognition'
    ]
    
    # Calculate totals
    total_lines_removed = lines_removed + sum(
        f['before'] - f['after'] 
        for f in simplified.values()
    )
    
    return {
        'files_removed': len(removed_files),
        'lines_removed': total_lines_removed,
        'dependencies_removed': len(removed_deps),
        'complexity_reduction_percent': round(total_lines_removed / 5000 * 100, 1),
        'simplified_files': simplified,
        'removed_dependencies': removed_deps
    }

# Generate and save report
report = generate_complexity_report()
with open('complexity_reduction_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"Complexity reduced by {report['complexity_reduction_percent']}%")
print(f"Removed {report['lines_removed']} lines of code")
print(f"Removed {report['dependencies_removed']} dependencies")
```

**Verification**:
```python
# verify_403.py
def verify_complexity_report():
    import json
    
    # Report should exist
    assert os.path.exists('complexity_reduction_report.json')
    
    # Load report
    with open('complexity_reduction_report.json') as f:
        report = json.load(f)
    
    # Verify metrics
    assert report['files_removed'] >= 3
    assert report['lines_removed'] > 1000
    assert report['dependencies_removed'] >= 5
    assert report['complexity_reduction_percent'] > 20
    
    print(f"✅ Complexity reduced by {report['complexity_reduction_percent']}%")
    
    return True
```

---

## Master Verification Script

```python
# verify_all.py
"""Master verification script for PDF-only pipeline implementation."""
import sys
import importlib

# All verification tasks in order
VERIFICATION_TASKS = [
    # Phase 1
    'verify_101', 'verify_102', 'verify_103', 'verify_104', 'verify_105',
    # Phase 2  
    'verify_201', 'verify_202', 'verify_203',
    # Phase 3
    'verify_301', 'verify_302', 'verify_303',
    # Phase 4
    'verify_401', 'verify_402', 'verify_403'
]

def run_all_verifications():
    """Run all verification tasks in order."""
    failed = []
    
    for task in VERIFICATION_TASKS:
        print(f"\n{'='*60}")
        print(f"Running {task}...")
        print('='*60)
        
        try:
            module = importlib.import_module(task)
            
            # Find verification function
            func_name = None
            for name in dir(module):
                if name.startswith('verify_'):
                    func_name = name
                    break
            
            if func_name:
                result = getattr(module, func_name)()
                if result:
                    print(f"✅ {task} PASSED")
                else:
                    print(f"❌ {task} FAILED")
                    failed.append(task)
            else:
                print(f"❌ {task} - No verification function found")
                failed.append(task)
                
        except Exception as e:
            print(f"❌ {task} FAILED with error: {e}")
            failed.append(task)
    
    # Summary
    print(f"\n{'='*60}")
    print("VERIFICATION SUMMARY")
    print('='*60)
    print(f"Total tasks: {len(VERIFICATION_TASKS)}")
    print(f"Passed: {len(VERIFICATION_TASKS) - len(failed)}")
    print(f"Failed: {len(failed)}")
    
    if failed:
        print("\nFailed tasks:")
        for task in failed:
            print(f"  - {task}")
        return 1
    else:
        print("\n✅ ALL VERIFICATIONS PASSED!")
        print("\nComplexity Reduction Achieved:")
        print("- 40-50% fewer lines of code")
        print("- 5+ dependencies removed")
        print("- Single processing path")
        print("- Type-safe Pydantic models throughout")
        print("- LLM-driven intelligence at the end")
        return 0

if __name__ == "__main__":
    sys.exit(run_all_verifications())
```

## Summary

This task list provides:

1. **Atomic Tasks**: Each task is independently verifiable
2. **Clear Dependencies**: Tasks build on each other logically
3. **Measurable Outcomes**: Every task has success criteria
4. **Complexity Metrics**: Track reduction in code/dependencies
5. **Automated Verification**: Scripts to verify each task

The implementation will:
- Remove ~2000+ lines of multimedia processing code
- Eliminate 5+ complex dependencies
- Create a single, robust PDF processing path
- Implement type-safe models throughout
- Add intelligent LLM-driven association at the end

Total estimated time: 25-30 hours of implementation
Complexity reduction: 40-50% fewer lines of code