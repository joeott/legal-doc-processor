#!/usr/bin/env python3
"""Quick status check for pipeline verification."""

import sys
sys.path.append('/Users/josephott/Documents/phase_1_2_3_process_v5')

from scripts.supabase_utils import get_supabase_client

def main():
    print("Quick Pipeline Status Check")
    print("=" * 60)
    
    supabase = get_supabase_client()
    
    # Get overall status counts
    response = supabase.table('source_documents').select('initial_processing_status', count='exact').execute()
    
    status_counts = {}
    for doc in response.data:
        status = doc['initial_processing_status']
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print("\nDocument Status Distribution:")
    total = sum(status_counts.values())
    for status, count in sorted(status_counts.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total * 100) if total > 0 else 0
        print(f"  {status}: {count} ({percentage:.1f}%)")
    
    # Get recent errors
    print("\nRecent Errors (last 10):")
    errors = supabase.table('source_documents')\
        .select('original_file_name,error_message')\
        .neq('error_message', None)\
        .order('id', desc=True)\
        .limit(10)\
        .execute()
    
    if errors.data:
        for err in errors.data:
            print(f"  - {err['original_file_name']}: {err['error_message'][:100]}...")
    else:
        print("  No errors found")
    
    # Check documents in processing
    processing = supabase.table('source_documents')\
        .select('document_uuid,original_file_name,initial_processing_status')\
        .in_('initial_processing_status', ['pending_ocr', 'pending_text_processing', 
                                          'pending_chunking', 'pending_entity_extraction'])\
        .order('id', desc=True)\
        .limit(5)\
        .execute()
    
    print(f"\nDocuments Currently Processing (showing {len(processing.data)} of first 5):")
    for doc in processing.data:
        print(f"  - {doc['original_file_name']}: {doc['initial_processing_status']}")
    
    # Success rate for verification test batch
    print("\nLooking for recent successful completions...")
    completed = supabase.table('source_documents')\
        .select('document_uuid,original_file_name,detected_file_type')\
        .eq('initial_processing_status', 'completed')\
        .order('id', desc=True)\
        .limit(10)\
        .execute()
    
    if completed.data:
        print(f"Found {len(completed.data)} recent completions:")
        file_types = {}
        for doc in completed.data:
            ft = doc['detected_file_type']
            file_types[ft] = file_types.get(ft, 0) + 1
        
        for ft, count in file_types.items():
            print(f"  {ft}: {count} documents")
    else:
        print("  No recent completions found")

if __name__ == "__main__":
    main()