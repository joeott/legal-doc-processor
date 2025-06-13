#!/usr/bin/env python3
"""
Filter manifest to exclude audio and video files for testing
"""
import json
import sys

def filter_manifest(input_file, output_file):
    """Filter out audio and video files from manifest"""
    
    # Load the full manifest
    with open(input_file, 'r') as f:
        manifest = json.load(f)

    # Filter out audio and video files
    audio_video_extensions = ['.m4a', '.mp3', '.wav', '.mov', '.mp4', '.avi', '.wmv', '.MOV']
    audio_video_mimes = ['audio/', 'video/', 'application/octet-stream']  # MOV files sometimes show as octet-stream

    filtered_files = []
    excluded_count = 0
    excluded_size = 0

    for file_info in manifest['files']:
        filename = file_info['filename'].lower()
        mime_type = file_info.get('mime_type', '').lower()
        
        # Check if it's audio/video by extension or mime type
        is_audio_video = any(filename.endswith(ext.lower()) for ext in audio_video_extensions)
        is_audio_video = is_audio_video or any(mime_type.startswith(mt) for mt in audio_video_mimes)
        
        # Special check for MOV files
        if filename.endswith('.mov') or mime_type == 'video/quicktime':
            is_audio_video = True
        
        if not is_audio_video:
            filtered_files.append(file_info)
        else:
            excluded_count += 1
            excluded_size += file_info.get('size_bytes', 0)

    # Create filtered manifest
    filtered_manifest = manifest.copy()
    filtered_manifest['files'] = filtered_files
    filtered_manifest['metadata']['case_name'] = manifest['metadata']['case_name'] + ' (No Audio/Video)'
    
    # Update statistics
    if 'statistics' in filtered_manifest:
        filtered_manifest['statistics']['total_files'] = len(filtered_files)
        filtered_manifest['statistics']['total_size_bytes'] -= excluded_size
        filtered_manifest['statistics']['total_size_gb'] = filtered_manifest['statistics']['total_size_bytes'] / (1024**3)
    
    # Update cost estimates proportionally
    if 'estimated_costs' in manifest:
        ratio = len(filtered_files) / len(manifest['files'])
        filtered_manifest['estimated_costs'] = {
            k: v * ratio for k, v in manifest['estimated_costs'].items()
        }

    # Save filtered manifest
    with open(output_file, 'w') as f:
        json.dump(filtered_manifest, f, indent=2)

    print(f'✅ Filtered manifest created: {output_file}')
    print(f'Original files: {len(manifest["files"])}')
    print(f'Filtered files: {len(filtered_files)}')
    print(f'Excluded audio/video files: {excluded_count}')
    print(f'Size reduction: {excluded_size / (1024*1024*1024):.2f} GB')

if __name__ == "__main__":
    filter_manifest('paul_michael_acuity_manifest.json', 'paul_michael_acuity_no_av_manifest.json')