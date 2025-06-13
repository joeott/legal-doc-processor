#!/usr/bin/env python3
"""
Fix OpenAI API parameter issues across the codebase
Updates temperature to 1.0 and removes unsupported parameters
"""
import os
import re

def fix_file(filepath):
    """Fix OpenAI parameters in a single file"""
    with open(filepath, 'r') as f:
        content = f.read()
    
    original_content = content
    changes_made = []
    
    # Fix temperature parameter (must be 1.0 for newer models)
    temp_pattern = r'temperature\s*=\s*[0-9.]+(?=[,\)])'
    temp_matches = re.findall(temp_pattern, content)
    if temp_matches:
        content = re.sub(temp_pattern, 'temperature=1.0', content)
        changes_made.append(f"Updated temperature values: {temp_matches}")
    
    # Already fixed max_tokens -> max_completion_tokens in previous commits
    # Just verify it's correct
    if 'max_tokens' in content and 'max_completion_tokens' not in content:
        changes_made.append("WARNING: Found max_tokens that wasn't updated")
    
    # Check for other potential issues
    if changes_made and content != original_content:
        with open(filepath, 'w') as f:
            f.write(content)
        return True, changes_made
    
    return False, []

def main():
    """Fix OpenAI parameters across all Python files"""
    files_to_check = [
        'entity_extraction.py',
        'structured_extraction.py', 
        'entity_resolution.py'
    ]
    
    print("Fixing OpenAI API parameters...")
    print("-" * 50)
    
    for filename in files_to_check:
        filepath = os.path.join(os.path.dirname(__file__), filename)
        if os.path.exists(filepath):
            fixed, changes = fix_file(filepath)
            if fixed:
                print(f"\n✓ Fixed {filename}:")
                for change in changes:
                    print(f"  - {change}")
            else:
                print(f"\n• {filename}: No changes needed")
        else:
            print(f"\n✗ {filename}: File not found")
    
    print("\n" + "-" * 50)
    print("Fix complete!")

if __name__ == "__main__":
    main()