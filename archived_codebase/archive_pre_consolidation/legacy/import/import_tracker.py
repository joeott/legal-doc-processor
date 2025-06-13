#!/usr/bin/env python3
"""
Import tracker using SQLite for persistent state management.

Tracks import progress, errors, costs, and provides recovery capabilities.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum
import threading
import time


class ImportStatus(Enum):
    """Import status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ImportTracker:
    """Track document import progress using SQLite."""
    
    def __init__(self, db_path: str = "import_tracking.db"):
        self.db_path = db_path
        self.conn = None
        self.lock = threading.Lock()
        self._init_database()
    
    def _init_database(self):
        """Initialize the SQLite database schema."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        
        cursor = self.conn.cursor()
        
        # Import sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS import_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_name TEXT NOT NULL,
                project_id TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                total_files INTEGER DEFAULT 0,
                processed_files INTEGER DEFAULT 0,
                failed_files INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0.0,
                manifest_path TEXT,
                status TEXT DEFAULT 'active'
            )
        """)
        
        # Document tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_imports (
                import_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                mime_type TEXT,
                size_bytes INTEGER,
                status TEXT DEFAULT 'pending',
                document_uuid TEXT,
                source_doc_id INTEGER,
                s3_key TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                processing_time_seconds REAL,
                retry_count INTEGER DEFAULT 0,
                error_message TEXT,
                error_type TEXT,
                cost_breakdown TEXT,  -- JSON
                metadata TEXT,  -- JSON
                FOREIGN KEY (session_id) REFERENCES import_sessions(session_id),
                UNIQUE(session_id, file_hash)
            )
        """)
        
        # Processing costs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processing_costs (
                cost_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                import_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                service TEXT NOT NULL,
                operation TEXT NOT NULL,
                units INTEGER DEFAULT 1,
                unit_cost REAL NOT NULL,
                total_cost REAL NOT NULL,
                metadata TEXT,  -- JSON
                FOREIGN KEY (session_id) REFERENCES import_sessions(session_id),
                FOREIGN KEY (import_id) REFERENCES document_imports(import_id)
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_status ON document_imports(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_session ON document_imports(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_hash ON document_imports(file_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cost_session ON processing_costs(session_id)")
        
        self.conn.commit()
    
    def create_session(self, case_name: str, project_id: str = None, manifest_path: str = None) -> int:
        """Create a new import session."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO import_sessions (case_name, project_id, manifest_path)
                VALUES (?, ?, ?)
            """, (case_name, project_id, manifest_path))
            self.conn.commit()
            return cursor.lastrowid
    
    def add_document(self, session_id: int, file_info: Dict) -> int:
        """Add a document to track."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO document_imports (
                    session_id, file_path, file_hash, mime_type, size_bytes, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                file_info['path'],
                file_info['file_hash'],
                file_info.get('mime_type'),
                file_info.get('size_bytes', 0),
                json.dumps(file_info)
            ))
            self.conn.commit()
            
            # Update session total files count
            cursor.execute("""
                UPDATE import_sessions 
                SET total_files = (
                    SELECT COUNT(*) FROM document_imports WHERE session_id = ?
                )
                WHERE session_id = ?
            """, (session_id, session_id))
            self.conn.commit()
            
            return cursor.lastrowid
    
    def update_document_status(self, import_id: int, status: ImportStatus, 
                             document_uuid: str = None, source_doc_id: int = None,
                             s3_key: str = None, error: Exception = None):
        """Update document import status."""
        with self.lock:
            cursor = self.conn.cursor()
            
            if status == ImportStatus.PROCESSING:
                cursor.execute("""
                    UPDATE document_imports 
                    SET status = ?, started_at = CURRENT_TIMESTAMP, retry_count = retry_count + 1
                    WHERE import_id = ?
                """, (status.value, import_id))
            
            elif status in [ImportStatus.COMPLETED, ImportStatus.UPLOADED, ImportStatus.QUEUED]:
                cursor.execute("""
                    UPDATE document_imports 
                    SET status = ?, completed_at = CURRENT_TIMESTAMP,
                        processing_time_seconds = (
                            julianday(CURRENT_TIMESTAMP) - julianday(started_at)
                        ) * 86400,
                        document_uuid = ?, source_doc_id = ?, s3_key = ?
                    WHERE import_id = ?
                """, (status.value, document_uuid, source_doc_id, s3_key, import_id))
            
            elif status == ImportStatus.FAILED:
                error_msg = str(error) if error else "Unknown error"
                error_type = type(error).__name__ if error else "Unknown"
                cursor.execute("""
                    UPDATE document_imports 
                    SET status = ?, completed_at = CURRENT_TIMESTAMP,
                        error_message = ?, error_type = ?
                    WHERE import_id = ?
                """, (status.value, error_msg, error_type, import_id))
            
            self.conn.commit()
            
            # Update session counts
            self._update_session_counts(cursor, import_id)
    
    def _update_session_counts(self, cursor, import_id: int):
        """Update session processing counts."""
        # Get session ID
        cursor.execute("SELECT session_id FROM document_imports WHERE import_id = ?", (import_id,))
        row = cursor.fetchone()
        if row:
            session_id = row['session_id']
            
            # Update counts
            cursor.execute("""
                UPDATE import_sessions
                SET processed_files = (
                    SELECT COUNT(*) FROM document_imports 
                    WHERE session_id = ? AND status IN ('completed', 'uploaded', 'queued')
                ),
                failed_files = (
                    SELECT COUNT(*) FROM document_imports
                    WHERE session_id = ? AND status = 'failed'
                )
                WHERE session_id = ?
            """, (session_id, session_id, session_id))
            self.conn.commit()
    
    def record_cost(self, session_id: int, service: str, operation: str,
                   units: int, unit_cost: float, import_id: int = None,
                   metadata: Dict = None):
        """Record processing cost."""
        with self.lock:
            cursor = self.conn.cursor()
            total_cost = units * unit_cost
            
            cursor.execute("""
                INSERT INTO processing_costs (
                    session_id, import_id, service, operation, 
                    units, unit_cost, total_cost, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, import_id, service, operation,
                units, unit_cost, total_cost,
                json.dumps(metadata) if metadata else None
            ))
            
            # Update session total cost
            cursor.execute("""
                UPDATE import_sessions
                SET total_cost = (
                    SELECT COALESCE(SUM(total_cost), 0) 
                    FROM processing_costs 
                    WHERE session_id = ?
                )
                WHERE session_id = ?
            """, (session_id, session_id))
            
            self.conn.commit()
    
    def get_session_status(self, session_id: int) -> Dict:
        """Get current session status."""
        with self.lock:
            cursor = self.conn.cursor()
            
            # Get session info
            cursor.execute("""
                SELECT * FROM import_sessions WHERE session_id = ?
            """, (session_id,))
            session = dict(cursor.fetchone())
            
            # Get status counts
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM document_imports
                WHERE session_id = ?
                GROUP BY status
            """, (session_id,))
            
            status_counts = {}
            for row in cursor.fetchall():
                status_counts[row['status']] = row['count']
            
            session['status_counts'] = status_counts
            
            # Get recent errors
            cursor.execute("""
                SELECT file_path, error_message, error_type
                FROM document_imports
                WHERE session_id = ? AND status = 'failed'
                ORDER BY completed_at DESC
                LIMIT 10
            """, (session_id,))
            
            session['recent_errors'] = [dict(row) for row in cursor.fetchall()]
            
            # Get cost breakdown
            cursor.execute("""
                SELECT service, SUM(total_cost) as total
                FROM processing_costs
                WHERE session_id = ?
                GROUP BY service
            """, (session_id,))
            
            cost_breakdown = {}
            for row in cursor.fetchall():
                cost_breakdown[row['service']] = row['total']
            
            session['cost_breakdown'] = cost_breakdown
            
            return session
    
    def get_pending_documents(self, session_id: int, limit: int = 100) -> List[Dict]:
        """Get pending documents for processing."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM document_imports
                WHERE session_id = ? AND status = 'pending'
                ORDER BY import_id
                LIMIT ?
            """, (session_id, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_failed_documents(self, session_id: int) -> List[Dict]:
        """Get failed documents for retry."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM document_imports
                WHERE session_id = ? AND status = 'failed' AND retry_count < 3
                ORDER BY import_id
            """, (session_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def mark_session_complete(self, session_id: int):
        """Mark session as complete."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE import_sessions
                SET completed_at = CURRENT_TIMESTAMP, status = 'completed'
                WHERE session_id = ?
            """, (session_id,))
            self.conn.commit()
    
    def get_import_summary(self, session_id: int) -> Dict:
        """Get comprehensive import summary."""
        status = self.get_session_status(session_id)
        
        with self.lock:
            cursor = self.conn.cursor()
            
            # Get processing time stats
            cursor.execute("""
                SELECT 
                    AVG(processing_time_seconds) as avg_time,
                    MIN(processing_time_seconds) as min_time,
                    MAX(processing_time_seconds) as max_time,
                    SUM(processing_time_seconds) as total_time
                FROM document_imports
                WHERE session_id = ? AND processing_time_seconds IS NOT NULL
            """, (session_id,))
            
            time_stats = dict(cursor.fetchone())
            
            # Get file type breakdown
            cursor.execute("""
                SELECT 
                    mime_type,
                    COUNT(*) as count,
                    SUM(size_bytes) as total_size,
                    AVG(processing_time_seconds) as avg_time
                FROM document_imports
                WHERE session_id = ?
                GROUP BY mime_type
            """, (session_id,))
            
            file_types = [dict(row) for row in cursor.fetchall()]
            
            return {
                'session': status,
                'time_stats': time_stats,
                'file_types': file_types
            }
    
    def export_session_data(self, session_id: int, output_path: str):
        """Export session data to JSON."""
        summary = self.get_import_summary(session_id)
        
        with self.lock:
            cursor = self.conn.cursor()
            
            # Get all documents
            cursor.execute("""
                SELECT * FROM document_imports
                WHERE session_id = ?
                ORDER BY import_id
            """, (session_id,))
            
            documents = []
            for row in cursor.fetchall():
                doc = dict(row)
                # Parse JSON fields
                if doc.get('metadata'):
                    doc['metadata'] = json.loads(doc['metadata'])
                if doc.get('cost_breakdown'):
                    doc['cost_breakdown'] = json.loads(doc['cost_breakdown'])
                documents.append(doc)
            
            # Get all costs
            cursor.execute("""
                SELECT * FROM processing_costs
                WHERE session_id = ?
                ORDER BY timestamp
            """, (session_id,))
            
            costs = []
            for row in cursor.fetchall():
                cost = dict(row)
                if cost.get('metadata'):
                    cost['metadata'] = json.loads(cost['metadata'])
                costs.append(cost)
        
        export_data = {
            'summary': summary,
            'documents': documents,
            'costs': costs,
            'export_timestamp': datetime.now().isoformat()
        }
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"Session data exported to: {output_path}")
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


def main():
    """Test the import tracker."""
    tracker = ImportTracker()
    
    # Create a test session
    session_id = tracker.create_session("Test Case", "test-project-123")
    print(f"Created session: {session_id}")
    
    # Add test document
    test_doc = {
        'path': 'test/document.pdf',
        'file_hash': 'abc123',
        'mime_type': 'application/pdf',
        'size_bytes': 1024000
    }
    
    import_id = tracker.add_document(session_id, test_doc)
    print(f"Added document: {import_id}")
    
    # Update status
    tracker.update_document_status(import_id, ImportStatus.PROCESSING)
    time.sleep(1)
    tracker.update_document_status(import_id, ImportStatus.COMPLETED, 
                                 document_uuid="doc-uuid-123",
                                 source_doc_id=456)
    
    # Record cost
    tracker.record_cost(session_id, "textract", "pages", 10, 0.015, import_id)
    
    # Get status
    status = tracker.get_session_status(session_id)
    print(f"Session status: {json.dumps(status, indent=2)}")
    
    tracker.close()


if __name__ == '__main__':
    main()