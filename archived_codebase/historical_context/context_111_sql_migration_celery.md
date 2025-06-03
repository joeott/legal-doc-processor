# Celery Migration - Database Update Instructions

## How to Apply the Celery Database Changes

### Option 1: Using Supabase Dashboard (Recommended)

1. **Login to Supabase Dashboard**
   - Go to your Supabase project dashboard
   - Navigate to the SQL Editor section

2. **Run the Migration Script**
   - Copy the entire contents of `apply_celery_migrations.sql`
   - Paste into the SQL Editor
   - Click "Run" or press Cmd/Ctrl + Enter

3. **Verify the Changes**
   - The script includes verification queries at the end
   - You should see:
     - 2 new columns listed (celery_task_id, celery_status)
     - No processing-related triggers
     - Document status distribution

### Option 2: Using psql Command Line

```bash
# If you have the database URL
psql $DATABASE_URL < apply_celery_migrations.sql

# Or with connection parameters
psql -h your-db-host -U your-db-user -d your-db-name < apply_celery_migrations.sql
```

### Option 3: Using Supabase CLI

```bash
# If you have Supabase CLI installed
supabase db push < apply_celery_migrations.sql
```

## What the Migration Does

1. **Adds Two New Columns to source_documents**:
   - `celery_task_id` (VARCHAR 255) - Stores the Celery task ID
   - `celery_status` (VARCHAR 50) - Tracks document progress through Celery

2. **Creates Indexes** for performance:
   - Index on celery_task_id for task lookups
   - Index on celery_status for monitoring queries

3. **Removes Database Triggers** that interfere with Celery:
   - Drops triggers that auto-update processing status
   - Removes queue-related triggers
   - Keeps only timestamp update triggers

## Post-Migration Verification

After running the migration, verify success by checking:

1. **New Columns Exist**:
   ```sql
   SELECT column_name FROM information_schema.columns 
   WHERE table_name = 'source_documents' 
   AND column_name IN ('celery_task_id', 'celery_status');
   ```
   Should return 2 rows.

2. **No Processing Triggers Remain**:
   ```sql
   SELECT trigger_name FROM information_schema.triggers 
   WHERE trigger_schema = 'public'
   AND trigger_name LIKE '%process%';
   ```
   Should return 0 rows.

3. **Run Verification Script**:
   ```bash
   python scripts/verify_celery_migration.py
   ```

## Next Steps After Migration

1. **Start Celery Workers**:
   ```bash
   ./scripts/start_celery_workers.sh
   ```

2. **Test Document Processing**:
   ```bash
   python scripts/live_document_test.py
   ```

3. **Monitor Progress**:
   ```bash
   python scripts/standalone_pipeline_monitor.py
   ```

## Rollback (If Needed)

To rollback the changes:

```sql
-- Remove Celery columns
ALTER TABLE source_documents 
DROP COLUMN IF EXISTS celery_task_id,
DROP COLUMN IF EXISTS celery_status;

-- Drop indexes
DROP INDEX IF EXISTS idx_source_documents_celery_task_id;
DROP INDEX IF EXISTS idx_source_documents_celery_status;

-- Note: Triggers would need to be recreated from backups
```

## Support

If you encounter any issues:
1. Check the Supabase logs for detailed error messages
2. Verify your database user has ALTER TABLE permissions
3. Ensure no active connections are locking the tables