#!/usr/bin/env python3
"""Analyze schema conformance issues"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.core.conformance_engine import ConformanceEngine

# Create conformance engine and check conformance
engine = ConformanceEngine()
report = engine.check_conformance()

print(f"\nConformance Check Results:")
print(f"Is Conformant: {report.is_conformant}")
print(f"Total Issues: {len(report.issues)}")

# Analyze issues by type
issue_types = {}
issue_tables = {}
issue_severities = {}

for issue in report.issues:
    # Convert issue to dict if it's an object
    if hasattr(issue, '__dict__'):
        issue_dict = issue.__dict__
    elif hasattr(issue, 'model_dump'):
        issue_dict = issue.model_dump()
    else:
        issue_dict = {'message': str(issue)}
    
    # Count by type
    issue_type = issue_dict.get('issue_type', 'unknown')
    issue_types[issue_type] = issue_types.get(issue_type, 0) + 1
    
    # Count by table
    table_name = issue_dict.get('table_name', 'unknown')
    issue_tables[table_name] = issue_tables.get(table_name, 0) + 1
    
    # Count by severity
    severity = issue_dict.get('severity', 'unknown')
    issue_severities[severity] = issue_severities.get(severity, 0) + 1

print("\nIssues by Type:")
for issue_type, count in sorted(issue_types.items(), key=lambda x: -x[1]):
    print(f"  {issue_type}: {count}")

print("\nIssues by Table:")
for table, count in sorted(issue_tables.items(), key=lambda x: -x[1])[:10]:
    print(f"  {table}: {count}")

print("\nIssues by Severity:")
for severity, count in sorted(issue_severities.items()):
    print(f"  {severity}: {count}")

# Show sample issues
print("\nSample Issues (first 5):")
for i, issue in enumerate(report.issues[:5], 1):
    print(f"\n{i}. Issue:")
    if hasattr(issue, '__dict__'):
        for key, value in issue.__dict__.items():
            if value and key != '_sa_instance_state':
                print(f"   {key}: {value}")