#!/usr/bin/env python3
"""
Analyze batch processing status and Redis issues
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import redis
from scripts.db import DatabaseManager
# Get Redis config from environment
REDIS_PUBLIC_ENDPOINT = os.getenv("REDIS_PUBLIC_ENDPOINT", "")
REDIS_PW = os.getenv("REDIS_PW") or os.getenv("REDIS_PASSWORD")
REDIS_USERNAME = os.getenv("REDIS_USERNAME", "default")
from rich.console import Console
from rich.table import Table

console = Console()

def main():
    """Analyze batch processing status."""
    
    # Parse Redis endpoint
    if REDIS_PUBLIC_ENDPOINT and ":" in REDIS_PUBLIC_ENDPOINT:
        host, port_str = REDIS_PUBLIC_ENDPOINT.rsplit(":", 1)
        redis_host = host
        redis_port = int(port_str)
    else:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
    
    console.print(f"[cyan]Connecting to Redis at {redis_host}:{redis_port}[/cyan]")
    
    # Try different Redis authentication methods
    redis_client = None
    auth_methods = [
        {"host": redis_host, "port": redis_port, "password": REDIS_PW, "decode_responses": True},
        {"host": redis_host, "port": redis_port, "username": REDIS_USERNAME, "password": REDIS_PW, "decode_responses": True},
        {"host": redis_host, "port": redis_port, "username": "default", "password": REDIS_PW, "decode_responses": True},
    ]
    
    for i, auth_config in enumerate(auth_methods):
        try:
            test_client = redis.Redis(**auth_config)
            test_client.ping()
            redis_client = test_client
            console.print(f"[green]✓ Redis connected using method {i+1}[/green]")
            break
        except Exception as e:
            console.print(f"[yellow]Method {i+1} failed: {e}[/yellow]")
    
    if not redis_client:
        console.print("[red]✗ Failed to connect to Redis[/red]")
        return
    
    # Check for batch keys
    console.print("\n[bold]Checking Redis batch keys:[/bold]")
    
    batch_patterns = [
        "batch:*",
        "campaign_*",
        "batch:progress:*",
        "batch:documents:*"
    ]
    
    for pattern in batch_patterns:
        console.print(f"\n[cyan]Pattern: {pattern}[/cyan]")
        count = 0
        
        try:
            for key in redis_client.scan_iter(match=pattern, count=100):
                count += 1
                if count <= 5:  # Show first 5 keys
                    key_type = redis_client.type(key)
                    ttl = redis_client.ttl(key)
                    console.print(f"  Key: {key}")
                    console.print(f"    Type: {key_type}, TTL: {ttl}s")
                    
                    if key_type == "string":
                        value = redis_client.get(key)
                        console.print(f"    Value: {value[:100]}..." if value and len(value) > 100 else f"    Value: {value}")
                    elif key_type == "hash":
                        fields = redis_client.hkeys(key)
                        console.print(f"    Fields: {fields[:5]}{'...' if len(fields) > 5 else ''}")
                    elif key_type == "list":
                        length = redis_client.llen(key)
                        console.print(f"    Length: {length}")
                        
            console.print(f"Total keys found: {count}")
        except Exception as e:
            console.print(f"[red]Error scanning pattern {pattern}: {e}[/red]")
    
    # Check database for recent documents
    console.print("\n[bold]Checking database for recent documents:[/bold]")
    
    try:
        from scripts.db import engine
        from sqlalchemy import text
        
        # Get documents from last 24 hours
        with engine.connect() as conn:
            query = text("""
                SELECT 
                    document_uuid,
                    file_name,
                    status,
                    created_at,
                    updated_at,
                    error_message,
                    project_uuid,
                    celery_task_id
                FROM source_documents
                WHERE created_at >= :cutoff_time
                ORDER BY created_at DESC
                LIMIT 20
            """)
            
            cutoff_time = datetime.utcnow() - timedelta(hours=24)
            result = conn.execute(query, {"cutoff_time": cutoff_time})
            documents = result.fetchall()
            
            if documents:
                table = Table(title="Recent Documents (Last 24 Hours)")
                table.add_column("UUID", style="cyan", width=20)
                table.add_column("File", style="white", width=40)
                table.add_column("Status", style="yellow", width=15)
                table.add_column("Created", style="green", width=20)
                
                for doc in documents:
                    uuid_short = str(doc[0])[:8] + "..."
                    filename = doc[1][:37] + "..." if doc[1] and len(doc[1]) > 40 else doc[1]
                    status = doc[2]
                    created = doc[3].strftime("%Y-%m-%d %H:%M:%S") if doc[3] else "N/A"
                    
                    table.add_row(uuid_short, filename, status, created)
                
                console.print(table)
                
                # Count by status
                status_counts = {}
                for doc in documents:
                    status = doc[2]
                    status_counts[status] = status_counts.get(status, 0) + 1
                
                console.print("\n[bold]Status Summary:[/bold]")
                for status, count in sorted(status_counts.items()):
                    console.print(f"  {status}: {count}")
            else:
                console.print("[yellow]No documents found in the last 24 hours[/yellow]")
                
    except Exception as e:
        console.print(f"[red]Database error: {e}[/red]")
        import traceback
        traceback.print_exc()
    
    # Check for the specific campaign
    campaign_id = "campaign_205692f0_20250612_231117"
    console.print(f"\n[bold]Looking for campaign: {campaign_id}[/bold]")
    
    campaign_keys = [
        f"batch:progress:{campaign_id}",
        f"batch:documents:{campaign_id}",
        campaign_id,
        f"campaign:{campaign_id}"
    ]
    
    for key in campaign_keys:
        try:
            if redis_client.exists(key):
                key_type = redis_client.type(key)
                console.print(f"[green]Found key: {key} (type: {key_type})[/green]")
                
                if key_type == "string":
                    value = redis_client.get(key)
                    console.print(f"Value: {value}")
                elif key_type == "hash":
                    data = redis_client.hgetall(key)
                    for field, value in data.items():
                        console.print(f"  {field}: {value}")
            else:
                console.print(f"[dim]Key not found: {key}[/dim]")
        except Exception as e:
            console.print(f"[red]Error checking key {key}: {e}[/red]")

if __name__ == "__main__":
    main()