#!/usr/bin/env python3
"""Test multiple documents through the pipeline"""
import os
import sys
from live_document_test import LiveDocumentTester
from datetime import datetime

# Select diverse document types for testing
test_documents = [
    "input/ARDC_Registration_Receipt_6333890.pdf",  # Small document (137KB)
    "input/Affidavit+of+Service.PDF",  # Different naming convention
    "input/Ali - Motion to Continue Trial Setting.pdf",  # Contains spaces in name
    "input/APRIL L DAVIS-Comprehensive-Report-202501221858.pdf",  # Large document (698KB)
]

def main():
    print(f"""
===================================
Multiple Document Processing Test
===================================
Start Time: {datetime.now()}
Testing {len(test_documents)} documents
""")
    
    # Clean up any existing test documents first
    print("Cleaning up previous test runs...")
    os.system("cd /Users/josephott/Documents/phase_1_2_3_process_v5 && python scripts/fix_triggers.py 2>&1 > /dev/null")
    
    tester = LiveDocumentTester()
    results = []
    
    for i, doc_path in enumerate(test_documents, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}/{len(test_documents)}: {os.path.basename(doc_path)}")
        print(f"File size: {os.path.getsize(doc_path) / 1024:.1f} KB")
        print(f"{'='*60}")
        
        try:
            result = tester.test_document(doc_path, test_mode="direct")
            results.append({
                'document': os.path.basename(doc_path),
                'status': 'SUCCESS' if result.get('success') else 'FAILED',
                'duration': result.get('duration', 'N/A'),
                'uuid': result.get('doc_uuid', 'N/A'),
                'text_length': result.get('text_length', 0),
                'error': result.get('error', None)
            })
            
            if result.get('success'):
                print(f"✓ SUCCESS - UUID: {result.get('doc_uuid')}")
            else:
                print(f"✗ FAILED - Error: {result.get('error')}")
                
        except Exception as e:
            print(f"✗ EXCEPTION: {str(e)}")
            results.append({
                'document': os.path.basename(doc_path),
                'status': 'EXCEPTION',
                'error': str(e)
            })
    
    # Summary report
    print(f"\n{'='*60}")
    print("SUMMARY REPORT")
    print(f"{'='*60}")
    print(f"Total documents tested: {len(results)}")
    print(f"Successful: {sum(1 for r in results if r['status'] == 'SUCCESS')}")
    print(f"Failed: {sum(1 for r in results if r['status'] in ['FAILED', 'EXCEPTION'])}")
    print(f"\nDetailed Results:")
    print(f"{'Document':<50} {'Status':<10} {'Duration':<15} {'Text Chars':<12}")
    print("-" * 90)
    
    for r in results:
        duration_str = str(r.get('duration', 'N/A'))[:14]
        text_len = r.get('text_length', 0)
        print(f"{r['document'][:49]:<50} {r['status']:<10} {duration_str:<15} {text_len:<12}")
        if r.get('error'):
            print(f"  └─ Error: {str(r['error'])[:80]}")
    
    print(f"\nEnd Time: {datetime.now()}")
    
    # Save detailed report
    report_path = f"test_reports/multi_doc_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(report_path, 'w') as f:
        f.write("# Multiple Document Test Report\n\n")
        f.write(f"Generated: {datetime.now()}\n\n")
        f.write("## Summary\n")
        f.write(f"- Total documents: {len(results)}\n")
        f.write(f"- Successful: {sum(1 for r in results if r['status'] == 'SUCCESS')}\n")
        f.write(f"- Failed: {sum(1 for r in results if r['status'] in ['FAILED', 'EXCEPTION'])}\n\n")
        f.write("## Detailed Results\n\n")
        
        for i, r in enumerate(results, 1):
            f.write(f"### {i}. {r['document']}\n")
            f.write(f"- Status: {r['status']}\n")
            if r.get('duration'):
                f.write(f"- Duration: {r['duration']}\n")
            if r.get('uuid'):
                f.write(f"- Document UUID: {r['uuid']}\n")
            if r.get('text_length'):
                f.write(f"- Text extracted: {r['text_length']} characters\n")
            if r.get('error'):
                f.write(f"- Error: {r['error']}\n")
            f.write("\n")
    
    print(f"\nDetailed report saved to: {report_path}")

if __name__ == "__main__":
    main()