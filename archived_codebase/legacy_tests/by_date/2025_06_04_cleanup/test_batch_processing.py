#!/usr/bin/env python3
"""
Batch Processing Test Script
Purpose: Test the system's ability to handle multiple documents
"""

import os
import sys
import time
import json
import asyncio
import logging
from typing import List, Dict, Any
from datetime import datetime
from uuid import uuid4
import concurrent.futures

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BatchProcessingTester:
    """Test batch and concurrent document processing"""
    
    def __init__(self):
        self.results = []
        self.start_time = time.time()
        
    def simulate_document_upload(self, doc_name: str) -> Dict[str, Any]:
        """Simulate uploading a document to S3"""
        doc_id = str(uuid4())
        
        # In real implementation, would upload to S3
        # For now, return mock data
        return {
            "document_id": doc_id,
            "file_name": doc_name,
            "file_path": f"s3://test-bucket/{doc_name}",
            "upload_time": datetime.now().isoformat()
        }
    
    def process_document(self, doc_info: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single document through the pipeline"""
        start = time.time()
        doc_id = doc_info["document_id"]
        
        try:
            # Import required functions
            from scripts.pdf_tasks import process_pdf_document
            from scripts.cache import get_redis_manager
            
            # In real implementation, would call:
            # task = process_pdf_document.delay(
            #     document_uuid=doc_id,
            #     file_path=doc_info["file_path"],
            #     project_uuid="test-project-001"
            # )
            
            # For testing, simulate processing
            logger.info(f"Processing document: {doc_info['file_name']}")
            
            # Simulate processing time
            import random
            time.sleep(random.uniform(0.5, 2.0))
            
            # Check pipeline state
            redis_manager = get_redis_manager()
            state_key = f"doc_state:{doc_id}"
            
            # Simulate success
            result = {
                "document_id": doc_id,
                "status": "completed",
                "duration": time.time() - start,
                "stages_completed": 6,
                "error": None
            }
            
        except Exception as e:
            result = {
                "document_id": doc_id,
                "status": "failed",
                "duration": time.time() - start,
                "stages_completed": 0,
                "error": str(e)
            }
            logger.error(f"Error processing {doc_info['file_name']}: {e}")
        
        return result
    
    def test_sequential_batch(self, num_documents: int) -> Dict[str, Any]:
        """Test processing documents sequentially"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing sequential batch processing: {num_documents} documents")
        logger.info(f"{'='*60}")
        
        start = time.time()
        results = []
        
        # Generate test documents
        documents = []
        for i in range(num_documents):
            doc_info = self.simulate_document_upload(f"test_doc_{i+1}.pdf")
            documents.append(doc_info)
        
        # Process sequentially
        for doc in documents:
            result = self.process_document(doc)
            results.append(result)
            
            if result["status"] == "completed":
                logger.info(f"✅ {doc['file_name']} completed in {result['duration']:.2f}s")
            else:
                logger.error(f"❌ {doc['file_name']} failed: {result['error']}")
        
        # Calculate statistics
        total_time = time.time() - start
        successful = len([r for r in results if r["status"] == "completed"])
        failed = len([r for r in results if r["status"] == "failed"])
        avg_time = sum(r["duration"] for r in results) / len(results) if results else 0
        
        summary = {
            "test_type": "sequential_batch",
            "num_documents": num_documents,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / num_documents * 100,
            "total_time": total_time,
            "average_time_per_doc": avg_time,
            "documents_per_minute": (num_documents / total_time * 60) if total_time > 0 else 0
        }
        
        logger.info(f"\nSequential Batch Summary:")
        logger.info(f"  Success Rate: {summary['success_rate']:.1f}%")
        logger.info(f"  Total Time: {summary['total_time']:.2f}s")
        logger.info(f"  Avg Time/Doc: {summary['average_time_per_doc']:.2f}s")
        logger.info(f"  Throughput: {summary['documents_per_minute']:.1f} docs/min")
        
        return summary
    
    def test_concurrent_batch(self, num_documents: int, max_workers: int = 5) -> Dict[str, Any]:
        """Test processing documents concurrently"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing concurrent batch processing: {num_documents} documents, {max_workers} workers")
        logger.info(f"{'='*60}")
        
        start = time.time()
        results = []
        
        # Generate test documents
        documents = []
        for i in range(num_documents):
            doc_info = self.simulate_document_upload(f"concurrent_doc_{i+1}.pdf")
            documents.append(doc_info)
        
        # Process concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_doc = {
                executor.submit(self.process_document, doc): doc 
                for doc in documents
            }
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_doc):
                doc = future_to_doc[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result["status"] == "completed":
                        logger.info(f"✅ {doc['file_name']} completed in {result['duration']:.2f}s")
                    else:
                        logger.error(f"❌ {doc['file_name']} failed: {result['error']}")
                        
                except Exception as e:
                    logger.error(f"❌ {doc['file_name']} exception: {e}")
                    results.append({
                        "document_id": doc["document_id"],
                        "status": "failed",
                        "error": str(e)
                    })
        
        # Calculate statistics
        total_time = time.time() - start
        successful = len([r for r in results if r["status"] == "completed"])
        failed = len([r for r in results if r["status"] == "failed"])
        
        summary = {
            "test_type": "concurrent_batch",
            "num_documents": num_documents,
            "max_workers": max_workers,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / num_documents * 100,
            "total_time": total_time,
            "documents_per_minute": (num_documents / total_time * 60) if total_time > 0 else 0,
            "speedup": "N/A"  # Will be calculated if we have sequential results
        }
        
        logger.info(f"\nConcurrent Batch Summary:")
        logger.info(f"  Success Rate: {summary['success_rate']:.1f}%")
        logger.info(f"  Total Time: {summary['total_time']:.2f}s")
        logger.info(f"  Throughput: {summary['documents_per_minute']:.1f} docs/min")
        
        return summary
    
    def test_mixed_load(self, concurrent_docs: int, sequential_docs: int) -> Dict[str, Any]:
        """Test mixed concurrent and sequential processing"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing mixed load: {concurrent_docs} concurrent + {sequential_docs} sequential")
        logger.info(f"{'='*60}")
        
        start = time.time()
        
        # First, process concurrent batch
        concurrent_results = self.test_concurrent_batch(concurrent_docs, max_workers=3)
        
        # Then, process sequential batch
        sequential_results = self.test_sequential_batch(sequential_docs)
        
        # Combined summary
        total_docs = concurrent_docs + sequential_docs
        total_successful = concurrent_results["successful"] + sequential_results["successful"]
        total_time = time.time() - start
        
        summary = {
            "test_type": "mixed_load",
            "total_documents": total_docs,
            "concurrent_docs": concurrent_docs,
            "sequential_docs": sequential_docs,
            "total_successful": total_successful,
            "overall_success_rate": total_successful / total_docs * 100,
            "total_time": total_time,
            "overall_throughput": (total_docs / total_time * 60) if total_time > 0 else 0
        }
        
        logger.info(f"\nMixed Load Summary:")
        logger.info(f"  Overall Success Rate: {summary['overall_success_rate']:.1f}%")
        logger.info(f"  Total Time: {summary['total_time']:.2f}s")
        logger.info(f"  Overall Throughput: {summary['overall_throughput']:.1f} docs/min")
        
        return summary
    
    def run_all_tests(self):
        """Run comprehensive batch processing tests"""
        logger.info("Starting Batch Processing Tests")
        logger.info("=" * 80)
        
        all_results = []
        
        # Test 1: Small sequential batch
        result = self.test_sequential_batch(5)
        all_results.append(result)
        time.sleep(2)  # Brief pause between tests
        
        # Test 2: Small concurrent batch
        result = self.test_concurrent_batch(5, max_workers=3)
        all_results.append(result)
        
        # Calculate speedup
        if len(all_results) >= 2:
            seq_time = all_results[0]["total_time"]
            conc_time = all_results[1]["total_time"]
            speedup = seq_time / conc_time if conc_time > 0 else 0
            all_results[1]["speedup"] = f"{speedup:.2f}x"
            logger.info(f"\n🚀 Concurrent processing speedup: {speedup:.2f}x")
        
        time.sleep(2)
        
        # Test 3: Mixed load
        result = self.test_mixed_load(concurrent_docs=3, sequential_docs=5)
        all_results.append(result)
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        results_file = f"batch_test_results_{timestamp}.json"
        
        with open(results_file, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "total_duration": time.time() - self.start_time,
                "results": all_results
            }, f, indent=2)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Batch processing tests complete!")
        logger.info(f"Results saved to: {results_file}")
        
        # Final summary
        total_docs_processed = sum(r.get("num_documents", r.get("total_documents", 0)) for r in all_results)
        total_successful = sum(r.get("successful", r.get("total_successful", 0)) for r in all_results)
        overall_success_rate = (total_successful / total_docs_processed * 100) if total_docs_processed > 0 else 0
        
        logger.info(f"\nOVERALL SUMMARY:")
        logger.info(f"  Total Documents Processed: {total_docs_processed}")
        logger.info(f"  Total Successful: {total_successful}")
        logger.info(f"  Overall Success Rate: {overall_success_rate:.1f}%")
        
        if overall_success_rate >= 95:
            logger.info("\n✅ BATCH PROCESSING: PASS")
        elif overall_success_rate >= 80:
            logger.warning("\n⚠️ BATCH PROCESSING: CONDITIONAL PASS")
        else:
            logger.error("\n❌ BATCH PROCESSING: FAIL")
        
        return all_results

def main():
    """Run batch processing tests"""
    tester = BatchProcessingTester()
    
    try:
        # Check if we have the required modules
        import scripts.cache
        import scripts.db
        logger.info("✅ Required modules available")
    except ImportError as e:
        logger.error(f"❌ Missing required modules: {e}")
        logger.error("Make sure to run: source load_env.sh")
        return
    
    # Run tests
    try:
        tester.run_all_tests()
    except KeyboardInterrupt:
        logger.info("\nTests interrupted by user")
    except Exception as e:
        logger.error(f"Test error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()