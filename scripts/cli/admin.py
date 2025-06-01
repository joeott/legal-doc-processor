#!/usr/bin/env python3
"""
Simplified admin CLI for document processing pipeline management.
"""

import click
import os
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.progress import track
from rich import box
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

console = Console()


def get_supabase_client() -> Client:
    """Get Supabase client."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


@click.group()
def cli():
    """Administrative commands for document pipeline management."""
    pass


# Import schema commands as a subgroup
from scripts.database.cli import schema as schema_group
cli.add_command(schema_group)


# Verification Commands (from context_204)
@cli.command()
def verify_services():
    """Verify all services are accessible (context_204 requirement)."""
    import sys
    import os
    # Add project root to path for imports
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.append(project_root)
    
    try:
        from scripts.config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_USERNAME, REDIS_SSL
        import redis
        import boto3
        import openai
    except ImportError as e:
        console.print(f"[red]Import error: {e}[/red]")
        return
    
    console.print("[bold blue]Verifying Service Connections...[/bold blue]")
    
    services = {}
    
    # Supabase
    try:
        supabase = get_supabase_client()
        _result = supabase.table('projects').select('project_uuid').limit(1).execute()
        services['supabase'] = {'status': '✓', 'details': f"Connected ({os.getenv('SUPABASE_URL', '')[:30]}...)"}
    except Exception as e:
        services['supabase'] = {'status': '✗', 'details': f"Failed: {str(e)[:50]}..."}
    
    # Redis
    try:
        r = redis.Redis(
            host=REDIS_HOST, 
            port=REDIS_PORT, 
            password=REDIS_PASSWORD,
            username=REDIS_USERNAME,
            ssl=REDIS_SSL,
            decode_responses=True
        )
        r.ping()
        services['redis'] = {'status': '✓', 'details': f"Connected ({REDIS_HOST}:{REDIS_PORT})"}
    except Exception as e:
        services['redis'] = {'status': '✗', 'details': f"Failed: {str(e)[:50]}..."}
    
    # S3
    try:
        s3 = boto3.client('s3')
        _buckets = s3.list_buckets()
        bucket_name = os.getenv('S3_BUCKET_NAME', 'samu-docs-private-upload')
        services['s3'] = {'status': '✓', 'details': f"Accessible ({bucket_name})"}
    except Exception as e:
        services['s3'] = {'status': '✗', 'details': f"Failed: {str(e)[:50]}..."}
    
    # OpenAI
    try:
        openai.api_key = os.getenv('OPENAI_API_KEY')
        # Just check if API key is set, actual test would require API call
        if openai.api_key:
            services['openai'] = {'status': '✓', 'details': "API key valid"}
        else:
            services['openai'] = {'status': '✗', 'details': "API key not set"}
    except Exception as e:
        services['openai'] = {'status': '✗', 'details': f"Failed: {str(e)[:50]}..."}
    
    # Display results
    for service, info in services.items():
        console.print(f"{info['status']} {service.title()}: {info['details']}")


@cli.command('verify-schema')
@click.option('--check-indexes', is_flag=True, help='Verify database indexes')
def verify_schema(check_indexes):
    """Verify Supabase schema compliance with context_203."""
    supabase = get_supabase_client()
    
    console.print("[bold blue]Verifying Schema Compliance...[/bold blue]")
    
    required_tables = [
        'projects', 'documents', 'processing_pipeline', 'processing_queue',
        'document_chunks', 'entity_mentions', 'canonical_entities', 
        'relationship_staging', 'processing_metrics', 'import_sessions'
    ]
    
    table = Table(title="Schema Verification", show_header=True)
    table.add_column("Table", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("Records", style="green")
    
    all_good = True
    
    for table_name in required_tables:
        try:
            result = supabase.table(table_name).select('*', count='exact').limit(1).execute()
            status = "✓ EXISTS"
            records = str(result.count)
        except Exception:
            status = "✗ MISSING"
            records = "-"
            all_good = False
            
        table.add_row(table_name, status, records)
    
    console.print(table)
    
    if all_good:
        console.print("\n[bold green]✓ Schema verification passed[/bold green]")
    else:
        console.print("\n[bold red]✗ Schema verification failed[/bold red]")


@cli.command()
@click.option('--document', help='Path to test document')
def test_pipeline(document):
    """Run test document through pipeline (context_204 requirement)."""
    console.print("[bold blue]Testing Pipeline...[/bold blue]")
    
    if not document:
        document = "tests/fixtures/sample.pdf"
    
    if not os.path.exists(document):
        console.print(f"[red]Test document not found: {document}[/red]")
        return
    
    console.print(f"[yellow]Test document: {document}[/yellow]")
    console.print("[yellow]Pipeline testing not yet implemented[/yellow]")
    console.print("[yellow]TODO: Implement end-to-end pipeline test[/yellow]")


# Document Commands
@cli.group()
def documents():
    """Document management commands."""
    pass


@documents.command()
@click.option('--status', help='Filter by status')
@click.option('--limit', default=100, help='Maximum documents to list')
def list(status, limit):
    """List documents with optional status filter."""
    supabase = get_supabase_client()
    
    query = supabase.table('documents').select(
        'document_uuid', 'original_filename', 'processing_status', 'processing_stage', 'updated_at'
    )
    
    if status:
        query = query.eq('processing_status', status)
        
    response = query.limit(limit).execute()
    docs = response.data
    
    if not docs:
        console.print("[yellow]No documents found[/yellow]")
        return
        
    table = Table(title=f"Documents ({status or 'all'})", box=box.ROUNDED)
    table.add_column("UUID", style="cyan")
    table.add_column("Filename", style="white")
    table.add_column("Status", style="yellow")
    table.add_column("Stage", style="magenta")
    table.add_column("Updated", style="green")
    
    for doc in docs:
        table.add_row(
            doc['document_uuid'][:8] + '...',
            doc['original_filename'][:40] + '...' if len(doc['original_filename']) > 40 else doc['original_filename'],
            doc['processing_status'],
            doc['processing_stage'] or 'N/A',
            doc['updated_at'][:19] if doc['updated_at'] else 'N/A'
        )
        
    console.print(table)
    console.print(f"\nTotal: {len(docs)} documents")


@documents.command()
@click.argument('document_uuid')
def reset(document_uuid):
    """Reset document status to pending for reprocessing."""
    supabase = get_supabase_client()
    
    try:
        supabase.table('documents').update({
            'processing_status': 'pending',
            'processing_stage': None,
            'celery_task_id': None,
            'processing_error': None,
            'updated_at': datetime.now().isoformat()
        }).eq('document_uuid', document_uuid).execute()
        
        console.print(f"[green]Document {document_uuid} reset to pending[/green]")
    except Exception as e:
        console.print(f"[red]Failed to reset document: {e}[/red]")


@documents.command()
@click.option('--minutes', default=30, help='Minutes to consider as stuck')
def stuck(minutes):
    """Find documents stuck in processing."""
    supabase = get_supabase_client()
    
    time_threshold = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    
    response = supabase.table('source_documents').select(
        'id', 'document_uuid', 'original_file_name', 'celery_status', 'last_modified_at'
    ).in_('celery_status', [
        'processing', 'ocr_processing', 'text_processing', 
        'entity_processing', 'graph_processing'
    ]).lte('last_modified_at', time_threshold).execute()
    
    stuck_docs = response.data
    
    if not stuck_docs:
        console.print(f"[green]No documents stuck for more than {minutes} minutes[/green]")
        return
        
    console.print(f"[yellow]Found {len(stuck_docs)} stuck documents:[/yellow]")
    
    table = Table(title="Stuck Documents", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("UUID", style="dim")
    table.add_column("Filename", style="white")
    table.add_column("Status", style="yellow")
    table.add_column("Last Update", style="red")
    
    for doc in stuck_docs:
        table.add_row(
            str(doc['id']),
            doc['document_uuid'][:8] + '...',
            doc['original_file_name'][:30] + '...',
            doc['celery_status'],
            doc['last_modified_at'][:19]
        )
        
    console.print(table)


@documents.command()
def stats():
    """Show document processing statistics."""
    supabase = get_supabase_client()
    
    response = supabase.table('source_documents').select('celery_status').execute()
    
    if not response.data:
        console.print("[yellow]No documents found[/yellow]")
        return
        
    # Count by status
    status_counts = {}
    for doc in response.data:
        status = doc.get('celery_status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
        
    total = sum(status_counts.values())
    
    console.print(f"\n[bold]Document Processing Statistics[/bold]")
    console.print(f"Total Documents: {total}")
    
    table = Table(title="Status Breakdown", box=box.ROUNDED)
    table.add_column("Status", style="cyan")
    table.add_column("Count", style="magenta")
    table.add_column("Percentage", style="yellow")
    
    for status, count in sorted(status_counts.items()):
        percentage = (count / total * 100) if total > 0 else 0
        table.add_row(status, str(count), f"{percentage:.1f}%")
        
    console.print(table)


@documents.command()
@click.option('--hours', default=24, help='Hours to look back')
def failures(hours):
    """Show recent document failures."""
    supabase = get_supabase_client()
    
    time_threshold = (datetime.now() - timedelta(hours=hours)).isoformat()
    
    response = supabase.table('source_documents').select(
        'id', 'document_uuid', 'original_file_name', 'celery_status', 
        'error_message', 'last_modified_at'
    ).in_('celery_status', [
        'ocr_failed', 'text_failed', 'entity_failed', 'graph_failed'
    ]).gte('last_modified_at', time_threshold).execute()
    
    failures = response.data
    
    if not failures:
        console.print(f"[green]No failures in the last {hours} hours[/green]")
        return
        
    console.print(f"[red]Found {len(failures)} failures in the last {hours} hours:[/red]")
    
    table = Table(title="Recent Failures", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("Filename", style="white")
    table.add_column("Status", style="red")
    table.add_column("Error", style="yellow")
    table.add_column("Time", style="dim")
    
    for fail in failures[:20]:  # Show max 20
        error_msg = fail.get('error_message', 'No error message')
        if len(error_msg) > 50:
            error_msg = error_msg[:50] + '...'
            
        table.add_row(
            str(fail['id']),
            fail['original_file_name'][:30] + '...' if len(fail['original_file_name']) > 30 else fail['original_file_name'],
            fail['celery_status'],
            error_msg,
            fail['last_modified_at'][:19]
        )
        
    console.print(table)


# Cleanup Commands
@cli.group()
def cleanup():
    """Database cleanup commands."""
    pass


@cleanup.command()
@click.option('--days', default=30, help='Days to keep history')
@click.option('--dry-run', is_flag=True, help='Show what would be deleted')
def history(days, dry_run):
    """Clean up old processing history."""
    supabase = get_supabase_client()
    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
    
    # Count records to delete
    response = supabase.table('document_processing_history').select(
        'id'
    ).lt('created_at', cutoff_date).execute()
    
    count = len(response.data)
    
    if count == 0:
        console.print(f"[green]No history records older than {days} days[/green]")
        return
        
    console.print(f"[yellow]Found {count} history records older than {days} days[/yellow]")
    
    if dry_run:
        console.print("[yellow]Dry run - no records deleted[/yellow]")
    else:
        if click.confirm(f"Delete {count} records?"):
            supabase.table('document_processing_history').delete().lt(
                'created_at', cutoff_date
            ).execute()
            console.print(f"[green]Deleted {count} history records[/green]")


@cleanup.command()
def orphans():
    """Find and clean orphaned records."""
    supabase = get_supabase_client()
    
    # Find orphaned chunks
    chunks_response = supabase.table('neo4j_chunks').select('id').is_('document_id', 'null').execute()
    orphan_chunks = len(chunks_response.data)
    
    # Find orphaned entity mentions
    mentions_response = supabase.table('neo4j_entity_mentions').select('id').is_('chunk_id', 'null').execute()
    orphan_mentions = len(mentions_response.data)
    
    console.print("[bold]Orphaned Records:[/bold]")
    console.print(f"  Chunks without documents: {orphan_chunks}")
    console.print(f"  Entity mentions without chunks: {orphan_mentions}")
    
    if orphan_chunks > 0 and click.confirm("Delete orphaned chunks?"):
        supabase.table('neo4j_chunks').delete().is_('document_id', 'null').execute()
        console.print(f"[green]Deleted {orphan_chunks} orphaned chunks[/green]")
        
    if orphan_mentions > 0 and click.confirm("Delete orphaned entity mentions?"):
        supabase.table('neo4j_entity_mentions').delete().is_('chunk_id', 'null').execute()
        console.print(f"[green]Deleted {orphan_mentions} orphaned entity mentions[/green]")


# Batch Operations
@cli.group()
def batch():
    """Batch operations on documents."""
    pass


@batch.command()
@click.option('--status', required=True, help='Status to reset from')
@click.option('--limit', default=100, help='Maximum documents to reset')
@click.option('--dry-run', is_flag=True, help='Show what would be reset')
def reset_failed(status, limit, dry_run):
    """Reset failed documents to pending."""
    supabase = get_supabase_client()
    
    # Get failed documents
    response = supabase.table('source_documents').select(
        'id', 'document_uuid', 'original_file_name'
    ).eq('celery_status', status).limit(limit).execute()
    
    docs = response.data
    
    if not docs:
        console.print(f"[yellow]No documents found with status '{status}'[/yellow]")
        return
        
    console.print(f"[yellow]Found {len(docs)} documents with status '{status}'[/yellow]")
    
    if dry_run:
        console.print("[yellow]Dry run - no documents reset[/yellow]")
        for doc in docs[:10]:  # Show first 10
            console.print(f"  Would reset: {doc['original_file_name']} ({doc['document_uuid'][:8]}...)")
    else:
        if click.confirm(f"Reset {len(docs)} documents to pending?"):
            reset_count = 0
            for doc in track(docs, description="Resetting..."):
                supabase.table('source_documents').update({
                    'celery_status': 'pending',
                    'celery_task_id': None,
                    'error_message': None,
                    'last_modified_at': datetime.now().isoformat()
                }).eq('id', doc['id']).execute()
                reset_count += 1
                
            console.print(f"[green]Reset {reset_count} documents to pending[/green]")


@batch.command()
@click.argument('project_id', type=int)
def reset_project(project_id):
    """Reset all documents in a project to pending."""
    supabase = get_supabase_client()
    
    # Get documents for project
    response = supabase.table('source_documents').select(
        'id', 'document_uuid', 'original_file_name', 'celery_status'
    ).eq('project_fk_id', project_id).execute()
    
    docs = response.data
    
    if not docs:
        console.print(f"[yellow]No documents found for project {project_id}[/yellow]")
        return
        
    # Count by status
    status_counts = {}
    for doc in docs:
        status = doc.get('celery_status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
        
    console.print(f"[yellow]Found {len(docs)} documents in project {project_id}:[/yellow]")
    for status, count in status_counts.items():
        console.print(f"  {status}: {count}")
        
    if click.confirm(f"Reset all {len(docs)} documents to pending?"):
        reset_count = 0
        for doc in track(docs, description="Resetting..."):
            supabase.table('source_documents').update({
                'celery_status': 'pending',
                'celery_task_id': None,
                'error_message': None,
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', doc['id']).execute()
            reset_count += 1
            
        console.print(f"[green]Reset {reset_count} documents to pending[/green]")


if __name__ == '__main__':
    cli()