#!/usr/bin/env python3
"""
Deploy RDS Schema CLI Command
Deploys the production schema to AWS RDS PostgreSQL instance
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple
import click
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax

console = Console()


class RDSSchemaDeployer:
    """Handles schema deployment to RDS instance."""
    
    def __init__(self, connection_string: str, via_bastion: bool = False):
        self.connection_string = connection_string
        self.via_bastion = via_bastion
        self.script_path = Path(__file__).parent.parent / "create_rds_schema.sql"
        
    def test_connection(self) -> Tuple[bool, str]:
        """Test database connection."""
        try:
            conn = psycopg2.connect(self.connection_string)
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version = cur.fetchone()[0]
            conn.close()
            return True, version
        except Exception as e:
            return False, str(e)
    
    def check_existing_schema(self) -> dict:
        """Check for existing tables in the database."""
        try:
            conn = psycopg2.connect(self.connection_string)
            with conn.cursor() as cur:
                # Check for existing tables
                cur.execute("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_type = 'BASE TABLE';
                """)
                table_count = cur.fetchone()[0]
                
                # Check for our schema version table
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_name = 'schema_version'
                    );
                """)
                has_schema_version = cur.fetchone()[0]
                
                # Get current version if exists
                current_version = None
                if has_schema_version:
                    cur.execute("SELECT MAX(version) FROM schema_version;")
                    result = cur.fetchone()
                    if result:
                        current_version = result[0]
                
            conn.close()
            
            return {
                "table_count": table_count,
                "has_schema_version": has_schema_version,
                "current_version": current_version
            }
        except Exception as e:
            return {"error": str(e)}
    
    def deploy_schema(self, force: bool = False) -> Tuple[bool, str]:
        """Deploy the schema to RDS."""
        try:
            # Read the SQL script
            if not self.script_path.exists():
                return False, f"Schema script not found: {self.script_path}"
            
            with open(self.script_path, 'r') as f:
                sql_script = f.read()
            
            # Connect and execute
            conn = psycopg2.connect(self.connection_string)
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            
            with conn.cursor() as cur:
                # Split by major sections to show progress
                sections = self._split_sql_sections(sql_script)
                
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("Deploying schema...", total=len(sections))
                    
                    for section_name, section_sql in sections:
                        progress.update(task, description=f"Creating {section_name}...")
                        try:
                            cur.execute(section_sql)
                        except psycopg2.Error as e:
                            if not force:
                                raise e
                            else:
                                console.print(f"[yellow]Warning in {section_name}: {str(e)}[/yellow]")
                        progress.update(task, advance=1)
            
            conn.close()
            return True, "Schema deployed successfully"
            
        except Exception as e:
            return False, f"Deployment failed: {str(e)}"
    
    def _split_sql_sections(self, sql_script: str) -> list:
        """Split SQL script into logical sections for progress tracking."""
        sections = []
        current_section = []
        current_name = "Initialization"
        
        for line in sql_script.split('\n'):
            if line.strip().startswith('--') and any(
                keyword in line for keyword in ['CORE TABLES', 'PROCESSING', 'CONTENT', 
                'ENTITY', 'RELATIONSHIP', 'MONITORING', 'AUDIT', 'VIEWS', 
                'FUNCTIONS', 'PERMISSIONS', 'INITIAL DATA']
            ):
                if current_section:
                    sections.append((current_name, '\n'.join(current_section)))
                current_section = [line]
                current_name = line.strip('- ').strip()
            else:
                current_section.append(line)
        
        if current_section:
            sections.append((current_name, '\n'.join(current_section)))
        
        return sections
    
    def verify_deployment(self) -> dict:
        """Verify the deployment was successful."""
        # Import and use the verification script
        sys.path.append(str(Path(__file__).parent.parent))
        from verify_rds_schema_conformance import SchemaVerifier
        
        verifier = SchemaVerifier(self.connection_string)
        return verifier.verify_all()


@click.group()
def deploy():
    """RDS schema deployment commands."""
    pass


@deploy.command()
@click.option('--connection-string', '-c', envvar='RDS_CONNECTION_STRING',
              help='PostgreSQL connection string for RDS')
@click.option('--host', '-h', help='RDS endpoint hostname')
@click.option('--port', '-p', default=5432, help='RDS port')
@click.option('--database', '-d', default='postgres', help='Database name')
@click.option('--username', '-u', default='postgres', help='Database username')
@click.option('--password', '-w', help='Database password (prompt if not provided)')
@click.option('--via-bastion', is_flag=True, help='Connect via bastion host')
@click.option('--force', '-f', is_flag=True, help='Force deployment even if schema exists')
@click.option('--verify', '-v', is_flag=True, help='Run verification after deployment')
def schema(connection_string, host, port, database, username, password, via_bastion, force, verify):
    """Deploy the production schema to RDS PostgreSQL."""
    
    console.print("[bold blue]RDS Schema Deployment[/bold blue]")
    
    # Build connection string if not provided
    if not connection_string:
        if not host:
            console.print("[red]Error: Either --connection-string or --host must be provided[/red]")
            sys.exit(1)
        
        if not password:
            password = click.prompt("Database password", hide_input=True)
        
        connection_string = f"postgresql://{username}:{password}@{host}:{port}/{database}"
    
    deployer = RDSSchemaDeployer(connection_string, via_bastion)
    
    # Test connection
    console.print("\n[yellow]Testing connection...[/yellow]")
    success, result = deployer.test_connection()
    
    if not success:
        console.print(f"[red]Connection failed: {result}[/red]")
        sys.exit(1)
    
    console.print(f"[green]✓ Connected to: {result.split()[0]}[/green]")
    
    # Check existing schema
    console.print("\n[yellow]Checking existing schema...[/yellow]")
    schema_info = deployer.check_existing_schema()
    
    if "error" in schema_info:
        console.print(f"[red]Error checking schema: {schema_info['error']}[/red]")
        sys.exit(1)
    
    if schema_info["table_count"] > 0:
        console.print(f"[yellow]Found {schema_info['table_count']} existing tables[/yellow]")
        if schema_info["current_version"]:
            console.print(f"[yellow]Current schema version: {schema_info['current_version']}[/yellow]")
        
        if not force:
            if not Confirm.ask("[yellow]Schema already exists. Deploy anyway?[/yellow]"):
                console.print("[red]Deployment cancelled[/red]")
                sys.exit(0)
    
    # Show schema preview
    console.print("\n[cyan]Schema to deploy:[/cyan]")
    schema_summary = """
    • Extensions: uuid-ossp, vector, pg_trgm
    • Custom Types: 5 enums (processing_status, entity_type, etc.)
    • Tables: 14 core tables with constraints and indexes
    • Views: 3 regular + 2 materialized views
    • Partitioning: Monthly partitions for processing_pipeline
    • Security: Role-based access control
    • Audit: Comprehensive logging tables
    """
    console.print(Panel(schema_summary, title="Schema Summary", border_style="cyan"))
    
    if not Confirm.ask("\n[bold]Deploy this schema?[/bold]"):
        console.print("[red]Deployment cancelled[/red]")
        sys.exit(0)
    
    # Deploy schema
    console.print("\n[green]Starting deployment...[/green]")
    success, message = deployer.deploy_schema(force)
    
    if not success:
        console.print(f"[red]Deployment failed: {message}[/red]")
        sys.exit(1)
    
    console.print(f"[green]✓ {message}[/green]")
    
    # Run verification if requested
    if verify:
        console.print("\n[yellow]Running schema verification...[/yellow]")
        results = deployer.verify_deployment()
        
        if results["summary"]["status"] == "PASS":
            console.print(Panel(
                f"[bold green]✓ Schema verification PASSED[/bold green]\n"
                f"Errors: {results['summary']['total_errors']}\n"
                f"Warnings: {results['summary']['total_warnings']}",
                title="Verification Complete",
                border_style="green"
            ))
        else:
            console.print(Panel(
                f"[bold red]✗ Schema verification FAILED[/bold red]\n"
                f"Errors: {results['summary']['total_errors']}\n"
                f"Warnings: {results['summary']['total_warnings']}",
                title="Verification Failed",
                border_style="red"
            ))
            
            if results["errors"]:
                console.print("\n[red]Errors:[/red]")
                for error in results["errors"]:
                    console.print(f"  • {error}")
    
    # Next steps
    console.print("\n[bold cyan]Next Steps:[/bold cyan]")
    next_steps = """
    1. Update .env.rds with connection details
    2. Run verification: python scripts/verify_rds_schema_conformance.py
    3. Update application DATABASE_URL
    4. Test application connectivity
    5. Schedule materialized view refreshes
    """
    console.print(Panel(next_steps, border_style="cyan"))


@deploy.command()
@click.option('--connection-string', '-c', envvar='RDS_CONNECTION_STRING', required=True,
              help='PostgreSQL connection string for RDS')
@click.option('--output', '-o', type=click.Path(), help='Output file for report')
@click.option('--format', '-f', type=click.Choice(['json', 'markdown']), default='markdown',
              help='Report format')
def verify(connection_string, output, format):
    """Verify the deployed schema."""
    console.print("[bold blue]Schema Verification[/bold blue]")
    
    sys.path.append(str(Path(__file__).parent.parent))
    from verify_rds_schema_conformance import SchemaVerifier
    
    verifier = SchemaVerifier(connection_string)
    results = verifier.verify_all()
    report = verifier.generate_report(results, format)
    
    if output:
        with open(output, 'w') as f:
            f.write(report)
        console.print(f"[green]Report saved to: {output}[/green]")
    else:
        console.print(report)


@deploy.command()
@click.option('--bastion-host', '-b', required=True, help='Bastion host IP or hostname')
@click.option('--bastion-key', '-k', required=True, type=click.Path(exists=True),
              help='Path to bastion SSH key')
@click.option('--rds-endpoint', '-r', required=True, help='RDS endpoint')
@click.option('--local-port', '-l', default=5433, help='Local port for tunnel')
def tunnel(bastion_host, bastion_key, rds_endpoint, local_port):
    """Create SSH tunnel to RDS via bastion host."""
    console.print(f"[yellow]Creating SSH tunnel to RDS via bastion...[/yellow]")
    
    tunnel_cmd = [
        'ssh', '-i', bastion_key,
        '-L', f'{local_port}:{rds_endpoint}:5432',
        '-N', f'ec2-user@{bastion_host}'
    ]
    
    console.print(f"[cyan]Tunnel command: {' '.join(tunnel_cmd)}[/cyan]")
    console.print(f"\n[green]Tunnel established on localhost:{local_port}[/green]")
    console.print("[yellow]Keep this terminal open. Use localhost:{local_port} to connect.[/yellow]")
    console.print("\n[cyan]Example connection:[/cyan]")
    console.print(f"psql -h localhost -p {local_port} -U postgres -d postgres")
    
    try:
        subprocess.run(tunnel_cmd)
    except KeyboardInterrupt:
        console.print("\n[yellow]Tunnel closed[/yellow]")


if __name__ == "__main__":
    deploy()