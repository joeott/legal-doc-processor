# Environment Configuration Update - Context 133

## Overview
This document details the migration of credentials and configuration files from the `document_processor_v3` project to the `phase_1_2_3_process_v5` project, completed on May 27, 2025.

## Directory Structure Created

```
/Users/josephott/Documents/phase_1_2_3_process_v5/
├── resources/
│   ├── google/
│   │   └── document-processor-v3-2400c9ce2ba1.json
│   └── aws/
│       ├── deepseekEC2install.pem
│       └── samu_legal_1.pem
└── .env (updated with comprehensive credentials)
```

## Files Migrated

### 1. Google Cloud Service Account Credentials
- **Source:** `/Users/josephott/Documents/document_processor_v3/document_processor/entity_extractor/batch/document-processor-v3-2400c9ce2ba1.json`
- **Destination:** `/Users/josephott/Documents/phase_1_2_3_process_v5/resources/google/document-processor-v3-2400c9ce2ba1.json`
- **Purpose:** Service account credentials for Google Cloud project "document-processor-v3"
- **Service Account Email:** `document-processor-v3@document-processor-v3.iam.gserviceaccount.com`

### 2. AWS EC2 PEM Files
- **deepseekEC2install.pem**
  - Source: `/Users/josephott/Documents/comprehend_multiclass_doctype/deepseekEC2install.pem`
  - Destination: `/Users/josephott/Documents/phase_1_2_3_process_v5/resources/aws/deepseekEC2install.pem`
  - Purpose: SSH key for EC2 instance access
  
- **samu_legal_1.pem**
  - Source: `/Users/josephott/Documents/phase_1_2_3_process_v4/samu_legal_1.pem`
  - Destination: `/Users/josephott/Documents/phase_1_2_3_process_v5/resources/aws/samu_legal_1.pem`
  - Purpose: SSH key for EC2 instance access

## Environment Variables Updated

The `.env` file at `/Users/josephott/Documents/phase_1_2_3_process_v5/.env` was comprehensively updated with credentials from `/Users/josephott/Documents/document_processor_v3/.env`. The following sections were added or updated:

### Google Cloud Configuration
```env
GOOGLE_ADMIN_EMAIL=joe@ott.law
GOOGLE_CREDENTIALS_SECRET_NAME=google-workspace-credentials
GOOGLE_DOMAIN=ott.law
GOOGLE_CLOUD_PROJECT=document-processor-v3
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/Users/josephott/Documents/phase_1_2_3_process_v5/resources/google/document-processor-v3-2400c9ce2ba1.json
```

### LLM API Keys Added
- **OpenAI:** Multiple models configured (GPT-4-turbo, text-embedding-3-large, etc.)
- **Anthropic:** Claude models (haiku)
- **Gemini:** Multiple Gemini models (2.0-flash, 1.5-flash-latest)
- **DeepSeek:** Chat model configuration

### Database Credentials
- **Neo4j:** Graph database connection (neo4j+s://0ddf63b7.databases.neo4j.io)
- **Supabase:** Two sets of credentials maintained (primary and alternative)
- **Pinecone:** Vector database with embedding dimensions specified
- **Redis:** Cache/queue configuration with authentication

### AWS/S3 Configuration
```env
S3_BUCKET_NAME=gmailoutputottlaw
AWS_REGION=us-east-1
S3_PRIMARY_DOCUMENT_BUCKET=samu-docs-private-upload
```

### Airtable Integration
- Personal Access Token (PAT)
- Workspace ID
- Base ID configurations

## Key Changes Made

1. **Organized Structure:** The `.env` file now has clear section headers for better organization
2. **Consolidated Credentials:** All API keys and credentials from multiple sources are now in one location
3. **Path Updates:** The `GOOGLE_APPLICATION_CREDENTIALS` path now points to the new resources directory
4. **Preserved Existing:** Original Supabase credentials were preserved as alternatives
5. **Added Comments:** Included helpful comments about PEM file locations

## Security Notes

- All credential files maintain their original permissions
- PEM files have restricted permissions (r--------) for security
- The `.env` file contains sensitive credentials and should be included in `.gitignore`

## Usage Instructions

1. **For Google Cloud Access:**
   - The application will automatically use the service account JSON file specified in `GOOGLE_APPLICATION_CREDENTIALS`

2. **For EC2 SSH Access:**
   - Use the PEM files in `resources/aws/` with appropriate SSH commands
   - Example: `ssh -i resources/aws/samu_legal_1.pem ec2-user@<instance-ip>`

3. **Environment Loading:**
   - Applications should load the `.env` file from the project root
   - All credentials are now centralized for easier management

## Verification

To verify the migration:
1. Check file existence: `ls -la resources/google/ resources/aws/`
2. Validate JSON: `cat resources/google/document-processor-v3-2400c9ce2ba1.json | jq .`
3. Test environment loading in your application

## Related Files

- Original source `.env`: `/Users/josephott/Documents/document_processor_v3/.env`
- Updated target `.env`: `/Users/josephott/Documents/phase_1_2_3_process_v5/.env`
- Duplicate Google credentials also found at: `/Users/josephott/Documents/document_processor_v4/document_processor/entity_extractor/batch/`

---
*Document created: May 27, 2025*
*Migration performed by: Claude Code Assistant*