#!/usr/bin/env python3
"""
Live document testing script for pipeline validation
Processes real PDFs through the entire pipeline and tracks errors
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import traceback

# Add scripts to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager
from scripts.main_pipeline import process_single_document
from scripts.queue_processor import QueueProcessor
from scripts.config import (
    DEPLOYMENT_STAGE,
    USE_S3_FOR_INPUT,
    S3_PRIMARY_DOCUMENT_BUCKET,
    PROJECT_ID_GLOBAL
)

# Configure logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f'live_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LiveDocumentTester:
    """Orchestrates live document testing with error tracking"""
    
    def __init__(self):
        self.db_manager = SupabaseManager()
        # Redis manager will be initialized by queue processor or other components as needed
        self.test_results = []
        self.error_summary = {}
        
    def test_document(self, file_path: str, test_mode: str = "direct") -> Dict:
        """Test a single document through the pipeline"""
        logger.info(f"Testing document: {file_path}")
        
        result = {
            "file": file_path,
            "start_time": datetime.now().isoformat(),
            "stages": {},
            "errors": [],
            "warnings": [],
            "success": False
        }
        
        try:
            # Stage 1: Document Upload/Registration
            logger.info("Stage 1: Document registration")
            doc_id, doc_uuid = self._register_document(file_path)
            result["document_id"] = doc_id
            result["document_uuid"] = doc_uuid
            result["stages"]["registration"] = "completed"
            
            # Stage 2: Process Document
            if test_mode == "direct":
                logger.info("Stage 2: Direct processing")
                self._test_direct_processing(doc_id, doc_uuid, file_path, result)
            else:
                logger.info("Stage 2: Queue processing")
                self._test_queue_processing(doc_id, doc_uuid, result)
            
            # Stage 3: Validate Results
            logger.info("Stage 3: Validating results")
            self._validate_results(doc_uuid, result)
            
            result["success"] = True
            
        except Exception as e:
            logger.error(f"Test failed: {str(e)}")
            result["errors"].append({
                "stage": "unknown",
                "error": str(e),
                "traceback": traceback.format_exc()
            })
        
        result["end_time"] = datetime.now().isoformat()
        self.test_results.append(result)
        return result
    
    def _register_document(self, file_path: str) -> Tuple[int, str]:
        """Register document in database"""
        filename = os.path.basename(file_path)
        
        # Get or create project
        project_id, project_uuid = self.db_manager.get_or_create_project(
            PROJECT_ID_GLOBAL or "live-test-project"
        )
        
        # Create source document entry
        doc_id, doc_uuid = self.db_manager.create_source_document_entry(
            project_fk_id=project_id,
            project_uuid=project_uuid,
            original_file_path=file_path,
            original_file_name=filename,
            detected_file_type=".pdf"
        )
        
        logger.info(f"Registered document: ID={doc_id}, UUID={doc_uuid}")
        return doc_id, doc_uuid
    
    def _test_direct_processing(self, doc_id: int, doc_uuid: str, file_path: str, result: Dict):
        """Test direct processing mode"""
        try:
            # Get project info
            project_id, _ = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL or "live-test-project")
            
            # Process document
            process_result = process_single_document(
                db_manager=self.db_manager,
                source_doc_sql_id=doc_id,
                file_path=file_path,
                file_name=os.path.basename(file_path),
                detected_file_type=".pdf",
                project_sql_id=project_id
            )
            
            result["stages"]["processing"] = "completed"
            result["processing_result"] = process_result
            
        except Exception as e:
            logger.error(f"Processing error: {str(e)}")
            result["errors"].append({
                "stage": "processing",
                "error": str(e),
                "traceback": traceback.format_exc()
            })
            raise
    
    def _test_queue_processing(self, doc_id: int, doc_uuid: str, result: Dict):
        """Test processing via Celery submission"""
        try:
            # CRITICAL CHANGE: Submit directly to Celery
            from scripts.celery_submission import submit_document_to_celery
            
            # Get document details for Celery submission
            doc_info = self.db_manager.client.table('source_documents')\
                .select('original_file_path, detected_file_type')\
                .eq('id', doc_id)\
                .single()\
                .execute()
            
            if not doc_info.data:
                raise Exception(f"Document {doc_id} not found")
            
            file_path = doc_info.data['original_file_path']
            file_type = doc_info.data['detected_file_type']
            
            # Submit to Celery
            task_id, success = submit_document_to_celery(
                document_id=doc_id,
                document_uuid=doc_uuid,
                file_path=file_path,
                file_type=file_type,
                project_id=PROJECT_ID_GLOBAL or "live-test-project"
            )
            
            if not success:
                raise Exception("Failed to submit to Celery")
            
            logger.info(f"✅ Document submitted to Celery: {task_id}")
            result["celery_task_id"] = task_id
            
            # Wait for completion
            self._wait_for_completion(doc_id, doc_uuid, timeout=300)
            
            result["stages"]["celery_processing"] = "completed"
            
        except Exception as e:
            logger.error(f"Celery processing error: {str(e)}")
            result["errors"].append({
                "stage": "celery_processing",
                "error": str(e),
                "traceback": traceback.format_exc()
            })
            raise
    
    def _wait_for_completion(self, doc_id: int, doc_uuid: str, timeout: int = 300):
        """Wait for document processing completion - monitor Supabase status"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check source_documents status
            result = self.db_manager.client.table('source_documents')\
                .select('initial_processing_status, celery_status')\
                .eq('id', doc_id)\
                .execute()
            
            if result.data:
                status = result.data[0]['initial_processing_status']
                celery_status = result.data[0].get('celery_status', '')
                
                # Success states
                if status == 'completed' or celery_status == 'graph_complete':
                    logger.info("Document processing completed")
                    return
                
                # Error states
                if status.startswith('error_') or status == 'failed':
                    raise Exception(f"Processing failed with status: {status}")
                
                logger.info(f"⏳ Current status: {status} / Celery: {celery_status}")
            
            time.sleep(5)
        
        raise TimeoutError(f"Processing timeout after {timeout} seconds")
    
    def _validate_results(self, doc_uuid: str, result: Dict):
        """Validate processing results"""
        validation = {
            "source_document": False,
            "neo4j_document": False,
            "chunks": False,
            "entities": False,
            "relationships": False
        }
        
        try:
            # Check source document
            source_doc = self.db_manager.client.table('source_documents')\
                .select('*')\
                .eq('document_uuid', doc_uuid)\
                .single()\
                .execute()
            
            if source_doc.data and source_doc.data.get("raw_extracted_text"):
                validation["source_document"] = True
                result["text_length"] = len(source_doc.data["raw_extracted_text"])
            
            # Check Neo4j document
            neo4j_docs = self.db_manager.client.table('neo4j_documents')\
                .select('*')\
                .eq('documentId', doc_uuid)\
                .execute()
            
            if neo4j_docs.data:
                validation["neo4j_document"] = True
                neo4j_doc_id = neo4j_docs.data[0]["id"]
                neo4j_doc_uuid = neo4j_docs.data[0]["uuid"]
                
                # Check chunks
                chunks = self.db_manager.client.table('neo4j_chunks')\
                    .select('*')\
                    .eq('document_uuid', neo4j_doc_uuid)\
                    .execute()
                
                if chunks.data:
                    validation["chunks"] = True
                    result["chunk_count"] = len(chunks.data)
                    
                    # Check entities
                    entities = self.db_manager.client.table('neo4j_entity_mentions')\
                        .select('*')\
                        .eq('document_uuid', neo4j_doc_uuid)\
                        .execute()
                    
                    if entities.data:
                        validation["entities"] = True
                        result["entity_count"] = len(entities.data)
                        
                        # Check relationships
                        relationships = self.db_manager.client.table('neo4j_relationship_staging')\
                            .select('*')\
                            .or_(f'from_node_uuid.eq.{neo4j_doc_uuid},to_node_uuid.eq.{neo4j_doc_uuid}')\
                            .execute()
                        
                        if relationships.data:
                            validation["relationships"] = True
                            result["relationship_count"] = len(relationships.data)
            
            result["validation"] = validation
            
            # Log warnings for incomplete processing
            for stage, passed in validation.items():
                if not passed:
                    result["warnings"].append(f"Stage '{stage}' did not produce expected output")
            
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            result["errors"].append({
                "stage": "validation",
                "error": str(e),
                "traceback": traceback.format_exc()
            })
    
    def test_batch(self, directory: str, pattern: str = "*.pdf") -> Dict:
        """Test all documents in a directory"""
        logger.info(f"Testing batch in directory: {directory}")
        
        pdf_files = list(Path(directory).glob(pattern))
        logger.info(f"Found {len(pdf_files)} PDF files")
        
        batch_result = {
            "directory": directory,
            "total_files": len(pdf_files),
            "successful": 0,
            "failed": 0,
            "results": []
        }
        
        for pdf_file in pdf_files:
            result = self.test_document(str(pdf_file))
            batch_result["results"].append(result)
            
            if result["success"]:
                batch_result["successful"] += 1
            else:
                batch_result["failed"] += 1
        
        return batch_result
    
    def generate_report(self) -> str:
        """Generate comprehensive test report"""
        report_lines = [
            "# Live Document Testing Report",
            f"Generated: {datetime.now().isoformat()}",
            f"Deployment Stage: {DEPLOYMENT_STAGE}",
            "",
            "## Summary",
            f"Total documents tested: {len(self.test_results)}",
            f"Successful: {sum(1 for r in self.test_results if r['success'])}",
            f"Failed: {sum(1 for r in self.test_results if not r['success'])}",
            "",
            "## Detailed Results",
            ""
        ]
        
        for i, result in enumerate(self.test_results, 1):
            report_lines.extend([
                f"### Document {i}: {result['file']}",
                f"- Status: {'✓ Success' if result['success'] else '✗ Failed'}",
                f"- Duration: {self._calculate_duration(result)}",
                f"- Document UUID: {result.get('document_uuid', 'N/A')}",
                ""
            ])
            
            # Stages
            if result.get("stages"):
                report_lines.append("#### Stages Completed:")
                for stage, status in result["stages"].items():
                    report_lines.append(f"- {stage}: {status}")
                report_lines.append("")
            
            # Validation
            if result.get("validation"):
                report_lines.append("#### Validation Results:")
                for check, passed in result["validation"].items():
                    emoji = "✓" if passed else "✗"
                    report_lines.append(f"- {emoji} {check}")
                report_lines.append("")
            
            # Metrics
            if result.get("text_length"):
                report_lines.append("#### Processing Metrics:")
                report_lines.append(f"- Text extracted: {result['text_length']} characters")
                report_lines.append(f"- Chunks created: {result.get('chunk_count', 0)}")
                report_lines.append(f"- Entities found: {result.get('entity_count', 0)}")
                report_lines.append(f"- Relationships: {result.get('relationship_count', 0)}")
                report_lines.append("")
            
            # Errors
            if result.get("errors"):
                report_lines.append("#### Errors:")
                for error in result["errors"]:
                    report_lines.append(f"- **Stage**: {error['stage']}")
                    report_lines.append(f"  - Error: {error['error']}")
                    report_lines.append("  - Traceback:")
                    report_lines.append("  ```")
                    report_lines.extend(f"  {line}" for line in error['traceback'].split('\n'))
                    report_lines.append("  ```")
                report_lines.append("")
            
            # Warnings
            if result.get("warnings"):
                report_lines.append("#### Warnings:")
                for warning in result["warnings"]:
                    report_lines.append(f"- {warning}")
                report_lines.append("")
            
            report_lines.append("---")
            report_lines.append("")
        
        # Error Summary
        if self._collect_error_summary():
            report_lines.extend([
                "## Error Summary",
                ""
            ])
            
            for error_type, occurrences in self.error_summary.items():
                report_lines.append(f"### {error_type} ({len(occurrences)} occurrences)")
                for occ in occurrences[:3]:  # Show first 3
                    report_lines.append(f"- File: {occ['file']}")
                    report_lines.append(f"  Stage: {occ['stage']}")
                report_lines.append("")
        
        return "\n".join(report_lines)
    
    def _calculate_duration(self, result: Dict) -> str:
        """Calculate processing duration"""
        if "start_time" in result and "end_time" in result:
            start = datetime.fromisoformat(result["start_time"])
            end = datetime.fromisoformat(result["end_time"])
            duration = end - start
            return str(duration)
        return "N/A"
    
    def _collect_error_summary(self) -> Dict:
        """Collect and categorize errors"""
        self.error_summary = {}
        
        for result in self.test_results:
            for error in result.get("errors", []):
                error_type = error["error"].split(":")[0] if ":" in error["error"] else "Unknown"
                
                if error_type not in self.error_summary:
                    self.error_summary[error_type] = []
                
                self.error_summary[error_type].append({
                    "file": result["file"],
                    "stage": error["stage"],
                    "full_error": error["error"]
                })
        
        return self.error_summary
    
    def save_report(self, filename: str = None):
        """Save test report to file"""
        if filename is None:
            filename = f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        report = self.generate_report()
        
        report_dir = Path("test_reports")
        report_dir.mkdir(exist_ok=True)
        
        report_path = report_dir / filename
        
        with open(report_path, "w") as f:
            f.write(report)
        
        logger.info(f"Report saved to: {report_path}")
        return str(report_path)


def main():
    """Main test execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Live document testing")
    parser.add_argument("path", help="Path to PDF file or directory")
    parser.add_argument("--mode", choices=["direct", "queue"], default="direct",
                       help="Processing mode")
    parser.add_argument("--batch", action="store_true",
                       help="Process all PDFs in directory")
    parser.add_argument("--report", default="test_report.md",
                       help="Report filename")
    
    args = parser.parse_args()
    
    # Initialize tester
    tester = LiveDocumentTester()
    
    # Run tests
    if args.batch or os.path.isdir(args.path):
        results = tester.test_batch(args.path)
        logger.info(f"Batch test complete: {results['successful']}/{results['total_files']} successful")
    else:
        result = tester.test_document(args.path, test_mode=args.mode)
        logger.info(f"Test {'successful' if result['success'] else 'failed'}")
    
    # Generate and save report
    report_path = tester.save_report(args.report)
    print(f"\nTest report saved to: {report_path}")
    
    # Return exit code based on results
    sys.exit(0 if all(r["success"] for r in tester.test_results) else 1)


if __name__ == "__main__":
    main()