#!/usr/bin/env python3
"""
Live Document Processing Monitor

This script provides real-time monitoring of the document processing pipeline,
including database status changes and consolidated logs.
"""

import os
import sys
import time
import json
import logging
import argparse
import datetime
import select
import psycopg2
import psycopg2.extensions
from tabulate import tabulate
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.logging import RichHandler
from rich import box

# Add the parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.supabase_utils import get_supabase_client

# Load environment variables from .env file
load_dotenv()

# Console setup for rich output
console = Console()

# Configure logging with rich
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("document_monitor")

# Queue status colors and icons
STATUS_COLORS = {
    'pending': 'yellow',
    'processing': 'blue',
    'completed': 'green',
    'failed': 'red',
    'error': 'red',
    'ocr_complete_pending_doc_node': 'green',
    'extraction_failed': 'red',
    'pending_intake': 'yellow',
    'retry': 'yellow'
}

STATUS_ICONS = {
    'pending': '⏳',
    'processing': '⚡',
    'completed': '✓',
    'failed': '✗',
    'retry': '🔄'
}

PROCESSING_STEPS = {
    'intake': 'intake',
    'ocr': 'ocr',
    'extracting_text': 'ocr',
    'processing_text': 'entity_extraction',
    'chunking': 'entity_extraction',
    'extracting_entities': 'entity_extraction',
    'resolving_entities': 'entity_resolution',
    'building_relationships': 'relationship_staging',
    'entity_extraction': 'entity_extraction',
    'entity_resolution': 'entity_resolution',
    'relationship_staging': 'relationship_staging'
}

class DocumentProcessMonitor:
    """
    Live monitor for document processing pipeline.
    Tracks database changes and provides real-time visualizations.
    """
    
    def __init__(self, 
                 refresh_interval=5, 
                 max_documents=10,
                 include_completed=True):
        self.refresh_interval = refresh_interval
        self.max_documents = max_documents
        self.include_completed = include_completed
        self.last_check_time = datetime.datetime.now() - datetime.timedelta(minutes=60)
        self.seen_document_ids = set()
        self.documents = []
        self.queue_stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        self.ocr_stats = {"total": 0, "textract": 0, "mistral": 0, "qwen": 0}
        self.active_processors = set()
        self.pipeline_stats = {}
        self.error_patterns = {}
        self.db_conn = None
        self.supabase = None
        self.notifications = []  # Store recent notifications
        self.max_notifications = 20
        self.filter_active_only = False
        self.show_extended_errors = False
        self.setup_database_connection()
        
    def setup_database_connection(self):
        """Set up database connections."""
        try:
            logger.info("Setting up database connections...")
            
            # Get Supabase connection parameters
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_ANON_KEY")
            direct_connect_url = os.getenv("SUPABASE_DIRECT_CONNECT_URL")
            
            if not supabase_url or not supabase_key:
                raise ValueError("SUPABASE_URL or SUPABASE_ANON_KEY not set")
            
            # Setup direct PostgreSQL connection for notifications
            if direct_connect_url:
                logger.info("Using direct connection URL for PostgreSQL")
                self.db_conn = psycopg2.connect(direct_connect_url)
                self.db_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                logger.info("Direct PostgreSQL connection established.")
            else:
                logger.warning("SUPABASE_DIRECT_CONNECT_URL not available, skipping direct PostgreSQL connection")
                self.db_conn = None
            
            # Set up Supabase client for normal queries
            self.supabase = get_supabase_client()
            logger.info("Supabase client established.")
            
            # Setup notification channel if direct PostgreSQL connection is available
            if self.db_conn:
                self.setup_notification_channel()
                
        except Exception as e:
            logger.error(f"Failed to establish database connections: {e}")
            logger.info("Continuing with periodic polling only...")
            self.db_conn = None
            self.supabase = None
            
    def setup_notification_channel(self):
        """Set up PostgreSQL notification channel to work with modernized triggers."""
        try:
            cursor = self.db_conn.cursor()
            
            # Create a dedicated monitoring notification function
            # This works alongside the modernized triggers, not replacing them
            monitoring_function_sql = """
            CREATE OR REPLACE FUNCTION monitoring_notify_status_change()
            RETURNS TRIGGER AS $$
            BEGIN
              -- Send notification specifically for monitoring dashboard
              PERFORM pg_notify(
                'document_status_changes',
                json_build_object(
                  'table', TG_TABLE_NAME,
                  'id', NEW.id,
                  'status', CASE 
                    WHEN TG_TABLE_NAME = 'source_documents' THEN NEW.initial_processing_status
                    WHEN TG_TABLE_NAME = 'document_processing_queue' THEN NEW.status
                    ELSE 'unknown'
                    END,
                  'document_uuid', COALESCE(NEW.document_uuid, NEW.source_document_uuid),
                  'timestamp', NOW(),
                  'monitoring_event', true
                )::text
              );
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
            cursor.execute(monitoring_function_sql)
            
            # Create monitoring-specific triggers (with unique names to avoid conflicts)
            # These supplement the modernized triggers for monitoring purposes
            source_docs_monitor_trigger_sql = """
            CREATE TRIGGER monitoring_source_docs_trigger
            AFTER UPDATE OF initial_processing_status ON source_documents
            FOR EACH ROW
            EXECUTE FUNCTION monitoring_notify_status_change();
            """
            
            queue_monitor_trigger_sql = """
            CREATE TRIGGER monitoring_queue_trigger  
            AFTER UPDATE OF status ON document_processing_queue
            FOR EACH ROW
            EXECUTE FUNCTION monitoring_notify_status_change();
            """
            
            # Drop existing monitoring triggers if they exist
            try:
                cursor.execute("DROP TRIGGER IF EXISTS monitoring_source_docs_trigger ON source_documents;")
                cursor.execute("DROP TRIGGER IF EXISTS monitoring_queue_trigger ON document_processing_queue;")
            except:
                pass
                
            # Create new monitoring triggers
            cursor.execute(source_docs_monitor_trigger_sql)
            cursor.execute(queue_monitor_trigger_sql)
            
            # Listen to the notification channel
            cursor.execute("LISTEN document_status_changes;")
            logger.info("Modernized monitoring notification channel set up successfully.")
            
        except Exception as e:
            logger.error(f"Failed to set up modernized notification channel: {e}")
            logger.info("Will use polling instead of notifications.")
    
    def check_for_notifications(self):
        """Check for database notifications with enhanced payload processing."""
        if not self.db_conn:
            return False
            
        try:
            if select.select([self.db_conn], [], [], 0) == ([], [], []):
                return False
                
            self.db_conn.poll()
            notification_received = False
            
            while self.db_conn.notifies:
                notify = self.db_conn.notifies.pop()
                try:
                    payload = json.loads(notify.payload)
                    logger.info(f"Notification: {payload.get('table')} ID {payload.get('id')} -> {payload.get('status')}")
                    
                    # Add to notification log
                    self.add_notification(payload)
                    
                    # Update local cache if we have the document
                    if payload.get('table') == 'source_documents':
                        self.update_document_status(payload.get('id'), None, payload.get('status'))
                    elif payload.get('table') == 'document_processing_queue':
                        self.update_document_status(None, payload.get('id'), payload.get('status'))
                        
                    notification_received = True
                    
                except json.JSONDecodeError:
                    logger.warning(f"Invalid notification payload: {notify.payload}")
                    notification_received = True
                    
            return notification_received
                
        except Exception as e:
            logger.error(f"Error checking notifications: {e}")
            
        return False
    
    def add_notification(self, payload):
        """Add a notification to the log with proper formatting."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        table = payload.get('table', '')
        doc_id = payload.get('id', '')
        status = payload.get('status', '')
        doc_uuid = payload.get('document_uuid', '')
        
        # Get document info if available
        doc_info = None
        if self.supabase:
            try:
                if table == 'source_documents' and doc_id:
                    response = self.supabase.table('source_documents').select('original_file_name').eq('id', doc_id).single().execute()
                    if response.data:
                        doc_info = response.data
                elif table == 'document_processing_queue' and doc_uuid:
                    response = self.supabase.table('source_documents').select('original_file_name, id').eq('document_uuid', doc_uuid).single().execute()
                    if response.data:
                        doc_info = response.data
            except:
                pass
        
        # Format notification message
        if doc_info:
            filename = doc_info.get('original_file_name', 'Unknown')
            doc_id_display = doc_info.get('id', doc_id)
            
            if status == 'pending' and table == 'source_documents':
                message = f"[📄 New document: \"{filename}\" (ID: {doc_id_display})"
            elif status == 'processing':
                message = f"[⚡ Processing started: Document {doc_id_display}"
            elif status == 'completed':
                message = f"[✅ Completed: Document {doc_id_display}"
            elif status == 'failed':
                message = f"[❌ Failed: Document {doc_id_display}"
            elif 'ocr' in status.lower():
                message = f"[🔍 OCR completed: Document {doc_id_display}"
            elif 'entity' in status.lower():
                message = f"[🏷️ Entities extracted: Document {doc_id_display}"
            elif 'relationship' in status.lower():
                message = f"[🔗 Relationships built: Document {doc_id_display}"
            else:
                message = f"[{status}: Document {doc_id_display}"
        else:
            message = f"[{status}: {table} ID {doc_id}"
        
        # Add timestamp and store
        full_message = f"[{timestamp}] {message}"
        self.notifications.insert(0, full_message)
        
        # Keep only recent notifications
        if len(self.notifications) > self.max_notifications:
            self.notifications = self.notifications[:self.max_notifications]
            
    def fetch_queue_stats(self):
        """Fetch summary statistics about document processing queue."""
        if not self.supabase:
            return
            
        try:
            # Get all queue entries and process locally
            response = self.supabase.table("document_processing_queue").select("status").execute()
            
            # Reset stats
            self.queue_stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
            
            # Count statuses locally
            if response.data:
                for item in response.data:
                    status = item.get('status', '')
                    if status in self.queue_stats:
                        self.queue_stats[status] += 1
                    
        except Exception as e:
            logger.error(f"Failed to fetch queue stats: {e}")
    
    def fetch_ocr_stats(self):
        """Fetch statistics about OCR methods used."""
        if not self.supabase:
            return
            
        try:
            # Get queue entries with OCR provider info
            response = self.supabase.table("document_processing_queue").select("ocr_provider").execute()
            
            # Reset stats
            self.ocr_stats = {"total": 0, "textract": 0, "mistral": 0, "qwen": 0}
            
            # Process results locally
            if response.data:
                for item in response.data:
                    provider = item.get('ocr_provider')
                    if provider:
                        self.ocr_stats['total'] += 1
                        if provider.lower() == 'textract':
                            self.ocr_stats['textract'] += 1
                        elif provider.lower() == 'mistral':
                            self.ocr_stats['mistral'] += 1
                        elif provider.lower() == 'qwen':
                            self.ocr_stats['qwen'] += 1
                    
        except Exception as e:
            logger.error(f"Failed to fetch OCR stats: {e}")
    
    def fetch_active_processors(self):
        """Fetch list of active document processors."""
        if not self.supabase:
            return
            
        try:
            # Get processing documents and extract processor info from metadata
            response = self.supabase.table("document_processing_queue").select(
                "processor_metadata"
            ).eq("status", "processing").execute()
            
            self.active_processors = set()
            if response.data:
                processor_ids = set()
                for item in response.data:
                    metadata = item.get('processor_metadata')
                    if metadata and isinstance(metadata, dict):
                        processor_id = metadata.get('processor_id')
                        if processor_id:
                            processor_ids.add(processor_id)
                
                if processor_ids:
                    for pid in processor_ids:
                        self.active_processors.add(pid)
                else:
                    # Fallback to showing count if no processor IDs found
                    processing_count = len(response.data)
                    if processing_count > 0:
                        self.active_processors.add(f"{processing_count} active tasks")
                    
        except Exception as e:
            logger.error(f"Failed to fetch active processors: {e}")
    
    def fetch_pipeline_stage_stats(self):
        """Fetch detailed statistics about document processing stages."""
        if not self.supabase:
            return
            
        try:
            # Get detailed processing step information
            response = self.supabase.table("document_processing_queue").select(
                "processing_step, status"
            ).execute()
            
            # Initialize pipeline stats with standard steps
            self.pipeline_stats = {
                'intake': 0,
                'ocr': 0,
                'entity_extraction': 0,
                'entity_resolution': 0,
                'relationship_staging': 0
            }
            
            if response.data:
                for item in response.data:
                    step = item.get('processing_step', 'unknown')
                    status = item.get('status', 'unknown')
                    
                    # Map processing steps to standard categories
                    if step in PROCESSING_STEPS:
                        mapped_step = PROCESSING_STEPS[step]
                        if status == 'processing':
                            self.pipeline_stats[mapped_step] += 1
                        
        except Exception as e:
            logger.error(f"Failed to fetch pipeline stage stats: {e}")
    
    def fetch_error_analysis(self):
        """Fetch and analyze error patterns."""
        if not self.supabase:
            return
            
        try:
            # Get recent errors from both tables
            doc_errors = self.supabase.table("source_documents").select(
                "id, original_file_name, error_message, initial_processing_status"
            ).not_.is_("error_message", "null").order("id", desc=True).limit(20).execute()
            
            queue_errors = self.supabase.table("document_processing_queue").select(
                "id, source_document_uuid, error_message, status, retry_count"
            ).not_.is_("error_message", "null").order("id", desc=True).limit(20).execute()
            
            # Analyze error patterns
            self.error_patterns = {}
            
            # Process document errors
            if doc_errors.data:
                for error in doc_errors.data:
                    msg = error.get('error_message', '')
                    error_type = self.categorize_error(msg)
                    self.error_patterns[error_type] = self.error_patterns.get(error_type, 0) + 1
            
            # Process queue errors  
            if queue_errors.data:
                for error in queue_errors.data:
                    msg = error.get('error_message', '')
                    error_type = self.categorize_error(msg)
                    self.error_patterns[error_type] = self.error_patterns.get(error_type, 0) + 1
                    
        except Exception as e:
            logger.error(f"Failed to fetch error analysis: {e}")

    def categorize_error(self, error_message):
        """Categorize error messages into types."""
        if not error_message:
            return 'Unknown'
            
        error_msg = error_message.lower()
        
        if 'ocr' in error_msg or 'extraction' in error_msg:
            return 'OCR/Extraction'
        elif 'timeout' in error_msg or 'stall' in error_msg:
            return 'Timeout/Stall'
        elif 's3' in error_msg or 'download' in error_msg:
            return 'File Access'
        elif 'api' in error_msg or 'rate limit' in error_msg:
            return 'API Issues'
        elif 'database' in error_msg or 'sql' in error_msg:
            return 'Database'
        else:
            return 'Other'
    
    def fetch_recent_documents(self):
        """Fetch recent documents and their processing status."""
        if not self.supabase:
            return
            
        try:
            # Get recent documents from source_documents table 
            response = self.supabase.table("source_documents").select(
                "id, document_uuid, original_file_name, initial_processing_status, ocr_metadata_json, error_message, intake_timestamp"
            ).order("id", desc=True).limit(self.max_documents).execute()
            
            if response.data:
                # Get queue information for these documents
                doc_uuids = [doc['document_uuid'] for doc in response.data if doc.get('document_uuid')]
                
                queue_data = {}
                if doc_uuids:
                    queue_response = self.supabase.table("document_processing_queue").select(
                        "source_document_uuid, id, status, created_at, updated_at, started_at, completed_at, error_message, processor_metadata, retry_count"
                    ).in_("source_document_uuid", doc_uuids).execute()
                    
                    if queue_response.data:
                        for q in queue_response.data:
                            queue_data[q['source_document_uuid']] = q
                
                # Combine document and queue data
                combined_docs = []
                for doc in response.data:
                    doc_uuid = doc.get('document_uuid')
                    queue_info = queue_data.get(doc_uuid, {})
                    
                    # Extract OCR method
                    ocr_method = ""
                    if doc.get('ocr_metadata_json') and isinstance(doc['ocr_metadata_json'], list) and len(doc['ocr_metadata_json']) > 0:
                        ocr_method = doc['ocr_metadata_json'][0].get('method', '')
                    
                    # Extract processor info from metadata
                    processor_info = ""
                    if queue_info.get('processor_metadata') and isinstance(queue_info['processor_metadata'], dict):
                        processor_info = queue_info['processor_metadata'].get('processor_id', '')
                    
                    combined_doc = {
                        'doc_id': doc.get('id'),
                        'document_uuid': doc_uuid,
                        'original_file_name': doc.get('original_file_name'),
                        'doc_status': doc.get('initial_processing_status'),
                        'queue_id': queue_info.get('id'),
                        'queue_status': queue_info.get('status'),
                        'created_at': queue_info.get('created_at'),
                        'updated_at': queue_info.get('updated_at'),
                        'started_at': queue_info.get('started_at'),
                        'completed_at': queue_info.get('completed_at'),
                        'processor_info': processor_info,
                        'retry_count': queue_info.get('retry_count', 0),
                        'ocr_method': ocr_method,
                        'error_message': doc.get('error_message') or queue_info.get('error_message', ''),
                        'intake_timestamp': doc.get('intake_timestamp'),
                        'processing_step': queue_info.get('processing_step', '')
                    }
                    
                    # Calculate seconds running if processing (use started_at if available, otherwise created_at)
                    if queue_info.get('status') == 'processing':
                        start_time = queue_info.get('started_at') or queue_info.get('created_at')
                        if start_time:
                            try:
                                started = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                                now = datetime.datetime.now(datetime.timezone.utc)
                                combined_doc['seconds_running'] = (now - started).total_seconds()
                            except:
                                combined_doc['seconds_running'] = 0
                    
                    combined_docs.append(combined_doc)
                    
                    # Track seen documents
                    if combined_doc['doc_id'] and combined_doc['doc_id'] not in self.seen_document_ids:
                        self.seen_document_ids.add(combined_doc['doc_id'])
                
                self.documents = combined_docs
                
            self.last_check_time = datetime.datetime.now()
            
        except Exception as e:
            logger.error(f"Failed to fetch recent documents: {e}")
    
    def update_document_status(self, doc_id, queue_id, new_status):
        """Update status of a document in our cached list."""
        for doc in self.documents:
            if (doc.get('doc_id') == doc_id) or (doc.get('queue_id') == queue_id):
                if 'queue_status' in doc and queue_id:
                    doc['queue_status'] = new_status
                elif 'doc_status' in doc and doc_id:
                    doc['doc_status'] = new_status
                return True
        return False
    
    def create_stats_table(self):
        """Create a rich table with stats."""
        table = Table(title="Document Processing Statistics")
        
        table.add_column("Queue Status", style="bold")
        table.add_column("Count")
        
        table.add_row("Pending", f"[yellow]{self.queue_stats.get('pending', 0)}[/yellow]")
        table.add_row("Processing", f"[blue]{self.queue_stats.get('processing', 0)}[/blue]")
        table.add_row("Completed", f"[green]{self.queue_stats.get('completed', 0)}[/green]")
        table.add_row("Failed", f"[red]{self.queue_stats.get('failed', 0)}[/red]")
        
        return table
    
    def create_ocr_stats_panel(self):
        """Create a panel with OCR provider statistics."""
        lines = ["OCR Providers:"]
        
        textract_count = self.ocr_stats.get('textract', 0)
        mistral_count = self.ocr_stats.get('mistral', 0)
        qwen_count = self.ocr_stats.get('qwen', 0)
        
        lines.append(f"• textract: {textract_count} docs")
        lines.append(f"• mistral: {mistral_count} docs")
        lines.append(f"• qwen: {qwen_count} docs")
        
        return Panel("\n".join(lines), title="OCR Statistics")
    
    def create_pipeline_stages_table(self):
        """Create a table showing current processing steps."""
        table = Table(title="Processing Steps")
        
        table.add_column("Step", style="bold")
        table.add_column("Count")
        
        # Display in order
        steps_order = ['intake', 'ocr', 'entity_extraction', 'entity_resolution', 'relationship_staging']
        
        for step in steps_order:
            count = self.pipeline_stats.get(step, 0)
            table.add_row(step, str(count))
            
        return table
    
    def create_error_table(self):
        """Create a table showing recent errors."""
        table = Table(title="Recent Errors")
        
        table.add_column("ID", style="dim")
        table.add_column("Document", style="bold")
        table.add_column("Error Message", style="red")
        
        if not self.supabase:
            return table
            
        try:
            # Get recent errors
            response = self.supabase.table("document_processing_queue").select(
                "source_document_id, source_document_uuid, error_message, source_documents(original_file_name)"
            ).not_.is_("error_message", "null").order("updated_at", desc=True).limit(10).execute()
            
            if response.data:
                for item in response.data:
                    doc_id = item.get('source_document_id', '')
                    error_msg = item.get('error_message', '')
                    filename = ''
                    
                    # Get filename from joined data
                    if item.get('source_documents') and isinstance(item['source_documents'], dict):
                        filename = item['source_documents'].get('original_file_name', 'Unknown')
                    
                    # Truncate long messages
                    if len(filename) > 20:
                        filename = filename[:17] + "..."
                    if len(error_msg) > 47:
                        error_msg = error_msg[:44] + "..."
                    
                    table.add_row(str(doc_id), filename, error_msg)
            else:
                table.add_row("", "No errors", "")
                
        except Exception as e:
            logger.error(f"Failed to fetch error table: {e}")
            table.add_row("", "Error fetching data", str(e)[:40])
            
        return table
    
    def create_notifications_panel(self):
        """Create a panel with real-time notifications."""
        lines = []
        
        if not self.notifications:
            lines.append("[dim]No recent notifications[/dim]")
        else:
            # Show recent notifications
            for notification in self.notifications[:10]:  # Show last 10
                lines.append(notification)
        
        content = "\n".join(lines)
        return Panel(content, title="Real-time Notifications", height=12)
    
    def create_processors_panel(self):
        """Create a panel with active processors."""
        lines = ["[bold]Active Queue Processors:[/bold]\n"]
        
        if not self.active_processors:
            lines.append("[dim]No active processors[/dim]")
            lines.append("")
            lines.append("[yellow]⚠ Start queue processor with:[/yellow]")
            lines.append("[dim]python scripts/queue_processor.py[/dim]")
        else:
            processor_list = list(self.active_processors)
            for i, proc in enumerate(processor_list[:5]):  # Show max 5
                # Add status indicator
                status_icon = "🟢" if "active" in str(proc).lower() else "⚙️"
                lines.append(f"{status_icon} {proc}")
            
            if len(processor_list) > 5:
                lines.append(f"[dim]... and {len(processor_list) - 5} more[/dim]")
                
            # Add capacity info
            active_count = len(self.active_processors)
            lines.append(f"• Total: {active_count}/10 capacity")
            
        return Panel("\n".join(lines), title="Processing Capacity")
    
    def create_documents_table(self):
        """Create a rich table with recent documents."""
        table = Table(title="Recent Documents", box=box.ROUNDED)
        
        table.add_column("ID", style="dim", width=6)
        table.add_column("Document Name", style="bold")
        table.add_column("Status")
        table.add_column("Queue", style="dim")
        table.add_column("Processing Time")
        table.add_column("Details", style="dim")
        
        # Filter documents if needed
        docs_to_show = self.documents
        if self.filter_active_only:
            docs_to_show = [d for d in self.documents if d.get('queue_status') in ['pending', 'processing']]
        
        for doc in docs_to_show:
            doc_id = doc.get('doc_id', '')
            filename = doc.get('original_file_name', '')
            
            # Truncate long filenames
            if len(filename) > 34:
                filename = filename[:31] + "..."
                
            queue_status = doc.get('queue_status', '')
            processing_step = doc.get('processing_step', '')
            
            # Determine display status with icon
            status_icon = STATUS_ICONS.get(queue_status, '')
            if queue_status == 'processing' and processing_step:
                # Map to standard step names
                if processing_step in PROCESSING_STEPS:
                    step = PROCESSING_STEPS[processing_step]
                    status_display = f"{status_icon} processing ({step})"
                else:
                    status_display = f"{status_icon} processing"
            else:
                status_display = f"{status_icon} {queue_status}"
            
            # Calculate processing time
            processing_time = "-"
            if queue_status == 'completed' and doc.get('completed_at') and doc.get('started_at'):
                try:
                    started_dt = datetime.datetime.fromisoformat(doc['started_at'].replace('Z', '+00:00'))
                    completed_dt = datetime.datetime.fromisoformat(doc['completed_at'].replace('Z', '+00:00'))
                    duration = completed_dt - started_dt
                    minutes = int(duration.total_seconds() // 60)
                    seconds = int(duration.total_seconds() % 60)
                    if minutes > 0:
                        processing_time = f"{minutes}m {seconds}s"
                    else:
                        processing_time = f"{seconds}s"
                except:
                    processing_time = "Completed"
            elif queue_status == 'processing' and doc.get('seconds_running'):
                seconds = int(doc.get('seconds_running', 0))
                if seconds > 60:
                    minutes = seconds // 60
                    sec = seconds % 60
                    processing_time = f"{minutes}m {sec}s ({processing_step or 'processing'})"
                else:
                    processing_time = f"{seconds}s ({processing_step or 'processing'})"
            
            # Apply colors to status
            status_colored = f"[{STATUS_COLORS.get(queue_status, 'white')}]{status_display}[/{STATUS_COLORS.get(queue_status, 'white')}]"
            
            # Add queue info
            queue_id = str(doc.get('queue_id', '-'))
            
            # Add details (retry count, OCR method, etc)
            details = []
            if doc.get('retry_count', 0) > 0:
                details.append(f"retry:{doc['retry_count']}")
            if doc.get('ocr_method'):
                details.append(f"ocr:{doc['ocr_method']}")
            if doc.get('processor_info'):
                proc_short = doc['processor_info'].split('_')[-1][:8]  # Last 8 chars of processor ID
                details.append(f"proc:{proc_short}")
            
            details_str = ", ".join(details) if details else "-"
            
            table.add_row(
                str(doc_id),
                filename,
                status_colored,
                queue_id,
                processing_time,
                details_str
            )
            
        return table
    
    def create_dashboard(self):
        """Create a comprehensive dashboard with all panels."""
        layout = Layout()
        
        # Create main layout structure to match context_65
        layout.split(
            Layout(name="header", size=3),
            Layout(name="summary", ratio=1),
            Layout(name="documents", ratio=1),
            Layout(name="bottom", ratio=1)
        )
        
        # Header
        header_text = Text("Document Processing Live Monitor", style="bold cyan")
        header_text.append("\nPress Ctrl+C to exit", style="dim")
        layout["header"].update(Panel(header_text))
        
        # Summary section
        layout["summary"].split_row(
            Layout(name="queue_stats", ratio=1),
            Layout(name="providers", ratio=1),
            Layout(name="steps", ratio=1)
        )
        
        # Providers section splits into OCR and processors
        layout["providers"].split(
            Layout(name="ocr_stats"),
            Layout(name="processors")
        )
        
        # Bottom section splits into errors and notifications
        layout["bottom"].split_row(
            Layout(name="errors", ratio=1),
            Layout(name="notifications", ratio=2)
        )
        
        # Assign panels to layout sections
        layout["queue_stats"].update(self.create_stats_table())
        layout["ocr_stats"].update(self.create_ocr_stats_panel())
        layout["processors"].update(self.create_processors_panel())
        layout["steps"].update(self.create_pipeline_stages_table())
        layout["documents"].update(self.create_documents_table())
        layout["errors"].update(self.create_error_table())
        layout["notifications"].update(self.create_notifications_panel())
        
        return layout
    
    def refresh_data(self, force=False):
        """Refresh all data from database."""
        notification_received = self.check_for_notifications()
        
        # Refresh if we received a notification or if it's time for a periodic refresh
        if force or notification_received or not hasattr(self, '_last_refresh') or \
           time.time() - self._last_refresh > self.refresh_interval:
            
            self.fetch_queue_stats()
            self.fetch_ocr_stats()
            self.fetch_active_processors()
            self.fetch_pipeline_stage_stats()
            self.fetch_error_analysis()
            self.fetch_recent_documents()
            
            self._last_refresh = time.time()
            return True
            
        return False
    
    def test_notification_system(self):
        """Test that notifications are received properly."""
        if not self.db_conn:
            logger.warning("No direct database connection for notification testing")
            return
            
        try:
            cursor = self.db_conn.cursor()
            
            # Send test notification
            cursor.execute("SELECT pg_notify('document_status_changes', 'test_payload');")
            
            # Check if received
            time.sleep(0.1)
            if self.check_for_notifications():
                logger.info("✅ Notification system working correctly")
            else:
                logger.warning("❌ Notification system not receiving messages")
                
        except Exception as e:
            logger.error(f"Notification system test failed: {e}")
    
    def handle_keypress(self, key):
        """Handle keyboard shortcuts."""
        if key.lower() == 'r':
            self.refresh_data(force=True)
            return True
        elif key.lower() == 'f':
            self.filter_active_only = not self.filter_active_only
            return True
        elif key.lower() == 'e':
            self.show_extended_errors = not self.show_extended_errors
            return True
        return False
    
    def run(self):
        """Run the live monitor continuously."""
        # Initial data load
        console.print("[bold cyan]Document Processing Live Monitor[/bold cyan]")
        console.print("[dim]Initializing... (press Ctrl+C to exit)[/dim]")
        console.print("[dim]Keyboard shortcuts: R=Refresh, F=Filter active only, E=Extended errors[/dim]\n")
        
        # Add initial notification
        self.add_notification({'status': 'Monitor started', 'table': 'system', 'id': 0})
        
        self.refresh_data(force=True)
        
        try:
            with Live(self.create_dashboard(), refresh_per_second=4) as live:
                self._last_refresh = time.time()
                
                while True:
                    if self.refresh_data():
                        live.update(self.create_dashboard())
                    
                    time.sleep(0.25)  # Small sleep to prevent CPU hogging
                    
        except KeyboardInterrupt:
            console.print("\n[bold red]Monitor stopped by user[/bold red]")
        except Exception as e:
            console.print(f"\n[bold red]Error: {e}[/bold red]")
            import traceback
            traceback.print_exc()
        finally:
            # Cleanup
            if self.db_conn:
                self.db_conn.close()
            
            console.print("[bold]Monitor shutdown complete[/bold]")

def setup_argument_parser():
    """Set up command line arguments."""
    parser = argparse.ArgumentParser(description="Live Document Processing Monitor")
    
    parser.add_argument(
        "--refresh", 
        type=int, 
        default=5,
        help="Refresh interval in seconds (default: 5)"
    )
    
    parser.add_argument(
        "--max-docs", 
        type=int, 
        default=15,
        help="Maximum number of documents to display (default: 15)"
    )
    
    parser.add_argument(
        "--hide-completed",
        action="store_true",
        help="Hide completed documents from the display"
    )
    
    return parser.parse_args()

if __name__ == "__main__":
    args = setup_argument_parser()
    
    monitor = DocumentProcessMonitor(
        refresh_interval=args.refresh,
        max_documents=args.max_docs,
        include_completed=not args.hide_completed
    )
    
    monitor.run()