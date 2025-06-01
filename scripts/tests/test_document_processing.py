#!/usr/bin/env python3
"""
End-to-end document processing test with schema validation at each stage.
"""

import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.pdf_tasks import process_pdf_document
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.monitoring.cloudwatch_logger import get_cloudwatch_logger
import logging

# Enhanced logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class DocumentProcessingTester:
    """Test document processing with schema validation."""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.redis = get_redis_manager()
        self.test_doc_path = "/tmp/test_schema.pdf"
        self.project_uuid = str(uuid.uuid4())
        
    def create_test_pdf(self):
        """Create a simple test PDF."""
        try:
            # Create test content
            test_content = """
# Legal Document Test

This is a test legal document for schema alignment testing.

## Parties Involved
- John Doe (Plaintiff)
- Jane Smith (Defendant)
- Acme Corporation

## Key Dates
- Filing Date: January 15, 2024
- Hearing Date: March 1, 2024

## Legal References
- Case No. 2024-CV-001234
- Statute: 42 U.S.C. § 1983

This document is for testing purposes only.
"""
            
            # Save as text file first
            with open('/tmp/test_content.txt', 'w') as f:
                f.write(test_content)
            
            # Convert to PDF using available tools
            import subprocess
            
            # Try different PDF creation methods
            methods = [
                # Method 1: Using pandoc if available
                ['pandoc', '-f', 'markdown', '-t', 'pdf', '-o', self.test_doc_path, '/tmp/test_content.txt'],
                # Method 2: Using Python reportlab
                None  # Will implement inline if needed
            ]
            
            for method in methods:
                if method:
                    try:
                        result = subprocess.run(method, capture_output=True, text=True)
                        if result.returncode == 0 and Path(self.test_doc_path).exists():
                            logger.info(f"Created test PDF using {method[0]}")
                            return True
                    except FileNotFoundError:
                        continue
            
            # Fallback: Create using Python
            try:
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter
                
                c = canvas.Canvas(self.test_doc_path, pagesize=letter)
                width, height = letter
                
                # Add content
                y = height - 50
                for line in test_content.split('\n'):
                    if line.strip():
                        c.drawString(50, y, line)
                        y -= 20
                
                c.save()
                logger.info("Created test PDF using reportlab")
                return True
                
            except ImportError:
                # Final fallback: create a minimal PDF
                # This creates a valid but minimal PDF
                minimal_pdf = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources 4 0 R /MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n4 0 obj\n<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>\nendobj\n5 0 obj\n<< /Length 44 >>\nstream\nBT\n/F1 12 Tf\n50 750 Td\n(Test Document) Tj\nET\nendstream\nendobj\nxref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000229 00000 n \n0000000328 00000 n \ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n426\n%%EOF'
                
                with open(self.test_doc_path, 'wb') as f:
                    f.write(minimal_pdf)
                
                logger.info("Created minimal test PDF")
                return True
                
        except Exception as e:
            logger.error(f"Failed to create test PDF: {e}")
            return False
        
    def test_synchronous_processing(self):
        """Test processing without Celery (for debugging)."""
        logger.info("Starting synchronous processing test")
        
        try:
            # Create test PDF
            if not self.create_test_pdf():
                logger.error("Failed to create test PDF")
                return False
                
            # Upload test document
            from scripts.s3_storage import S3StorageManager
            s3_manager = S3StorageManager()
            
            doc_uuid = str(uuid.uuid4())
            s3_key = s3_manager.upload_document_with_uuid_naming(
                self.test_doc_path, 
                doc_uuid,
                'pdf'
            )
            
            logger.info(f"Uploaded to S3: {s3_key}")
            
            # Create document entry
            from scripts.core.schemas import SourceDocumentModel
            doc_model = SourceDocumentModel(
                document_uuid=uuid.UUID(doc_uuid),
                original_file_name="test_schema.pdf",
                detected_file_type="application/pdf",
                s3_bucket=s3_manager.bucket_name,
                s3_key=s3_key,
                file_size_bytes=Path(self.test_doc_path).stat().st_size,
                project_uuid=self.project_uuid,
                initial_processing_status="pending"
            )
            
            # Insert to database
            result = self.db.create_source_document(doc_model)
            logger.info(f"Created document: {result.document_uuid}")
            
            # Process each stage manually
            stages = [
                ("OCR", self._test_ocr_stage),
                ("Text Chunking", self._test_text_stage),
                ("Entity Extraction", self._test_entity_stage),
                ("Graph Building", self._test_graph_stage)
            ]
            
            for stage_name, stage_func in stages:
                logger.info(f"\n{'='*40}")
                logger.info(f"Testing {stage_name}")
                logger.info(f"{'='*40}")
                
                success = stage_func(doc_uuid)
                if not success:
                    logger.error(f"{stage_name} failed!")
                    return False
                    
                # Verify schema after each stage
                self._verify_schema_state(doc_uuid, stage_name)
            
            return True
            
        except Exception as e:
            logger.exception("Synchronous processing failed")
            return False
    
    def _test_ocr_stage(self, doc_uuid: str) -> bool:
        """Test OCR extraction."""
        try:
            from scripts.pdf_tasks import extract_text_from_document
            
            # Mock task context
            class MockTask:
                request = type('Request', (), {'id': 'test-task'})()
                name = 'test_ocr'
            
            # Get S3 path
            doc = self.db.get_source_document(doc_uuid)
            s3_path = f"s3://{doc.s3_bucket}/{doc.s3_key}"
            
            # Run OCR
            result = extract_text_from_document(
                MockTask(),
                document_uuid=doc_uuid,
                file_path=s3_path
            )
            
            logger.info(f"OCR Result: {result.get('status')}")
            return result.get('status') == 'success'
            
        except Exception as e:
            logger.exception("OCR stage failed")
            return False
    
    def _test_text_stage(self, doc_uuid: str) -> bool:
        """Test text chunking."""
        try:
            from scripts.pdf_tasks import chunk_document_text
            
            class MockTask:
                request = type('Request', (), {'id': 'test-task'})()
                name = 'test_chunk'
            
            result = chunk_document_text(
                MockTask(),
                document_uuid=doc_uuid
            )
            
            logger.info(f"Chunking Result: {result.get('status')}")
            return result.get('status') == 'success'
            
        except Exception as e:
            logger.exception("Text chunking stage failed")
            return False
    
    def _test_entity_stage(self, doc_uuid: str) -> bool:
        """Test entity extraction."""
        try:
            from scripts.pdf_tasks import extract_entities_from_chunks
            
            class MockTask:
                request = type('Request', (), {'id': 'test-task'})()
                name = 'test_entity'
            
            result = extract_entities_from_chunks(
                MockTask(),
                document_uuid=doc_uuid
            )
            
            logger.info(f"Entity extraction Result: {result.get('status')}")
            return result.get('status') == 'success'
            
        except Exception as e:
            logger.exception("Entity extraction stage failed")
            return False
    
    def _test_graph_stage(self, doc_uuid: str) -> bool:
        """Test graph building."""
        try:
            from scripts.pdf_tasks import build_document_relationships
            
            class MockTask:
                request = type('Request', (), {'id': 'test-task'})()
                name = 'test_graph'
            
            result = build_document_relationships(
                MockTask(),
                document_uuid=doc_uuid
            )
            
            logger.info(f"Graph building Result: {result.get('status')}")
            return result.get('status') == 'success'
            
        except Exception as e:
            logger.exception("Graph building stage failed")
            return False
    
    def _verify_schema_state(self, doc_uuid: str, stage: str):
        """Verify schema consistency after each stage."""
        logger.info(f"Verifying schema state after {stage}")
        
        from scripts.rds_utils import execute_query
        
        # Check document status
        doc_check = execute_query(
            "SELECT status, metadata FROM documents WHERE id = :uuid",
            {"uuid": doc_uuid}
        )
        
        if doc_check:
            logger.info(f"  Document status: {doc_check[0]['status']}")
        
        # Check related records
        counts = {
            'chunks': execute_query(
                "SELECT COUNT(*) as cnt FROM chunks WHERE document_uuid = :uuid",
                {"uuid": doc_uuid}
            ),
            'entities': execute_query(
                "SELECT COUNT(*) as cnt FROM entities WHERE document_uuid = :uuid",
                {"uuid": doc_uuid}
            )
        }
        
        for table, result in counts.items():
            if result:
                logger.info(f"  {table}: {result[0]['cnt']} records")

if __name__ == "__main__":
    tester = DocumentProcessingTester()
    success = tester.test_synchronous_processing()
    sys.exit(0 if success else 1)