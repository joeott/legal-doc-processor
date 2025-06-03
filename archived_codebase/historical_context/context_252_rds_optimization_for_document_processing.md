# RDS Optimization for Legal Document Processing Pipeline

## Overview

This document provides comprehensive guidance for optimizing AWS RDS PostgreSQL to meet the specific needs of the legal document processing pipeline. The recommendations are based on analysis of the actual processing flow, data patterns, and performance requirements.

## System Characteristics

### Workload Profile
- **Type**: Write-heavy OLTP with batch processing characteristics
- **Write/Read Ratio**: Approximately 70% writes, 30% reads during active processing
- **Data Growth**: Multiplicative - each document generates 1000s of child records
- **Processing Pattern**: Burst processing with sustained high write throughput

### Data Volume Metrics (Per Document)
- Source Documents: 1 record
- Document Chunks: 100-500 records (1000 chars each, 200 char overlap)
- Entity Mentions: 200-2000 records
- Canonical Entities: 50-200 unique entities
- Relationships: 500-5000 records
- Processing History: Multiple status updates

## RDS Configuration Recommendations

### 1. Instance Selection

**Recommended Instance Class**: db.r6g.xlarge or db.r6g.2xlarge

**Rationale**:
- Memory-optimized (r6g) for large buffer cache
- 4-8 vCPUs handle concurrent Celery workers
- 32-64 GB RAM supports write-heavy workload
- Graviton2 processors offer 40% better price/performance
- Enhanced networking for high throughput operations

### 2. Storage Configuration

**Storage Type**: General Purpose SSD (gp3)

**Configuration**:
```yaml
Initial Size: 500 GB
Max Size: 2 TB (auto-scaling enabled)
Provisioned IOPS: 12,000-16,000
Provisioned Throughput: 500-750 MB/s
```

**Rationale**:
- GP3 allows independent IOPS/throughput scaling
- High IOPS critical for write-heavy workload
- Throughput supports bulk insert operations
- Auto-scaling prevents storage-full events

### 3. PostgreSQL Parameter Optimization

```sql
-- Memory Configuration (for 64GB instance)
shared_buffers = '16GB'                    # 25% of RAM for buffer cache
effective_cache_size = '48GB'              # 75% of RAM for query planning
work_mem = '256MB'                         # Per-operation memory
maintenance_work_mem = '2GB'               # For VACUUM, CREATE INDEX

-- Write Performance
wal_buffers = '64MB'                       # WAL write buffer
max_wal_size = '4GB'                       # WAL size before checkpoint
min_wal_size = '1GB'                       # WAL retention
checkpoint_completion_target = 0.9         # Spread checkpoint I/O
checkpoint_timeout = '15min'               # Force checkpoint interval

-- Connection Management
max_connections = 200                      # Support worker pool + monitoring
superuser_reserved_connections = 5         # Admin access guarantee

-- Parallel Query Execution
max_worker_processes = 8                   # Total background workers
max_parallel_workers_per_gather = 4        # Per-query parallelism
max_parallel_workers = 8                   # Total parallel workers

-- Autovacuum Tuning (Critical for write-heavy)
autovacuum_max_workers = 4                 # Concurrent vacuum workers
autovacuum_naptime = '30s'                 # Check interval
autovacuum_vacuum_scale_factor = 0.1       # 10% dead tuples trigger
autovacuum_analyze_scale_factor = 0.05     # 5% change triggers analyze
autovacuum_vacuum_cost_limit = 1000        # Increased vacuum speed

-- Logging and Monitoring
log_min_duration_statement = 1000          # Log queries > 1 second
log_checkpoints = on                       # Monitor checkpoint performance
log_connections = on                       # Track connection patterns
log_disconnections = on                    # Track connection lifecycle
log_lock_waits = on                        # Identify lock contention
log_temp_files = 0                         # Log all temp file usage

-- Query Planning
random_page_cost = 1.1                     # SSD-optimized
effective_io_concurrency = 200             # SSD can handle parallel I/O
```

### 4. Critical Index Strategy

```sql
-- Document Processing Indexes
CREATE INDEX idx_chunks_doc_uuid ON document_chunks(document_uuid);
CREATE INDEX idx_chunks_sequence ON document_chunks(document_uuid, chunk_index);

-- Entity Extraction Indexes
CREATE INDEX idx_entities_doc_uuid ON entity_mentions(document_uuid);
CREATE INDEX idx_entities_chunk_uuid ON entity_mentions(chunk_uuid);
CREATE INDEX idx_entities_canonical ON entity_mentions(canonical_entity_uuid) 
    WHERE canonical_entity_uuid IS NOT NULL;

-- Relationship Building Indexes
CREATE INDEX idx_relationships_source ON relationship_staging(source_id);
CREATE INDEX idx_relationships_target ON relationship_staging(target_id);
CREATE INDEX idx_relationships_doc ON relationship_staging(document_uuid);

-- Monitoring and Status Indexes
CREATE INDEX idx_docs_status ON source_documents(processing_status);
CREATE INDEX idx_docs_status_updated ON source_documents(processing_status, updated_at);
CREATE INDEX idx_docs_project ON source_documents(project_uuid) WHERE project_uuid IS NOT NULL;

-- Task Processing Indexes
CREATE INDEX idx_tasks_doc_status ON processing_tasks(document_uuid, status);
CREATE INDEX idx_tasks_created ON processing_tasks(created_at) WHERE status = 'pending';
```

### 5. Connection Pooling Architecture

**Recommended Setup**:
1. **Application-level pooling** (SQLAlchemy):
   ```python
   pool_size=20
   max_overflow=40
   pool_timeout=30
   pool_pre_ping=True
   ```

2. **External pooler** (PgBouncer on EC2):
   ```ini
   pool_mode = transaction
   max_client_conn = 500
   default_pool_size = 25
   reserve_pool_size = 5
   ```

### 6. High Availability Configuration

**Multi-AZ Deployment**:
- Synchronous standby in different AZ
- Automatic failover with <60 second RTO
- Zero data loss (RPO = 0)

**Read Replica Strategy**:
- 1-2 read replicas for reporting/monitoring
- Async replication with <5 second lag
- Dedicated replica for analytics queries

**Backup Configuration**:
```yaml
Automated Backups: Enabled
Backup Retention: 7 days
Backup Window: 3:00-4:00 AM UTC
Snapshot Copy: Cross-region for DR
Point-in-Time Recovery: Enabled
```

### 7. Monitoring and Alerting

**CloudWatch Enhanced Monitoring**:
- Granularity: 60 seconds
- OS metrics enabled

**Performance Insights**:
- Retention: 7 days (free tier)
- Top SQL tracking enabled

**Critical Alerts**:
```yaml
CPU Utilization: > 80% for 5 minutes
Write Latency: > 10ms for 5 minutes
Connection Count: > 150 connections
Storage Space: < 10% free
Replication Lag: > 30 seconds
Failed Connections: > 10 per minute
Deadlocks: > 5 per hour
Transaction Rollbacks: > 10% of commits
```

### 8. Performance Optimization Patterns

**Bulk Insert Optimization**:
```python
# Use COPY for large batches
COPY document_chunks FROM STDIN WITH (FORMAT csv)

# Or multi-value inserts
INSERT INTO entity_mentions (document_uuid, chunk_uuid, ...) 
VALUES (?,?,...), (?,?,...), ... -- Up to 1000 rows
```

**Transaction Management**:
```python
# Batch related operations
with db.begin():
    # Insert chunks
    # Insert entities
    # Update document status
```

**Query Optimization**:
- Use prepared statements for repeated queries
- Implement query result caching in Redis
- Partition large tables by document_uuid or date

### 9. Capacity Planning

**Scaling Triggers**:
- Storage: Auto-scale at 80% capacity
- CPU: Vertical scale at sustained 70%
- Connections: Add read replicas or pooling
- Write throughput: Consider Aurora PostgreSQL

**Growth Projections**:
```yaml
Documents/Day: 100-1000
Storage Growth: 1-10 GB/day
Connection Growth: Linear with workers
IOPS Growth: Linear with documents
```

### 10. Cost Optimization

**Strategies**:
1. Use Reserved Instances for 40-60% savings
2. Implement aggressive Redis caching to reduce database load
3. Use read replicas for expensive queries
4. Schedule non-critical maintenance during off-peak
5. Right-size based on actual metrics after 2 weeks

**Estimated Monthly Costs** (us-east-1):
- db.r6g.xlarge: ~$460/month
- Storage (500GB): ~$60/month
- IOPS (12,000): ~$480/month
- Backup Storage: ~$25/month
- **Total**: ~$1,025/month

## Implementation Checklist

1. [ ] Create custom parameter group with optimized settings
2. [ ] Launch RDS instance with Multi-AZ enabled
3. [ ] Configure security groups for worker access
4. [ ] Apply critical indexes after schema creation
5. [ ] Set up Enhanced Monitoring and Performance Insights
6. [ ] Configure CloudWatch alarms
7. [ ] Test failover scenarios
8. [ ] Implement connection pooling
9. [ ] Verify backup and recovery procedures
10. [ ] Load test with realistic document volumes

## Summary

This RDS configuration is optimized for the write-heavy, batch-oriented nature of legal document processing. The emphasis on write performance, connection management, and monitoring ensures the database can handle burst processing while maintaining reliability. Regular monitoring and adjustment based on actual workload patterns will further optimize performance and costs.