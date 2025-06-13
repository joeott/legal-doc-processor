# Context 261: EC2 Instance Hardware Specifications

## Instance Overview

### AWS Instance Details
- **Instance Type**: t3.medium
- **Instance ID**: i-0e431c454a7c3c6a1
- **Region**: us-east-1a
- **Public IP**: 54.162.223.205
- **Private IP**: 172.31.33.106
- **Security Group**: sg-03ba8403ff7b45bf7

### Access Credentials
- **SSH Key**: `~/Documents/phase_1_2_3_process_v5/resources/aws/legal-doc-processor-bastion.pem`
- **SSH User**: ubuntu
- **SSH Config Alias**: legal-doc-ec2
- **Project Directory**: `/opt/legal-doc-processor`

## Hardware Specifications

### CPU Configuration
- **Architecture**: x86_64
- **CPU Model**: Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz
- **Physical Cores**: 1
- **Threads per Core**: 2 (Hyperthreading enabled)
- **Total vCPUs**: 2
- **CPU Cache**:
  - L1 Data: 32 KiB
  - L1 Instruction: 32 KiB
  - L2: 1 MiB
  - L3: 35.8 MiB

### Memory Configuration
- **Total RAM**: 3.7 GiB (3,928,936 KB)
- **Memory Usage** (as of last check):
  - Used: 2.8 GiB (75%)
  - Free: 531 MiB
  - Available: 647 MiB
  - Buffer/Cache: 392 MiB
- **Swap**: Not configured

### Storage Configuration
- **Root Volume**: 30 GB NVMe SSD
  - Device: `/dev/nvme0n1p1`
  - Filesystem: ext4
  - Used: 9.4 GB (33%)
  - Available: 20 GB
- **Boot Partition**: 106 MB EFI System Partition
  - Device: `/dev/nvme0n1p15`
  - Filesystem: vfat
- **No additional EBS volumes attached**

### Network Configuration
- **Primary Interface**: ens5 (Elastic Network Adapter)
- **MAC Address**: 0e:02:0b:8b:a6:dd
- **MTU**: 9001 (Jumbo frames enabled for enhanced performance)
- **Network Performance**: Up to 5 Gbps
- **IPv4 Only** (No IPv6 configured)

## System Software

### Operating System
- **Distribution**: Ubuntu 22.04.5 LTS (Jammy Jellyfish)
- **Kernel**: 6.8.0-1029-aws (AWS-optimized)
- **Architecture**: x86_64
- **System Uptime**: 6+ days (as of last check)
- **Load Average**: Low (0.04, 0.09, 0.16)

### Key Installed Software
- Python 3.10 (system)
- Docker (if installed)
- Supervisor (for process management)
- Redis client tools
- AWS CLI
- Git
- Node.js (for MCP servers)

## Performance Characteristics

### t3.medium Instance Type
- **Baseline Performance**: 20% CPU continuously
- **Burst Credits**: Can burst to 100% CPU when needed
- **Network Burst**: Up to 5 Gbps
- **EBS Burst**: Up to 1,536 Mbps

### Current Resource Utilization
- **CPU**: Low utilization (~5-10% average)
- **Memory**: 75% utilized (primarily by application processes)
- **Disk I/O**: Low to moderate
- **Network**: Minimal usage

## Recommendations

### Memory Optimization
- Current memory usage at 75% is acceptable but leaves limited headroom
- Consider upgrading to t3.large (8 GB RAM) if memory pressure increases
- No swap configured - could add swap file for safety

### Storage Considerations
- 20 GB free space is sufficient for current operations
- Consider periodic cleanup of logs and temporary files
- Monitor `/opt/legal-doc-processor/logs` directory size

### Performance Tuning
- CPU credits are likely sufficient for current workload
- Network MTU already optimized at 9001
- Consider enabling monitoring for CPU credit balance

## Quick Reference Commands

```bash
# Check current resource usage
free -h                    # Memory usage
df -h                     # Disk usage
top                       # Process and CPU usage
htop                      # Better process viewer (if installed)

# Monitor instance metadata
curl http://169.254.169.254/latest/meta-data/instance-type
curl http://169.254.169.254/latest/meta-data/instance-id

# Check network performance
ethtool ens5              # Network interface details
iperf3 -c <target>        # Network throughput test

# System information
lscpu                     # CPU details
lsblk                     # Block devices
cat /proc/meminfo         # Detailed memory info
```

## SSH Access Shortcuts

```bash
# Direct SSH
ssh legal-doc-ec2

# SSH with directory change
legal-ssh  # Drops you into /opt/legal-doc-processor

# Open in Cursor IDE
legal      # Opens Cursor directly to project directory
```

---

**Last Updated**: January 2025
**Next Review**: Check instance performance metrics monthly