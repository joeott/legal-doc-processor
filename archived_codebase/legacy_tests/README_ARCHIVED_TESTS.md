# Archived Test Scripts

## Archive Date: 2025-06-04

This directory contains test scripts that were removed during the comprehensive codebase cleanup (context_396).

### What Was Archived

**Total Files Archived**: 108 test files
- 83 test_*.py files
- 11 verify_*.py files  
- 1 comprehensive_*.py file
- Various debug and experimental scripts

### Archive Structure

- `by_date/2025_06_04_cleanup/` - All files archived during cleanup
- `by_category/` - Files organized by functional category:
  - `ocr_tests/` - OCR and Textract related tests
  - `entity_tests/` - Entity extraction and resolution tests
  - `pipeline_tests/` - End-to-end pipeline tests
  - `debug_scripts/` - Debug and diagnostic scripts
  - `verification_scripts/` - Production verification scripts

### Reason for Archival

These test scripts represented significant technical debt:
- 108+ scattered test files with no organization
- Massive duplication of testing functionality
- No clear entry point for testing
- Mixed production and test code
- No standardized execution or CI/CD integration

### What Replaced Them

New organized test structure in `/tests/`:
- `tests/unit/` - Isolated component tests
- `tests/integration/` - Multi-component tests  
- `tests/e2e/` - Full pipeline tests
- Pytest framework with proper fixtures
- Clear documentation and execution paths

### Recovery Process

If specific archived tests are needed:

1. **Identify the test**: Check this manifest for original location
2. **Find replacement**: Check if functionality exists in new `/tests/` structure
3. **Extract if needed**: Copy specific test logic to appropriate new test file
4. **Do NOT restore wholesale**: Maintain organized structure

### Key Archived Files

**Most Important Archived Tests**:
- `test_complete_pipeline.py` → Replaced by `tests/e2e/test_document_processing.py`
- `test_entity_extraction.py` → Replaced by `tests/unit/test_entity_service.py`
- `test_ocr_sync.py` → Replaced by `tests/unit/test_textract_utils.py`
- `comprehensive_pipeline_test.py` → Replaced by `tests/e2e/test_production_simulation.py`

**Production Scripts Kept**:
- Core scripts in `/scripts/` (production code only)
- Configuration files
- Database utilities
- Monitoring tools

### Lessons Learned

1. **Prevent Test Proliferation**: Use organized `/tests/` structure
2. **Single Responsibility**: Each test file has clear purpose
3. **Framework Consistency**: Pytest exclusively
4. **Documentation**: Clear test purposes and execution
5. **Agentic Guidance**: System prompts prevent future proliferation

### Contact

For questions about archived tests or recovery needs, refer to:
- Context 396: Comprehensive codebase cleanup plan
- New test documentation in `/tests/README.md`
- System maintenance guidelines in `CLAUDE.md`