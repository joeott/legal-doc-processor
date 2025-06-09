#!/usr/bin/env python3
"""
Comprehensive PDF document discovery script.
Recursively finds all PDF documents in input_docs directory.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

def discover_pdf_documents(root_dir="/opt/legal-doc-processor/input_docs"):
    """Recursively find all PDF documents."""
    pdf_files = []
    total_size = 0
    
    print(f"🔍 Scanning directory: {root_dir}")
    print("=" * 70)
    
    if not os.path.exists(root_dir):
        print(f"❌ Directory not found: {root_dir}")
        return []
    
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith('.pdf'):
                full_path = os.path.join(root, file)
                
                try:
                    file_size = os.path.getsize(full_path)
                    total_size += file_size
                    
                    relative_path = os.path.relpath(full_path, root_dir)
                    size_mb = round(file_size / (1024*1024), 2)
                    
                    pdf_files.append({
                        'filename': file,
                        'full_path': full_path,
                        'relative_path': relative_path,
                        'directory': os.path.dirname(relative_path),
                        'size_bytes': file_size,
                        'size_mb': size_mb,
                        'readable': os.access(full_path, os.R_OK)
                    })
                    
                    print(f"📄 {size_mb:6.2f}MB  {relative_path}")
                    
                except OSError as e:
                    print(f"❌ Error accessing {file}: {e}")
    
    # Sort by size (smallest first for testing)
    pdf_files.sort(key=lambda x: x['size_bytes'])
    
    total_size_mb = round(total_size / (1024*1024), 2)
    
    print("\n" + "=" * 70)
    print(f"📊 DISCOVERY SUMMARY")
    print("=" * 70)
    print(f"Total PDFs found: {len(pdf_files)}")
    print(f"Total size: {total_size_mb} MB")
    print(f"Average size: {round(total_size_mb / len(pdf_files), 2) if pdf_files else 0} MB")
    
    if pdf_files:
        print(f"Smallest: {pdf_files[0]['size_mb']} MB - {pdf_files[0]['filename']}")
        print(f"Largest: {pdf_files[-1]['size_mb']} MB - {pdf_files[-1]['filename']}")
    
    # Size distribution
    small_docs = [doc for doc in pdf_files if doc['size_mb'] < 1.0]
    medium_docs = [doc for doc in pdf_files if 1.0 <= doc['size_mb'] < 10.0]
    large_docs = [doc for doc in pdf_files if doc['size_mb'] >= 10.0]
    
    print(f"\n📏 SIZE DISTRIBUTION:")
    print(f"Small (<1MB): {len(small_docs)} documents")
    print(f"Medium (1-10MB): {len(medium_docs)} documents")
    print(f"Large (>10MB): {len(large_docs)} documents")
    
    return pdf_files

def save_discovery_results(pdf_files):
    """Save discovery results to JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"/opt/legal-doc-processor/document_discovery_{timestamp}.json"
    
    discovery_data = {
        'discovery_timestamp': datetime.now().isoformat(),
        'total_documents': len(pdf_files),
        'total_size_mb': round(sum(doc['size_bytes'] for doc in pdf_files) / (1024*1024), 2),
        'documents': pdf_files
    }
    
    with open(output_file, 'w') as f:
        json.dump(discovery_data, f, indent=2)
    
    print(f"\n💾 Discovery results saved to: {output_file}")
    return output_file

def main():
    """Main discovery process."""
    print("🚀 PDF DOCUMENT DISCOVERY FOR PRODUCTION TESTING")
    print("=" * 70)
    
    # Discover all PDF documents
    pdf_files = discover_pdf_documents()
    
    if not pdf_files:
        print("❌ No PDF documents found!")
        return 1
    
    # Save results
    output_file = save_discovery_results(pdf_files)
    
    print("\n🎯 READY FOR PRODUCTION TESTING")
    print("=" * 70)
    print("Next step: Run comprehensive pipeline test on all discovered documents")
    print("CRITICAL: All documents must be processed via Textract (not Tesseract)")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())