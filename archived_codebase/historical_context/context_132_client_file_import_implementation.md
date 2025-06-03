# Context 132: Complete Client File Import Implementation Plan

## Overview
Implementation plan for importing the complete "Paul, Michael (Acuity)" legal case file containing 497 documents across 60+ nested directories. This $10M+ case requires meticulous document tracking, cost monitoring, and verification systems.

## Pre-Import Analysis
- **Total Documents**: 497 files (excluding hidden files)
- **File Types**: 
  - 201 PDFs (legal documents, policies, estimates)
  - 199 JPGs (property photos, damage documentation)
  - 41 PNGs (screenshots, digital photos)
  - 28 MOV videos (property walkthroughs)
  - 22 Word documents (drafts, correspondence)
  - 4 M4A audio files (calls, voicemails)
  - 1 HEIC image
- **Directory Depth**: Up to 5 levels deep
- **Special Patterns**: Numbered folders indicate chronological events

## Step-by-Step Implementation Guide

### Step 1: Database Cleanup and Backup
**Purpose**: Clear test data and create clean slate for production import

```bash
# 1.1 Create database backup record
python scripts/cleanup_database.py --stats > backup_stats_$(date +%Y%m%d_%H%M%S).json

# 1.2 Clear all test data (requires double confirmation)
python scripts/cleanup_database.py --all

# 1.3 Verify clean state
python scripts/cleanup_database.py --stats
```

### Step 2: Pre-Import File Analysis and Validation
**Purpose**: Create manifest and identify potential issues before import

Create `scripts/analyze_client_files.py`:

```python
#!/usr/bin/env python3
"""
Analyze client files for import readiness and create detailed manifest.
"""
import os
import sys
import json
import hashlib
import mimetypes
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple
import magic
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class ClientFileAnalyzer:
    """Analyze client file structure and create import manifest."""
    
    IGNORE_FILES = {'.DS_Store', 'Icon', 'Thumbs.db', '.gitkeep'}
    IGNORE_DIRS = {'.git', '__pycache__', 'node_modules'}
    
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.manifest = {
            'analysis_timestamp': datetime.now().isoformat(),
            'base_path': str(self.base_path),
            'client_name': None,
            'case_name': None,
            'total_files': 0,
            'total_size_bytes': 0,
            'file_types': defaultdict(int),
            'directory_structure': {},
            'files': [],
            'issues': [],
            'cost_estimate': {}
        }
        
    def analyze(self) -> Dict[str, Any]:
        """Perform complete analysis of client files."""
        print(f"Analyzing files in: {self.base_path}")
        
        # Extract client and case info from path
        self._extract_case_info()
        
        # Walk directory tree
        for root, dirs, files in os.walk(self.base_path):
            # Remove ignored directories
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]
            
            rel_path = os.path.relpath(root, self.base_path)
            level = len(Path(rel_path).parts) - 1 if rel_path != '.' else 0
            
            for file in files:
                if file in self.IGNORE_FILES:
                    continue
                    
                file_path = os.path.join(root, file)
                self._analyze_file(file_path, rel_path, level)
        
        # Calculate cost estimates
        self._estimate_costs()
        
        # Generate summary
        self._generate_summary()
        
        return self.manifest
    
    def _extract_case_info(self):
        """Extract client and case information from directory name."""
        # Example: "Paul, Michael (Acuity)"
        top_dir = list(self.base_path.iterdir())[0].name
        if '(' in top_dir and ')' in top_dir:
            client_name = top_dir.split('(')[0].strip()
            case_name = top_dir.split('(')[1].rstrip(')')
            self.manifest['client_name'] = client_name
            self.manifest['case_name'] = case_name
    
    def _analyze_file(self, file_path: str, rel_dir: str, depth: int):
        """Analyze individual file."""
        try:
            stat = os.stat(file_path)
            file_info = {
                'path': file_path,
                'relative_path': os.path.relpath(file_path, self.base_path),
                'directory': rel_dir,
                'depth': depth,
                'filename': os.path.basename(file_path),
                'size_bytes': stat.st_size,
                'modified_time': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'file_extension': Path(file_path).suffix.lower(),
                'mime_type': self._get_mime_type(file_path),
                'sha256_hash': self._calculate_hash(file_path),
                'issues': []
            }
            
            # Check for issues
            self._check_file_issues(file_info)
            
            # Update counters
            self.manifest['total_files'] += 1
            self.manifest['total_size_bytes'] += stat.st_size
            self.manifest['file_types'][file_info['file_extension']] += 1
            
            # Add to files list
            self.manifest['files'].append(file_info)
            
        except Exception as e:
            self.manifest['issues'].append({
                'file': file_path,
                'error': str(e),
                'type': 'analysis_error'
            })
    
    def _get_mime_type(self, file_path: str) -> str:
        """Get MIME type of file."""
        try:
            # Use python-magic for accurate detection
            mime = magic.from_file(file_path, mime=True)
            return mime
        except:
            # Fallback to mimetypes
            mime_type, _ = mimetypes.guess_type(file_path)
            return mime_type or 'application/octet-stream'
    
    def _calculate_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash for deduplication."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _check_file_issues(self, file_info: Dict[str, Any]):
        """Check for potential issues with file."""
        issues = []
        
        # Check file size
        if file_info['size_bytes'] > 100 * 1024 * 1024:  # 100MB
            issues.append({
                'type': 'large_file',
                'message': f"File exceeds 100MB ({file_info['size_bytes'] / 1024 / 1024:.1f}MB)"
            })
        
        # Check filename issues
        filename = file_info['filename']
        if len(filename) > 255:
            issues.append({
                'type': 'long_filename',
                'message': f"Filename exceeds 255 characters"
            })
        
        # Check for special characters that might cause issues
        if any(char in filename for char in ['#', '&', '?', '%']):
            issues.append({
                'type': 'special_characters',
                'message': f"Filename contains special characters that may cause issues"
            })
        
        # Check for zero-byte files
        if file_info['size_bytes'] == 0:
            issues.append({
                'type': 'empty_file',
                'message': 'File is empty (0 bytes)'
            })
        
        if issues:
            file_info['issues'] = issues
            self.manifest['issues'].extend([
                {**issue, 'file': file_info['relative_path']} 
                for issue in issues
            ])
    
    def _estimate_costs(self):
        """Estimate processing costs based on file types and sizes."""
        costs = {
            'ocr_cost': 0.0,  # Textract costs
            'embedding_cost': 0.0,  # OpenAI embedding costs
            'entity_extraction_cost': 0.0,  # OpenAI GPT-4 costs
            'storage_cost': 0.0,  # S3 storage costs
            'details': {}
        }
        
        # Textract pricing (per page)
        textract_price_per_page = 0.015  # $0.015 per page
        
        # OpenAI pricing
        gpt4_price_per_1k_tokens = 0.03  # GPT-4 input pricing
        embedding_price_per_1k_tokens = 0.0001  # text-embedding-3-large
        
        # Estimate pages and tokens by file type
        for file in self.manifest['files']:
            ext = file['file_extension']
            size_mb = file['size_bytes'] / (1024 * 1024)
            
            if ext == '.pdf':
                # Estimate ~50KB per page
                pages = max(1, file['size_bytes'] / (50 * 1024))
                costs['ocr_cost'] += pages * textract_price_per_page
                
                # Estimate tokens (roughly 500 tokens per page)
                tokens = pages * 500
                costs['entity_extraction_cost'] += (tokens / 1000) * gpt4_price_per_1k_tokens
                costs['embedding_cost'] += (tokens / 1000) * embedding_price_per_1k_tokens
                
            elif ext in ['.doc', '.docx']:
                # Estimate tokens from file size (roughly 1000 tokens per 5KB)
                tokens = file['size_bytes'] / 5000 * 1000
                costs['entity_extraction_cost'] += (tokens / 1000) * gpt4_price_per_1k_tokens
                costs['embedding_cost'] += (tokens / 1000) * embedding_price_per_1k_tokens
                
            elif ext in ['.jpg', '.png', '.heic']:
                # OCR cost for images
                costs['ocr_cost'] += textract_price_per_page
                
            elif ext in ['.mov', '.mp4']:
                # Transcription costs (if needed)
                # Placeholder for now
                pass
        
        # S3 storage cost (per GB per month)
        storage_gb = self.manifest['total_size_bytes'] / (1024**3)
        costs['storage_cost'] = storage_gb * 0.023  # $0.023 per GB per month
        
        # Add 20% buffer for retries and overhead
        for key in ['ocr_cost', 'embedding_cost', 'entity_extraction_cost']:
            costs[key] *= 1.2
        
        costs['total_estimated_cost'] = sum([
            costs['ocr_cost'],
            costs['embedding_cost'],
            costs['entity_extraction_cost'],
            costs['storage_cost']
        ])
        
        self.manifest['cost_estimate'] = costs
    
    def _generate_summary(self):
        """Generate analysis summary."""
        self.manifest['summary'] = {
            'total_files': self.manifest['total_files'],
            'total_size_mb': round(self.manifest['total_size_bytes'] / (1024**2), 2),
            'unique_file_types': len(self.manifest['file_types']),
            'total_issues': len(self.manifest['issues']),
            'estimated_processing_cost': round(
                self.manifest['cost_estimate']['total_estimated_cost'], 2
            ),
            'estimated_processing_time_hours': round(
                self.manifest['total_files'] * 0.5 / 60, 1  # ~30 seconds per file
            )
        }
    
    def save_manifest(self, output_path: str):
        """Save manifest to JSON file."""
        with open(output_path, 'w') as f:
            json.dump(self.manifest, f, indent=2, default=str)
        print(f"Manifest saved to: {output_path}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze client files for import")
    parser.add_argument('path', help="Path to client files directory")
    parser.add_argument('--output', '-o', default='client_file_manifest.json',
                       help="Output manifest file path")
    
    args = parser.parse_args()
    
    analyzer = ClientFileAnalyzer(args.path)
    manifest = analyzer.analyze()
    analyzer.save_manifest(args.output)
    
    # Print summary
    print("\n" + "="*60)
    print("ANALYSIS SUMMARY")
    print("="*60)
    for key, value in manifest['summary'].items():
        print(f"{key.replace('_', ' ').title()}: {value}")
```

### Step 3: Create Import Tracking System
**Purpose**: Track import progress and handle failures gracefully

Create `scripts/import_tracker.py`:

```python
#!/usr/bin/env python3
"""
Import tracking system for monitoring document processing status and costs.
"""
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
import uuid

class ImportTracker:
    """Track document import progress and costs."""
    
    def __init__(self, db_path: str = "import_tracking.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_database()
    
    def _init_database(self):
        """Initialize tracking database."""
        cursor = self.conn.cursor()
        
        # Import sessions table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS import_sessions (
            session_id TEXT PRIMARY KEY,
            client_name TEXT,
            case_name TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            status TEXT,
            total_files INTEGER,
            processed_files INTEGER,
            failed_files INTEGER,
            total_cost REAL,
            manifest_path TEXT,
            notes TEXT
        )
        """)
        
        # Document tracking table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            file_path TEXT,
            file_hash TEXT,
            document_uuid TEXT,
            supabase_id INTEGER,
            status TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            processing_time_seconds REAL,
            retry_count INTEGER DEFAULT 0,
            error_message TEXT,
            cost_breakdown TEXT,
            FOREIGN KEY (session_id) REFERENCES import_sessions(session_id)
        )
        """)
        
        # Cost tracking table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS import_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            document_id INTEGER,
            operation TEXT,
            provider TEXT,
            units REAL,
            unit_cost REAL,
            total_cost REAL,
            timestamp TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES import_sessions(session_id),
            FOREIGN KEY (document_id) REFERENCES document_imports(id)
        )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_session ON document_imports(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_status ON document_imports(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_hash ON document_imports(file_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cost_session ON import_costs(session_id)")
        
        self.conn.commit()
    
    def start_import_session(self, client_name: str, case_name: str, 
                           total_files: int, manifest_path: str) -> str:
        """Start a new import session."""
        session_id = str(uuid.uuid4())
        
        cursor = self.conn.cursor()
        cursor.execute("""
        INSERT INTO import_sessions (
            session_id, client_name, case_name, started_at, status,
            total_files, processed_files, failed_files, total_cost,
            manifest_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, client_name, case_name, datetime.now(), 'in_progress',
            total_files, 0, 0, 0.0, manifest_path
        ))
        self.conn.commit()
        
        return session_id
    
    def track_document_start(self, session_id: str, file_path: str, 
                           file_hash: str) -> int:
        """Track start of document processing."""
        cursor = self.conn.cursor()
        cursor.execute("""
        INSERT INTO document_imports (
            session_id, file_path, file_hash, status, started_at
        ) VALUES (?, ?, ?, ?, ?)
        """, (session_id, file_path, file_hash, 'processing', datetime.now()))
        self.conn.commit()
        
        return cursor.lastrowid
    
    def track_document_complete(self, doc_id: int, document_uuid: str, 
                              supabase_id: int, processing_time: float,
                              cost_breakdown: Dict[str, float]):
        """Track successful document completion."""
        cursor = self.conn.cursor()
        cursor.execute("""
        UPDATE document_imports SET
            document_uuid = ?,
            supabase_id = ?,
            status = 'completed',
            completed_at = ?,
            processing_time_seconds = ?,
            cost_breakdown = ?
        WHERE id = ?
        """, (
            document_uuid, supabase_id, datetime.now(), 
            processing_time, json.dumps(cost_breakdown), doc_id
        ))
        
        # Update session counters
        cursor.execute("""
        UPDATE import_sessions SET
            processed_files = processed_files + 1
        WHERE session_id = (
            SELECT session_id FROM document_imports WHERE id = ?
        )
        """, (doc_id,))
        
        self.conn.commit()
    
    def track_document_error(self, doc_id: int, error_message: str):
        """Track document processing error."""
        cursor = self.conn.cursor()
        
        # Update document status
        cursor.execute("""
        UPDATE document_imports SET
            status = 'failed',
            completed_at = ?,
            error_message = ?,
            retry_count = retry_count + 1
        WHERE id = ?
        """, (datetime.now(), error_message, doc_id))
        
        # Update session counters
        cursor.execute("""
        UPDATE import_sessions SET
            failed_files = failed_files + 1
        WHERE session_id = (
            SELECT session_id FROM document_imports WHERE id = ?
        )
        """, (doc_id,))
        
        self.conn.commit()
    
    def track_cost(self, session_id: str, doc_id: Optional[int],
                  operation: str, provider: str, units: float,
                  unit_cost: float):
        """Track operation cost."""
        total_cost = units * unit_cost
        
        cursor = self.conn.cursor()
        cursor.execute("""
        INSERT INTO import_costs (
            session_id, document_id, operation, provider,
            units, unit_cost, total_cost, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, doc_id, operation, provider,
            units, unit_cost, total_cost, datetime.now()
        ))
        
        # Update session total
        cursor.execute("""
        UPDATE import_sessions SET
            total_cost = (
                SELECT SUM(total_cost) FROM import_costs 
                WHERE session_id = ?
            )
        WHERE session_id = ?
        """, (session_id, session_id))
        
        self.conn.commit()
    
    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get current session status."""
        cursor = self.conn.cursor()
        
        # Get session info
        cursor.execute("""
        SELECT * FROM import_sessions WHERE session_id = ?
        """, (session_id,))
        session = dict(cursor.fetchone())
        
        # Get document statistics
        cursor.execute("""
        SELECT 
            status,
            COUNT(*) as count,
            AVG(processing_time_seconds) as avg_time
        FROM document_imports
        WHERE session_id = ?
        GROUP BY status
        """, (session_id,))
        
        session['document_stats'] = {
            row['status']: {
                'count': row['count'],
                'avg_time': row['avg_time']
            }
            for row in cursor.fetchall()
        }
        
        # Get cost breakdown
        cursor.execute("""
        SELECT 
            operation,
            provider,
            SUM(total_cost) as total
        FROM import_costs
        WHERE session_id = ?
        GROUP BY operation, provider
        """, (session_id,))
        
        session['cost_breakdown'] = [
            dict(row) for row in cursor.fetchall()
        ]
        
        return session
    
    def get_failed_documents(self, session_id: str) -> List[Dict[str, Any]]:
        """Get list of failed documents for retry."""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT * FROM document_imports
        WHERE session_id = ? AND status = 'failed'
        ORDER BY retry_count ASC, id ASC
        """, (session_id,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def complete_session(self, session_id: str, notes: str = None):
        """Mark session as complete."""
        cursor = self.conn.cursor()
        cursor.execute("""
        UPDATE import_sessions SET
            status = 'completed',
            completed_at = ?,
            notes = ?
        WHERE session_id = ?
        """, (datetime.now(), notes, session_id))
        self.conn.commit()
    
    def generate_report(self, session_id: str) -> Dict[str, Any]:
        """Generate comprehensive import report."""
        session = self.get_session_status(session_id)
        
        # Add detailed failure analysis
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT 
            error_message,
            COUNT(*) as count,
            GROUP_CONCAT(file_path) as files
        FROM document_imports
        WHERE session_id = ? AND status = 'failed'
        GROUP BY error_message
        """, (session_id,))
        
        session['failure_analysis'] = [
            dict(row) for row in cursor.fetchall()
        ]
        
        return session
```

### Step 4: Implement Batch Import with Progress Monitoring
**Purpose**: Import documents with real-time progress and error handling

Create `scripts/import_client_files.py`:

```python
#!/usr/bin/env python3
"""
Import client files with comprehensive tracking and error handling.
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import concurrent.futures
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.celery_submission import submit_document_to_celery
from scripts.import_tracker import ImportTracker
from scripts.redis_utils import get_redis_manager
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ClientFileImporter:
    """Import client files with tracking and verification."""
    
    def __init__(self, manifest_path: str, project_name: str = None):
        self.manifest = self._load_manifest(manifest_path)
        self.project_name = project_name or f"{self.manifest['client_name']} - {self.manifest['case_name']}"
        self.db_manager = SupabaseManager()
        self.tracker = ImportTracker()
        self.redis_mgr = get_redis_manager()
        self.session_id = None
        self.project_id = None
        self.project_uuid = None
        
    def _load_manifest(self, manifest_path: str) -> Dict[str, Any]:
        """Load import manifest."""
        with open(manifest_path, 'r') as f:
            return json.load(f)
    
    def import_all(self, max_concurrent: int = 5, dry_run: bool = False):
        """Import all files from manifest."""
        print(f"\n{'='*60}")
        print(f"CLIENT FILE IMPORT")
        print(f"{'='*60}")
        print(f"Client: {self.manifest['client_name']}")
        print(f"Case: {self.manifest['case_name']}")
        print(f"Total Files: {self.manifest['total_files']}")
        print(f"Estimated Cost: ${self.manifest['cost_estimate']['total_estimated_cost']:.2f}")
        print(f"{'='*60}\n")
        
        if dry_run:
            print("DRY RUN MODE - No actual imports will be performed")
            return
        
        # Start import session
        self.session_id = self.tracker.start_import_session(
            client_name=self.manifest['client_name'],
            case_name=self.manifest['case_name'],
            total_files=self.manifest['total_files'],
            manifest_path=self.manifest.get('manifest_path', 'unknown')
        )
        
        # Create or get project
        self._setup_project()
        
        # Import files in batches
        self._import_files_batch(max_concurrent)
        
        # Handle any failures
        self._handle_failures()
        
        # Complete session
        self.tracker.complete_session(self.session_id)
        
        # Generate and display report
        self._generate_report()
    
    def _setup_project(self):
        """Create or retrieve project."""
        logger.info(f"Setting up project: {self.project_name}")
        
        # Generate project UUID from name (consistent across runs)
        import hashlib
        project_uuid = hashlib.md5(self.project_name.encode()).hexdigest()
        
        self.project_id, self.project_uuid = self.db_manager.get_or_create_project(
            project_id=project_uuid,
            name=self.project_name
        )
        
        logger.info(f"Using project ID: {self.project_id}, UUID: {self.project_uuid}")
    
    def _import_files_batch(self, max_concurrent: int):
        """Import files in concurrent batches."""
        files_to_import = self.manifest['files']
        
        # Check for duplicates
        logger.info("Checking for existing documents...")
        files_to_import = self._filter_existing_documents(files_to_import)
        
        if not files_to_import:
            logger.info("All files already imported!")
            return
        
        logger.info(f"Importing {len(files_to_import)} new files...")
        
        # Progress bar
        pbar = tqdm(total=len(files_to_import), desc="Importing files")
        
        # Process in batches
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # Submit initial batch
            futures = {
                executor.submit(self._import_single_file, file_info): file_info
                for file_info in files_to_import[:max_concurrent]
            }
            
            remaining = files_to_import[max_concurrent:]
            
            while futures:
                # Wait for any future to complete
                done, pending = concurrent.futures.wait(
                    futures, return_when=concurrent.futures.FIRST_COMPLETED
                )
                
                # Process completed
                for future in done:
                    file_info = futures.pop(future)
                    try:
                        result = future.result()
                        pbar.update(1)
                    except Exception as e:
                        logger.error(f"Failed to import {file_info['filename']}: {e}")
                        pbar.update(1)
                    
                    # Submit next file if any remaining
                    if remaining:
                        next_file = remaining.pop(0)
                        new_future = executor.submit(self._import_single_file, next_file)
                        futures[new_future] = next_file
        
        pbar.close()
    
    def _filter_existing_documents(self, files: List[Dict]) -> List[Dict]:
        """Filter out already imported documents."""
        # Get existing hashes
        existing_hashes = set()
        
        try:
            result = self.db_manager.client.table('source_documents').select(
                'original_file_path'
            ).eq('project_fk_id', self.project_id).execute()
            
            existing_paths = {doc['original_file_path'] for doc in result.data}
            
            # Filter files
            new_files = []
            for file_info in files:
                if file_info['path'] not in existing_paths:
                    new_files.append(file_info)
                else:
                    logger.debug(f"Skipping existing file: {file_info['filename']}")
            
            logger.info(f"Found {len(files) - len(new_files)} existing documents to skip")
            return new_files
            
        except Exception as e:
            logger.warning(f"Could not check existing documents: {e}")
            return files
    
    def _import_single_file(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """Import a single file."""
        start_time = time.time()
        
        # Track in database
        doc_track_id = self.tracker.track_document_start(
            session_id=self.session_id,
            file_path=file_info['path'],
            file_hash=file_info['sha256_hash']
        )
        
        try:
            # Create document entry
            doc_id, doc_uuid = self.db_manager.create_source_document_entry(
                project_fk_id=self.project_id,
                project_uuid=self.project_uuid,
                original_file_path=file_info['path'],
                original_file_name=file_info['filename'],
                detected_file_type=file_info['file_extension']
            )
            
            # Submit to Celery
            celery_task_id, success = submit_document_to_celery(
                document_id=doc_id,
                document_uuid=doc_uuid,
                file_path=file_info['path'],
                file_type=file_info['file_extension'].lstrip('.'),
                file_name=file_info['filename'],
                project_sql_id=self.project_id
            )
            
            if not success:
                raise Exception("Failed to submit to Celery")
            
            # Track completion
            processing_time = time.time() - start_time
            
            # Estimate costs (simplified)
            cost_breakdown = self._estimate_file_cost(file_info)
            
            self.tracker.track_document_complete(
                doc_id=doc_track_id,
                document_uuid=doc_uuid,
                supabase_id=doc_id,
                processing_time=processing_time,
                cost_breakdown=cost_breakdown
            )
            
            # Track individual costs
            for operation, cost in cost_breakdown.items():
                if cost > 0:
                    self.tracker.track_cost(
                        session_id=self.session_id,
                        doc_id=doc_track_id,
                        operation=operation,
                        provider=self._get_provider_for_operation(operation),
                        units=1,  # Simplified
                        unit_cost=cost
                    )
            
            return {
                'success': True,
                'document_uuid': doc_uuid,
                'celery_task_id': celery_task_id,
                'processing_time': processing_time
            }
            
        except Exception as e:
            # Track error
            self.tracker.track_document_error(
                doc_id=doc_track_id,
                error_message=str(e)
            )
            raise
    
    def _estimate_file_cost(self, file_info: Dict[str, Any]) -> Dict[str, float]:
        """Estimate processing cost for a file."""
        costs = {
            'ocr': 0.0,
            'embedding': 0.0,
            'entity_extraction': 0.0,
            'storage': 0.0
        }
        
        ext = file_info['file_extension']
        size_bytes = file_info['size_bytes']
        
        if ext == '.pdf':
            pages = max(1, size_bytes / (50 * 1024))
            costs['ocr'] = pages * 0.015
            costs['entity_extraction'] = pages * 0.015
            costs['embedding'] = pages * 0.0001
        elif ext in ['.jpg', '.png']:
            costs['ocr'] = 0.015
        elif ext in ['.doc', '.docx']:
            costs['entity_extraction'] = 0.01
            costs['embedding'] = 0.0001
        
        costs['storage'] = (size_bytes / (1024**3)) * 0.023
        
        return costs
    
    def _get_provider_for_operation(self, operation: str) -> str:
        """Get provider name for operation."""
        providers = {
            'ocr': 'AWS Textract',
            'embedding': 'OpenAI',
            'entity_extraction': 'OpenAI',
            'storage': 'AWS S3'
        }
        return providers.get(operation, 'Unknown')
    
    def _handle_failures(self):
        """Handle failed imports with retry."""
        failed_docs = self.tracker.get_failed_documents(self.session_id)
        
        if not failed_docs:
            return
        
        logger.warning(f"Found {len(failed_docs)} failed documents")
        
        # Retry failed documents (up to 3 times)
        for doc in failed_docs:
            if doc['retry_count'] >= 3:
                logger.error(f"Max retries exceeded for: {doc['file_path']}")
                continue
            
            logger.info(f"Retrying: {doc['file_path']}")
            
            # Find file info
            file_info = next(
                (f for f in self.manifest['files'] if f['path'] == doc['file_path']),
                None
            )
            
            if file_info:
                try:
                    self._import_single_file(file_info)
                except Exception as e:
                    logger.error(f"Retry failed: {e}")
    
    def _generate_report(self):
        """Generate and display import report."""
        report = self.tracker.generate_report(self.session_id)
        
        print(f"\n{'='*60}")
        print("IMPORT REPORT")
        print(f"{'='*60}")
        print(f"Session ID: {report['session_id']}")
        print(f"Status: {report['status']}")
        print(f"Duration: {report.get('duration', 'N/A')}")
        print(f"\nFiles:")
        print(f"  Total: {report['total_files']}")
        print(f"  Processed: {report['processed_files']}")
        print(f"  Failed: {report['failed_files']}")
        
        print(f"\nCost Breakdown:")
        total_cost = 0
        for cost in report['cost_breakdown']:
            print(f"  {cost['operation']} ({cost['provider']}): ${cost['total']:.4f}")
            total_cost += cost['total']
        print(f"  TOTAL: ${total_cost:.4f}")
        
        if report.get('failure_analysis'):
            print(f"\nFailure Analysis:")
            for failure in report['failure_analysis']:
                print(f"  {failure['error_message']}: {failure['count']} files")
        
        # Save report
        report_path = f"import_report_{self.session_id}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nDetailed report saved to: {report_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import client files")
    parser.add_argument('manifest', help="Path to import manifest JSON")
    parser.add_argument('--project-name', help="Override project name")
    parser.add_argument('--max-concurrent', type=int, default=5,
                       help="Maximum concurrent imports")
    parser.add_argument('--dry-run', action='store_true',
                       help="Perform dry run without actual imports")
    
    args = parser.parse_args()
    
    importer = ClientFileImporter(args.manifest, args.project_name)
    importer.import_all(
        max_concurrent=args.max_concurrent,
        dry_run=args.dry_run
    )
```

### Step 5: Create Live Cost Dashboard
**Purpose**: Real-time monitoring of import progress and costs

Create `scripts/import_dashboard.py`:

```python
#!/usr/bin/env python3
"""
Live dashboard for monitoring import progress and costs.
"""
import os
import sys
import time
import curses
from datetime import datetime
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.import_tracker import ImportTracker

class ImportDashboard:
    """Live dashboard for import monitoring."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.tracker = ImportTracker()
        
    def run(self, stdscr):
        """Run the dashboard."""
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(1)   # Non-blocking input
        
        while True:
            # Clear screen
            stdscr.clear()
            
            # Get current status
            status = self.tracker.get_session_status(self.session_id)
            
            # Draw dashboard
            self._draw_header(stdscr, status)
            self._draw_progress(stdscr, status, 5)
            self._draw_costs(stdscr, status, 12)
            self._draw_performance(stdscr, status, 20)
            
            # Refresh
            stdscr.refresh()
            
            # Check for quit
            key = stdscr.getch()
            if key == ord('q'):
                break
            
            # Update every second
            time.sleep(1)
    
    def _draw_header(self, stdscr, status: Dict[str, Any]):
        """Draw header section."""
        h, w = stdscr.getmaxyx()
        
        # Title
        title = f"IMPORT DASHBOARD - {status['client_name']} - {status['case_name']}"
        stdscr.addstr(0, (w - len(title)) // 2, title, curses.A_BOLD)
        
        # Session info
        stdscr.addstr(2, 2, f"Session ID: {status['session_id']}")
        stdscr.addstr(2, w // 2, f"Status: {status['status'].upper()}")
        
        # Divider
        stdscr.addstr(3, 0, "=" * w)
    
    def _draw_progress(self, stdscr, status: Dict[str, Any], start_row: int):
        """Draw progress section."""
        h, w = stdscr.getmaxyx()
        
        stdscr.addstr(start_row, 2, "FILE PROGRESS", curses.A_BOLD)
        
        # Progress bar
        total = status['total_files']
        processed = status['processed_files']
        failed = status['failed_files']
        
        if total > 0:
            progress = processed / total
            bar_width = w - 10
            filled = int(bar_width * progress)
            
            # Draw bar
            stdscr.addstr(start_row + 2, 2, "[")
            stdscr.addstr(start_row + 2, 3, "=" * filled, curses.A_REVERSE)
            stdscr.addstr(start_row + 2, 3 + filled, " " * (bar_width - filled))
            stdscr.addstr(start_row + 2, 3 + bar_width, "]")
            stdscr.addstr(start_row + 2, 5 + bar_width, f" {progress*100:.1f}%")
        
        # Stats
        stdscr.addstr(start_row + 4, 2, f"Total: {total}")
        stdscr.addstr(start_row + 4, 20, f"Processed: {processed}")
        stdscr.addstr(start_row + 4, 40, f"Failed: {failed}")
        
        # Document status breakdown
        if 'document_stats' in status:
            row = start_row + 6
            for stat_status, stats in status['document_stats'].items():
                stdscr.addstr(row, 2, f"{stat_status}: {stats['count']}")
                if stats['avg_time']:
                    stdscr.addstr(row, 25, f"(avg: {stats['avg_time']:.1f}s)")
                row += 1
    
    def _draw_costs(self, stdscr, status: Dict[str, Any], start_row: int):
        """Draw costs section."""
        h, w = stdscr.getmaxyx()
        
        stdscr.addstr(start_row, 2, "COST TRACKING", curses.A_BOLD)
        
        # Cost breakdown
        row = start_row + 2
        total_cost = 0
        
        for cost in status.get('cost_breakdown', []):
            operation = cost['operation']
            provider = cost['provider']
            amount = cost['total']
            total_cost += amount
            
            stdscr.addstr(row, 2, f"{operation} ({provider}):")
            stdscr.addstr(row, 40, f"${amount:.4f}")
            row += 1
        
        # Total
        stdscr.addstr(row + 1, 2, "TOTAL COST:", curses.A_BOLD)
        stdscr.addstr(row + 1, 40, f"${total_cost:.4f}", curses.A_BOLD)
    
    def _draw_performance(self, stdscr, status: Dict[str, Any], start_row: int):
        """Draw performance metrics."""
        h, w = stdscr.getmaxyx()
        
        stdscr.addstr(start_row, 2, "PERFORMANCE METRICS", curses.A_BOLD)
        
        # Calculate rates
        if status.get('started_at') and status['processed_files'] > 0:
            start_time = datetime.fromisoformat(status['started_at'])
            elapsed = (datetime.now() - start_time).total_seconds()
            
            if elapsed > 0:
                files_per_min = (status['processed_files'] / elapsed) * 60
                cost_per_file = status.get('total_cost', 0) / status['processed_files']
                
                stdscr.addstr(start_row + 2, 2, f"Files/min: {files_per_min:.1f}")
                stdscr.addstr(start_row + 3, 2, f"Cost/file: ${cost_per_file:.4f}")
                
                # ETA
                remaining = status['total_files'] - status['processed_files']
                if files_per_min > 0:
                    eta_minutes = remaining / files_per_min
                    stdscr.addstr(start_row + 4, 2, f"ETA: {eta_minutes:.0f} minutes")
        
        # Footer
        stdscr.addstr(h - 2, 2, "Press 'q' to quit")

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Import progress dashboard")
    parser.add_argument('session_id', help="Import session ID to monitor")
    
    args = parser.parse_args()
    
    dashboard = ImportDashboard(args.session_id)
    curses.wrapper(dashboard.run)

if __name__ == "__main__":
    main()
```

### Step 6: Create Verification and Validation System
**Purpose**: Ensure all documents are properly imported and linked

Create `scripts/verify_import.py`:

```python
#!/usr/bin/env python3
"""
Verify and validate document imports.
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Any, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.import_tracker import ImportTracker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ImportVerifier:
    """Verify document imports are complete and correct."""
    
    def __init__(self, session_id: str, manifest_path: str):
        self.session_id = session_id
        self.manifest = self._load_manifest(manifest_path)
        self.db_manager = SupabaseManager()
        self.tracker = ImportTracker()
        self.verification_results = {
            'session_id': session_id,
            'timestamp': datetime.now().isoformat(),
            'total_files_expected': len(self.manifest['files']),
            'total_files_found': 0,
            'missing_files': [],
            'duplicate_files': [],
            'processing_errors': [],
            'integrity_checks': {},
            'recommendations': []
        }
    
    def _load_manifest(self, manifest_path: str) -> Dict[str, Any]:
        """Load import manifest."""
        with open(manifest_path, 'r') as f:
            return json.load(f)
    
    def verify_all(self) -> Dict[str, Any]:
        """Perform complete verification."""
        logger.info("Starting import verification...")
        
        # Get session info
        session_info = self.tracker.get_session_status(self.session_id)
        project_id = self._get_project_id(session_info)
        
        # Verify file completeness
        self._verify_file_completeness(project_id)
        
        # Check for duplicates
        self._check_duplicates(project_id)
        
        # Verify processing status
        self._verify_processing_status(project_id)
        
        # Check data integrity
        self._check_data_integrity(project_id)
        
        # Generate recommendations
        self._generate_recommendations()
        
        return self.verification_results
    
    def _get_project_id(self, session_info: Dict[str, Any]) -> int:
        """Get project ID from session."""
        # Get from first successfully imported document
        cursor = self.tracker.conn.cursor()
        cursor.execute("""
        SELECT supabase_id FROM document_imports
        WHERE session_id = ? AND status = 'completed'
        LIMIT 1
        """, (self.session_id,))
        
        result = cursor.fetchone()
        if result:
            doc_id = result[0]
            # Get project from document
            doc_result = self.db_manager.client.table('source_documents').select(
                'project_fk_id'
            ).eq('id', doc_id).single().execute()
            
            if doc_result.data:
                return doc_result.data['project_fk_id']
        
        raise ValueError("Could not determine project ID from session")
    
    def _verify_file_completeness(self, project_id: int):
        """Verify all expected files are imported."""
        logger.info("Verifying file completeness...")
        
        # Get all imported files for project
        result = self.db_manager.client.table('source_documents').select(
            'original_file_path', 'document_uuid', 'celery_status'
        ).eq('project_fk_id', project_id).execute()
        
        imported_files = {doc['original_file_path']: doc for doc in result.data}
        self.verification_results['total_files_found'] = len(imported_files)
        
        # Check each expected file
        for file_info in self.manifest['files']:
            file_path = file_info['path']
            
            if file_path not in imported_files:
                self.verification_results['missing_files'].append({
                    'path': file_path,
                    'relative_path': file_info['relative_path'],
                    'size': file_info['size_bytes'],
                    'type': file_info['file_extension']
                })
            else:
                # Check processing status
                doc = imported_files[file_path]
                if doc['celery_status'] != 'completed':
                    self.verification_results['processing_errors'].append({
                        'path': file_path,
                        'document_uuid': doc['document_uuid'],
                        'status': doc['celery_status']
                    })
    
    def _check_duplicates(self, project_id: int):
        """Check for duplicate imports."""
        logger.info("Checking for duplicates...")
        
        # Get all documents with counts by original path
        result = self.db_manager.client.rpc(
            'get_duplicate_documents',
            {'project_id': project_id}
        ).execute()
        
        # Note: You'll need to create this database function
        # For now, do it in Python
        result = self.db_manager.client.table('source_documents').select(
            'original_file_path', 'document_uuid', 'created_at'
        ).eq('project_fk_id', project_id).order('original_file_path', 'created_at').execute()
        
        # Group by path
        path_groups = {}
        for doc in result.data:
            path = doc['original_file_path']
            if path not in path_groups:
                path_groups[path] = []
            path_groups[path].append(doc)
        
        # Find duplicates
        for path, docs in path_groups.items():
            if len(docs) > 1:
                self.verification_results['duplicate_files'].append({
                    'path': path,
                    'count': len(docs),
                    'document_uuids': [d['document_uuid'] for d in docs],
                    'created_dates': [d['created_at'] for d in docs]
                })
    
    def _verify_processing_status(self, project_id: int):
        """Verify processing completion."""
        logger.info("Verifying processing status...")
        
        # Check each processing stage
        stages = [
            'neo4j_documents',
            'neo4j_chunks', 
            'neo4j_entity_mentions',
            'neo4j_canonical_entities',
            'neo4j_relationships_staging'
        ]
        
        processing_stats = {}
        
        for stage in stages:
            if stage == 'neo4j_documents':
                result = self.db_manager.client.table(stage).select(
                    'count'
                ).eq('source_document_fk_id', 
                    self.db_manager.client.table('source_documents').select('id').eq(
                        'project_fk_id', project_id
                    )
                ).execute()
            else:
                # Need to join through neo4j_documents
                # Simplified for now
                result = self.db_manager.client.table(stage).select('count').execute()
            
            processing_stats[stage] = len(result.data) if result.data else 0
        
        self.verification_results['integrity_checks']['processing_stages'] = processing_stats
    
    def _check_data_integrity(self, project_id: int):
        """Check data integrity."""
        logger.info("Checking data integrity...")
        
        integrity_checks = {}
        
        # Check for orphaned records
        # Check for missing relationships
        # Check for invalid data
        
        # Example: Check for chunks without documents
        chunks_result = self.db_manager.client.table('neo4j_chunks').select(
            'document_uuid'
        ).execute()
        
        doc_uuids_result = self.db_manager.client.table('source_documents').select(
            'document_uuid'
        ).eq('project_fk_id', project_id).execute()
        
        chunk_doc_uuids = {c['document_uuid'] for c in chunks_result.data}
        valid_doc_uuids = {d['document_uuid'] for d in doc_uuids_result.data}
        
        orphaned_chunks = chunk_doc_uuids - valid_doc_uuids
        if orphaned_chunks:
            integrity_checks['orphaned_chunks'] = list(orphaned_chunks)
        
        self.verification_results['integrity_checks'].update(integrity_checks)
    
    def _generate_recommendations(self):
        """Generate recommendations based on verification."""
        recommendations = []
        
        # Missing files
        if self.verification_results['missing_files']:
            count = len(self.verification_results['missing_files'])
            recommendations.append({
                'priority': 'HIGH',
                'issue': f"{count} files failed to import",
                'action': "Re-run import for missing files using --retry-failed flag"
            })
        
        # Processing errors
        if self.verification_results['processing_errors']:
            count = len(self.verification_results['processing_errors'])
            recommendations.append({
                'priority': 'HIGH',
                'issue': f"{count} files have processing errors",
                'action': "Check Celery logs and retry processing"
            })
        
        # Duplicates
        if self.verification_results['duplicate_files']:
            count = len(self.verification_results['duplicate_files'])
            recommendations.append({
                'priority': 'MEDIUM',
                'issue': f"{count} files have duplicates",
                'action': "Review and remove duplicate entries"
            })
        
        self.verification_results['recommendations'] = recommendations
    
    def save_report(self, output_path: str):
        """Save verification report."""
        with open(output_path, 'w') as f:
            json.dump(self.verification_results, f, indent=2, default=str)
        
        logger.info(f"Verification report saved to: {output_path}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Verify document import")
    parser.add_argument('session_id', help="Import session ID")
    parser.add_argument('manifest', help="Path to import manifest")
    parser.add_argument('--output', '-o', 
                       default='verification_report.json',
                       help="Output report path")
    
    args = parser.parse_args()
    
    verifier = ImportVerifier(args.session_id, args.manifest)
    results = verifier.verify_all()
    verifier.save_report(args.output)
    
    # Print summary
    print("\nVERIFICATION SUMMARY")
    print("="*50)
    print(f"Expected files: {results['total_files_expected']}")
    print(f"Found files: {results['total_files_found']}")
    print(f"Missing files: {len(results['missing_files'])}")
    print(f"Processing errors: {len(results['processing_errors'])}")
    print(f"Duplicate files: {len(results['duplicate_files'])}")
    
    if results['recommendations']:
        print("\nRECOMMENDATIONS:")
        for rec in results['recommendations']:
            print(f"[{rec['priority']}] {rec['issue']}")
            print(f"  → {rec['action']}")
```

## Usage Workflow

### Complete Import Process

```bash
# Step 1: Clean database
python scripts/cleanup_database.py --stats > pre_cleanup_stats.json
python scripts/cleanup_database.py --all

# Step 2: Analyze files
python scripts/analyze_client_files.py /path/to/client/files -o manifest.json

# Step 3: Review manifest and costs
cat manifest.json | jq '.summary'

# Step 4: Start import (in one terminal)
python scripts/import_client_files.py manifest.json

# Step 5: Monitor progress (in another terminal)
python scripts/import_dashboard.py <session_id>

# Step 6: Verify import
python scripts/verify_import.py <session_id> manifest.json

# Step 7: Generate final report
python scripts/import_tracker.py report <session_id>
```

## Key Features

1. **Pre-Import Analysis**
   - File manifest generation
   - Cost estimation
   - Issue detection

2. **Progress Tracking**
   - SQLite-based tracking
   - Real-time status updates
   - Failure tracking and retry

3. **Cost Monitoring**
   - Per-operation cost tracking
   - Running totals
   - Provider attribution

4. **Verification System**
   - Completeness checks
   - Duplicate detection
   - Integrity validation

5. **Error Handling**
   - Automatic retries
   - Detailed error logging
   - Recovery recommendations

## Security Considerations

1. **File Path Validation**: Ensure paths don't escape intended directories
2. **Hash Verification**: Use SHA256 for deduplication
3. **Access Control**: Verify user permissions for each operation
4. **Audit Trail**: Complete logging of all operations

## Performance Optimizations

1. **Concurrent Processing**: Configurable parallelism
2. **Duplicate Detection**: Skip already imported files
3. **Batch Operations**: Group database operations
4. **Caching**: Leverage Redis for frequently accessed data

## Next Steps

1. Add support for incremental imports
2. Implement file change detection
3. Add support for versioning documents
4. Create automated test suite
5. Add support for custom metadata extraction