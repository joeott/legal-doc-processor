#!/usr/bin/env python3
"""
SSH Tunnel Monitor and Maintenance
Monitors SSH tunnel health and automatically restarts if needed
"""

import subprocess
import time
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Tuple
# import psutil  # Optional dependency

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.config import (
    RDS_TUNNEL_LOCAL_PORT, RDS_BASTION_HOST, 
    RDS_BASTION_USER, RDS_BASTION_KEY
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SSHTunnelMonitor:
    """Monitor and maintain SSH tunnel health."""
    
    def __init__(self):
        self.tunnel_port = RDS_TUNNEL_LOCAL_PORT
        self.bastion_host = RDS_BASTION_HOST
        self.bastion_user = RDS_BASTION_USER
        self.pem_key = Path(project_root) / RDS_BASTION_KEY
        self.rds_endpoint = "database1.cuviucyodbeg.us-east-1.rds.amazonaws.com"
        self.rds_port = 5432
        
    def get_tunnel_pid(self) -> Optional[int]:
        """Get PID of SSH tunnel process if it exists."""
        try:
            # Method 1: Check with lsof
            result = subprocess.run(
                ['lsof', f'-ti:{self.tunnel_port}'],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                return int(result.stdout.strip().split('\n')[0])
                
            # Method 2: Check with ps
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True
            )
            for line in result.stdout.split('\n'):
                if f'{self.tunnel_port}:{self.rds_endpoint}' in line and 'ssh' in line:
                    parts = line.split()
                    if len(parts) > 1:
                        return int(parts[1])
                        
        except Exception as e:
            logger.error(f"Error getting tunnel PID: {e}")
            
        return None
        
    def check_tunnel_process(self) -> bool:
        """Check if SSH tunnel process is running."""
        pid = self.get_tunnel_pid()
        if pid:
            try:
                # Check if process exists using kill -0
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                # Process exists but we can't signal it
                return True
        return False
        
    def check_tunnel_connectivity(self) -> bool:
        """Check if tunnel is accepting connections."""
        try:
            # Try to connect to the tunnel port
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex(('localhost', self.tunnel_port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.error(f"Error checking tunnel connectivity: {e}")
            return False
            
    def check_database_connection(self) -> bool:
        """Test actual database connection through tunnel."""
        try:
            from scripts.rds_utils import test_connection
            return test_connection()
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
            
    def check_tunnel_health(self) -> Tuple[bool, str]:
        """
        Comprehensive tunnel health check.
        Returns (is_healthy, status_message)
        """
        # Check 1: Process exists
        if not self.check_tunnel_process():
            return False, "SSH tunnel process not found"
            
        # Check 2: Port is listening
        if not self.check_tunnel_connectivity():
            return False, "SSH tunnel port not responding"
            
        # Check 3: Database connection works
        if not self.check_database_connection():
            return False, "Database connection through tunnel failed"
            
        return True, "SSH tunnel healthy"
        
    def stop_tunnel(self):
        """Stop existing SSH tunnel."""
        pid = self.get_tunnel_pid()
        if pid:
            try:
                logger.info(f"Stopping SSH tunnel (PID: {pid})")
                os.kill(pid, 9)
                time.sleep(2)  # Wait for process to die
            except Exception as e:
                logger.error(f"Error stopping tunnel: {e}")
                
    def start_tunnel(self) -> bool:
        """Start new SSH tunnel."""
        try:
            # Ensure PEM key has correct permissions
            os.chmod(self.pem_key, 0o400)
            
            cmd = [
                'ssh', '-f', '-N', '-C',
                '-o', 'ServerAliveInterval=60',
                '-o', 'ServerAliveCountMax=3',
                '-o', 'TCPKeepAlive=yes',
                '-o', 'Compression=yes',
                '-o', 'CompressionLevel=6',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-L', f'{self.tunnel_port}:{self.rds_endpoint}:{self.rds_port}',
                '-i', str(self.pem_key),
                f'{self.bastion_user}@{self.bastion_host}'
            ]
            
            logger.info(f"Starting SSH tunnel to {self.bastion_host}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Failed to start tunnel: {result.stderr}")
                return False
                
            # Wait for tunnel to establish
            time.sleep(3)
            
            # Verify it's working
            if self.check_tunnel_connectivity():
                logger.info("SSH tunnel started successfully")
                return True
            else:
                logger.error("SSH tunnel started but not responding")
                return False
                
        except Exception as e:
            logger.error(f"Error starting tunnel: {e}")
            return False
            
    def restart_tunnel(self) -> bool:
        """Restart SSH tunnel."""
        logger.info("Restarting SSH tunnel...")
        self.stop_tunnel()
        return self.start_tunnel()
        
    def ensure_tunnel_healthy(self) -> bool:
        """Ensure tunnel is healthy, restart if needed."""
        is_healthy, status = self.check_tunnel_health()
        
        if is_healthy:
            logger.debug(f"Tunnel status: {status}")
            return True
        else:
            logger.warning(f"Tunnel unhealthy: {status}")
            return self.restart_tunnel()
            
    def monitor_loop(self, check_interval: int = 60):
        """
        Continuous monitoring loop.
        
        Args:
            check_interval: Seconds between health checks
        """
        logger.info(f"Starting SSH tunnel monitor (checking every {check_interval}s)")
        
        while True:
            try:
                self.ensure_tunnel_healthy()
            except KeyboardInterrupt:
                logger.info("Monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                
            time.sleep(check_interval)


def main():
    """Main entry point for CLI usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='SSH Tunnel Monitor')
    parser.add_argument('command', choices=['check', 'start', 'stop', 'restart', 'monitor'],
                       help='Command to execute')
    parser.add_argument('--interval', type=int, default=60,
                       help='Monitor check interval in seconds')
    
    args = parser.parse_args()
    
    monitor = SSHTunnelMonitor()
    
    if args.command == 'check':
        is_healthy, status = monitor.check_tunnel_health()
        print(f"{'✓' if is_healthy else '✗'} {status}")
        sys.exit(0 if is_healthy else 1)
        
    elif args.command == 'start':
        success = monitor.start_tunnel()
        print(f"{'✓' if success else '✗'} Tunnel {'started' if success else 'failed to start'}")
        sys.exit(0 if success else 1)
        
    elif args.command == 'stop':
        monitor.stop_tunnel()
        print("✓ Tunnel stopped")
        
    elif args.command == 'restart':
        success = monitor.restart_tunnel()
        print(f"{'✓' if success else '✗'} Tunnel {'restarted' if success else 'failed to restart'}")
        sys.exit(0 if success else 1)
        
    elif args.command == 'monitor':
        try:
            monitor.monitor_loop(args.interval)
        except KeyboardInterrupt:
            print("\nMonitor stopped")


if __name__ == '__main__':
    main()