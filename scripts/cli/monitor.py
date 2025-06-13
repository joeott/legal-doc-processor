#!/usr/bin/env python3
"""
Unified monitoring script for the legal document processing pipeline.
Combines all monitoring functionality into one comprehensive tool.
"""

import click
import time
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict
from collections import Counter, defaultdict
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import redis as redis_lib
from celery import Celery
# from supabase import create_client, Client  # Replaced with RDS
from rich.console import Console
from rich.table import Table
# from rich.progress import Progress, SpinnerColumn, TextColumn  # Not currently used
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich import box
from rich.text import Text
from dotenv import load_dotenv

load_dotenv()

console = Console()

class UnifiedMonitor:
    """Unified monitoring system for the document pipeline."""
    
    def __init__(self):
        # Initialize database manager (RDS PostgreSQL)
        from scripts.db import DatabaseManager
        try:
            # TODO: Re-enable conformance validation after schema issues are resolved
            self.db = DatabaseManager(validate_conformance=False)
        except Exception as e:
            console.print(f"[red]Error: Could not initialize database connection: {e}[/red]")
            raise
        
        # Initialize Redis client with proper configuration
        # Parse Redis Cloud endpoint if available
        redis_endpoint = os.getenv("REDIS_PUBLIC_ENDPOINT", "")
        if redis_endpoint and ":" in redis_endpoint:
            host, port_str = redis_endpoint.rsplit(":", 1)
            redis_host = host
            redis_port = int(port_str)
        else:
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
        
        redis_config = {
            'host': redis_host,
            'port': redis_port,
            'password': os.getenv('REDIS_PW') or os.getenv('REDIS_PASSWORD'),
            'ssl': os.getenv('REDIS_SSL', 'false').lower() == 'true',
            'decode_responses': True,
            'socket_timeout': 5,
            'socket_connect_timeout': 5
        }
        
        # Handle Redis Cloud specific settings
        if redis_config['password']:
            redis_config['username'] = os.getenv('REDIS_USERNAME', 'default')
        
        try:
            self.redis_client = redis_lib.Redis(**redis_config)
            # Test connection
            self.redis_client.ping()
            self.redis_available = True
        except Exception as e:
            console.print(f"[yellow]Warning: Redis connection failed: {e}[/yellow]")
            self.redis_available = False
            self.redis_client = None
        
        # Initialize Celery app
        broker_url = os.getenv('CELERY_BROKER_URL', f"redis://{redis_host}:{redis_port}/0")
        if redis_config['password']:
            # Update broker URL with auth
            username = redis_config.get('username', 'default')
            broker_url = f"redis://{username}:{redis_config['password']}@{redis_host}:{redis_port}/0"
        
        self.celery_app = Celery('scripts.celery_app', broker=broker_url)
        self.celery_app.conf.update(
            broker_connection_retry_on_startup=True,
            broker_connection_retry=True,
            broker_connection_max_retries=3,
            task_track_started=True,
            task_send_sent_event=True,
            result_expires=3600,
        )
        
        # Initialize conformance engine
        try:
            from scripts.validation.conformance_engine import ConformanceEngine
            self.conformance_engine = ConformanceEngine()
        except Exception as e:
            console.print(f"[yellow]Warning: Could not initialize conformance engine: {e}[/yellow]")
            self.conformance_engine = None
        
    def get_pipeline_stats(self) -> Dict:
        """Get comprehensive pipeline statistics."""
        try:
            # Get all documents with detailed info from RDS
            from scripts.rds_utils import execute_query
            
            query = """
            SELECT 
                sd.id, 
                sd.document_uuid, 
                sd.original_file_name, 
                sd.status,
                sd.created_at, 
                sd.updated_at,
                sd.error_message, 
                sd.file_type as detected_file_type, 
                sd.project_uuid,
                pt.task_type as current_stage,
                pt.status as stage_status,
                tj.job_id as textract_job_id,
                tj.status as textract_job_status
            FROM source_documents sd
            LEFT JOIN processing_tasks pt ON sd.document_uuid = pt.document_id 
                AND pt.created_at = (
                    SELECT MAX(created_at) 
                    FROM processing_tasks 
                    WHERE document_id = sd.document_uuid
                )
            LEFT JOIN textract_jobs tj ON sd.document_uuid = tj.document_uuid
            ORDER BY sd.updated_at DESC
            """
            
            results = execute_query(query)
            
            # Convert to expected format
            response_data = []
            for row in results:
                doc = dict(row)
                # Convert datetime objects to ISO format strings
                if doc.get('created_at'):
                    doc['created_at'] = doc['created_at'].isoformat() + 'Z'
                if doc.get('updated_at'):
                    doc['updated_at'] = doc['updated_at'].isoformat() + 'Z'
                response_data.append(doc)
            
            # Simulate the old response.data structure
            class FakeResponse:
                def __init__(self, data):
                    self.data = data
            
            response = FakeResponse(response_data)
            
            status_counts = Counter()
            file_type_counts = Counter()
            processing_times = []
            processing_docs = []
            failed_docs = []
            stuck_docs = []
            recently_processed = []
            stage_errors = defaultdict(list)
            
            now = datetime.now(timezone.utc)
            stuck_threshold = now - timedelta(minutes=30)
            recent_threshold = now - timedelta(minutes=5)
            
            for doc in response.data:
                status = doc.get('status', 'unknown')
                status_counts[status] += 1
                
                # Count file types
                file_type = doc.get('detected_file_type', 'unknown')
                file_type_counts[file_type] += 1
                
                # Track processing documents
                if status == 'processing':
                    processing_docs.append(doc)
                    # Check if stuck
                    updated = self._parse_datetime(doc['updated_at'])
                    if updated and updated < stuck_threshold:
                        stuck_docs.append(doc)
                
                # Track failed documents and categorize by stage
                elif status in ['failed', 'ocr_failed', 'chunking_failed', 'entity_extraction_failed', 
                              'entity_resolution_failed', 'graph_building_failed']:
                    failed_docs.append(doc)
                    # Determine failure stage
                    stage = self._determine_failure_stage(doc)
                    stage_errors[stage].append({
                        'file': doc['original_file_name'],
                        'uuid': doc['document_uuid'],
                        'error': doc.get('error_message', 'Unknown error')
                    })
                
                # Track recently processed documents
                if doc.get('updated_at'):
                    updated = self._parse_datetime(doc['updated_at'])
                    if updated and updated > recent_threshold and status in ['completed', 'failed']:
                        recently_processed.append({
                            'uuid': doc['document_uuid'],
                            'file': doc['original_file_name'],
                            'status': status,
                            'time': updated,
                            'stage': self._determine_processing_stage(doc['document_uuid']) if status == 'completed' else self._determine_failure_stage(doc)
                        })
                
                # Calculate processing times for completed
                elif status == 'completed':
                    try:
                        created = self._parse_datetime(doc['created_at'])
                        updated = self._parse_datetime(doc['updated_at'])
                        if created and updated:
                            processing_time = (updated - created).total_seconds()
                            processing_times.append(processing_time)
                    except:
                        pass
            
            # Calculate average processing time
            avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
            
            # Get processing stages for active documents
            stage_counts = Counter()
            for doc in processing_docs:
                stage = self._determine_processing_stage(doc['document_uuid'])
                stage_counts[stage] += 1
            
            # Sort recently processed by time
            recently_processed.sort(key=lambda x: x['time'], reverse=True)
            
            return {
                'status_counts': dict(status_counts),
                'file_type_counts': dict(file_type_counts),
                'total_documents': sum(status_counts.values()),
                'processing_documents': processing_docs[:20],  # First 20
                'failed_documents': failed_docs[:10],  # First 10
                'stuck_documents': stuck_docs,
                'recently_processed': recently_processed[:10],  # Last 10
                'stage_counts': dict(stage_counts),
                'stage_errors': dict(stage_errors),
                'avg_processing_time_seconds': avg_processing_time,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            console.print(f"[red]Error getting pipeline stats: {e}[/red]")
            return {'error': str(e)}
    
    def _determine_processing_stage(self, document_uuid: str) -> str:
        """Determine the processing stage of a document using RDS."""
        try:
            from scripts.rds_utils import execute_query
            
            # Check if document chunks exist
            chunks_query = """
            SELECT COUNT(*) as chunk_count 
            FROM document_chunks 
            WHERE document_uuid = %s
            """
            chunks_result = execute_query(chunks_query, (document_uuid,))
            chunk_count = chunks_result[0]['chunk_count'] if chunks_result else 0
            
            if chunk_count == 0:
                return 'ocr'
            
            # Check if entities exist
            entities_query = """
            SELECT COUNT(*) as entity_count 
            FROM entity_mentions em
            JOIN document_chunks dc ON em.chunk_uuid = dc.chunk_uuid
            WHERE dc.document_uuid = %s
            """
            entities_result = execute_query(entities_query, (document_uuid,))
            entity_count = entities_result[0]['entity_count'] if entities_result else 0
            
            if entity_count == 0:
                return 'chunking'
            
            # Check if relationships exist (using correct table name)
            relationships_query = """
            SELECT COUNT(*) as rel_count 
            FROM relationship_staging rs
            JOIN canonical_entities ce ON rs.source_entity_uuid = ce.canonical_entity_uuid
            JOIN entity_mentions em ON ce.canonical_entity_uuid = em.canonical_entity_uuid
            WHERE em.document_uuid = %s
            """
            relationships_result = execute_query(relationships_query, (document_uuid,))
            rel_count = relationships_result[0]['rel_count'] if relationships_result else 0
            
            if rel_count == 0:
                return 'entity_extraction'
            
            return 'relationship_building'
        except Exception as e:
            console.print(f"[yellow]Warning: Could not determine processing stage for {document_uuid}: {e}[/yellow]")
            return 'unknown'
            
    def _determine_failure_stage(self, doc: Dict) -> str:
        """Determine at which stage a document failed."""
        status = doc.get('celery_status', '')
        error_msg = doc.get('error_message', '')
        
        # Check for specific failure statuses
        if status == 'ocr_failed' or 'textract' in error_msg.lower() or 'ocr' in error_msg.lower():
            return 'ocr'
        elif status == 'chunking_failed' or 'chunk' in error_msg.lower():
            return 'chunking'
        elif status == 'entity_extraction_failed' or 'entity extraction' in error_msg.lower():
            return 'entity_extraction'
        elif status == 'entity_resolution_failed' or 'resolution' in error_msg.lower():
            return 'entity_resolution'
        elif status == 'graph_building_failed' or 'graph' in error_msg.lower() or 'relationship' in error_msg.lower():
            return 'graph_building'
        
        # Check OCR metadata for errors
        if doc.get('ocr_metadata_json'):
            for entry in doc['ocr_metadata_json']:
                if isinstance(entry, dict) and entry.get('status') == 'error':
                    stage = entry.get('stage', '').lower()
                    if 'upload' in stage or 's3' in stage:
                        return 'ocr_upload'
                    elif 'textract' in stage:
                        return 'ocr_textract'
                    else:
                        return 'ocr'
        
        # Default based on what exists
        return self._determine_processing_stage(doc['document_uuid'])
            
    def get_celery_stats(self) -> Dict:
        """Get Celery worker and task statistics."""
        try:
            # Set short timeout for inspect operations
            inspect = self.celery_app.control.inspect(timeout=2.0)
            
            # Get active tasks with timeout
            active = None
            stats = None
            # Variables for worker inspection - commented out as not currently used
            # registered = None
            # reserved = None
            
            try:
                active = inspect.active()
            except Exception as e:
                console.print(f"[yellow]Warning: Could not get active tasks: {e}[/yellow]")
            
            try:
                stats = inspect.stats()
            except Exception as e:
                console.print(f"[yellow]Warning: Could not get worker stats: {e}[/yellow]")
            
            # Currently not used - uncomment if needed for debugging
            # try:
            #     registered = inspect.registered()
            # except Exception as e:
            #     console.print(f"[yellow]Warning: Could not get registered tasks: {e}[/yellow]")
            
            # try:
            #     reserved = inspect.reserved()
            # except Exception as e:
            #     console.print(f"[yellow]Warning: Could not get reserved tasks: {e}[/yellow]")
            
            # Process results
            active_tasks = []
            task_counts = Counter()
            worker_info = {}
            
            if active:
                for worker, tasks in active.items():
                    worker_name = worker.split('@')[1] if '@' in worker else worker
                    active_tasks.extend(tasks)
                    worker_info[worker_name] = {
                        'active_count': len(tasks),
                        'tasks': [t.get('name', 'Unknown').split('.')[-1] for t in tasks]
                    }
                    for task in tasks:
                        task_name = task.get('name', 'Unknown').split('.')[-1]
                        task_counts[task_name] += 1
            
            if stats:
                for worker, info in stats.items():
                    worker_name = worker.split('@')[1] if '@' in worker else worker
                    if worker_name not in worker_info:
                        worker_info[worker_name] = {}
                    worker_info[worker_name].update({
                        'pool': info.get('pool', {}),
                        'total_tasks': info.get('total', {})
                    })
            
            # Get queue lengths from Redis
            queue_lengths = {}
            if self.redis_available and self.redis_client:
                try:
                    for queue in ['ocr', 'text', 'entity', 'graph', 'embeddings', 'celery']:
                        queue_key = f"celery.{queue}"
                        length = self.redis_client.llen(queue_key)
                        if length > 0:
                            queue_lengths[queue] = length
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not get queue lengths: {e}[/yellow]")
            
            return {
                'active_tasks': active_tasks,
                'active_count': len(active_tasks),
                'task_counts': dict(task_counts),
                'worker_count': len(worker_info),
                'workers': worker_info,
                'queue_lengths': queue_lengths,
                'total_queued': sum(queue_lengths.values())
            }
        except Exception as e:
            console.print(f"[red]Error getting Celery stats: {e}[/red]")
            return {
                'error': str(e),
                'active_count': 0,
                'worker_count': 0,
                'workers': {},
                'queue_lengths': {}
            }
            
    def get_redis_stats(self) -> Dict:
        """Get Redis cache statistics."""
        if not self.redis_available or not self.redis_client:
            return {
                'available': False,
                'error': 'Redis not available'
            }
            
        try:
            info = self.redis_client.info()
            
            # Get cache hit rate
            keyspace_hits = info.get('keyspace_hits', 0)
            keyspace_misses = info.get('keyspace_misses', 0)
            total_ops = keyspace_hits + keyspace_misses
            hit_rate = (keyspace_hits / total_ops * 100) if total_ops > 0 else 0
            
            # Count keys by pattern (with timeout) - all on DB 0
            cache_patterns = {
                'document_states': 'doc:state:*',
                'ocr_results': 'doc:ocr:*',
                'chunks': 'doc:chunks:*',
                'entity_mentions': 'doc:entity_mentions:*',
                'canonical_entities': 'doc:canonical_entities:*',
                'batch_progress': 'batch:progress:*',
                'rate_limits': 'rate:limit:*',
                'metrics': 'metrics:*'
            }
            
            key_counts = {}
            total_keys = 0
            active_batches = 0
            rate_limited_endpoints = 0
            
            for name, pattern in cache_patterns.items():
                try:
                    # Use SCAN with small count to avoid blocking
                    count = 0
                    for key in self.redis_client.scan_iter(match=pattern, count=100):
                        count += 1
                        if count > 1000:  # Limit to prevent hanging
                            count = f"{count}+"
                            break
                        
                        # Check for active batches
                        if name == 'batch_progress' and isinstance(count, int) and count <= 100:
                            try:
                                data = self.redis_client.get(key)
                                if data:
                                    import json
                                    batch_data = json.loads(data)
                                    if batch_data.get('status') == 'processing':
                                        active_batches += 1
                            except:
                                pass
                                
                    key_counts[name] = count
                    if isinstance(count, int):
                        total_keys += count
                        if name == 'rate_limits':
                            rate_limited_endpoints = count
                except:
                    key_counts[name] = 'N/A'
                    
            return {
                'available': True,
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_human': info.get('used_memory_human', 'N/A'),
                'used_memory_peak_human': info.get('used_memory_peak_human', 'N/A'),
                'hit_rate': f"{hit_rate:.1f}%",
                'keyspace_hits': keyspace_hits,
                'keyspace_misses': keyspace_misses,
                'evicted_keys': info.get('evicted_keys', 0),
                'key_counts': key_counts,
                'total_keys': total_keys,
                'active_batches': active_batches,
                'rate_limited_endpoints': rate_limited_endpoints,
                'uptime_days': info.get('uptime_in_days', 0)
            }
        except Exception as e:
            return {
                'available': False,
                'error': str(e)
            }
    
    def _read_batch_progress(self, key: str) -> Dict:
        """Read batch progress data, handling both JSON string and hash formats."""
        try:
            import json
            # Try to get as JSON string first (new format)
            data = self.redis_client.get(key)
            if data:
                return json.loads(data)
        except Exception:
            pass
        
        try:
            # Fallback to hash format (old format)
            raw_data = self.redis_client.hgetall(key)
            batch_data = {}
            for field, value in raw_data.items():
                # Try to parse JSON values
                try:
                    batch_data[field] = json.loads(value)
                except:
                    batch_data[field] = value
            return batch_data
        except Exception:
            return {}

    def get_batch_stats(self) -> Dict:
        """Get batch processing statistics."""
        if not self.redis_available:
            return {
                'available': False,
                'error': 'Redis not available'
            }
        
        try:
            from scripts.config import REDIS_PREFIX_BATCH
            from scripts.batch_metrics import BatchMetricsCollector
            
            # Get active batches
            batch_pattern = f"{REDIS_PREFIX_BATCH}progress:*"
            active_batches = []
            completed_batches = []
            
            for key in self.redis_client.scan_iter(match=batch_pattern, count=100):
                try:
                    batch_data = self._read_batch_progress(key)
                    
                    if batch_data:
                        batch_id = key.split(':')[-1]
                        batch_data['batch_id'] = batch_id
                        
                        if batch_data.get('status') == 'processing':
                            active_batches.append(batch_data)
                        elif batch_data.get('status') == 'completed':
                            completed_batches.append(batch_data)
                except Exception as e:
                    console.print(f"[yellow]Error reading batch {key}: {e}[/yellow]")
            
            # Get metrics for last 24 hours
            collector = BatchMetricsCollector()
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=24)
            
            batch_metrics = collector.get_batch_metrics(start_time, end_time)
            stage_metrics = collector.get_stage_metrics(start_time, end_time)
            error_summary = collector.get_error_summary(hours=1)
            
            # Sort batches by start time
            active_batches.sort(key=lambda x: x.get('started_at', ''), reverse=True)
            completed_batches.sort(key=lambda x: x.get('completed_at', ''), reverse=True)
            
            return {
                'available': True,
                'active_batches': active_batches[:10],  # Limit to 10 most recent
                'completed_batches': completed_batches[:10],
                'metrics_24h': batch_metrics,
                'stage_performance': stage_metrics,
                'recent_errors': error_summary
            }
            
        except Exception as e:
            return {
                'available': False,
                'error': str(e)
            }
    
    def get_textract_jobs(self) -> Dict:
        """Get pending Textract jobs status."""
        try:
            from scripts.rds_utils import execute_query
            
            # Get all documents with pending Textract jobs
            query = """
            SELECT 
                sd.document_uuid,
                sd.original_file_name,
                sd.textract_job_id,
                sd.textract_job_status,
                sd.textract_start_time,
                sd.textract_page_count,
                sd.status
            FROM source_documents sd
            WHERE sd.textract_job_status IN ('IN_PROGRESS', 'SUBMITTED')
               OR (sd.textract_job_id IS NOT NULL AND sd.textract_job_status IS NULL)
            ORDER BY sd.textract_start_time DESC
            LIMIT 10
            """
            
            results = execute_query(query)
            pending_jobs = []
            now = datetime.now(timezone.utc)
            
            for row in results:
                start_time = self._parse_datetime(row.get('textract_start_time'))
                if start_time:
                    duration = (now - start_time).total_seconds()
                else:
                    duration = 0
                
                pending_jobs.append({
                    'job_id': row.get('textract_job_id', 'Unknown'),
                    'document_uuid': str(row.get('document_uuid', '')),
                    'file_name': row.get('original_file_name', 'Unknown'),
                    'status': row.get('textract_job_status', 'UNKNOWN'),
                    'duration_seconds': duration,
                    'pages': row.get('textract_page_count', 0)
                })
            
            return {
                'pending_count': len(pending_jobs),
                'jobs': pending_jobs
            }
        except Exception as e:
            console.print(f"[red]Error getting Textract jobs: {e}[/red]")
            return {'pending_count': 0, 'jobs': []}
    
    def _parse_datetime(self, datetime_str: str) -> datetime:
        """Safely parse datetime string handling various formats."""
        if not datetime_str:
            return None
        
        try:
            # If it's already a datetime object, return it
            if isinstance(datetime_str, datetime):
                return datetime_str
            
            # Handle string formats
            if datetime_str.endswith('Z'):
                # Remove Z and parse as UTC
                dt_str = datetime_str[:-1]
                if '+00:00' in dt_str:
                    # Already has timezone info, just remove Z
                    return datetime.fromisoformat(dt_str)
                else:
                    # Add UTC timezone
                    return datetime.fromisoformat(dt_str + '+00:00')
            elif '+00:00' in datetime_str:
                # Already has timezone, parse directly
                return datetime.fromisoformat(datetime_str)
            else:
                # No timezone info, assume UTC
                dt = datetime.fromisoformat(datetime_str)
                return dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not parse datetime '{datetime_str}': {e}[/yellow]")
            return None

    def get_ocr_status(self) -> Dict:
        """Track Textract job status."""
        try:
            from scripts.rds_utils import execute_query
            
            query = """
            SELECT 
                status,
                COUNT(*) as count,
                AVG(EXTRACT(EPOCH FROM (NOW() - created_at))) as avg_wait_time
            FROM textract_jobs
            WHERE created_at > NOW() - INTERVAL '1 hour'
            GROUP BY status
            """
            
            results = execute_query(query)
            ocr_stats = {
                'active_jobs': 0,
                'completed_jobs': 0,
                'failed_jobs': 0,
                'avg_wait_time': 0
            }
            
            for row in results:
                status = row.get('status', '')
                count = row.get('count', 0)
                
                if status in ['PENDING', 'IN_PROGRESS']:
                    ocr_stats['active_jobs'] += count
                elif status == 'SUCCEEDED':
                    ocr_stats['completed_jobs'] = count
                elif status == 'FAILED':
                    ocr_stats['failed_jobs'] = count
                    
                if row.get('avg_wait_time'):
                    ocr_stats['avg_wait_time'] = max(ocr_stats['avg_wait_time'], row['avg_wait_time'])
            
            return ocr_stats
        except Exception as e:
            console.print(f"[yellow]Warning: Could not get OCR status: {e}[/yellow]")
            return {
                'active_jobs': 0,
                'completed_jobs': 0,
                'failed_jobs': 0,
                'avg_wait_time': 0
            }
    
    def identify_bottlenecks(self) -> Dict:
        """Identify where documents are getting stuck."""
        try:
            from scripts.rds_utils import execute_query
            
            # Check for stuck OCR jobs
            stuck_ocr_query = """
            SELECT COUNT(*) as count
            FROM processing_tasks pt
            JOIN textract_jobs tj ON pt.document_id = tj.document_uuid
            WHERE pt.task_type = 'extract_text'
            AND pt.status = 'completed'
            AND tj.status IN ('PENDING', 'IN_PROGRESS')
            AND tj.created_at < NOW() - INTERVAL '30 minutes'
            """
            
            stuck_ocr_result = execute_query(stuck_ocr_query)
            stuck_ocr_count = stuck_ocr_result[0]['count'] if stuck_ocr_result else 0
            
            # Check for missing chunk tasks
            missing_chunks_query = """
            SELECT COUNT(*) as count
            FROM source_documents sd
            LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
            WHERE sd.status = 'pending'
            AND dc.chunk_uuid IS NULL
            AND sd.created_at < NOW() - INTERVAL '1 hour'
            """
            
            missing_chunks_result = execute_query(missing_chunks_query)
            missing_chunks_count = missing_chunks_result[0]['count'] if missing_chunks_result else 0
            
            # Check for batch processor errors
            batch_errors_query = """
            SELECT task_type, error_message, COUNT(*) as count
            FROM processing_tasks
            WHERE status = 'failed'
            AND created_at > NOW() - INTERVAL '1 hour'
            GROUP BY task_type, error_message
            ORDER BY count DESC
            LIMIT 5
            """
            
            batch_errors_result = execute_query(batch_errors_query)
            
            return {
                'stuck_ocr_jobs': stuck_ocr_count,
                'missing_chunks': missing_chunks_count,
                'recent_errors': batch_errors_result or []
            }
        except Exception as e:
            console.print(f"[yellow]Warning: Could not identify bottlenecks: {e}[/yellow]")
            return {
                'stuck_ocr_jobs': 0,
                'missing_chunks': 0,
                'recent_errors': []
            }

    def format_duration(self, seconds: float) -> str:
        """Format duration in seconds to human-readable string."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"

@click.group()
def cli():
    """Unified monitoring commands for the document processing pipeline."""
    pass

@cli.command()
@click.option('--refresh', '-r', default=5, help='Refresh interval in seconds')
@click.option('--once', is_flag=True, help='Run once and exit')
def live(refresh, once):
    """Live monitoring dashboard with auto-refresh."""
    monitor = UnifiedMonitor()
    
    def create_dashboard():
        """Create the monitoring dashboard."""
        # Get all stats
        pipeline_stats = monitor.get_pipeline_stats()
        celery_stats = monitor.get_celery_stats()
        redis_stats = monitor.get_redis_stats()
        textract_jobs = monitor.get_textract_jobs()
        batch_stats = monitor.get_batch_stats()
        
        # Create layout
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3)
        )
        
        # Header
        header_text = Text("📊 Legal Document Processing Pipeline Monitor", style="bold cyan")
        header_text.append(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="dim")
        layout["header"].update(Panel(header_text, box=box.ROUNDED))
        
        # Main content split
        layout["main"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1)
        )
        
        # Left side - Pipeline stats
        left_content = Layout()
        left_content.split_column(
            Layout(name="status", size=10),
            Layout(name="recent_feed", size=12),
            Layout(name="processing"),
            Layout(name="errors")
        )
        
        # Status table
        status_table = Table(title="Document Status", box=box.SIMPLE)
        status_table.add_column("Status", style="cyan")
        status_table.add_column("Count", style="magenta")
        status_table.add_column("%", style="yellow")
        
        total_docs = pipeline_stats.get('total_documents', 0)
        for status, count in sorted(pipeline_stats.get('status_counts', {}).items()):
            percentage = (count / total_docs * 100) if total_docs > 0 else 0
            emoji = {
                'completed': '✅',
                'failed': '❌',
                'processing': '🔄',
                'pending': '⏳',
                'submitted': '📤'
            }.get(status, '❓')
            status_table.add_row(f"{emoji} {status}", str(count), f"{percentage:.1f}%")
        
        left_content["status"].update(Panel(status_table, title="📄 Documents", box=box.ROUNDED))
        
        # Recent document feed
        recent_docs = pipeline_stats.get('recently_processed', [])
        if recent_docs:
            recent_table = Table(box=box.SIMPLE)
            recent_table.add_column("Time", style="dim", width=8)
            recent_table.add_column("UUID", style="cyan", width=12)
            recent_table.add_column("File", style="white", width=25)
            recent_table.add_column("Status", style="yellow", width=10)
            
            for doc in recent_docs[:8]:  # Show last 8
                time_str = doc['time'].strftime('%H:%M:%S')
                uuid_short = doc['uuid'][:8] + "..."
                filename = doc['file']
                if len(filename) > 25:
                    filename = filename[:22] + "..."
                
                status_emoji = '✅' if doc['status'] == 'completed' else '❌'
                status_color = 'green' if doc['status'] == 'completed' else 'red'
                recent_table.add_row(
                    time_str, 
                    uuid_short, 
                    filename,
                    f"[{status_color}]{status_emoji} {doc['status']}[/{status_color}]"
                )
            
            left_content["recent_feed"].update(Panel(recent_table, title="🔄 Recent Activity", box=box.ROUNDED))
        else:
            left_content["recent_feed"].update(Panel("No recent activity", title="🔄 Recent Activity", box=box.ROUNDED))
        
        # Processing documents
        processing_docs = pipeline_stats.get('processing_documents', [])
        if processing_docs:
            proc_table = Table(box=box.SIMPLE)
            proc_table.add_column("File", style="cyan", width=30)
            proc_table.add_column("Stage", style="yellow")
            proc_table.add_column("Duration", style="green")
            
            for doc in processing_docs[:5]:  # Show first 5
                filename = doc['original_file_name']
                if len(filename) > 30:
                    filename = filename[:27] + "..."
                
                # Calculate duration
                created = monitor._parse_datetime(doc['created_at'])
                if created:
                    duration = (datetime.now(timezone.utc) - created).total_seconds()
                else:
                    duration = 0
                
                stage = monitor._determine_processing_stage(doc['document_uuid'])
                proc_table.add_row(filename, stage, monitor.format_duration(duration))
            
            left_content["processing"].update(Panel(proc_table, title=f"⏳ Processing ({len(processing_docs)})", box=box.ROUNDED))
        
        # Recent errors
        failed_docs = pipeline_stats.get('failed_documents', [])
        if failed_docs:
            error_table = Table(box=box.SIMPLE)
            error_table.add_column("File", style="red", width=30)
            error_table.add_column("Error", style="dim red", width=40)
            
            for doc in failed_docs[:3]:  # Show first 3
                filename = doc['original_file_name']
                if len(filename) > 30:
                    filename = filename[:27] + "..."
                error = doc.get('error_message') or 'Unknown error'
                if len(error) > 40:
                    error = error[:37] + "..."
                error_table.add_row(filename, error)
            
            left_content["errors"].update(Panel(error_table, title="❌ Recent Errors", box=box.ROUNDED))
        
        layout["left"].update(left_content)
        
        # Right side - System stats
        right_content = Layout()
        right_content.split_column(
            Layout(name="ocr_status", size=7),
            Layout(name="bottlenecks", size=8),
            Layout(name="workers", size=8),
            Layout(name="queues", size=6),
            Layout(name="batches", size=10),
            Layout(name="textract", size=8),
            Layout(name="stage_errors", size=6),
            Layout(name="redis", size=5)
        )
        
        # Workers
        worker_table = Table(title="Celery Workers", box=box.SIMPLE)
        worker_table.add_column("Worker", style="cyan")
        worker_table.add_column("Active", style="yellow")
        worker_table.add_column("Pool", style="green")
        
        for worker_name, info in celery_stats.get('workers', {}).items():
            pool_type = info.get('pool', {}).get('implementation', 'N/A')
            if pool_type == 'prefork':
                pool_type = f"Fork({info.get('pool', {}).get('max-concurrency', '?')})"
            worker_table.add_row(worker_name, str(info.get('active_count', 0)), pool_type)
        
        if not celery_stats.get('workers'):
            worker_table.add_row("No workers", "-", "-")
        
        # OCR Status
        ocr_table = Table(box=box.SIMPLE)
        ocr_table.add_column("Metric", style="cyan")
        ocr_table.add_column("Value", style="yellow")
        ocr_table.add_row("Active Jobs", str(ocr_status['active_jobs']))
        ocr_table.add_row("Completed", str(ocr_status['completed_jobs']))
        ocr_table.add_row("Failed", str(ocr_status['failed_jobs']))
        ocr_table.add_row("Avg Wait", f"{ocr_status['avg_wait_time']:.1f}s")
        right_content["ocr_status"].update(Panel(ocr_table, title="🔍 OCR Processing", box=box.ROUNDED))
        
        # Bottleneck Detection
        if bottlenecks['stuck_ocr_jobs'] > 0 or bottlenecks['missing_chunks'] > 0:
            bottleneck_text = Text()
            bottleneck_text.append("⚠️  ISSUES DETECTED:\n", style="bold red")
            if bottlenecks['stuck_ocr_jobs'] > 0:
                bottleneck_text.append(f"• {bottlenecks['stuck_ocr_jobs']} OCR jobs stuck\n", style="red")
            if bottlenecks['missing_chunks'] > 0:
                bottleneck_text.append(f"• {bottlenecks['missing_chunks']} documents missing chunks\n", style="red")
            if bottlenecks['recent_errors']:
                bottleneck_text.append(f"• {len(bottlenecks['recent_errors'])} error types\n", style="red")
            right_content["bottlenecks"].update(Panel(bottleneck_text, title="🚨 Bottlenecks", box=box.ROUNDED, border_style="red"))
        else:
            right_content["bottlenecks"].update(Panel("✅ No bottlenecks detected", title="🚨 Bottlenecks", box=box.ROUNDED, border_style="green"))
        
        right_content["workers"].update(Panel(worker_table, title="👷 Workers", box=box.ROUNDED))
        
        # Queues
        queue_table = Table(box=box.SIMPLE)
        queue_table.add_column("Queue", style="cyan")
        queue_table.add_column("Length", style="magenta")
        
        queue_lengths = celery_stats.get('queue_lengths', {})
        if queue_lengths:
            for queue, length in sorted(queue_lengths.items()):
                queue_table.add_row(queue.upper(), str(length))
        else:
            queue_table.add_row("All queues empty", "-")
        
        right_content["queues"].update(Panel(queue_table, title="📥 Queues", box=box.ROUNDED))
        
        # Batch processing stats
        batch_stats = monitor.get_batch_stats()
        if batch_stats.get('available'):
            batch_table = Table(box=box.SIMPLE)
            batch_table.add_column("Batch Type", style="cyan", width=20)
            batch_table.add_column("Count", style="magenta", width=10)
            
            # Show active batches
            active_count = len(batch_stats.get('active_batches', []))
            if active_count > 0:
                batch_table.add_row("🔄 Active Batches", str(active_count))
                
                # Show first 3 active batches
                for batch in batch_stats.get('active_batches', [])[:3]:
                    batch_id_short = batch.get('batch_id', '')[:8] + "..."
                    priority = batch.get('priority', 'normal')
                    total = batch.get('total', 0)
                    completed = batch.get('completed', 0)
                    progress = (completed / total * 100) if total > 0 else 0
                    
                    batch_table.add_row(
                        f"  └─ {batch_id_short} ({priority})",
                        f"{completed}/{total} ({progress:.0f}%)"
                    )
            else:
                batch_table.add_row("No active batches", "-")
            
            # Show 24h metrics summary
            metrics_24h = batch_stats.get('metrics_24h', {}).get('summary', {})
            if metrics_24h:
                batch_table.add_row("", "")  # Empty row
                batch_table.add_row("📊 Last 24 Hours", "")
                batch_table.add_row("  └─ Total Batches", str(metrics_24h.get('total_batches', 0)))
                batch_table.add_row("  └─ Documents", str(metrics_24h.get('total_documents', 0)))
                batch_table.add_row("  └─ Success Rate", f"{metrics_24h.get('overall_success_rate', 0):.1f}%")
            
            right_content["batches"].update(Panel(batch_table, title="📦 Batch Processing", box=box.ROUNDED))
        else:
            right_content["batches"].update(Panel("Batch stats not available", title="📦 Batch Processing", box=box.ROUNDED))
        
        # Textract jobs
        if textract_jobs.get('pending_count', 0) > 0:
            textract_table = Table(box=box.SIMPLE)
            textract_table.add_column("File", style="cyan", width=25)
            textract_table.add_column("Status", style="yellow")
            textract_table.add_column("Duration", style="magenta")
            
            for job in textract_jobs.get('jobs', [])[:5]:  # Show first 5
                filename = job['file_name']
                if len(filename) > 25:
                    filename = filename[:22] + "..."
                textract_table.add_row(
                    filename,
                    job['status'],
                    monitor.format_duration(job['duration_seconds'])
                )
            
            right_content["textract"].update(Panel(
                textract_table, 
                title=f"⏳ Textract Jobs ({textract_jobs['pending_count']})", 
                box=box.ROUNDED
            ))
        else:
            right_content["textract"].update(Panel(
                "No pending Textract jobs", 
                title="⏳ Textract Jobs", 
                box=box.ROUNDED
            ))
        
        # Stage-specific errors
        stage_errors = pipeline_stats.get('stage_errors', {})
        if stage_errors:
            stage_error_table = Table(box=box.SIMPLE)
            stage_error_table.add_column("Stage", style="cyan")
            stage_error_table.add_column("Errors", style="red")
            
            stage_names = {
                'ocr': 'OCR',
                'ocr_upload': 'OCR Upload',
                'ocr_textract': 'Textract',
                'chunking': 'Chunking',
                'entity_extraction': 'Entity Extract',
                'entity_resolution': 'Entity Resolve',
                'graph_building': 'Graph Build'
            }
            
            for stage, errors in sorted(stage_errors.items()):
                stage_display = stage_names.get(stage, stage.replace('_', ' ').title())
                stage_error_table.add_row(stage_display, str(len(errors)))
            
            right_content["stage_errors"].update(Panel(stage_error_table, title="🚨 Errors by Stage", box=box.ROUNDED))
        else:
            right_content["stage_errors"].update(Panel("No stage errors", title="🚨 Errors by Stage", box=box.ROUNDED))
        
        # Redis stats
        if redis_stats.get('available'):
            redis_text = Text()
            redis_text.append(f"Memory: {redis_stats.get('used_memory_human', 'N/A')}\n")
            redis_text.append(f"Hit Rate: {redis_stats.get('hit_rate', 'N/A')}\n")
            redis_text.append(f"Clients: {redis_stats.get('connected_clients', 0)}\n")
            redis_text.append(f"Keys: {redis_stats.get('total_keys', 0)}")
        else:
            redis_text = Text("Redis not available", style="red")
        
        right_content["redis"].update(Panel(redis_text, title="💾 Redis Cache", box=box.ROUNDED))
        
        layout["right"].update(right_content)
        
        # Footer
        footer_text = Text(f"Press Ctrl+C to exit | Refresh: {refresh}s", style="dim")
        if pipeline_stats.get('avg_processing_time_seconds', 0) > 0:
            avg_time = monitor.format_duration(pipeline_stats['avg_processing_time_seconds'])
            footer_text.append(f" | Avg processing: {avg_time}", style="green")
        
        layout["footer"].update(Panel(footer_text, box=box.ROUNDED))
        
        return layout
    
    if once:
        console.print(create_dashboard())
    else:
        with Live(create_dashboard(), refresh_per_second=1, console=console) as live:
            try:
                while True:
                    time.sleep(refresh)
                    live.update(create_dashboard())
            except KeyboardInterrupt:
                pass
        console.print("\n[green]Monitoring stopped.[/green]")

@cli.command()
def pipeline():
    """Show pipeline statistics."""
    monitor = UnifiedMonitor()
    stats = monitor.get_pipeline_stats()
    
    # Status summary
    table = Table(title="Pipeline Status Summary", box=box.ROUNDED)
    table.add_column("Status", style="cyan", no_wrap=True)
    table.add_column("Count", style="magenta")
    table.add_column("Percentage", style="yellow")
    
    total = stats.get('total_documents', 0)
    for status, count in sorted(stats.get('status_counts', {}).items()):
        percentage = (count / total * 100) if total > 0 else 0
        emoji = {
            'completed': '✅',
            'failed': '❌', 
            'processing': '🔄',
            'pending': '⏳',
            'submitted': '📤'
        }.get(status, '❓')
        table.add_row(f"{emoji} {status}", str(count), f"{percentage:.1f}%")
    
    table.add_section()
    table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]", "100.0%")
    
    console.print(table)
    
    # Processing stages
    if stats.get('stage_counts'):
        console.print("\n")
        stage_table = Table(title="Documents by Processing Stage", box=box.ROUNDED)
        stage_table.add_column("Stage", style="cyan")
        stage_table.add_column("Count", style="magenta")
        
        for stage, count in stats['stage_counts'].items():
            stage_table.add_row(stage.replace('_', ' ').title(), str(count))
        
        console.print(stage_table)
    
    # File types
    if stats.get('file_type_counts'):
        console.print("\n")
        type_table = Table(title="Documents by File Type", box=box.ROUNDED)
        type_table.add_column("Type", style="cyan")
        type_table.add_column("Count", style="magenta")
        
        for file_type, count in sorted(stats['file_type_counts'].items(), key=lambda x: x[0] or 'unknown'):
            type_table.add_row(file_type or "unknown", str(count))
        
        console.print(type_table)
    
    # Recent failures
    failures = stats.get('failed_documents', [])
    if failures:
        console.print("\n[bold red]Recent Failures:[/bold red]")
        for fail in failures[:5]:
            console.print(f"• {fail['original_file_name']}: {fail.get('error_message', 'Unknown error')}")
    
    # Stuck documents
    stuck = stats.get('stuck_documents', [])
    if stuck:
        console.print(f"\n[bold yellow]⚠️  {len(stuck)} documents stuck in processing (>30 min):[/bold yellow]")
        for doc in stuck[:3]:
            console.print(f"• {doc['original_file_name']} (ID: {doc['id']})")

@cli.command()
def workers():
    """Show Celery worker status."""
    monitor = UnifiedMonitor()
    stats = monitor.get_celery_stats()
    
    console.print(f"[bold]Worker Count:[/bold] {stats.get('worker_count', 0)}")
    console.print(f"[bold]Active Tasks:[/bold] {stats.get('active_count', 0)}")
    console.print(f"[bold]Queued Tasks:[/bold] {stats.get('total_queued', 0)}")
    
    # Worker details table
    if stats.get('workers'):
        console.print("\n")
        table = Table(title="Worker Details", box=box.ROUNDED)
        table.add_column("Worker", style="cyan")
        table.add_column("Active", style="yellow")
        table.add_column("Pool Type", style="green")
        table.add_column("Concurrency", style="magenta")
        
        for worker_name, info in stats['workers'].items():
            pool = info.get('pool', {})
            pool_type = pool.get('implementation', 'N/A')
            concurrency = pool.get('max-concurrency', 'N/A')
            active = info.get('active_count', 0)
            
            table.add_row(worker_name, str(active), pool_type, str(concurrency))
        
        console.print(table)
    
    # Queue lengths
    if stats.get('queue_lengths'):
        console.print("\n")
        queue_table = Table(title="Queue Lengths", box=box.ROUNDED)
        queue_table.add_column("Queue", style="cyan")
        queue_table.add_column("Length", style="magenta")
        
        for queue, length in sorted(stats['queue_lengths'].items()):
            queue_table.add_row(queue.upper(), str(length))
        
        console.print(queue_table)
    
    # Active tasks
    if stats.get('task_counts'):
        console.print("\n")
        task_table = Table(title="Active Tasks by Type", box=box.ROUNDED)
        task_table.add_column("Task", style="cyan")
        task_table.add_column("Count", style="magenta")
        
        for task, count in sorted(stats['task_counts'].items()):
            task_table.add_row(task, str(count))
        
        console.print(task_table)

@cli.command(name='cache')
def redis_cache():
    """Show Redis cache statistics."""
    monitor = UnifiedMonitor()
    stats = monitor.get_redis_stats()
    
    if not stats.get('available'):
        console.print(f"[red]Redis not available: {stats.get('error', 'Connection failed')}[/red]")
        return
    
    # Basic stats
    console.print(f"[bold]Connected Clients:[/bold] {stats.get('connected_clients', 0)}")
    console.print(f"[bold]Memory Usage:[/bold] {stats.get('used_memory_human', 'N/A')} (peak: {stats.get('used_memory_peak_human', 'N/A')})")
    console.print(f"[bold]Cache Hit Rate:[/bold] {stats.get('hit_rate', 'N/A')} ({stats.get('keyspace_hits', 0):,} hits, {stats.get('keyspace_misses', 0):,} misses)")
    console.print(f"[bold]Evicted Keys:[/bold] {stats.get('evicted_keys', 0):,}")
    console.print(f"[bold]Uptime:[/bold] {stats.get('uptime_days', 0)} days")
    
    # Key counts
    key_counts = stats.get('key_counts', {})
    if key_counts:
        console.print("\n")
        table = Table(title="Cached Objects by Type", box=box.ROUNDED)
        table.add_column("Type", style="cyan")
        table.add_column("Count", style="magenta")
        
        for key_type, count in sorted(key_counts.items()):
            table.add_row(key_type, str(count))
        
        table.add_section()
        table.add_row("[bold]Total[/bold]", f"[bold]{stats.get('total_keys', 0)}[/bold]")
        
        console.print(table)

@cli.command()
@click.argument('document_uuid')
def document(document_uuid):
    """Show detailed status for a specific document by UUID."""
    console.print("[yellow]This command is temporarily disabled during migration from Supabase to RDS.[/yellow]")
    console.print("Use the 'live' command for real-time monitoring instead.")
    return
    
    monitor = UnifiedMonitor()
    
    try:
        # Get document details
        response = monitor.supabase.table('source_documents').select(
            '*'
        ).eq('document_uuid', document_uuid).execute()
        
        if not response.data:
            # Try by ID if it's a number
            if document_uuid.isdigit():
                response = monitor.supabase.table('source_documents').select(
                    '*'
                ).eq('id', int(document_uuid)).execute()
        
        if not response.data:
            console.print(f"[red]Document {document_uuid} not found.[/red]")
            return
            
        doc = response.data[0]
        
        # Document info panel
        doc_info = Table(box=box.SIMPLE)
        doc_info.add_column("Field", style="cyan")
        doc_info.add_column("Value", style="white")
        
        doc_info.add_row("ID", str(doc['id']))
        doc_info.add_row("UUID", doc['document_uuid'])
        doc_info.add_row("Filename", doc['original_file_name'])
        doc_info.add_row("File Type", doc.get('detected_file_type', 'N/A'))
        doc_info.add_row("Status", f"[yellow]{doc['celery_status']}[/yellow]")
        doc_info.add_row("Task ID", doc.get('celery_task_id', 'N/A'))
        doc_info.add_row("Created", doc['intake_timestamp'])
        doc_info.add_row("Updated", doc['last_modified_at'])
        
        console.print(Panel(doc_info, title=f"📄 Document: {doc['original_file_name']}", box=box.ROUNDED))
        
        # Processing stage
        if doc['celery_status'] == 'processing':
            stage = monitor._determine_processing_stage(doc['document_uuid'])
            console.print(f"\n[bold]Current Stage:[/bold] [yellow]{stage}[/yellow]")
        
        # Error details
        if doc.get('error_message'):
            console.print(f"\n[bold red]Error:[/bold red]")
            console.print(Panel(doc['error_message'], style="red", box=box.ROUNDED))
        
        # OCR metadata
        if doc.get('ocr_metadata_json'):
            console.print(f"\n[bold]OCR Metadata:[/bold]")
            for entry in doc['ocr_metadata_json']:
                if isinstance(entry, dict):
                    if entry.get('status') == 'error':
                        console.print(f"  [red]Error at {entry.get('stage', 'unknown')}:[/red] {entry.get('error_message', 'N/A')}")
                    elif entry.get('pages'):
                        console.print(f"  Pages processed: {entry.get('pages', 0)}")
        
        # Check downstream tables
        console.print(f"\n[bold]Processing Progress:[/bold]")
        
        # Neo4j document
        doc_node = monitor.supabase.table('neo4j_documents').select('id').eq('documentId', doc['document_uuid']).execute()
        console.print(f"  Document Node: {'✅ Created' if doc_node.data else '❌ Not created'}")
        
        # Chunks
        chunks = monitor.supabase.table('neo4j_chunks').select('id').eq('document_uuid', doc['document_uuid']).execute()
        console.print(f"  Chunks: {'✅ ' + str(len(chunks.data)) + ' chunks' if chunks.data else '❌ No chunks'}")
        
        # Entities
        # Get chunks first to find entity mentions
        chunks = monitor.supabase.table('neo4j_chunks').select('chunkId').eq('document_uuid', doc['document_uuid']).execute()
        if chunks.data:
            chunk_uuids = [c['chunkId'] for c in chunks.data]
            entities = monitor.supabase.table('neo4j_entity_mentions').select('id').in_('chunk_uuid', chunk_uuids).execute()
        else:
            entities = {'data': []}
        console.print(f"  Entities: {'✅ ' + str(len(entities.data)) + ' entities' if entities.data else '❌ No entities'}")
        
        # Relationships
        relationships = monitor.supabase.table('neo4j_relationships_staging').select('id').eq('from_node_id', doc['document_uuid']).execute()
        console.print(f"  Relationships: {'✅ ' + str(len(relationships.data)) + ' relationships' if relationships.data else '❌ No relationships'}")
            
    except Exception as e:
        console.print(f"[red]Error retrieving document: {e}[/red]")

@cli.command()
@click.argument('action', type=click.Choice(['stop', 'start', 'retry']))
@click.argument('document_uuid')
@click.option('--stage', help='Specific stage to start from (for retry)')
def control(action, document_uuid, stage):
    """Control individual document processing (stop/start/retry)."""
    console.print("[yellow]This command is temporarily disabled during migration from Supabase to RDS.[/yellow]")
    console.print("Use Celery commands directly for worker control.")
    return
    
    monitor = UnifiedMonitor()
    
    try:
        # Get document details
        response = monitor.supabase.table('source_documents').select(
            'id', 'document_uuid', 'original_file_name', 'original_file_path', 
            'celery_status', 'celery_task_id', 'project_fk_id', 'detected_file_type', 's3_key'
        ).eq('document_uuid', document_uuid).execute()
        
        if not response.data:
            console.print(f"[red]Document {document_uuid} not found.[/red]")
            return
            
        doc = response.data[0]
        
        if action == 'stop':
            # Revoke Celery task if active
            if doc.get('celery_task_id'):
                monitor.celery_app.control.revoke(doc['celery_task_id'], terminate=True)
                console.print(f"[yellow]Revoking task {doc['celery_task_id']}...[/yellow]")
            
            # Update status to stopped
            monitor.supabase.table('source_documents').update({
                'celery_status': 'stopped',
                'error_message': 'Processing stopped by user'
            }).eq('id', doc['id']).execute()
            
            console.print(f"[green]✅ Stopped processing for {doc['original_file_name']}[/green]")
            
        elif action == 'start':
            # Check if already processing
            if doc['celery_status'] == 'processing':
                console.print(f"[yellow]Document is already processing.[/yellow]")
                return
                
            # Import and submit processing task
            from scripts.pdf_tasks import process_pdf_document
            
            # Submit to Celery
            task = process_pdf_document.delay(
                document_uuid=doc['document_uuid'],
                project_uuid=doc.get('project_uuid', ''),
                options={}
            )
            
            # Update document with task ID
            monitor.supabase.table('source_documents').update({
                'celery_task_id': task.id,
                'celery_status': 'submitted',
                'error_message': None
            }).eq('id', doc['id']).execute()
            
            console.print(f"[green]✅ Started processing for {doc['original_file_name']}[/green]")
            console.print(f"Task ID: {task.id}")
            
        elif action == 'retry':
            # Clear error and set to pending
            monitor.supabase.table('source_documents').update({
                'celery_status': 'pending',
                'celery_task_id': None,
                'error_message': None
            }).eq('id', doc['id']).execute()
            
            if stage:
                # Clear downstream data based on stage
                if stage in ['ocr', 'document_creation']:
                    # Clear everything
                    monitor.supabase.table('neo4j_documents').delete().eq('documentId', document_uuid).execute()
                    monitor.supabase.table('neo4j_chunks').delete().eq('document_uuid', document_uuid).execute()
                    # Delete entity mentions by chunk_uuid
                    chunks_to_delete = monitor.supabase.table('neo4j_chunks').select('chunkId').eq('document_uuid', document_uuid).execute()
                    if chunks_to_delete.data:
                        chunk_uuids = [c['chunkId'] for c in chunks_to_delete.data]
                        monitor.supabase.table('neo4j_entity_mentions').delete().in_('chunk_uuid', chunk_uuids).execute()
                    monitor.supabase.table('neo4j_relationships_staging').delete().eq('from_node_id', document_uuid).execute()
                elif stage == 'chunking':
                    # Clear chunks and downstream
                    monitor.supabase.table('neo4j_chunks').delete().eq('document_uuid', document_uuid).execute()
                    # Delete entity mentions by chunk_uuid
                    chunks_to_delete = monitor.supabase.table('neo4j_chunks').select('chunkId').eq('document_uuid', document_uuid).execute()
                    if chunks_to_delete.data:
                        chunk_uuids = [c['chunkId'] for c in chunks_to_delete.data]
                        monitor.supabase.table('neo4j_entity_mentions').delete().in_('chunk_uuid', chunk_uuids).execute()
                    monitor.supabase.table('neo4j_relationships_staging').delete().eq('from_node_id', document_uuid).execute()
                elif stage == 'entity_extraction':
                    # Clear entities and relationships
                    # Delete entity mentions by chunk_uuid
                    chunks_to_delete = monitor.supabase.table('neo4j_chunks').select('chunkId').eq('document_uuid', document_uuid).execute()
                    if chunks_to_delete.data:
                        chunk_uuids = [c['chunkId'] for c in chunks_to_delete.data]
                        monitor.supabase.table('neo4j_entity_mentions').delete().in_('chunk_uuid', chunk_uuids).execute()
                    monitor.supabase.table('neo4j_relationships_staging').delete().eq('from_node_id', document_uuid).execute()
                elif stage == 'graph_building':
                    # Clear only relationships
                    monitor.supabase.table('neo4j_relationships_staging').delete().eq('from_node_id', document_uuid).execute()
                
                console.print(f"[yellow]Cleared data from {stage} onwards[/yellow]")
            
            console.print(f"[green]✅ Reset {doc['original_file_name']} for retry[/green]")
            console.print("Use 'monitor control start' to begin processing")
            
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()

@cli.command()
@click.option('--check-interval', '-i', default=15, help='Check interval in seconds')
@click.option('--once', is_flag=True, help='Check once and exit')
def textract(check_interval, once):
    """Monitor and process pending Textract jobs."""
    monitor = UnifiedMonitor()
    
    def check_textract_jobs():
        """Check for completed Textract jobs and process them."""
        jobs = monitor.get_textract_jobs()
        
        if jobs.get('pending_count', 0) == 0:
            console.print("[dim]No pending Textract jobs[/dim]")
            return
        
        console.print(f"\n[bold]Found {jobs['pending_count']} pending Textract jobs[/bold]")
        
        # Import required modules
        from scripts.textract_utils import check_textract_job_status
        from scripts.database import SupabaseManager
        
        db = SupabaseManager()
        processed = 0
        
        for job in jobs.get('jobs', []):
            job_id = job['job_id']
            doc_uuid = job['document_uuid']
            
            console.print(f"\n📄 Checking job for {job['file_name'][:50]}...")
            console.print(f"   Job ID: {job_id}")
            console.print(f"   Status: {job['status']}")
            console.print(f"   Duration: {monitor.format_duration(job['duration_seconds'])}")
            
            try:
                # Check job status with AWS
                status, result = check_textract_job_status(job_id)
                console.print(f"   AWS Status: {status}")
                
                if status == 'SUCCEEDED':
                    console.print(f"   [green]✅ Textract completed! Processing results...[/green]")
                    
                    # Get document info
                    doc_response = db.client.table('source_documents').select(
                        'id', 'celery_task_id', 'project_fk_id'
                    ).eq('document_uuid', doc_uuid).execute()
                    
                    if doc_response.data:
                        doc = doc_response.data[0]
                        
                        # Import and trigger the continuation task
                        from scripts.celery_tasks.ocr_tasks import process_textract_result
                        
                        # Submit task to process the result
                        task = process_textract_result.delay(
                            job_id=job_id,
                            document_uuid=doc_uuid,
                            source_doc_sql_id=doc['id'],
                            project_sql_id=doc['project_fk_id']
                        )
                        
                        console.print(f"   [green]Submitted processing task: {task.id}[/green]")
                        processed += 1
                        
                elif status == 'FAILED':
                    console.print(f"   [red]❌ Textract job failed[/red]")
                    if result:
                        console.print(f"   [red]Error: {result}[/red]")
                        
                elif status == 'IN_PROGRESS':
                    console.print(f"   [yellow]⏳ Still processing...[/yellow]")
                    
            except Exception as e:
                console.print(f"   [red]Error checking job: {e}[/red]")
                import traceback
                traceback.print_exc()
        
        if processed > 0:
            console.print(f"\n[green]✅ Triggered processing for {processed} completed jobs[/green]")
    
    if once:
        check_textract_jobs()
    else:
        console.print(f"[bold]Monitoring Textract jobs every {check_interval} seconds[/bold]")
        console.print("Press Ctrl+C to stop\n")
        
        try:
            while True:
                check_textract_jobs()
                time.sleep(check_interval)
        except KeyboardInterrupt:
            console.print("\n[yellow]Monitoring stopped[/yellow]")

@cli.command()
@click.option('--document-id', required=True, help='Document ID or UUID to diagnose')
def diagnose_chunking(document_id):
    """Diagnose chunking issues for a specific document."""
    console.print("[yellow]This command is temporarily disabled during migration from Supabase to RDS.[/yellow]")
    console.print("Use the 'live' command for real-time monitoring instead.")
    return
    
    monitor = UnifiedMonitor()
    
    try:
        # Try to find document by UUID first, then by ID
        response = monitor.supabase.table('source_documents').select(
            'id', 'document_uuid', 'original_file_name', 'detected_file_type',
            'celery_status', 'error_message', 'ocr_metadata_json'
        ).eq('document_uuid', document_id).execute()
        
        if not response.data and document_id.isdigit():
            # Try by ID
            response = monitor.supabase.table('source_documents').select(
                'id', 'document_uuid', 'original_file_name', 'detected_file_type',
                'celery_status', 'error_message', 'ocr_metadata_json'
            ).eq('id', int(document_id)).execute()
        
        if not response.data:
            console.print(f"[red]Document {document_id} not found.[/red]")
            return
        
        doc = response.data[0]
        console.print(f"\n[bold cyan]📄 Document Chunking Diagnosis[/bold cyan]")
        console.print(f"[dim]File: {doc['original_file_name']}[/dim]")
        console.print(f"[dim]UUID: {doc['document_uuid']}[/dim]")
        console.print(f"[dim]Type: {doc['detected_file_type']}[/dim]")
        console.print(f"[dim]Status: {doc['celery_status']}[/dim]\n")
        
        # Get chunks
        chunks_response = monitor.supabase.table('chunks').select(
            'id', 'chunk_index', 'text', 'cleaned_text',
            'char_start_index', 'char_end_index', 'metadata_json'
        ).eq('document_uuid', doc['document_uuid']).order('chunk_index').execute()
        
        if not chunks_response.data:
            console.print("[red]❌ No chunks found for this document![/red]")
            if doc['celery_status'] == 'failed':
                console.print(f"\n[yellow]Document failed with error:[/yellow]")
                console.print(f"[red]{doc.get('error_message', 'Unknown error')}[/red]")
            return
        
        chunks = chunks_response.data
        console.print(f"[green]✅ Found {len(chunks)} chunks[/green]\n")
        
        # Import validation function
        from scripts.chunking_utils import validate_chunks
        
        # Get OCR text if available
        ocr_text = ""
        if doc.get('ocr_metadata_json'):
            for entry in doc['ocr_metadata_json']:
                if isinstance(entry, dict) and entry.get('ocr_output_type') == 'text' and entry.get('ocr_output'):
                    ocr_text = entry['ocr_output']
                    break
        
        if not ocr_text:
            # Try to get from textract_jobs table
            textract_response = monitor.supabase.table('textract_jobs').select(
                'result_text'
            ).eq('document_uuid', doc['document_uuid']).execute()
            
            if textract_response.data and textract_response.data[0].get('result_text'):
                ocr_text = textract_response.data[0]['result_text']
        
        # Validate chunks
        if ocr_text:
            validation_result = validate_chunks(chunks, ocr_text)
            
            # Display validation results
            validation_table = Table(title="Chunk Validation Results", box=box.ROUNDED)
            validation_table.add_column("Metric", style="cyan")
            validation_table.add_column("Value", style="white")
            validation_table.add_column("Status", style="green")
            
            # Basic metrics
            validation_table.add_row("Total Chunks", str(validation_result['total_chunks']), "ℹ️")
            validation_table.add_row("Average Size", f"{validation_result['avg_chunk_size']:.0f} chars", "ℹ️")
            validation_table.add_row("Min Size", f"{validation_result['min_chunk_size']} chars", "ℹ️")
            validation_table.add_row("Max Size", f"{validation_result['max_chunk_size']} chars", "ℹ️")
            
            # Coverage
            coverage = validation_result['coverage']
            coverage_status = "✅" if 0.95 <= coverage <= 1.05 else "⚠️"
            validation_table.add_row("Coverage", f"{coverage:.1%}", coverage_status)
            
            # Quality issues
            if validation_result['empty_chunks'] > 0:
                validation_table.add_row("Empty Chunks", str(validation_result['empty_chunks']), "❌")
            if validation_result['very_short_chunks'] > 0:
                validation_table.add_row("Very Short Chunks", str(validation_result['very_short_chunks']), "⚠️")
            if validation_result['incomplete_chunks'] > 0:
                validation_table.add_row("Incomplete Chunks", str(validation_result['incomplete_chunks']), "⚠️")
            if validation_result['overlapping_chunks'] > 0:
                validation_table.add_row("Overlapping Chunks", str(validation_result['overlapping_chunks']), "❌")
            
            # Quality score
            score = validation_result['quality_score']
            score_status = "✅" if score >= 0.8 else "⚠️" if score >= 0.6 else "❌"
            validation_table.add_row("Quality Score", f"{score:.2f}", score_status)
            
            console.print(validation_table)
            
            # Show quality issues if any
            if validation_result['quality_issues']:
                console.print("\n[yellow]⚠️  Quality Issues:[/yellow]")
                for issue in validation_result['quality_issues']:
                    console.print(f"  • {issue}")
            
            # Show validation errors if any
            if validation_result['validation_errors']:
                console.print("\n[red]❌ Validation Errors:[/red]")
                for error in validation_result['validation_errors']:
                    console.print(f"  • {error}")
            
            # Chunk types breakdown
            if validation_result['chunk_types']:
                console.print("\n[bold]Chunk Types:[/bold]")
                for chunk_type, count in validation_result['chunk_types'].items():
                    console.print(f"  • {chunk_type}: {count}")
        else:
            console.print("[yellow]⚠️  No OCR text found - cannot validate coverage[/yellow]")
        
        # Display sample chunks
        console.print("\n[bold]Sample Chunks:[/bold]")
        samples_table = Table(box=box.SIMPLE)
        samples_table.add_column("#", style="dim", width=3)
        samples_table.add_column("Size", style="cyan", width=8)
        samples_table.add_column("Type", style="yellow", width=12)
        samples_table.add_column("Density", style="magenta", width=8)
        samples_table.add_column("Text Preview", style="white", width=60)
        
        # Show first 3 and last 2 chunks
        sample_indices = list(range(min(3, len(chunks)))) + list(range(max(3, len(chunks)-2), len(chunks)))
        sample_indices = sorted(set(sample_indices))
        
        for idx in sample_indices:
            chunk = chunks[idx]
            text_preview = chunk['text'][:60].replace('\n', ' ')
            if len(chunk['text']) > 60:
                text_preview += "..."
            
            chunk_type = 'unknown'
            density_score = None
            if chunk.get('metadata_json'):
                try:
                    import json
                    metadata = json.loads(chunk['metadata_json']) if isinstance(chunk['metadata_json'], str) else chunk['metadata_json']
                    chunk_type = metadata.get('chunk_type', metadata.get('type', 'unknown'))
                    # Check for enhanced metadata
                    if metadata.get('enhanced'):
                        density_score = metadata.get('density_score')
                except:
                    pass
            
            density_str = f"{density_score:.2f}" if density_score is not None else "-"
            
            samples_table.add_row(
                str(chunk['chunk_index']),
                f"{len(chunk['text'])}",
                chunk_type,
                density_str,
                text_preview
            )
            
            if idx == 2 and len(chunks) > 5:
                samples_table.add_row("...", "...", "...", "...", "...")
        
        console.print(samples_table)
        
        # Check for common issues
        console.print("\n[bold]Common Issues Check:[/bold]")
        
        # Check for markdown artifacts
        markdown_count = sum(1 for c in chunks if '##' in c['text'] or '###' in c['text'])
        if markdown_count > 0:
            console.print(f"  ⚠️  {markdown_count} chunks contain markdown formatting")
        
        # Check for page break handling
        page_break_count = sum(1 for c in chunks if '<END_OF_PAGE>' in c['text'])
        if page_break_count > 0:
            console.print(f"  ℹ️  {page_break_count} chunks contain page breaks")
        
        # Check chunk distribution
        if chunks:
            chunk_sizes = [len(c['text']) for c in chunks]
            avg_size = sum(chunk_sizes) / len(chunk_sizes)
            if any(size > avg_size * 2 for size in chunk_sizes):
                console.print("  ⚠️  Some chunks are significantly larger than average")
            if any(size < avg_size * 0.2 for size in chunk_sizes):
                console.print("  ⚠️  Some chunks are significantly smaller than average")
        
        # Check if enhanced metadata is present
        enhanced_chunks = 0
        total_citations = 0
        total_dates = 0
        total_amounts = 0
        
        for chunk in chunks[:10]:  # Check first 10 chunks
            if chunk.get('metadata_json'):
                try:
                    import json
                    metadata = json.loads(chunk['metadata_json']) if isinstance(chunk['metadata_json'], str) else chunk['metadata_json']
                    if metadata.get('enhanced'):
                        enhanced_chunks += 1
                        legal_elements = metadata.get('legal_elements', {})
                        total_citations += len(legal_elements.get('citations', []))
                        total_dates += len(legal_elements.get('dates', []))
                        total_amounts += len(legal_elements.get('monetary_amounts', []))
                except:
                    pass
        
        if enhanced_chunks > 0:
            console.print("\n[bold]Enhanced Metadata:[/bold]")
            console.print(f"  ✅ {enhanced_chunks} chunks have enhanced metadata")
            console.print(f"  📚 {total_citations} legal citations detected")
            console.print(f"  📅 {total_dates} dates detected")
            console.print(f"  💰 {total_amounts} monetary amounts detected")
        
        # Success message
        if validation_result and validation_result['quality_score'] >= 0.8:
            console.print("\n[green]✅ Chunking appears to be working correctly![/green]")
        else:
            console.print("\n[yellow]⚠️  Chunking may have issues - review the validation results above[/yellow]")
            
    except Exception as e:
        console.print(f"[red]Error diagnosing chunking: {e}[/red]")
        import traceback
        traceback.print_exc()

@cli.command()
@click.argument('document_uuids', nargs=-1, required=True)
@click.option('--refresh', '-r', default=5, help='Refresh interval in seconds')
@click.option('--once', is_flag=True, help='Run once and exit')
def documents(document_uuids, refresh, once):
    """Monitor multiple documents by UUID."""
    console.print("[yellow]This command is temporarily disabled during migration from Supabase to RDS.[/yellow]")
    console.print("Use the 'live' command for real-time monitoring instead.")
    return
    
    monitor = UnifiedMonitor()
    
    def show_documents_status():
        """Display status for multiple documents."""
        console.clear()
        console.print('[bold cyan]📊 Multi-Document Pipeline Monitor[/bold cyan]')
        console.print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        console.print(f'Monitoring {len(document_uuids)} documents\n')
        
        # Get document status from database
        from scripts.db import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            # Get document status
            uuid_list = "','".join(document_uuids)
            query = f"""
                SELECT 
                    document_uuid,
                    file_name,
                    status,
                    celery_task_id,
                    textract_job_id,
                    textract_job_status,
                    ocr_completed_at,
                    raw_extracted_text IS NOT NULL as has_text,
                    error_message
                FROM source_documents
                WHERE document_uuid IN ('{uuid_list}')
                ORDER BY file_name
            """
            
            result = conn.execute(text(query))
            documents = result.fetchall()
            
            if not documents:
                console.print("[red]No documents found with the provided UUIDs[/red]")
                return
            
            # Status counts
            status_counts = {'pending': 0, 'processing': 0, 'ocr_in_progress': 0, 
                            'ocr_complete': 0, 'completed': 0, 'failed': 0}
            
            # Document status table
            doc_table = Table(title="Document Status", box=box.ROUNDED)
            doc_table.add_column("File", style="cyan", width=40)
            doc_table.add_column("Status", style="yellow", width=15)
            doc_table.add_column("OCR", style="green", width=12)
            doc_table.add_column("Textract Job", style="blue", width=15)
            doc_table.add_column("Error", style="red", width=30)
            
            for row in documents:
                doc_uuid = row[0]
                file_name = row[1][:37] + '...' if len(row[1]) > 37 else row[1]
                status = row[2]
                has_textract = bool(row[4])
                has_text = row[7]
                error_msg = row[8][:27] + '...' if row[8] and len(row[8]) > 27 else row[8]
                
                status_counts[status] = status_counts.get(status, 0) + 1
                
                # Status icon
                if status == 'completed':
                    status_icon = '✓ ' + status
                elif status in ['processing', 'ocr_in_progress']:
                    status_icon = '⏳ ' + status
                elif status == 'failed':
                    status_icon = '✗ ' + status
                else:
                    status_icon = '· ' + status
                
                # OCR status
                ocr_status = '✓ Complete' if row[6] else '⏳ Processing' if has_textract else '· Pending'
                
                # Textract status
                textract_status = row[5] if has_textract else '-'
                
                doc_table.add_row(file_name, status_icon, ocr_status, textract_status, error_msg or '')
            
            console.print(doc_table)
            
            # Summary
            console.print(f"\n[bold]Summary:[/bold]")
            console.print(f"  Pending: {status_counts.get('pending', 0)}")
            console.print(f"  Processing/OCR: {status_counts.get('processing', 0) + status_counts.get('ocr_in_progress', 0)}")
            console.print(f"  Completed: {status_counts.get('completed', 0)}")
            console.print(f"  Failed: {status_counts.get('failed', 0)}")
            
            # Processing stages
            console.print("\n[bold]Processing Stages:[/bold]")
            
            query = f"""
                SELECT 
                    sd.document_uuid,
                    sd.file_name,
                    pt.task_type,
                    pt.status,
                    pt.created_at,
                    pt.completed_at
                FROM processing_tasks pt
                JOIN source_documents sd ON pt.document_id = sd.document_uuid
                WHERE sd.document_uuid IN ('{uuid_list}')
                ORDER BY sd.file_name, pt.created_at
            """
            
            result = conn.execute(text(query))
            tasks = result.fetchall()
            
            # Group by document
            doc_tasks = {}
            for task in tasks:
                doc_uuid = task[0]
                if doc_uuid not in doc_tasks:
                    doc_tasks[doc_uuid] = []
                doc_tasks[doc_uuid].append(task)
            
            # Show pipeline stages for each document
            stages = ['ocr', 'chunking', 'entity_extraction', 'entity_resolution', 
                     'relationship_extraction', 'finalization']
            
            stage_table = Table(box=box.SIMPLE)
            stage_table.add_column("Document", style="cyan", width=35)
            for stage in stages:
                stage_table.add_column(stage.replace('_', ' ').title()[:10], style="yellow", width=10)
            
            for doc in documents[:10]:  # Limit to 10 docs for display
                doc_uuid = doc[0]
                file_name = doc[1][:32] + '...' if len(doc[1]) > 32 else doc[1]
                
                row_data = [file_name]
                doc_task_list = doc_tasks.get(doc_uuid, [])
                
                for stage in stages:
                    stage_task = next((t for t in doc_task_list if t[2] == stage), None)
                    if stage_task:
                        if stage_task[3] == 'completed':
                            row_data.append('✓')
                        elif stage_task[3] == 'processing':
                            row_data.append('⏳')
                        elif stage_task[3] == 'failed':
                            row_data.append('✗')
                        else:
                            row_data.append('·')
                    else:
                        row_data.append('-')
                
                stage_table.add_row(*row_data)
            
            console.print(stage_table)
    
    # Run monitoring
    if once:
        show_documents_status()
    else:
        with Live(refresh_per_second=1/refresh) as live:
            while True:
                try:
                    show_documents_status()
                    time.sleep(refresh)
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                    time.sleep(refresh)

@cli.command()
@click.option('--output-format', '-f', type=click.Choice(['json', 'text']), default='text', help='Output format')
def health(output_format):
    """System health check."""
    monitor = UnifiedMonitor()
    
    health_status = {
        'timestamp': datetime.now().isoformat(),
        'components': {}
    }
    
    # Check RDS Database
    try:
        from scripts.rds_utils import execute_query
        execute_query("SELECT 1")
        health_status['components']['database'] = {'status': 'healthy', 'message': 'RDS Connected'}
        database_ok = True
    except Exception as e:
        health_status['components']['database'] = {'status': 'unhealthy', 'message': str(e)}
        database_ok = False
    
    # Check Redis
    if monitor.redis_available:
        health_status['components']['redis'] = {'status': 'healthy', 'message': 'Connected'}
        redis_ok = True
    else:
        health_status['components']['redis'] = {'status': 'unhealthy', 'message': 'Not available'}
        redis_ok = False
    
    # Check Celery
    try:
        celery_stats = monitor.get_celery_stats()
        worker_count = celery_stats.get('worker_count', 0)
        if worker_count > 0:
            health_status['components']['celery'] = {
                'status': 'healthy',
                'message': f'{worker_count} workers active'
            }
            celery_ok = True
        else:
            health_status['components']['celery'] = {
                'status': 'unhealthy',
                'message': 'No workers detected'
            }
            celery_ok = False
    except Exception as e:
        health_status['components']['celery'] = {'status': 'unhealthy', 'message': str(e)}
        celery_ok = False
    
    # Overall status
    all_healthy = database_ok and redis_ok and celery_ok
    health_status['overall'] = 'healthy' if all_healthy else 'unhealthy'
    
    if output_format == 'json':
        console.print_json(data=health_status)
    else:
        # Text output
        console.print("[bold]System Health Check[/bold]\n")
        
        for component, status in health_status['components'].items():
            if status['status'] == 'healthy':
                console.print(f"✅ {component.title()}: {status['message']}")
            else:
                console.print(f"❌ {component.title()}: [red]{status['message']}[/red]")
        
        console.print(f"\n[bold]Overall Status:[/bold] ", end="")
        if all_healthy:
            console.print("[green]All systems operational[/green]")
        else:
            console.print("[red]System degraded[/red]")

if __name__ == '__main__':
    cli()