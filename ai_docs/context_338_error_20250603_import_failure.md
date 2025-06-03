# Context 338: Import Failure Error - Production Verification

## Error Description

During production readiness verification, all module imports failed with "No module named 'scripts'".

## Stack Trace
```
Error: No module named 'scripts'
```

## Steps to Reproduce

1. Run `python3 scripts/verify_production_readiness.py`
2. Observe import failures for all scripts modules

## Environment Details

- Working directory: /opt/legal-doc-processor
- Python path issue: scripts directory not in PYTHONPATH
- Environment loaded via: source load_env.sh

## Root Cause

The verification script runs from the scripts directory but tries to import modules as `scripts.module_name`. This fails because:
1. Python doesn't include the parent directory in the path
2. The scripts aren't installed as a package

## Attempted Fixes

### Fix 1: Add Parent Directory to Python Path
Need to add the parent directory to sys.path before imports:
```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

### Fix 2: Run from Project Root
Change execution to:
```bash
cd /opt/legal-doc-processor
python3 -m scripts.verify_production_readiness
```

## Resolution

The proper fix is to:
1. Add the parent directory to Python path in the verification script
2. Ensure all test scripts handle the import path correctly
3. Document the proper way to run tests

## Prevention Recommendations

1. Create a standard test runner script that sets up the environment
2. Add import path setup to all test scripts
3. Consider making scripts a proper Python package with __init__.py
4. Document the correct way to run tests in README

## Additional Findings

- Missing Redis environment variables (REDIS_HOST, REDIS_PORT, REDIS_PASSWORD)
- Only 1/33 tests passed (monitoring_tools check)
- Need proper environment setup before testing