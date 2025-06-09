#!/usr/bin/env python3
"""
Paul, Michael (Acuity) Document Discovery Script
Discovers and catalogs all PDF documents in the Paul, Michael (Acuity) case directory.
"""

import os
import json
from datetime import datetime
from pathlib import Path
import hashlib

def get_file_hash(filepath):
    """Generate SHA256 hash for file integrity verification."""
    sha256_hash = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        return f"ERROR: {str(e)}"

def discover_paul_michael_documents():
    """Discover all PDF documents in Paul, Michael (Acuity) directory."""
    
    base_dir = Path("/opt/legal-doc-processor")
    input_dir = base_dir / "input_docs" / "Paul, Michael (Acuity)"
    
    if not input_dir.exists():
        raise FileNotFoundError(f"Paul, Michael (Acuity) directory not found: {input_dir}")
    
    discovery_results = {
        "discovery_timestamp": datetime.now().isoformat(),
        "base_directory": str(input_dir),
        "total_documents": 0,
        "total_size_bytes": 0,
        "documents": [],
        "size_categories": {
            "small": {"count": 0, "max_size": 1024*1024, "documents": []},  # < 1MB
            "medium": {"count": 0, "max_size": 10*1024*1024, "documents": []},  # 1MB - 10MB
            "large": {"count": 0, "max_size": float('inf'), "documents": []},  # > 10MB
        },
        "directory_structure": {}
    }
    
    print(f"🔍 Discovering PDF documents in: {input_dir}")
    print("=" * 80)
    
    # Walk through all subdirectories
    for root, dirs, files in os.walk(input_dir):
        pdf_files = [f for f in files if f.lower().endswith('.pdf')]
        
        if pdf_files:
            relative_root = Path(root).relative_to(input_dir)
            discovery_results["directory_structure"][str(relative_root)] = len(pdf_files)
            print(f"📁 {relative_root}: {len(pdf_files)} PDF files")
            
            for pdf_file in pdf_files:
                file_path = Path(root) / pdf_file
                relative_path = file_path.relative_to(base_dir)
                
                try:
                    file_stat = file_path.stat()
                    file_size = file_stat.st_size
                    file_hash = get_file_hash(file_path)
                    
                    # Categorize by size
                    if file_size < discovery_results["size_categories"]["small"]["max_size"]:
                        category = "small"
                    elif file_size < discovery_results["size_categories"]["medium"]["max_size"]:
                        category = "medium" 
                    else:
                        category = "large"
                    
                    discovery_results["size_categories"][category]["count"] += 1
                    discovery_results["size_categories"][category]["documents"].append(str(relative_path))
                    
                    document_info = {
                        "filename": pdf_file,
                        "relative_path": str(relative_path),
                        "absolute_path": str(file_path),
                        "size_bytes": file_size,
                        "size_mb": round(file_size / (1024*1024), 2),
                        "size_category": category,
                        "directory": str(relative_root),
                        "sha256_hash": file_hash,
                        "last_modified": datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                    }
                    
                    discovery_results["documents"].append(document_info)
                    discovery_results["total_size_bytes"] += file_size
                    
                    print(f"  📄 {pdf_file} ({document_info['size_mb']} MB)")
                    
                except Exception as e:
                    print(f"  ❌ Error processing {pdf_file}: {e}")
    
    discovery_results["total_documents"] = len(discovery_results["documents"])
    discovery_results["total_size_mb"] = round(discovery_results["total_size_bytes"] / (1024*1024), 2)
    
    print("=" * 80)
    print(f"📊 DISCOVERY SUMMARY:")
    print(f"Total Documents: {discovery_results['total_documents']}")
    print(f"Total Size: {discovery_results['total_size_mb']} MB")
    print(f"Small files (<1MB): {discovery_results['size_categories']['small']['count']}")
    print(f"Medium files (1-10MB): {discovery_results['size_categories']['medium']['count']}")
    print(f"Large files (>10MB): {discovery_results['size_categories']['large']['count']}")
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = base_dir / f"paul_michael_discovery_{timestamp}.json"
    
    with open(output_file, 'w') as f:
        json.dump(discovery_results, f, indent=2)
    
    print(f"💾 Results saved to: {output_file}")
    return discovery_results, output_file

if __name__ == "__main__":
    try:
        results, output_file = discover_paul_michael_documents()
        print(f"\n✅ Discovery completed successfully!")
        print(f"📋 Results available in: {output_file}")
    except Exception as e:
        print(f"❌ Discovery failed: {e}")
        exit(1)