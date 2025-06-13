# Context 509: Optimal EC2 Specifications Analysis for Legal Document Processing

## Date: 2025-06-12
## Current Hardware Analysis and Recommendations

## Current Setup (t3.medium)

### Specifications
- **Instance Type**: t3.medium
- **vCPUs**: 2 (Intel Xeon Platinum 8259CL @ 2.50GHz)
- **Memory**: 3.7 GB (3836 MB)
- **Current Usage**: 2.9 GB used (78% baseline, peaks at 88%+)
- **Storage**: 29 GB (33% used - 9.4 GB)
- **Architecture**: 2 threads, 1 core per socket

### Current Memory Allocation

#### System Overhead
- OS and system services: ~700 MB
- Node.js processes (Cursor IDE): ~1.5 GB (37% of total!)
- Available for application: ~1.5 GB

#### Worker Memory Requirements (from configuration)
- OCR Worker: 800 MB (Textract operations)
- Text Worker: 2 × 400 MB = 800 MB (chunking)
- Entity Worker: 600 MB (NLP/AI operations)
- Graph Worker: 400 MB
- Default Worker: 300 MB
- Batch Workers: 3 × 300 MB = 900 MB
- **Total Worker Requirements**: 3.8 GB

### Current Issues

1. **Memory Exhaustion**
   - Circuit breaker triggers at 88% memory usage
   - Workers require 3.8 GB but only 1.5 GB available
   - Node.js processes consuming 37% of system memory
   - Textract processing blocked due to high memory

2. **Large Document Processing**
   - Largest document in batch: 629 MB (Acuity Settlement Agreement)
   - Textract requires document + processing overhead in memory
   - Current setup cannot handle documents > 100 MB reliably

3. **Concurrent Processing Limitations**
   - Cannot run all 8 workers simultaneously
   - Batch processing fails due to memory constraints
   - Pipeline bottlenecked by memory, not CPU

## Memory Requirements Analysis

### Per-Stage Memory Requirements

1. **OCR/Textract Stage**
   - Base: 800 MB
   - Large PDF (600 MB): +1.2 GB for processing
   - Total peak: 2 GB per large document

2. **Entity Extraction**
   - OpenAI API calls: 600 MB
   - Spacy models: +400 MB when loaded
   - Total: 1 GB

3. **Database Operations**
   - Connection pooling: 200 MB
   - Query buffers: 300 MB
   - Total: 500 MB

4. **Redis Caching**
   - Client connections: 100 MB
   - Cache data: 200-500 MB depending on load
   - Total: 600 MB

### Total Application Requirements
- **Minimum**: 6 GB (all workers + services)
- **Recommended**: 8 GB (with headroom)
- **Optimal**: 16 GB (large document processing)

## EC2 Instance Recommendations

### Option 1: t3.large (Minimum Viable)
- **vCPUs**: 2
- **Memory**: 8 GB
- **Network**: Up to 5 Gbps
- **Cost**: ~$0.0832/hour
- **Pros**: 
  - Sufficient for normal operations
  - Can run all workers
  - 2x current memory
- **Cons**: 
  - Still tight for large documents
  - Limited concurrent processing

### Option 2: t3.xlarge (Recommended)
- **vCPUs**: 4
- **Memory**: 16 GB
- **Network**: Up to 5 Gbps
- **Cost**: ~$0.1664/hour
- **Pros**:
  - Comfortable memory headroom
  - Can process large documents
  - Better CPU for parallel operations
  - Room for scaling workers
- **Cons**:
  - 2x the cost

### Option 3: m5.xlarge (Production Optimal)
- **vCPUs**: 4
- **Memory**: 16 GB
- **Network**: Up to 10 Gbps
- **Cost**: ~$0.192/hour
- **Pros**:
  - Consistent performance (no burst credits)
  - Better network for S3 operations
  - EBS optimized
  - Production-grade reliability
- **Cons**:
  - Higher cost
  - Over-provisioned for light loads

### Option 4: m5.2xlarge (High Volume)
- **vCPUs**: 8
- **Memory**: 32 GB
- **Network**: Up to 10 Gbps
- **Cost**: ~$0.384/hour
- **Pros**:
  - Can process multiple large documents
  - Support 2x worker processes
  - Future-proof for growth
- **Cons**:
  - Significant cost increase
  - Underutilized for current load

## Optimization Recommendations

### Immediate Actions (Current t3.medium)
1. **Remove Non-Essential Processes**
   - Kill Node.js/Cursor processes: `pkill -f node`
   - Frees up 1.5 GB (40% of total memory)

2. **Adjust Worker Configuration**
   - Reduce worker concurrency
   - Lower memory limits to fit available RAM
   - Implement worker rotation schedule

3. **Implement Document Size Limits**
   - Reject documents > 100 MB on t3.medium
   - Queue large documents for off-peak processing

### Migration Path

1. **Short Term**: Upgrade to t3.large
   - Immediate relief from memory pressure
   - Minimal configuration changes
   - Can process current document set

2. **Medium Term**: Move to t3.xlarge or m5.xlarge
   - Full pipeline capacity
   - Large document support
   - Better cost/performance ratio

3. **Long Term**: Implement Auto-Scaling
   - Use m5.large as baseline
   - Scale to m5.xlarge for large batches
   - Implement spot instances for batch processing

## Cost-Benefit Analysis

| Instance | Memory | Monthly Cost* | Documents/Day** | Cost/1K Docs |
|----------|--------|--------------|-----------------|--------------|
| t3.medium | 3.7 GB | $60 | 50 | $40 |
| t3.large | 8 GB | $120 | 200 | $20 |
| t3.xlarge | 16 GB | $240 | 500 | $16 |
| m5.xlarge | 16 GB | $276 | 600 | $15 |

*Based on 24/7 operation
**Estimated based on average document size and processing time

## Final Recommendation

**For Immediate Production Use: t3.xlarge**

Rationale:
- 4x current memory resolves all memory issues
- 2x CPU cores improve concurrent processing
- Handles largest documents (600+ MB)
- Best balance of cost and capability
- Allows full worker configuration
- Provides growth headroom

**Alternative for Cost Optimization: t3.large**
- If willing to limit large document processing
- Requires optimized worker configuration
- Suitable for documents < 200 MB

## Implementation Steps

1. **Prepare for Migration**
   ```bash
   # Create AMI snapshot of current instance
   # Document current configuration
   # Plan maintenance window
   ```

2. **Resize Instance**
   ```bash
   # Stop instance
   # Change instance type
   # Start instance
   # Verify services
   ```

3. **Optimize Configuration**
   ```bash
   # Adjust worker memory limits
   # Increase concurrency where appropriate
   # Update circuit breaker thresholds
   ```

4. **Validate Performance**
   ```bash
   # Process test batch
   # Monitor memory usage
   # Verify large document handling
   ```