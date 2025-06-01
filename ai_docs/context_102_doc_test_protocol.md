# Context 101: Live Document Testing Strategy

## Overview

This document outlines a comprehensive strategy for testing the legal document processing pipeline with actual PDF documents, identifying and fixing errors in real-time. This approach complements unit testing by validating the entire system end-to-end with real data.

## Testing Strategy

### 1. Test Document Selection

#### Sample Documents
```
input_docs/
├── simple_contract.pdf      # 1-2 pages, clear text
├── complex_legal_brief.pdf  # 10+ pages, mixed formatting
├── scanned_document.pdf     # OCR-required document
├── multi_column.pdf         # Complex layout
└── mixed_media.pdf          # Text + images + tables
```

### 2. Live Testing Script

Create `scripts/live_document_test.py`:

```python
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

from supabase_utils import SupabaseManager
from redis_utils import get_redis_manager
from main_pipeline import process_single_document
from queue_processor import QueueProcessor
from config import (
    DEPLOYMENT_STAGE,
    USE_S3_FOR_INPUT,
    S3_PRIMARY_DOCUMENT_BUCKET,
    PROJECT_ID_GLOBAL
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/live_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LiveDocumentTester:
    """Orchestrates live document testing with error tracking"""
    
    def __init__(self):
        self.db_manager = SupabaseManager()
        self.redis_manager = get_redis_manager()
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
            filename=filename,
            project_uuid=project_uuid,
            file_path=file_path,
            file_size=os.path.getsize(file_path),
            mime_type="application/pdf",
            detected_file_type=".pdf"
        )
        
        logger.info(f"Registered document: ID={doc_id}, UUID={doc_uuid}")
        return doc_id, doc_uuid
    
    def _test_direct_processing(self, doc_id: int, doc_uuid: str, file_path: str, result: Dict):
        """Test direct processing mode"""
        try:
            # Get project info
            project_id, _ = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL)
            
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
        """Test queue-based processing"""
        try:
            # Create queue entry
            queue_id = self.db_manager.create_queue_entry(doc_id)
            logger.info(f"Created queue entry: {queue_id}")
            
            # Process via queue
            processor = QueueProcessor(batch_size=1)
            processor.process_queue(max_documents_to_process=1, single_run=True)
            
            # Wait for completion
            self._wait_for_completion(doc_uuid, timeout=300)
            
            result["stages"]["queue_processing"] = "completed"
            
        except Exception as e:
            logger.error(f"Queue processing error: {str(e)}")
            result["errors"].append({
                "stage": "queue_processing",
                "error": str(e),
                "traceback": traceback.format_exc()
            })
            raise
    
    def _wait_for_completion(self, doc_uuid: str, timeout: int = 300):
        """Wait for document processing to complete"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check status
            status = self.db_manager.get_document_status(doc_uuid)
            
            if status.get("status") == "completed":
                logger.info("Document processing completed")
                return
            elif status.get("status") == "failed":
                raise Exception(f"Processing failed: {status.get('error_message')}")
            
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
            source_doc = self.db_manager.get_document_by_uuid(doc_uuid)
            if source_doc and source_doc.get("raw_text"):
                validation["source_document"] = True
                result["text_length"] = len(source_doc["raw_text"])
            
            # Check Neo4j document
            neo4j_docs = self.db_manager.get_neo4j_documents_by_source(doc_uuid)
            if neo4j_docs:
                validation["neo4j_document"] = True
                neo4j_doc_id = neo4j_docs[0]["id"]
                
                # Check chunks
                chunks = self.db_manager.get_chunks_by_document(neo4j_doc_id)
                if chunks:
                    validation["chunks"] = True
                    result["chunk_count"] = len(chunks)
                    
                    # Check entities
                    entities = self.db_manager.get_entities_by_document(neo4j_doc_id)
                    if entities:
                        validation["entities"] = True
                        result["entity_count"] = len(entities)
                        
                        # Check relationships
                        relationships = self.db_manager.get_relationships_by_document(neo4j_doc_id)
                        if relationships:
                            validation["relationships"] = True
                            result["relationship_count"] = len(relationships)
            
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
        
        report_path = Path("test_reports") / filename
        report_path.parent.mkdir(exist_ok=True)
        
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
```

## 3. Error Detection and Fixing Strategy

### 3.1 Common Error Patterns

#### OCR Errors
```python
# Error: Textract job timeout
Fix: Increase timeout in textract_utils.py
def wait_for_job_completion(self, job_id, max_wait=600):  # Increase from 300

# Error: Missing AWS credentials
Fix: Ensure environment variables are set
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-2
```

#### Database Errors
```python
# Error: UUID constraint violation
Fix: Check for existing documents before insert
existing = self.db_manager.get_document_by_hash(content_hash)
if existing:
    return existing['id'], existing['uuid']

# Error: Foreign key constraint
Fix: Ensure parent records exist
if not self.db_manager.document_exists(doc_uuid):
    raise ValueError(f"Document {doc_uuid} not found")
```

#### Processing Errors
```python
# Error: Empty text extraction
Fix: Add fallback OCR methods
if not text:
    text = self.try_pypdf2_extraction(file_path)
if not text:
    text = self.try_ocrmypdf(file_path)

# Error: Entity extraction timeout
Fix: Chunk text for large documents
if len(text) > 50000:
    chunks = self.split_text_for_processing(text, max_size=40000)
```

### 3.2 Monitoring Script

Create `scripts/monitor_live_test.py`:

```python
#!/usr/bin/env python3
"""Monitor live document testing in real-time"""

import time
import sys
from rich.console import Console
from rich.table import Table
from rich.live import Live
from supabase_utils import SupabaseManager

console = Console()

def get_processing_status():
    """Get current processing status from database"""
    db = SupabaseManager()
    
    # Get queue status
    queue_stats = db.client.table('document_processing_queue')\
        .select('status, COUNT(*)')\
        .execute()
    
    # Get recent errors
    recent_errors = db.client.table('document_processing_queue')\
        .select('*')\
        .eq('status', 'failed')\
        .order('updated_at', desc=True)\
        .limit(5)\
        .execute()
    
    # Get processing times
    completed = db.client.table('document_processing_queue')\
        .select('created_at, completed_at')\
        .eq('status', 'completed')\
        .order('completed_at', desc=True)\
        .limit(10)\
        .execute()
    
    return {
        'queue_stats': queue_stats.data,
        'recent_errors': recent_errors.data,
        'completed': completed.data
    }

def create_status_table():
    """Create status display table"""
    table = Table(title="Document Processing Status")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")
    
    status = get_processing_status()
    
    # Add queue statistics
    for stat in status['queue_stats']:
        table.add_row(f"Queue - {stat['status']}", str(stat['count']))
    
    # Add recent errors
    if status['recent_errors']:
        table.add_row("Recent Errors", str(len(status['recent_errors'])))
        for error in status['recent_errors'][:3]:
            table.add_row(
                f"  Error at {error['updated_at'][:19]}", 
                error['error_message'][:50] + "..."
            )
    
    return table

def monitor():
    """Run monitoring loop"""
    with Live(create_status_table(), refresh_per_second=1) as live:
        while True:
            time.sleep(5)
            live.update(create_status_table())

if __name__ == "__main__":
    try:
        monitor()
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped[/yellow]")
```

## 4. Quick Fix Procedures

### 4.1 OCR Fix Script

```python
# scripts/fix_ocr_errors.py
def fix_missing_textract_results():
    """Retry failed Textract jobs"""
    db = SupabaseManager()
    
    # Find failed Textract jobs
    failed_jobs = db.client.table('textract_jobs')\
        .select('*')\
        .eq('status', 'FAILED')\
        .execute()
    
    for job in failed_jobs.data:
        # Retry the job
        processor = TextractProcessor()
        new_job_id = processor.start_document_text_detection(
            s3_bucket=job['s3_bucket'],
            s3_key=job['s3_key'],
            document_uuid=job['document_uuid']
        )
        logger.info(f"Retrying job for document {job['document_uuid']}")
```

### 4.2 Entity Fix Script

```python
# scripts/fix_entity_errors.py
def fix_missing_entities():
    """Re-run entity extraction for documents missing entities"""
    db = SupabaseManager()
    
    # Find documents without entities
    docs_without_entities = db.client.rpc(
        'get_documents_without_entities'
    ).execute()
    
    for doc in docs_without_entities.data:
        # Re-extract entities
        from entity_extraction import extract_entities_from_chunk
        
        chunks = db.get_chunks_by_document(doc['id'])
        for chunk in chunks:
            entities = extract_entities_from_chunk(chunk['text'])
            # Save entities...
```

## 5. Testing Workflow

### Step 1: Prepare Test Documents
```bash
# Create test directory
mkdir -p input_docs/test_batch

# Copy sample PDFs
cp samples/*.pdf input_docs/test_batch/
```

### Step 2: Run Single Document Test
```bash
# Test with direct processing
python scripts/live_document_test.py input_docs/simple_contract.pdf --mode direct

# Test with queue processing
python scripts/live_document_test.py input_docs/complex_brief.pdf --mode queue
```

### Step 3: Run Batch Test
```bash
# Test entire directory
python scripts/live_document_test.py input_docs/test_batch/ --batch

# Monitor in another terminal
python scripts/monitor_live_test.py
```

### Step 4: Analyze Results
```bash
# View test report
cat test_reports/test_report_*.md

# Check specific errors
grep -A5 "Error:" test_reports/test_report_*.md
```

### Step 5: Apply Fixes
```bash
# Fix OCR errors
python scripts/fix_ocr_errors.py

# Fix entity errors  
python scripts/fix_entity_errors.py

# Re-run failed documents
python scripts/reprocess_failed.py
```

## 6. Validation Checklist

### Document Level
- [ ] Document registered in `source_documents`
- [ ] Raw text extracted and stored
- [ ] Document status is "completed"
- [ ] Processing timestamps are set

### Neo4j Preparation
- [ ] Neo4j document created
- [ ] Chunks created with proper indexing
- [ ] All chunks have text content
- [ ] Chunk metadata is valid JSON

### Entity Extraction
- [ ] Entities extracted for each chunk
- [ ] Entity types are valid
- [ ] Entity positions are within chunk bounds
- [ ] Canonical entities created

### Relationship Building
- [ ] Document-Project relationship exists
- [ ] Document-Chunk relationships exist
- [ ] Chunk-Entity relationships exist
- [ ] Next/Previous chunk relationships exist

### Error Handling
- [ ] Failed documents have error messages
- [ ] Retry count is tracked
- [ ] Timeout errors are logged
- [ ] Partial failures are recoverable

## 7. Performance Metrics

Track these metrics during live testing:

1. **Processing Time**
   - OCR extraction time
   - Entity extraction time
   - Total pipeline time

2. **Success Rates**
   - Documents processed successfully
   - OCR success rate
   - Entity extraction success rate

3. **Error Rates**
   - OCR failures
   - Database errors
   - Timeout errors

4. **Resource Usage**
   - Redis cache hit rate
   - API call counts
   - Database query count

## 8. Continuous Improvement

### Error Pattern Analysis
```python
# Analyze common errors
def analyze_error_patterns():
    errors = load_all_error_logs()
    
    patterns = {}
    for error in errors:
        pattern = extract_error_pattern(error)
        patterns[pattern] = patterns.get(pattern, 0) + 1
    
    # Identify top issues
    top_issues = sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:10]
```

### Automated Fix Recommendations
```python
# Generate fix recommendations
def recommend_fixes(error_patterns):
    fixes = {
        "timeout": "Increase timeout values",
        "memory": "Reduce batch sizes",
        "api_limit": "Implement rate limiting",
        "encoding": "Add encoding detection"
    }
    
    recommendations = []
    for pattern, count in error_patterns:
        if pattern in fixes:
            recommendations.append({
                "issue": pattern,
                "frequency": count,
                "recommendation": fixes[pattern]
            })
    
    return recommendations
```

## Summary

This live document testing strategy provides:

1. **Comprehensive Testing**: Tests all pipeline stages with real documents
2. **Error Detection**: Identifies and categorizes errors systematically
3. **Quick Fixes**: Provides scripts to fix common issues
4. **Monitoring**: Real-time visibility into processing status
5. **Reporting**: Detailed reports for analysis and improvement

The approach ensures the pipeline works correctly with actual legal documents while providing tools to quickly identify and resolve issues.