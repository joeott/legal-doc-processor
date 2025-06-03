# Context 245: Explicit Database Connectivity Error Documentation

## The Exact Error We Are Experiencing

### Primary Error Manifestation

When any script attempts to connect to the RDS PostgreSQL database, we encounter one of three specific errors:

#### Error 1: SSH Tunnel Connection Timeout
```
psycopg2.OperationalError: could not connect to server: Connection timed out
    Is the server running on host "localhost" (127.0.0.1) and accepting
    TCP/IP connections on port 5433?
```

**Where it occurs:**
```python
# scripts/db.py, line 24-32
def get_engine():
    """Get or create the SQLAlchemy engine with connection pooling."""
    global _engine
    if _engine is None:
        database_url = os.getenv('DATABASE_URL')  # postgresql://ottlaw_admin:***@localhost:5433/ottlaw_legal_db
        
        engine_config = {**DB_POOL_CONFIG}
        
        _engine = create_engine(database_url, **engine_config)  # <-- FAILS HERE
```

#### Error 2: SSH Tunnel Dies During Operation
```
psycopg2.OperationalError: server closed the connection unexpectedly
    This probably means the server terminated abnormally
    before or while processing the request.
```

**Where it occurs:**
```python
# During any database operation after initial connection
# Example from scripts/pdf_tasks.py, line 145-150
session = Session()
pdf_doc = session.query(PDFDocument).filter_by(
    document_uuid=document_uuid
).first()  # <-- SSH tunnel dies here, connection lost
```

#### Error 3: Authentication Failure Through Tunnel
```
psycopg2.OperationalError: FATAL:  password authentication failed for user "ottlaw_admin"
FATAL:  password authentication failed for user "ottlaw_admin"
```

**Where it occurs:**
```python
# When SSH tunnel is active but PostgreSQL rejects credentials
# Even though the same credentials work via direct psql command
```

### The Exact Connection Flow That Fails

1. **Script starts** → Imports `db.py`
2. **First database operation** → Calls `get_engine()`
3. **SQLAlchemy attempts connection** → Uses `DATABASE_URL=postgresql://ottlaw_admin:***@localhost:5433/ottlaw_legal_db`
4. **Connection attempt** → Tries to reach localhost:5433 (SSH tunnel)
5. **FAILURE POINT** → Either:
   - No SSH tunnel running (Error 1)
   - SSH tunnel dies immediately (Error 2)  
   - PostgreSQL rejects auth through tunnel (Error 3)

### Specific Code Paths Affected

#### 1. Celery Worker Initialization
```python
# scripts/celery_app.py, lines 89-92
# Worker cannot start because it tries to verify database connection
from scripts.db import get_engine
engine = get_engine()  # <-- Worker crashes here
```

#### 2. PDF Processing Task
```python
# scripts/pdf_tasks.py, line 123
@celery_app.task(bind=True, name='pdf_tasks.process_pdf_document')
def process_pdf_document(self, document_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process a PDF document through the extraction pipeline."""
    Session = get_session()  # <-- Task fails immediately
```

#### 3. CLI Import Command
```python
# scripts/cli/import.py, line 78
def create_import_session(project_uuid: str, manifest_file: str):
    """Create a new import session."""
    session = Session()  # <-- CLI command fails
```

#### 4. Entity Service Operations
```python
# scripts/entity_service.py, line 43
class EntityService:
    def __init__(self):
        self.engine = get_engine()  # <-- Service initialization fails
        self.Session = sessionmaker(bind=self.engine)
```

### The Root Cause

The fundamental issue is architectural:

1. **RDS Configuration**: 
   - Endpoint: `ottlaw-legal-rds.c3cr8vdq90jk.us-east-1.rds.amazonaws.com`
   - Port: 5432
   - VPC: Private subnet only
   - Public accessibility: Disabled

2. **Access Method**:
   - Must use SSH tunnel through bastion host
   - Bastion: `ec2-54-145-68-133.compute-1.amazonaws.com`
   - Tunnel command: `ssh -L 5433:ottlaw-legal-rds.c3cr8vdq90jk.us-east-1.rds.amazonaws.com:5432 -i ~/.ssh/legal-doc-processor-bastion.pem ubuntu@ec2-54-145-68-133.compute-1.amazonaws.com`

3. **Why It Fails**:
   - SSH tunnels are not designed for persistent database connections
   - SQLAlchemy connection pooling conflicts with SSH tunnel lifecycle
   - Multiple Celery workers overwhelm single SSH tunnel
   - No automatic tunnel restart on failure

### Exact Impact on Production

```python
# What should happen:
document_data = {...}
result = process_pdf_document.delay(document_data)  # Queued to Celery
# ... worker processes document ...
# ... stores results in database ...

# What actually happens:
document_data = {...}
result = process_pdf_document.delay(document_data)  # Queued to Celery
# Worker picks up task
# Worker tries to connect to database
# ERROR: Connection timeout/SSH tunnel failure
# Task marked as FAILED
# No data is processed or stored
```

### Verification Commands That Show The Error

```bash
# Test 1: Direct script execution
$ python -c "from scripts.db import get_engine; engine = get_engine(); print('Connected')"
# Result: psycopg2.OperationalError: could not connect to server: Connection timed out

# Test 2: Celery worker startup
$ celery -A scripts.celery_app worker --loglevel=info
# Result: [ERROR/MainProcess] consumer: Cannot connect to database

# Test 3: CLI command
$ python scripts/cli/admin.py verify-services
# Result: Database connection failed: could not connect to server

# Test 4: With SSH tunnel running
$ ssh -L 5433:ottlaw-legal-rds.c3cr8vdq90jk.us-east-1.rds.amazonaws.com:5432 -i ~/.ssh/legal-doc-processor-bastion.pem ubuntu@ec2-54-145-68-133.compute-1.amazonaws.com
# In another terminal:
$ python -c "from scripts.db import get_engine; engine = get_engine(); print('Connected')"
# Result: Works briefly, then "server closed the connection unexpectedly"
```

### Why Standard Solutions Don't Work

1. **Connection Pooling**: Makes SSH tunnel die faster due to multiple connections
2. **Retry Logic**: SSH tunnel doesn't recover, retries just fail again
3. **Keep-Alive**: PostgreSQL keep-alive packets don't traverse SSH tunnel properly
4. **Public RDS Access**: Not possible due to firm security requirements

### The Precise Problem Statement

**Our production scripts cannot maintain stable database connections because:**
1. RDS is only accessible via SSH tunnel through bastion host
2. SSH tunnels are inherently unstable for database connection pooling
3. Multiple Celery workers cannot share a single SSH tunnel
4. There is no automatic mechanism to restart failed SSH tunnels
5. Even when tunnel is active, PostgreSQL authentication fails intermittently

**This results in:**
- 0% success rate for document processing
- Complete inability to store extracted data
- Celery workers crashing on startup
- No visibility into processing status

**The error is not intermittent - it is consistent and prevents all database operations.**