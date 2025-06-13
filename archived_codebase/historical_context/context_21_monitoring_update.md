# Monitoring System Update and Trigger Alignment

## Executive Summary

The current monitoring system (`live_monitor.py`) attempts to create legacy triggers that conflict with the modernized trigger architecture implemented in context_19. This document provides a comprehensive approach to update the monitoring system while maintaining high visibility of all document processing pipeline subprocesses, ensuring compatibility with the modernized trigger system, and cleaning up any legacy components that may persist in the database.

## Current Monitoring System Analysis

### Existing Capabilities
The monitoring system provides excellent visibility across the document processing pipeline:

1. **Real-Time Dashboard Features**:
   - Queue statistics (pending, processing, completed, failed)
   - OCR method statistics (Mistral, Qwen2-VL, other)
   - Active processor tracking
   - Recent document processing status
   - Processing time tracking
   - Error monitoring
   - Retry count display

2. **Notification System**:
   - PostgreSQL LISTEN/NOTIFY for real-time updates
   - Direct database connection for immediate notifications
   - Fallback to periodic polling if notifications unavailable

3. **Rich UI Components**:
   - Live-updating tables and panels
   - Color-coded status indicators
   - Processing time calculations
   - Comprehensive error display

### Critical Issues Identified

#### 1. Legacy Trigger Creation Conflict
**Problem**: The monitoring system creates legacy triggers that conflict with modernized triggers:

```python
# Lines 127-145: Creates OLD function
CREATE OR REPLACE FUNCTION notify_document_status_change()

# Lines 151-171: Creates OLD triggers  
CREATE TRIGGER document_status_change_trigger
CREATE TRIGGER queue_status_change_trigger
```

#### 2. Database Analysis Results
Current trigger state analysis reveals:

**Modernized Triggers Present** ✅:
- `modernized_queue_status_change_trigger` on `document_processing_queue`
- `modernized_document_status_change_trigger` on `source_documents` 
- `modernized_sync_queue_on_document_update` on `source_documents`
- `modernized_create_queue_entry_trigger` on `source_documents`

**Legacy Function Status**: No conflicting legacy `notify_document_status_change()` function currently exists in database, indicating the monitoring system may not have been run recently or the function was cleaned up.

**Risk**: If monitoring system runs, it will create conflicting triggers.

## Modernized Monitoring Solution

### Strategy: Leverage Existing Modernized Triggers

Instead of creating its own triggers, the monitoring system should leverage the existing modernized trigger system through the notification channel that the modernized triggers already support.

### Updated Architecture Approach

#### Option 1: Use Modernized Trigger Notifications (Recommended)
**Concept**: Modify monitoring to listen to notifications from existing modernized triggers rather than creating its own.

**Implementation Steps**:
1. Remove legacy trigger creation from monitoring system
2. Create monitoring-specific notification listener that works with modernized triggers
3. Update notification payload parsing to handle modernized trigger format

#### Option 2: Polling-Only Approach (Fallback)
**Concept**: Remove notification system entirely, rely on periodic polling.

**Pros**: Simple, no trigger conflicts
**Cons**: Less real-time responsiveness

### Recommended Implementation: Option 1

## Detailed Implementation Plan

### Phase 1: Database Cleanup and Verification

#### 1.1 Check for Existing Legacy Components
```sql
-- Check for any legacy triggers that might exist
SELECT trigger_name, event_object_table 
FROM information_schema.triggers 
WHERE trigger_name IN ('document_status_change_trigger', 'queue_status_change_trigger')
  AND event_object_table IN ('source_documents', 'document_processing_queue');

-- Check for legacy functions
SELECT routine_name 
FROM information_schema.routines 
WHERE routine_name = 'notify_document_status_change';
```

#### 1.2 Clean Up Any Legacy Components (if found)
```sql
-- Remove legacy triggers if they exist
DROP TRIGGER IF EXISTS document_status_change_trigger ON source_documents;
DROP TRIGGER IF EXISTS queue_status_change_trigger ON document_processing_queue;

-- Remove legacy function if it exists  
DROP FUNCTION IF EXISTS notify_document_status_change();
```

### Phase 2: Modernized Monitoring Integration

#### 2.1 Update Notification Channel Setup

**Current Problematic Code** (lines 120-179):
```python
def setup_notification_channel(self):
    # REMOVE: Legacy trigger creation
    # ADD: Modernized notification listener
```

**New Implementation**:
```python
def setup_notification_channel(self):
    """Set up PostgreSQL notification channel to work with modernized triggers."""
    try:
        cursor = self.db_conn.cursor()
        
        # Create a dedicated monitoring notification function
        # This works alongside the modernized triggers, not replacing them
        monitoring_function_sql = """
        CREATE OR REPLACE FUNCTION monitoring_notify_status_change()
        RETURNS TRIGGER AS $$
        BEGIN
          -- Send notification specifically for monitoring dashboard
          PERFORM pg_notify(
            'document_status_changes',
            json_build_object(
              'table', TG_TABLE_NAME,
              'id', NEW.id,
              'status', CASE 
                WHEN TG_TABLE_NAME = 'source_documents' THEN NEW.initial_processing_status
                WHEN TG_TABLE_NAME = 'document_processing_queue' THEN NEW.status
                ELSE 'unknown'
                END,
              'document_uuid', COALESCE(NEW.document_uuid, NEW.source_document_uuid),
              'timestamp', NOW(),
              'monitoring_event', true
            )::text
          );
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
        cursor.execute(monitoring_function_sql)
        
        # Create monitoring-specific triggers (with unique names to avoid conflicts)
        # These supplement the modernized triggers for monitoring purposes
        source_docs_monitor_trigger_sql = """
        CREATE TRIGGER monitoring_source_docs_trigger
        AFTER UPDATE OF initial_processing_status ON source_documents
        FOR EACH ROW
        EXECUTE FUNCTION monitoring_notify_status_change();
        """
        
        queue_monitor_trigger_sql = """
        CREATE TRIGGER monitoring_queue_trigger  
        AFTER UPDATE OF status ON document_processing_queue
        FOR EACH ROW
        EXECUTE FUNCTION monitoring_notify_status_change();
        """
        
        # Drop existing monitoring triggers if they exist
        try:
            cursor.execute("DROP TRIGGER IF EXISTS monitoring_source_docs_trigger ON source_documents;")
            cursor.execute("DROP TRIGGER IF EXISTS monitoring_queue_trigger ON document_processing_queue;")
        except:
            pass
            
        # Create new monitoring triggers
        cursor.execute(source_docs_monitor_trigger_sql)
        cursor.execute(queue_monitor_trigger_sql)
        
        # Listen to the notification channel
        cursor.execute("LISTEN document_status_changes;")
        logger.info("Modernized monitoring notification channel set up successfully.")
        
    except Exception as e:
        logger.error(f"Failed to set up modernized notification channel: {e}")
        logger.info("Will use polling instead of notifications.")
```

#### 2.2 Enhanced Notification Processing

**Update notification handling** to process enhanced payload:
```python
def check_for_notifications(self):
    """Check for database notifications with enhanced payload processing."""
    if not self.db_conn:
        return False
        
    try:
        if select.select([self.db_conn], [], [], 0) == ([], [], []):
            return False
            
        self.db_conn.poll()
        notification_received = False
        
        while self.db_conn.notifies:
            notify = self.db_conn.notifies.pop()
            try:
                payload = json.loads(notify.payload)
                logger.info(f"Notification: {payload.get('table')} ID {payload.get('id')} -> {payload.get('status')}")
                
                # Update local cache if we have the document
                if payload.get('table') == 'source_documents':
                    self.update_document_status(payload.get('id'), None, payload.get('status'))
                elif payload.get('table') == 'document_processing_queue':
                    self.update_document_status(None, payload.get('id'), payload.get('status'))
                    
                notification_received = True
                
            except json.JSONDecodeError:
                logger.warning(f"Invalid notification payload: {notify.payload}")
                notification_received = True
                
        return notification_received
        
    except Exception as e:
        logger.error(f"Error checking notifications: {e}")
        
    return False
```

### Phase 3: Enhanced Monitoring Features

#### 3.1 Pipeline Stage Visibility Enhancement

Add detailed subprocess monitoring to capture all pipeline stages:

```python
def fetch_pipeline_stage_stats(self):
    """Fetch detailed statistics about document processing stages."""
    if not self.supabase:
        return
        
    try:
        # Get detailed processing step information
        response = self.supabase.table("document_processing_queue").select(
            "processing_step, status, COUNT(*)"
        ).execute()
        
        # Process into stage statistics
        self.pipeline_stats = {}
        if response.data:
            for item in response.data:
                step = item.get('processing_step', 'unknown')
                status = item.get('status', 'unknown')
                count = item.get('count', 0)
                
                if step not in self.pipeline_stats:
                    self.pipeline_stats[step] = {}
                self.pipeline_stats[step][status] = count
                
    except Exception as e:
        logger.error(f"Failed to fetch pipeline stage stats: {e}")

def create_pipeline_stages_table(self):
    """Create a rich table showing pipeline stage breakdown."""
    table = Table(title="Document Processing Pipeline Stages")
    
    table.add_column("Processing Step", style="bold")
    table.add_column("Pending", style="yellow")
    table.add_column("Processing", style="blue") 
    table.add_column("Completed", style="green")
    table.add_column("Failed", style="red")
    
    for step, statuses in self.pipeline_stats.items():
        table.add_row(
            step,
            str(statuses.get('pending', 0)),
            str(statuses.get('processing', 0)),
            str(statuses.get('completed', 0)),
            str(statuses.get('failed', 0))
        )
        
    return table
```

#### 3.2 Error Analysis Enhancement

Add comprehensive error tracking and analysis:

```python
def fetch_error_analysis(self):
    """Fetch and analyze error patterns."""
    if not self.supabase:
        return
        
    try:
        # Get recent errors from both tables
        doc_errors = self.supabase.table("source_documents").select(
            "id, original_file_name, error_message, initial_processing_status"
        ).not_.is_("error_message", "null").order("id", desc=True).limit(20).execute()
        
        queue_errors = self.supabase.table("document_processing_queue").select(
            "id, source_document_uuid, error_message, status, retry_count"
        ).not_.is_("error_message", "null").order("id", desc=True).limit(20).execute()
        
        # Analyze error patterns
        self.error_patterns = {}
        
        # Process document errors
        if doc_errors.data:
            for error in doc_errors.data:
                msg = error.get('error_message', '')
                error_type = self.categorize_error(msg)
                self.error_patterns[error_type] = self.error_patterns.get(error_type, 0) + 1
        
        # Process queue errors  
        if queue_errors.data:
            for error in queue_errors.data:
                msg = error.get('error_message', '')
                error_type = self.categorize_error(msg)
                self.error_patterns[error_type] = self.error_patterns.get(error_type, 0) + 1
                
    except Exception as e:
        logger.error(f"Failed to fetch error analysis: {e}")

def categorize_error(self, error_message):
    """Categorize error messages into types."""
    error_msg = error_message.lower()
    
    if 'ocr' in error_msg or 'extraction' in error_msg:
        return 'OCR/Extraction'
    elif 'timeout' in error_msg or 'stall' in error_msg:
        return 'Timeout/Stall'
    elif 's3' in error_msg or 'download' in error_msg:
        return 'File Access'
    elif 'api' in error_msg or 'rate limit' in error_msg:
        return 'API Issues'
    elif 'database' in error_msg or 'sql' in error_msg:
        return 'Database'
    else:
        return 'Other'
```

### Phase 4: Testing and Validation

#### 4.1 Trigger Conflict Testing
```bash
# Test script to verify no trigger conflicts
python -c "
import sys
sys.path.append('monitoring')
from live_monitor import DocumentProcessMonitor
monitor = DocumentProcessMonitor()
print('Monitor initialization completed without conflicts')
"
```

#### 4.2 Notification System Testing
```python
# Add to monitoring script for testing
def test_notification_system(self):
    \"\"\"Test that notifications are received properly.\"\"\"
    if not self.db_conn:
        logger.warning("No direct database connection for notification testing")
        return
        
    try:
        cursor = self.db_conn.cursor()
        
        # Send test notification
        cursor.execute("SELECT pg_notify('document_status_changes', 'test_payload');")
        
        # Check if received
        time.sleep(0.1)
        if self.check_for_notifications():
            logger.info("✅ Notification system working correctly")
        else:
            logger.warning("❌ Notification system not receiving messages")
            
    except Exception as e:
        logger.error(f"Notification system test failed: {e}")
```

## Database Cleanup Commands

### Pre-Implementation Cleanup Script

```sql
-- Clean up any existing legacy monitoring components
DROP TRIGGER IF EXISTS document_status_change_trigger ON source_documents;
DROP TRIGGER IF EXISTS queue_status_change_trigger ON document_processing_queue;
DROP FUNCTION IF EXISTS notify_document_status_change();

-- Verify modernized triggers are intact
SELECT 
    trigger_name, 
    event_object_table,
    action_statement 
FROM information_schema.triggers 
WHERE trigger_name LIKE 'modernized_%'
  AND event_object_table IN ('source_documents', 'document_processing_queue');

-- Expected results should show:
-- modernized_document_status_change_trigger | source_documents | EXECUTE FUNCTION modernized_notify_status_change()
-- modernized_queue_status_change_trigger | document_processing_queue | EXECUTE FUNCTION modernized_notify_status_change()
-- modernized_sync_queue_on_document_update | source_documents | EXECUTE FUNCTION modernized_sync_document_queue_status()
-- modernized_create_queue_entry_trigger | source_documents | EXECUTE FUNCTION modernized_create_queue_entry()
```

## Implementation Timeline

### Phase 1: Database Cleanup (30 minutes)
1. Run database analysis queries
2. Execute cleanup commands if legacy components found
3. Verify modernized triggers are intact

### Phase 2: Code Updates (2-3 hours)
1. Update `setup_notification_channel()` method
2. Enhance notification processing
3. Add pipeline stage monitoring
4. Implement error analysis features

### Phase 3: Testing (1-2 hours)
1. Test monitoring system startup
2. Verify notification system functionality
3. Test dashboard updates with live data
4. Validate no trigger conflicts

### Phase 4: Deployment (30 minutes)
1. Deploy updated monitoring script
2. Monitor for any issues
3. Verify all dashboard features working

## Risk Mitigation

### High Risk Items
1. **Trigger Conflicts**: Carefully test before deployment
2. **Notification Disruption**: Have polling fallback ready
3. **Dashboard Functionality**: Ensure all features work after update

### Mitigation Strategies
1. **Comprehensive Testing**: Test all components before deployment
2. **Gradual Rollout**: Test in development environment first
3. **Monitoring**: Watch for errors during initial deployment
4. **Rollback Plan**: Keep original version available for quick revert

## Success Criteria

### Immediate Success
- ✅ Monitoring system starts without creating trigger conflicts
- ✅ Real-time notifications continue working
- ✅ Dashboard displays all information correctly
- ✅ No impact on existing modernized trigger functionality

### Enhanced Success
- ✅ New pipeline stage visibility features working
- ✅ Enhanced error analysis providing insights
- ✅ Improved monitoring responsiveness
- ✅ No performance degradation

## Conclusion

The monitoring system requires updates to align with the modernized trigger architecture while maintaining its excellent visibility features. The recommended approach leverages existing modernized triggers through dedicated monitoring notifications, avoiding conflicts while preserving real-time capabilities.

**Critical Action**: Execute database cleanup before implementing code changes to prevent any trigger conflicts.

**Strategic Benefit**: Updated monitoring system will work harmoniously with modernized triggers while providing enhanced visibility into the document processing pipeline.