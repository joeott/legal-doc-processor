#!/usr/bin/env python3
"""Get schema conformance errors - simple version"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import json
from scripts.core.conformance_engine import ConformanceEngine

# Create conformance engine and check conformance
engine = ConformanceEngine()
report = engine.check_conformance()

print(f"\nIs Conformant: {report.is_conformant}")
print(f"Total Issues: {len(report.issues)}")

# Save full report
report_data = {
    'is_conformant': report.is_conformant,
    'timestamp': str(report.timestamp),
    'issues': report.issues
}

with open('/opt/legal-doc-processor/conformance_report.json', 'w') as f:
    json.dump(report_data, f, indent=2)

# Show first 10 issues
print("\nFirst 10 issues:")
for i, issue in enumerate(report.issues[:10], 1):
    print(f"\n{i}. {issue}")