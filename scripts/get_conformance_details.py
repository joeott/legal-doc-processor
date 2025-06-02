#!/usr/bin/env python3
"""Get detailed schema conformance errors"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from scripts.core.conformance_engine import ConformanceEngine

try:
    # Create conformance engine and check conformance
    engine = ConformanceEngine()
    report = engine.check_conformance()
    
    print("\n" + "="*80)
    print("SCHEMA CONFORMANCE VALIDATION REPORT")
    print("="*80)
    
    print(f"\nIs Conformant: {report.is_conformant}")
    print(f"Total Issues: {len(report.issues)}")
    print(f"Tables Checked: {len(report.tables_checked)}")
    
    # Count issues by severity
    severity_counts = {}
    for issue in report.issues:
        severity = issue.get('severity', 'unknown')
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    
    print("\nIssues by Severity:")
    for severity, count in severity_counts.items():
        print(f"  {severity}: {count}")
    
    if report.issues:
        print("\n" + "-"*80)
        print("DETAILED ISSUES:")
        print("-"*80)
        
        # Group issues by table
        issues_by_table = {}
        for issue in report.issues:
            table = issue.get('table', 'unknown')
            if table not in issues_by_table:
                issues_by_table[table] = []
            issues_by_table[table].append(issue)
        
        for table, table_issues in sorted(issues_by_table.items()):
            print(f"\n[TABLE: {table}]")
            for i, issue in enumerate(table_issues, 1):
                print(f"\n  Issue #{i}:")
                print(f"    Type: {issue.get('type', 'unknown')}")
                print(f"    Severity: {issue.get('severity', 'unknown')}")
                print(f"    Message: {issue.get('message', 'No message')}")
                if issue.get('field'):
                    print(f"    Field: {issue['field']}")
                if issue.get('expected'):
                    print(f"    Expected: {issue['expected']}")
                if issue.get('actual'):
                    print(f"    Actual: {issue['actual']}")
                if issue.get('details'):
                    print(f"    Details: {issue['details']}")
    
    # Write to file for analysis
    import json
    with open('/opt/legal-doc-processor/conformance_report.json', 'w') as f:
        # Convert report to JSON-serializable format
        report_dict = {
            'is_conformant': report.is_conformant,
            'timestamp': str(report.timestamp),
            'tables_checked': report.tables_checked,
            'issues': report.issues
        }
        json.dump(report_dict, f, indent=2)
    print(f"\nFull report saved to: /opt/legal-doc-processor/conformance_report.json")
    
except Exception as e:
    logger.error(f"Failed to get conformance details: {e}")
    import traceback
    traceback.print_exc()