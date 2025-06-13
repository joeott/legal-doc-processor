# Context 358: SNS Topic ARN Parameter Fix

## Issue Identified
The `create_textract_job_entry` method in `db.py` was missing the `sns_topic_arn` parameter that `textract_utils.py` was attempting to pass when creating Textract job entries.

## Root Cause
- The TextractJobModel in `schemas.py` has a field called `notification_channel_sns_topic_arn`
- The `create_textract_job_entry` method didn't accept the `sns_topic_arn` parameter
- `textract_utils.py` was trying to pass this parameter, causing a TypeError

## Fix Applied
1. Added `sns_topic_arn: Optional[str] = None` to the method signature of `create_textract_job_entry` in `db.py`
2. Updated the TextractJobModel instantiation to include `notification_channel_sns_topic_arn=sns_topic_arn`

## Files Modified
- `/opt/legal-doc-processor/scripts/db.py`:
  - Line 636: Added `sns_topic_arn` parameter to method signature
  - Line 650: Added `notification_channel_sns_topic_arn=sns_topic_arn` to model instantiation

## Verification
- The parameter is now properly accepted and mapped to the correct field in the Pydantic model
- This allows Textract jobs to be created with SNS notification channels for async processing
- The fix maintains backward compatibility as the parameter is optional with a default value of None