#!/usr/bin/env python3
"""
Live dashboard for monitoring document import progress and costs.

Uses curses for terminal UI with real-time updates.
"""

import os
import sys
import curses
import time
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import threading
from collections import defaultdict

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.import_tracker import ImportTracker, ImportStatus
from scripts.supabase_utils import SupabaseManager


class ImportDashboard:
    """Live dashboard for import monitoring."""
    
    def __init__(self, session_id: int, refresh_interval: float = 2.0):
        self.session_id = session_id
        self.refresh_interval = refresh_interval
        self.tracker = ImportTracker()
        self.db_manager = SupabaseManager()
        
        # Dashboard data
        self.session_data = {}
        self.processing_docs = []
        self.recent_completions = []
        self.recent_errors = []
        self.cost_history = []
        
        # UI state
        self.selected_tab = 0
        self.scroll_offset = 0
        self.running = True
        
        # Colors
        self.colors = {}
    
    def init_colors(self):
        """Initialize color pairs for the UI."""
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)   # Success
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)     # Error
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Warning
        curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)    # Info
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)    # Header
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)   # Selected
        
        self.colors = {
            'success': curses.color_pair(1),
            'error': curses.color_pair(2),
            'warning': curses.color_pair(3),
            'info': curses.color_pair(4),
            'header': curses.color_pair(5),
            'selected': curses.color_pair(6)
        }
    
    def run(self, stdscr):
        """Main dashboard loop."""
        # Setup curses
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(1)   # Non-blocking input
        stdscr.timeout(100) # 100ms timeout for getch()
        
        # Initialize colors
        if curses.has_colors():
            curses.start_color()
            self.init_colors()
        
        # Start data refresh thread
        refresh_thread = threading.Thread(target=self._refresh_data_loop)
        refresh_thread.daemon = True
        refresh_thread.start()
        
        # Main UI loop
        while self.running:
            # Handle input
            key = stdscr.getch()
            self._handle_input(key)
            
            # Clear and redraw
            stdscr.clear()
            self._draw_dashboard(stdscr)
            stdscr.refresh()
            
            # Small delay to prevent CPU spinning
            time.sleep(0.05)
    
    def _refresh_data_loop(self):
        """Background thread to refresh data."""
        while self.running:
            try:
                self._refresh_data()
            except Exception as e:
                # Log error but keep running
                pass
            time.sleep(self.refresh_interval)
    
    def _refresh_data(self):
        """Refresh dashboard data from database."""
        # Get session status
        self.session_data = self.tracker.get_session_status(self.session_id)
        
        # Get currently processing documents
        with self.tracker.lock:
            cursor = self.tracker.conn.cursor()
            
            # Processing documents
            cursor.execute("""
                SELECT file_path, started_at, 
                       julianday('now') - julianday(started_at) as processing_time
                FROM document_imports
                WHERE session_id = ? AND status = 'processing'
                ORDER BY started_at DESC
                LIMIT 10
            """, (self.session_id,))
            
            self.processing_docs = [dict(row) for row in cursor.fetchall()]
            
            # Recent completions
            cursor.execute("""
                SELECT file_path, completed_at, processing_time_seconds, status
                FROM document_imports
                WHERE session_id = ? AND status IN ('completed', 'queued', 'uploaded')
                ORDER BY completed_at DESC
                LIMIT 20
            """, (self.session_id,))
            
            self.recent_completions = [dict(row) for row in cursor.fetchall()]
            
            # Recent errors
            cursor.execute("""
                SELECT file_path, error_message, error_type, completed_at
                FROM document_imports
                WHERE session_id = ? AND status = 'failed'
                ORDER BY completed_at DESC
                LIMIT 20
            """, (self.session_id,))
            
            self.recent_errors = [dict(row) for row in cursor.fetchall()]
            
            # Cost history (last hour)
            cursor.execute("""
                SELECT timestamp, service, operation, total_cost
                FROM processing_costs
                WHERE session_id = ? 
                  AND timestamp > datetime('now', '-1 hour')
                ORDER BY timestamp DESC
                LIMIT 100
            """, (self.session_id,))
            
            self.cost_history = [dict(row) for row in cursor.fetchall()]
    
    def _handle_input(self, key):
        """Handle keyboard input."""
        if key == ord('q') or key == 27:  # q or ESC
            self.running = False
        elif key == ord('\t'):  # TAB
            self.selected_tab = (self.selected_tab + 1) % 4
            self.scroll_offset = 0
        elif key == curses.KEY_UP:
            self.scroll_offset = max(0, self.scroll_offset - 1)
        elif key == curses.KEY_DOWN:
            self.scroll_offset += 1
        elif key == ord('r'):  # Force refresh
            self._refresh_data()
    
    def _draw_dashboard(self, stdscr):
        """Draw the complete dashboard."""
        height, width = stdscr.getmaxyx()
        
        # Draw header
        self._draw_header(stdscr, width)
        
        # Draw stats bar
        self._draw_stats_bar(stdscr, width, 2)
        
        # Draw tabs
        self._draw_tabs(stdscr, width, 4)
        
        # Draw content area
        content_start = 6
        content_height = height - content_start - 2
        
        if self.selected_tab == 0:
            self._draw_overview(stdscr, content_start, content_height, width)
        elif self.selected_tab == 1:
            self._draw_processing(stdscr, content_start, content_height, width)
        elif self.selected_tab == 2:
            self._draw_errors(stdscr, content_start, content_height, width)
        elif self.selected_tab == 3:
            self._draw_costs(stdscr, content_start, content_height, width)
        
        # Draw footer
        self._draw_footer(stdscr, height - 1, width)
    
    def _draw_header(self, stdscr, width):
        """Draw dashboard header."""
        session = self.session_data
        case_name = session.get('case_name', 'Unknown Case')
        
        header = f" IMPORT DASHBOARD - {case_name} "
        header = header[:width-2].center(width-2)
        
        stdscr.attron(self.colors['header'])
        stdscr.addstr(0, 0, " " * width)
        stdscr.addstr(0, 1, header)
        stdscr.attroff(self.colors['header'])
    
    def _draw_stats_bar(self, stdscr, width, y):
        """Draw statistics bar."""
        session = self.session_data
        
        total = session.get('total_files', 0)
        processed = session.get('processed_files', 0)
        failed = session.get('failed_files', 0)
        pending = total - processed - failed
        
        # Calculate progress
        progress = processed / total if total > 0 else 0
        
        # Format stats
        stats = [
            f"Total: {total}",
            f"Processed: {processed}",
            f"Failed: {failed}",
            f"Pending: {pending}",
            f"Progress: {progress*100:.1f}%",
            f"Cost: ${session.get('total_cost', 0):.2f}"
        ]
        
        # Draw stats
        x = 2
        for stat in stats:
            if x + len(stat) + 3 < width:
                stdscr.addstr(y, x, stat)
                x += len(stat) + 3
        
        # Draw progress bar
        bar_width = width - 4
        filled = int(bar_width * progress)
        
        stdscr.addstr(y + 1, 2, "[")
        if filled > 0:
            stdscr.attron(self.colors['success'])
            stdscr.addstr("=" * filled)
            stdscr.attroff(self.colors['success'])
        if filled < bar_width:
            stdscr.addstr(" " * (bar_width - filled))
        stdscr.addstr("]")
    
    def _draw_tabs(self, stdscr, width, y):
        """Draw tab bar."""
        tabs = ["Overview", "Processing", "Errors", "Costs"]
        
        x = 2
        for i, tab in enumerate(tabs):
            if i == self.selected_tab:
                stdscr.attron(self.colors['selected'])
            
            stdscr.addstr(y, x, f" {tab} ")
            
            if i == self.selected_tab:
                stdscr.attroff(self.colors['selected'])
            
            x += len(tab) + 4
    
    def _draw_overview(self, stdscr, y, height, width):
        """Draw overview tab."""
        session = self.session_data
        status_counts = session.get('status_counts', {})
        
        # Draw title
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(y, 2, "STATUS OVERVIEW")
        stdscr.attroff(curses.A_BOLD)
        
        y += 2
        
        # Draw status breakdown
        for status, count in sorted(status_counts.items()):
            if y >= height - 2:
                break
                
            # Choose color based on status
            if status in ['completed', 'queued', 'uploaded']:
                color = self.colors['success']
            elif status == 'failed':
                color = self.colors['error']
            elif status == 'processing':
                color = self.colors['warning']
            else:
                color = 0
            
            label = f"{status.capitalize():15} {count:6}"
            
            if color:
                stdscr.attron(color)
            stdscr.addstr(y, 4, label)
            if color:
                stdscr.attroff(color)
            
            y += 1
        
        # Draw timing stats
        if 'time_stats' in session:
            y += 2
            if y < height - 4:
                stdscr.attron(curses.A_BOLD)
                stdscr.addstr(y, 2, "TIMING STATISTICS")
                stdscr.attroff(curses.A_BOLD)
                
                y += 2
                time_stats = session['time_stats']
                if time_stats.get('avg_time'):
                    stdscr.addstr(y, 4, f"Average: {time_stats['avg_time']:.1f}s")
                    y += 1
                if time_stats.get('total_time'):
                    total_minutes = time_stats['total_time'] / 60
                    stdscr.addstr(y, 4, f"Total: {total_minutes:.1f} minutes")
    
    def _draw_processing(self, stdscr, y, height, width):
        """Draw processing tab."""
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(y, 2, "CURRENTLY PROCESSING")
        stdscr.attroff(curses.A_BOLD)
        
        y += 2
        
        if not self.processing_docs:
            stdscr.addstr(y, 4, "No documents currently processing")
        else:
            for doc in self.processing_docs:
                if y >= height - 2:
                    break
                
                filename = os.path.basename(doc['file_path'])[:40]
                proc_time = doc.get('processing_time', 0) * 86400  # Convert days to seconds
                
                line = f"{filename:<40} {proc_time:>6.1f}s"
                
                stdscr.attron(self.colors['warning'])
                stdscr.addstr(y, 4, line[:width-6])
                stdscr.attroff(self.colors['warning'])
                
                y += 1
        
        # Recent completions
        y += 2
        if y < height - 4:
            stdscr.attron(curses.A_BOLD)
            stdscr.addstr(y, 2, "RECENT COMPLETIONS")
            stdscr.attroff(curses.A_BOLD)
            
            y += 2
            
            start_idx = self.scroll_offset
            visible_completions = self.recent_completions[start_idx:start_idx + (height - y - 2)]
            
            for doc in visible_completions:
                if y >= height - 2:
                    break
                
                filename = os.path.basename(doc['file_path'])[:40]
                proc_time = doc.get('processing_time_seconds', 0)
                
                line = f"{filename:<40} {proc_time:>6.1f}s"
                
                stdscr.attron(self.colors['success'])
                stdscr.addstr(y, 4, line[:width-6])
                stdscr.attroff(self.colors['success'])
                
                y += 1
    
    def _draw_errors(self, stdscr, y, height, width):
        """Draw errors tab."""
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(y, 2, "RECENT ERRORS")
        stdscr.attroff(curses.A_BOLD)
        
        y += 2
        
        if not self.recent_errors:
            stdscr.attron(self.colors['success'])
            stdscr.addstr(y, 4, "No errors reported")
            stdscr.attroff(self.colors['success'])
        else:
            start_idx = self.scroll_offset
            visible_errors = self.recent_errors[start_idx:start_idx + (height - y - 2)]
            
            for error in visible_errors:
                if y >= height - 2:
                    break
                
                filename = os.path.basename(error['file_path'])[:30]
                error_type = error.get('error_type', 'Unknown')[:20]
                
                # First line: filename and error type
                stdscr.attron(self.colors['error'])
                stdscr.addstr(y, 4, f"{filename} - {error_type}")
                stdscr.attroff(self.colors['error'])
                
                y += 1
                
                # Second line: error message (truncated)
                if y < height - 2:
                    error_msg = error.get('error_message', '')[:width-8]
                    stdscr.addstr(y, 6, error_msg)
                    y += 2
    
    def _draw_costs(self, stdscr, y, height, width):
        """Draw costs tab."""
        session = self.session_data
        cost_breakdown = session.get('cost_breakdown', {})
        
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(y, 2, "COST BREAKDOWN")
        stdscr.attroff(curses.A_BOLD)
        
        y += 2
        
        # Total cost
        total_cost = session.get('total_cost', 0)
        stdscr.attron(self.colors['info'])
        stdscr.addstr(y, 4, f"Total Cost: ${total_cost:.2f}")
        stdscr.attroff(self.colors['info'])
        
        y += 2
        
        # Cost by service
        for service, cost in sorted(cost_breakdown.items(), key=lambda x: x[1], reverse=True):
            if y >= height - 2:
                break
            
            bar_width = int((cost / total_cost * 30)) if total_cost > 0 else 0
            bar = "█" * bar_width
            
            line = f"{service:<15} ${cost:>8.2f} {bar}"
            stdscr.addstr(y, 4, line[:width-6])
            
            y += 1
        
        # Recent cost events
        y += 2
        if y < height - 4 and self.cost_history:
            stdscr.attron(curses.A_BOLD)
            stdscr.addstr(y, 2, "RECENT ACTIVITY")
            stdscr.attroff(curses.A_BOLD)
            
            y += 2
            
            for event in self.cost_history[:5]:
                if y >= height - 2:
                    break
                
                timestamp = event['timestamp'].split('T')[1][:8]
                service = event['service'][:10]
                operation = event['operation'][:15]
                cost = event['total_cost']
                
                line = f"{timestamp} {service} {operation} ${cost:.4f}"
                stdscr.addstr(y, 4, line[:width-6])
                
                y += 1
    
    def _draw_footer(self, stdscr, y, width):
        """Draw footer with help."""
        help_text = " TAB: Switch tabs | ↑↓: Scroll | R: Refresh | Q: Quit "
        help_text = help_text[:width-2].center(width-2)
        
        stdscr.attron(self.colors['header'])
        stdscr.addstr(y, 0, " " * width)
        stdscr.addstr(y, 1, help_text)
        stdscr.attroff(self.colors['header'])


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Live import dashboard')
    parser.add_argument('session_id', type=int, help='Import session ID to monitor')
    parser.add_argument('--refresh', type=float, default=2.0, 
                       help='Refresh interval in seconds')
    
    args = parser.parse_args()
    
    # Create and run dashboard
    dashboard = ImportDashboard(args.session_id, args.refresh)
    
    try:
        curses.wrapper(dashboard.run)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Dashboard error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()