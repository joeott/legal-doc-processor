# redis_monitor.py
"""Real-time Redis monitoring dashboard for the document processing pipeline."""

import time
import sys
import os
from typing import Dict, List, Optional
from datetime import datetime

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text

from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys

console = Console()


class RedisMonitor:
    """Real-time Redis monitoring dashboard."""
    
    def __init__(self):
        self.console = Console()
        self.redis_mgr = get_redis_manager()
        self.start_time = time.time()
        
    def get_redis_stats(self) -> Dict:
        """Get current Redis statistics."""
        if not self.redis_mgr.is_available():
            return {'error': 'Redis not available'}
            
        try:
            client = self.redis_mgr.get_client()
            info = client.info()
            
            # Get key counts by pattern
            key_counts = {}
            patterns = [
                ('Documents', 'doc:*'),
                ('Jobs', 'job:*'),
                ('Queues', 'queue:*'),
                ('Rate Limits', 'rate:*'),
                ('Cache Metrics', 'cache:*'),
                ('Workers', 'workers:*'),
                ('Tasks', 'tasks:*')
            ]
            
            for name, pattern in patterns:
                count = sum(1 for _ in client.scan_iter(match=pattern, count=1000))
                key_counts[name] = count
            
            # Get cache metrics
            cache_metrics = self.redis_mgr._metrics.get_metrics()
            
            # Get memory details
            memory_stats = {
                'used_memory_mb': info.get('used_memory', 0) / (1024 * 1024),
                'used_memory_peak_mb': info.get('used_memory_peak', 0) / (1024 * 1024),
                'used_memory_rss_mb': info.get('used_memory_rss', 0) / (1024 * 1024),
                'mem_fragmentation_ratio': info.get('mem_fragmentation_ratio', 0),
            }
            
            # Get command stats
            cmd_stats = {}
            for key, value in info.items():
                if key.startswith('cmdstat_'):
                    cmd_name = key.replace('cmdstat_', '')
                    # Parse command stats
                    stats_dict = dict(item.split('=') for item in value.split(','))
                    cmd_stats[cmd_name] = {
                        'calls': int(stats_dict.get('calls', 0)),
                        'usec': int(stats_dict.get('usec', 0)),
                        'usec_per_call': float(stats_dict.get('usec_per_call', 0))
                    }
            
            return {
                'uptime_hours': info.get('uptime_in_seconds', 0) / 3600,
                'connected_clients': info.get('connected_clients', 0),
                'blocked_clients': info.get('blocked_clients', 0),
                'memory': memory_stats,
                'total_commands': info.get('total_commands_processed', 0),
                'instantaneous_ops': info.get('instantaneous_ops_per_sec', 0),
                'keyspace_hits': info.get('keyspace_hits', 0),
                'keyspace_misses': info.get('keyspace_misses', 0),
                'evicted_keys': info.get('evicted_keys', 0),
                'expired_keys': info.get('expired_keys', 0),
                'key_counts': key_counts,
                'total_keys': sum(key_counts.values()),
                'cache_metrics': cache_metrics,
                'command_stats': cmd_stats,
                'redis_version': info.get('redis_version', 'unknown'),
                'role': info.get('role', 'unknown'),
                'persistence': {
                    'rdb_last_save_time': info.get('rdb_last_save_time', 0),
                    'rdb_changes_since_last_save': info.get('rdb_changes_since_last_save', 0),
                    'aof_enabled': info.get('aof_enabled', 0) == 1,
                    'aof_rewrite_in_progress': info.get('aof_rewrite_in_progress', 0) == 1,
                }
            }
        except Exception as e:
            return {'error': f'Error getting Redis stats: {str(e)}'}
    
    def create_overview_panel(self, stats: Dict) -> Panel:
        """Create overview panel."""
        if 'error' in stats:
            return Panel(
                Text(stats['error'], style="red"),
                title="❌ Redis Error",
                border_style="red"
            )
        
        # Calculate uptime
        monitor_uptime = (time.time() - self.start_time) / 60  # minutes
        
        content = f"""
[bold cyan]Redis Server[/bold cyan]
Version: {stats.get('redis_version', 'unknown')}
Role: {stats.get('role', 'unknown')}
Uptime: {stats.get('uptime_hours', 0):.1f} hours

[bold cyan]Connection[/bold cyan]
Connected Clients: {stats.get('connected_clients', 0)}
Blocked Clients: {stats.get('blocked_clients', 0)}

[bold cyan]Performance[/bold cyan]
Commands/sec: {stats.get('instantaneous_ops', 0)}
Total Commands: {stats.get('total_commands', 0):,}

[bold cyan]Monitor[/bold cyan]
Running for: {monitor_uptime:.1f} minutes
Last Update: {datetime.now().strftime('%H:%M:%S')}
"""
        
        return Panel(
            content.strip(),
            title="📊 Overview",
            border_style="cyan"
        )
    
    def create_memory_panel(self, stats: Dict) -> Panel:
        """Create memory statistics panel."""
        if 'error' in stats:
            return Panel("No data", title="💾 Memory", border_style="red")
        
        memory = stats.get('memory', {})
        
        # Calculate memory usage percentage
        used_mb = memory.get('used_memory_mb', 0)
        peak_mb = memory.get('used_memory_peak_mb', 0)
        
        # Create memory bar
        bar_width = 30
        if peak_mb > 0:
            usage_pct = min(used_mb / peak_mb, 1.0)
            filled = int(bar_width * usage_pct)
            bar = "█" * filled + "░" * (bar_width - filled)
            usage_str = f"{usage_pct * 100:.1f}%"
        else:
            bar = "░" * bar_width
            usage_str = "N/A"
        
        content = f"""
[bold yellow]Memory Usage[/bold yellow]
Used: {used_mb:.1f} MB
Peak: {peak_mb:.1f} MB
RSS: {memory.get('used_memory_rss_mb', 0):.1f} MB

[bold yellow]Usage Bar[/bold yellow]
[{bar}] {usage_str}

[bold yellow]Fragmentation[/bold yellow]
Ratio: {memory.get('mem_fragmentation_ratio', 0):.2f}

[bold yellow]Eviction[/bold yellow]
Evicted Keys: {stats.get('evicted_keys', 0):,}
Expired Keys: {stats.get('expired_keys', 0):,}
"""
        
        return Panel(
            content.strip(),
            title="💾 Memory",
            border_style="yellow"
        )
    
    def create_cache_panel(self, stats: Dict) -> Panel:
        """Create cache performance panel."""
        if 'error' in stats:
            return Panel("No data", title="🎯 Cache Performance", border_style="red")
        
        # Redis keyspace stats
        hits = stats.get('keyspace_hits', 0)
        misses = stats.get('keyspace_misses', 0)
        total = hits + misses
        hit_rate = (hits / total * 100) if total > 0 else 0
        
        # Application cache metrics
        cache_metrics = stats.get('cache_metrics', {})
        app_hits = cache_metrics.get('hits', 0)
        app_misses = cache_metrics.get('misses', 0)
        app_sets = cache_metrics.get('sets', 0)
        app_total = app_hits + app_misses
        app_hit_rate = cache_metrics.get('hit_rate', 0)
        
        content = f"""
[bold green]Redis Keyspace[/bold green]
Hits: {hits:,}
Misses: {misses:,}
Hit Rate: {hit_rate:.1f}%

[bold green]Application Cache[/bold green]
Hits: {app_hits:,}
Misses: {app_misses:,}
Sets: {app_sets:,}
Hit Rate: {app_hit_rate:.1f}%

[bold green]Efficiency[/bold green]
Total Requests: {app_total:,}
Cache Benefit: {app_hits:,} API calls saved
"""
        
        return Panel(
            content.strip(),
            title="🎯 Cache Performance",
            border_style="green"
        )
    
    def create_keys_table(self, stats: Dict) -> Table:
        """Create key distribution table."""
        table = Table(title="🔑 Key Distribution")
        
        table.add_column("Category", style="cyan")
        table.add_column("Count", justify="right", style="green")
        table.add_column("Percentage", justify="right", style="yellow")
        
        if 'error' not in stats and 'key_counts' in stats:
            key_counts = stats['key_counts']
            total_keys = stats.get('total_keys', 1)
            
            # Sort by count
            sorted_counts = sorted(key_counts.items(), key=lambda x: x[1], reverse=True)
            
            for category, count in sorted_counts:
                percentage = (count / total_keys * 100) if total_keys > 0 else 0
                table.add_row(
                    category,
                    f"{count:,}",
                    f"{percentage:.1f}%"
                )
            
            # Add total row
            table.add_row(
                "[bold]Total[/bold]",
                f"[bold]{total_keys:,}[/bold]",
                "[bold]100.0%[/bold]"
            )
        else:
            table.add_row("No data", "-", "-")
        
        return table
    
    def create_commands_table(self, stats: Dict) -> Table:
        """Create top commands table."""
        table = Table(title="⚡ Top Commands")
        
        table.add_column("Command", style="cyan")
        table.add_column("Calls", justify="right", style="green")
        table.add_column("Avg μs", justify="right", style="yellow")
        
        if 'error' not in stats and 'command_stats' in stats:
            cmd_stats = stats['command_stats']
            
            # Sort by calls
            sorted_cmds = sorted(
                cmd_stats.items(), 
                key=lambda x: x[1]['calls'], 
                reverse=True
            )[:10]  # Top 10
            
            for cmd, stats_dict in sorted_cmds:
                table.add_row(
                    cmd.upper(),
                    f"{stats_dict['calls']:,}",
                    f"{stats_dict['usec_per_call']:.1f}"
                )
        else:
            table.add_row("No data", "-", "-")
        
        return table
    
    def create_dashboard_layout(self, stats: Dict) -> Layout:
        """Create the full dashboard layout."""
        layout = Layout()
        
        # Create main sections
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="body"),
            Layout(name="footer", size=1)
        )
        
        # Header
        layout["header"].update(
            Text("🚀 Redis Monitor Dashboard", style="bold magenta", justify="center")
        )
        
        # Body split into rows
        layout["body"].split_column(
            Layout(name="top_row", size=15),
            Layout(name="middle_row", size=12),
            Layout(name="bottom_row")
        )
        
        # Top row: Overview, Memory, Cache
        layout["top_row"].split_row(
            Layout(self.create_overview_panel(stats)),
            Layout(self.create_memory_panel(stats)),
            Layout(self.create_cache_panel(stats))
        )
        
        # Middle row: Key distribution
        layout["middle_row"].update(self.create_keys_table(stats))
        
        # Bottom row: Commands
        layout["bottom_row"].update(self.create_commands_table(stats))
        
        # Footer
        persistence = stats.get('persistence', {})
        footer_text = f"AOF: {'✓' if persistence.get('aof_enabled') else '✗'} | "
        footer_text += f"Last RDB Save: {persistence.get('rdb_changes_since_last_save', 0)} changes ago | "
        footer_text += "Press Ctrl+C to exit"
        
        layout["footer"].update(
            Text(footer_text, style="dim", justify="center")
        )
        
        return layout
    
    def run(self, refresh_interval: int = 5):
        """Run the monitoring dashboard."""
        console.print("[bold green]Starting Redis Monitor...[/bold green]")
        
        try:
            with Live(
                self.create_dashboard_layout(self.get_redis_stats()),
                refresh_per_second=1/refresh_interval,
                console=console
            ) as live:
                while True:
                    time.sleep(refresh_interval)
                    stats = self.get_redis_stats()
                    live.update(self.create_dashboard_layout(stats))
                    
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Redis Monitor stopped.[/bold yellow]")
        except Exception as e:
            console.print(f"\n[bold red]Error: {e}[/bold red]")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Redis monitoring dashboard")
    parser.add_argument(
        '--interval', '-i',
        type=int,
        default=5,
        help='Refresh interval in seconds (default: 5)'
    )
    
    args = parser.parse_args()
    
    monitor = RedisMonitor()
    monitor.run(refresh_interval=args.interval)


if __name__ == "__main__":
    main()