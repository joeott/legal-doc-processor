#!/usr/bin/env python3
"""
Analyze client files for import into the document processing system.

This script scans a directory tree, analyzes file types and sizes,
estimates processing costs, and generates an import manifest.
"""

import os
import json
import hashlib
import mimetypes
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import magic  # python-magic for better file type detection

# Cost estimates (based on AWS/OpenAI pricing as of 2024)
COST_ESTIMATES = {
    'textract_per_page': 0.015,  # AWS Textract per page
    'openai_gpt4_per_1k_tokens': 0.03,  # GPT-4 API per 1K tokens
    'openai_embedding_per_1k_tokens': 0.0001,  # text-embedding-3-large
    's3_storage_per_gb_month': 0.023,  # S3 standard storage
    's3_put_per_1k': 0.005,  # S3 PUT requests per 1K
}

# Supported file types and their processing requirements
FILE_TYPE_CONFIG = {
    'application/pdf': {
        'processor': 'textract',
        'avg_pages_per_mb': 15,
        'requires_ocr': True
    },
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': {
        'processor': 'docx',
        'avg_pages_per_mb': 50,
        'requires_ocr': False
    },
    'application/msword': {
        'processor': 'doc',
        'avg_pages_per_mb': 40,
        'requires_ocr': False
    },
    'text/plain': {
        'processor': 'text',
        'avg_pages_per_mb': 200,
        'requires_ocr': False
    },
    'message/rfc822': {
        'processor': 'email',
        'avg_pages_per_mb': 100,
        'requires_ocr': False
    },
    'image/jpeg': {
        'processor': 'textract',
        'avg_pages_per_mb': 1,
        'requires_ocr': True
    },
    'image/png': {
        'processor': 'textract',
        'avg_pages_per_mb': 1,
        'requires_ocr': True
    },
    'image/heic': {
        'processor': 'textract',
        'avg_pages_per_mb': 1,
        'requires_ocr': True
    },
    'video/mp4': {
        'processor': 'skip',
        'avg_pages_per_mb': 0,
        'requires_ocr': False
    },
    'video/quicktime': {
        'processor': 'skip',
        'avg_pages_per_mb': 0,
        'requires_ocr': False
    }
}


class ClientFileAnalyzer:
    """Analyze client files for import."""
    
    def __init__(self, base_path: str, case_name: str):
        self.base_path = Path(base_path)
        self.case_name = case_name
        self.files = []
        self.errors = []
        self.stats = defaultdict(int)
        self.cost_breakdown = defaultdict(float)
        
        # Initialize magic for file type detection
        self.mime = magic.Magic(mime=True)
    
    def analyze(self) -> Dict:
        """Perform complete analysis of the directory tree."""
        print(f"Analyzing files in: {self.base_path}")
        print(f"Case name: {self.case_name}")
        
        # Scan directory tree
        self._scan_directory()
        
        # Calculate statistics
        self._calculate_stats()
        
        # Estimate costs
        self._estimate_costs()
        
        # Generate manifest
        manifest = self._generate_manifest()
        
        return manifest
    
    def _scan_directory(self):
        """Recursively scan directory tree."""
        for root, dirs, files in os.walk(self.base_path):
            # Calculate relative path for folder structure
            rel_root = Path(root).relative_to(self.base_path)
            
            for filename in files:
                # Skip hidden files and system files
                if filename.startswith('.') or filename.startswith('~'):
                    continue
                
                filepath = Path(root) / filename
                rel_path = filepath.relative_to(self.base_path)
                
                try:
                    file_info = self._analyze_file(filepath, rel_path)
                    if file_info:
                        self.files.append(file_info)
                except Exception as e:
                    self.errors.append({
                        'path': str(rel_path),
                        'error': str(e),
                        'type': type(e).__name__
                    })
    
    def _analyze_file(self, filepath: Path, rel_path: Path) -> Optional[Dict]:
        """Analyze a single file."""
        try:
            stat = filepath.stat()
            
            # Get file type
            mime_type = self.mime.from_file(str(filepath))
            
            # Fall back to mimetypes if magic fails
            if not mime_type or mime_type == 'application/octet-stream':
                mime_type, _ = mimetypes.guess_type(str(filepath))
            
            # Skip unsupported types
            if mime_type not in FILE_TYPE_CONFIG:
                self.stats['unsupported_files'] += 1
                return None
            
            # Get file hash for deduplication
            file_hash = self._calculate_hash(filepath)
            
            # Determine folder category from path
            folder_category = self._categorize_folder(rel_path)
            
            file_info = {
                'filename': filepath.name,
                'path': str(rel_path),
                'folder_category': folder_category,
                'size_bytes': stat.st_size,
                'mime_type': mime_type,
                'processor': FILE_TYPE_CONFIG[mime_type]['processor'],
                'requires_ocr': FILE_TYPE_CONFIG[mime_type]['requires_ocr'],
                'modified_time': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'file_hash': file_hash,
                'estimated_pages': self._estimate_pages(stat.st_size, mime_type)
            }
            
            return file_info
            
        except Exception as e:
            raise Exception(f"Error analyzing {filepath}: {str(e)}")
    
    def _calculate_hash(self, filepath: Path, chunk_size: int = 8192) -> str:
        """Calculate SHA-256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    def _categorize_folder(self, rel_path: Path) -> str:
        """Categorize folder based on path structure."""
        parts = rel_path.parts
        if not parts:
            return 'root'
        
        # Common legal document categories
        folder_name = parts[0].lower()
        
        if 'plead' in folder_name:
            return 'pleadings'
        elif 'medical' in folder_name or 'health' in folder_name:
            return 'medical_records'
        elif 'discovery' in folder_name:
            return 'discovery'
        elif 'correspondence' in folder_name:
            return 'correspondence'
        elif 'exhibit' in folder_name:
            return 'exhibits'
        elif 'depo' in folder_name:
            return 'depositions'
        elif 'expert' in folder_name:
            return 'expert_reports'
        elif 'financial' in folder_name:
            return 'financial_records'
        else:
            return 'miscellaneous'
    
    def _estimate_pages(self, size_bytes: int, mime_type: str) -> int:
        """Estimate number of pages based on file size and type."""
        size_mb = size_bytes / (1024 * 1024)
        config = FILE_TYPE_CONFIG.get(mime_type, {})
        avg_pages_per_mb = config.get('avg_pages_per_mb', 10)
        return max(1, int(size_mb * avg_pages_per_mb))
    
    def _calculate_stats(self):
        """Calculate statistics from analyzed files."""
        self.stats['total_files'] = len(self.files)
        self.stats['total_errors'] = len(self.errors)
        self.stats['total_size_bytes'] = sum(f['size_bytes'] for f in self.files)
        self.stats['total_size_gb'] = self.stats['total_size_bytes'] / (1024**3)
        
        # Count by type
        type_counts = defaultdict(int)
        for f in self.files:
            type_counts[f['mime_type']] += 1
        self.stats['file_types'] = dict(type_counts)
        
        # Count by processor
        processor_counts = defaultdict(int)
        for f in self.files:
            processor_counts[f['processor']] += 1
        self.stats['processors'] = dict(processor_counts)
        
        # Count by folder category
        category_counts = defaultdict(int)
        for f in self.files:
            category_counts[f['folder_category']] += 1
        self.stats['categories'] = dict(category_counts)
        
        # Find duplicates
        hash_counts = defaultdict(list)
        for f in self.files:
            hash_counts[f['file_hash']].append(f['path'])
        
        duplicates = {h: paths for h, paths in hash_counts.items() if len(paths) > 1}
        self.stats['duplicate_count'] = sum(len(paths) - 1 for paths in duplicates.values())
        self.stats['unique_files'] = len(hash_counts)
    
    def _estimate_costs(self):
        """Estimate processing costs."""
        # Textract costs
        textract_pages = sum(
            f['estimated_pages'] 
            for f in self.files 
            if f['requires_ocr']
        )
        self.cost_breakdown['textract'] = textract_pages * COST_ESTIMATES['textract_per_page']
        
        # OpenAI costs (rough estimates)
        # Assume ~500 tokens per page for extraction, 100 tokens for embeddings
        total_pages = sum(f['estimated_pages'] for f in self.files)
        extraction_tokens = total_pages * 500
        embedding_tokens = total_pages * 100
        
        self.cost_breakdown['openai_extraction'] = (
            extraction_tokens / 1000 * COST_ESTIMATES['openai_gpt4_per_1k_tokens']
        )
        self.cost_breakdown['openai_embeddings'] = (
            embedding_tokens / 1000 * COST_ESTIMATES['openai_embedding_per_1k_tokens']
        )
        
        # S3 costs
        self.cost_breakdown['s3_storage_monthly'] = (
            self.stats['total_size_gb'] * COST_ESTIMATES['s3_storage_per_gb_month']
        )
        self.cost_breakdown['s3_uploads'] = (
            self.stats['total_files'] / 1000 * COST_ESTIMATES['s3_put_per_1k']
        )
        
        # Total estimated cost
        self.cost_breakdown['total_processing'] = sum([
            self.cost_breakdown['textract'],
            self.cost_breakdown['openai_extraction'],
            self.cost_breakdown['openai_embeddings'],
            self.cost_breakdown['s3_uploads']
        ])
        
        self.cost_breakdown['total_monthly'] = (
            self.cost_breakdown['total_processing'] + 
            self.cost_breakdown['s3_storage_monthly']
        )
    
    def _generate_manifest(self) -> Dict:
        """Generate import manifest."""
        return {
            'metadata': {
                'case_name': self.case_name,
                'base_path': str(self.base_path),
                'analysis_timestamp': datetime.now().isoformat(),
                'analyzer_version': '1.0.0'
            },
            'statistics': dict(self.stats),
            'cost_estimates': dict(self.cost_breakdown),
            'files': self.files,
            'errors': self.errors,
            'import_config': {
                'batch_size': 50,
                'concurrent_workers': 4,
                'retry_attempts': 3,
                'processing_order': [
                    'pleadings',
                    'medical_records',
                    'discovery',
                    'depositions',
                    'expert_reports',
                    'correspondence',
                    'exhibits',
                    'financial_records',
                    'miscellaneous'
                ]
            }
        }
    
    def save_manifest(self, output_path: str):
        """Save manifest to JSON file."""
        manifest = self._generate_manifest()
        
        with open(output_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        print(f"Manifest saved to: {output_path}")
        return manifest
    
    def print_summary(self):
        """Print analysis summary."""
        print("\n" + "="*60)
        print(f"FILE ANALYSIS SUMMARY - {self.case_name}")
        print("="*60)
        
        print(f"\nTotal files: {self.stats['total_files']:,}")
        print(f"Unique files: {self.stats['unique_files']:,}")
        print(f"Duplicates: {self.stats['duplicate_count']:,}")
        print(f"Total size: {self.stats['total_size_gb']:.2f} GB")
        print(f"Errors encountered: {self.stats['total_errors']}")
        
        print("\nFiles by type:")
        for mime_type, count in sorted(self.stats['file_types'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {mime_type}: {count}")
        
        print("\nFiles by category:")
        for category, count in sorted(self.stats['categories'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {category}: {count}")
        
        print("\nEstimated costs:")
        print(f"  Textract OCR: ${self.cost_breakdown['textract']:.2f}")
        print(f"  OpenAI extraction: ${self.cost_breakdown['openai_extraction']:.2f}")
        print(f"  OpenAI embeddings: ${self.cost_breakdown['openai_embeddings']:.2f}")
        print(f"  S3 uploads: ${self.cost_breakdown['s3_uploads']:.2f}")
        print(f"  Total processing: ${self.cost_breakdown['total_processing']:.2f}")
        print(f"  Monthly storage: ${self.cost_breakdown['s3_storage_monthly']:.2f}")
        
        print("\n" + "="*60)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze client files for import')
    parser.add_argument('path', help='Path to client files directory')
    parser.add_argument('--case-name', required=True, help='Case name for this import')
    parser.add_argument('--output', default='import_manifest.json', help='Output manifest file')
    
    args = parser.parse_args()
    
    # Create analyzer
    analyzer = ClientFileAnalyzer(args.path, args.case_name)
    
    # Run analysis
    manifest = analyzer.analyze()
    
    # Save manifest
    analyzer.save_manifest(args.output)
    
    # Print summary
    analyzer.print_summary()


if __name__ == '__main__':
    main()