#!/usr/bin/env python3
# monitor_production_test.py

import time
import psycopg2
import os
from datetime import datetime

# Database connection from environment
db_url = os.environ.get('DATABASE_URL_DIRECT', 'postgresql://app_user:LegalDoc2025%5C%21Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require')

# Parse connection string
import urllib.parse
parsed = urllib.parse.urlparse(db_url)
db_config = {
    'host': parsed.hostname,
    'port': parsed.port,
    'database': parsed.path[1:].split('?')[0],
    'user': parsed.username,
    'password': urllib.parse.unquote(parsed.password) if parsed.password else None
}

def get_db_stats():
    """Get current database statistics"""
    conn = psycopg2.connect(**db_config)
    cur = conn.cursor()
    
    # Get counts for each table
    cur.execute("""
        SELECT 
            (SELECT COUNT(*) FROM source_documents) as documents,
            (SELECT COUNT(*) FROM source_documents WHERE raw_extracted_text IS NOT NULL) as with_text,
            (SELECT COUNT(*) FROM document_chunks) as chunks,
            (SELECT COUNT(*) FROM entity_mentions) as entities,
            (SELECT COUNT(*) FROM canonical_entities) as canonical,
            (SELECT COUNT(*) FROM relationship_staging) as relationships,
            (SELECT COUNT(*) FROM processing_tasks WHERE status = 'failed') as failed_tasks,
            (SELECT COUNT(*) FROM textract_jobs WHERE job_status = 'SUCCEEDED') as completed_jobs
    """)
    
    stats = cur.fetchone()
    cur.close()
    conn.close()
    
    return {
        'documents': stats[0],
        'with_text': stats[1],
        'chunks': stats[2],
        'entities': stats[3],
        'canonical': stats[4],
        'relationships': stats[5],
        'failed_tasks': stats[6],
        'completed_jobs': stats[7]
    }

def format_stats(stats, elapsed_time):
    """Format statistics for display"""
    docs_per_hour = (stats['documents'] / (elapsed_time / 3600)) if elapsed_time > 0 else 0
    text_rate = (stats['with_text'] / stats['documents'] * 100) if stats['documents'] > 0 else 0
    
    output = f"""
╔════════════════════════════════════════════════════════════╗
║           PRODUCTION TEST MONITORING DASHBOARD              ║
╚════════════════════════════════════════════════════════════╝

Time Elapsed: {elapsed_time/60:.1f} minutes

📄 DOCUMENTS
  Total Uploaded:     {stats['documents']:>6}
  With Extracted Text: {stats['with_text']:>6} ({text_rate:.1f}%)
  Throughput:         {docs_per_hour:>6.1f} docs/hour

📝 PROCESSING STAGES
  Text Chunks:        {stats['chunks']:>6}
  Entity Mentions:    {stats['entities']:>6}
  Canonical Entities: {stats['canonical']:>6}
  Relationships:      {stats['relationships']:>6}

🔄 JOBS
  Textract Completed: {stats['completed_jobs']:>6}
  Failed Tasks:       {stats['failed_tasks']:>6}

══════════════════════════════════════════════════════════════
"""
    return output

# Monitor loop
print("Starting production test monitoring...")
print("Press Ctrl+C to stop")
print()

start_time = time.time()
last_stats = None

try:
    while True:
        try:
            stats = get_db_stats()
            elapsed = time.time() - start_time
            
            # Clear screen and show updated stats
            os.system('clear' if os.name == 'posix' else 'cls')
            print(format_stats(stats, elapsed))
            
            # Show recent changes
            if last_stats:
                docs_delta = stats['documents'] - last_stats['documents']
                if docs_delta > 0:
                    print(f"📈 +{docs_delta} documents in last 5 seconds")
            
            last_stats = stats
            
            # Check if we're done (201 documents)
            if stats['documents'] >= 201:
                print("\n✅ ALL DOCUMENTS PROCESSED!")
                if stats['with_text'] >= 199:  # 99% threshold
                    print("✅ Text extraction ≥99% complete!")
                break
                
        except Exception as e:
            print(f"Error getting stats: {e}")
        
        time.sleep(5)  # Update every 5 seconds
        
except KeyboardInterrupt:
    print("\nMonitoring stopped by user")
    
# Final summary
if last_stats:
    print(f"\nFinal Statistics:")
    print(f"- Documents processed: {last_stats['documents']}/201")
    print(f"- Text extraction rate: {(last_stats['with_text']/last_stats['documents']*100) if last_stats['documents'] > 0 else 0:.1f}%")
    print(f"- Total time: {(time.time() - start_time)/60:.1f} minutes")