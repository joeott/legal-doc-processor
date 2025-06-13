# AWS EC2 Instance Resize Instructions

## Current Instance: t3.medium → Target: t3.xlarge

### Pre-Resize Checklist

1. **[ ] Create Backup**
   ```bash
   # Create AMI snapshot of current instance
   aws ec2 create-image \
     --instance-id i-0e431c454a7c3c6a1 \
     --name "legal-doc-processor-backup-$(date +%Y%m%d)" \
     --description "Backup before resize to t3.xlarge" \
     --no-reboot
   ```

2. **[ ] Document Current State**
   ```bash
   # Save current configuration
   cd /opt/legal-doc-processor
   python3 scripts/utils/schema_inspector.py -o pre_resize_schema
   ps aux > ~/pre_resize_processes.txt
   df -h > ~/pre_resize_disk.txt
   free -h > ~/pre_resize_memory.txt
   ```

3. **[ ] Stop All Services**
   ```bash
   # Stop Celery workers
   ps aux | grep "[c]elery.*worker" | awk '{print $2}' | xargs -r kill -9
   
   # Stop any batch processing
   # Check for running tasks in monitoring
   ```

4. **[ ] Note Current IPs**
   - Public IP: 54.162.223.205 (will change!)
   - Private IP: 172.31.33.106 (will stay the same)
   - Elastic IP: None configured (consider adding one)

### Step-by-Step Resize Process

#### Step 1: Stop the Instance
```bash
# From AWS CLI (if configured)
aws ec2 stop-instances --instance-ids i-0e431c454a7c3c6a1

# Or from AWS Console:
# 1. Go to EC2 Console: https://console.aws.amazon.com/ec2/
# 2. Select instance i-0e431c454a7c3c6a1
# 3. Actions → Instance State → Stop Instance
# 4. Confirm stop
# 5. Wait for "Instance State" to show "stopped" (3-5 minutes)
```

#### Step 2: Change Instance Type
```bash
# From AWS CLI
aws ec2 modify-instance-attribute \
  --instance-id i-0e431c454a7c3c6a1 \
  --instance-type "{\"Value\": \"t3.xlarge\"}"

# Or from AWS Console:
# 1. With instance stopped, select it
# 2. Actions → Instance Settings → Change Instance Type
# 3. Select "t3.xlarge" from dropdown
# 4. Check "EBS-optimized" if available
# 5. Click "Apply"
```

#### Step 3: Start the Instance
```bash
# From AWS CLI
aws ec2 start-instances --instance-ids i-0e431c454a7c3c6a1

# Or from AWS Console:
# 1. Select the instance
# 2. Actions → Instance State → Start Instance
# 3. Wait for "Instance State" to show "running"
# 4. Note the NEW PUBLIC IP ADDRESS!
```

### Post-Resize Steps

1. **Update SSH Configuration**
   ```bash
   # Get new public IP
   aws ec2 describe-instances \
     --instance-ids i-0e431c454a7c3c6a1 \
     --query 'Reservations[0].Instances[0].PublicIpAddress' \
     --output text
   
   # Update ~/.ssh/config with new IP
   # Update any saved connections in Cursor/VS Code
   ```

2. **Reconnect and Verify**
   ```bash
   # SSH with new IP
   ssh -i ~/Documents/phase_1_2_3_process_v5/resources/aws/legal-doc-processor-bastion.pem ubuntu@<NEW_PUBLIC_IP>
   
   # Verify instance type
   curl http://169.254.169.254/latest/meta-data/instance-type
   # Should show: t3.xlarge
   
   # Check resources
   free -h  # Should show ~15.5 GB RAM
   nproc    # Should show 4 CPUs
   ```

3. **Restart Services**
   ```bash
   cd /opt/legal-doc-processor
   
   # Load environment
   set -a && source .env && set +a
   
   # Start all workers with new memory limits
   ./scripts/start_all_workers.sh
   
   # Verify workers
   ./scripts/monitoring/monitor_workers.sh
   ```

4. **Update Worker Configuration** (optional optimization)
   ```bash
   # Edit worker memory limits in start_all_workers.sh
   # With 16GB, you can increase:
   # OCR: 800MB → 1500MB
   # Entity: 600MB → 1000MB
   # Batch workers: Add more concurrency
   ```

### Important Warnings

⚠️ **Public IP Will Change!** 
- The instance will get a NEW public IP address
- Update all references to the old IP
- Consider allocating an Elastic IP to avoid this in future

⚠️ **Downtime Expected**
- Total downtime: 5-10 minutes
- Plan for 15 minutes to be safe
- Notify team/users before starting

⚠️ **Cost Implications**
- t3.medium: $0.0416/hour → t3.xlarge: $0.1664/hour
- Monthly: ~$30 → ~$120 (4x increase)
- Review AWS bill after change

### Rollback Plan

If issues occur after resize:
```bash
# Stop instance
aws ec2 stop-instances --instance-ids i-0e431c454a7c3c6a1

# Change back to t3.medium
aws ec2 modify-instance-attribute \
  --instance-id i-0e431c454a7c3c6a1 \
  --instance-type "{\"Value\": \"t3.medium\"}"

# Start instance
aws ec2 start-instances --instance-ids i-0e431c454a7c3c6a1
```

### Alternative: Elastic IP Setup (Recommended)

To avoid IP changes in future:
```bash
# Allocate Elastic IP
aws ec2 allocate-address --domain vpc

# Associate with instance
aws ec2 associate-address \
  --instance-id i-0e431c454a7c3c6a1 \
  --allocation-id <ALLOCATION_ID>
```

### Verification Checklist

After resize, verify:
- [ ] Instance type is t3.xlarge
- [ ] Memory shows ~16 GB
- [ ] CPUs show 4
- [ ] All workers start successfully
- [ ] Can process documents without memory errors
- [ ] Database connections work
- [ ] Redis connections work
- [ ] S3 access works

### Support Resources

- AWS Instance Resize Docs: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-resize.html
- t3 Instance Types: https://aws.amazon.com/ec2/instance-types/t3/
- Instance Type Compatibility: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/resize-limitations.html

---

**Created**: 2025-06-12
**For**: Legal Document Processor EC2 Resize
**Current**: t3.medium (2 vCPU, 3.7 GB) → t3.xlarge (4 vCPU, 16 GB)