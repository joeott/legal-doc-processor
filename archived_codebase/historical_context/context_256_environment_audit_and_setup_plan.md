# Environment Audit and Python Setup Plan

## Executive Summary

The current environment lacks all required Python packages for the legal document processor. Additionally, `pip` is not installed, making package installation impossible without first setting up the Python package management infrastructure.

## Current Environment Status

### Python Installation
- **Python Version**: 3.10.12 (Ubuntu 22.04 default)
- **Python Path**: `/usr/bin/python3`
- **pip**: NOT INSTALLED
- **venv**: NOT AVAILABLE

### Package Audit Results

All required packages are **NOT INSTALLED**:
- ❌ celery==5.3.4
- ❌ redis==5.0.1
- ❌ sqlalchemy==2.0.23
- ❌ pydantic==2.5.2
- ❌ boto3==1.34.7
- ❌ openai==1.6.1
- ❌ psycopg2-binary==2.9.9
- ❌ PyMuPDF==1.23.8
- ❌ python-dateutil==2.8.2
- ❌ dateparser==1.2.0
- ❌ numpy==1.26.2
- ❌ python-dotenv==1.0.0
- ❌ botocore==1.34.7
- ❌ simplejson==3.19.2
- ❌ nltk==3.8.1
- ❌ tiktoken==0.5.2
- ❌ cloudwatch==1.1.2

## Installation Plan

### Phase 1: Install Python Package Management Tools

```bash
# Update package list
sudo apt update

# Install pip and venv
sudo apt install -y python3-pip python3-venv

# Verify installation
python3 -m pip --version
```

### Phase 2: Create Virtual Environment (STRONGLY RECOMMENDED)

A virtual environment is **highly recommended** for this project because:
1. **Isolation**: Prevents conflicts with system Python packages
2. **Version Control**: Ensures exact package versions from requirements.txt
3. **Clean Uninstall**: Easy to remove all project dependencies
4. **Multiple Projects**: Allows different projects with different dependencies
5. **No Root Required**: Install packages without sudo after venv creation

```bash
# Create virtual environment
cd /opt/legal-doc-processor
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip within venv
python -m pip install --upgrade pip
```

### Phase 3: Install System Dependencies

Some packages require system libraries:

```bash
# PostgreSQL development files (for psycopg2)
sudo apt install -y libpq-dev

# Python development files (for compiled packages)
sudo apt install -y python3-dev

# Additional libraries for document processing
sudo apt install -y libmupdf-dev mupdf-tools  # For PyMuPDF
sudo apt install -y build-essential            # For compiled packages
```

### Phase 4: Install Python Requirements

```bash
# Ensure virtual environment is activated
source /opt/legal-doc-processor/venv/bin/activate

# Install all requirements
pip install -r requirements.txt

# Verify installation
pip list
```

### Phase 5: Post-Installation Setup

```bash
# Download NLTK data (required for text processing)
python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords')"

# Create required directories
mkdir -p /opt/legal-doc-processor/input_docs
mkdir -p /opt/legal-doc-processor/document_intake
mkdir -p /opt/legal-doc-processor/s3_downloads

# Set up environment file
cp .env.example .env  # Then edit with credentials
```

## Alternative: System-Wide Installation (NOT Recommended)

If you must install system-wide:

```bash
# Install packages globally (requires sudo for each)
sudo python3 -m pip install -r requirements.txt
```

**Risks**:
- May conflict with system packages
- Requires root for all pip operations
- Harder to manage versions
- Can break system Python tools

## Verification Steps

After installation:

```bash
# Test imports
python3 -c "
import celery
import redis
import sqlalchemy
import pydantic
import boto3
print('Core imports successful!')
"

# Run connection tests
python3 scripts/check_rds_connection.py
python3 scripts/test_minimal_pipeline.py
```

## Troubleshooting

### Common Issues:

1. **Permission Denied**:
   - Ensure you own the project directory: `sudo chown -R $USER:$USER /opt/legal-doc-processor`

2. **Package Compilation Fails**:
   - Install development headers: `sudo apt install python3-dev`

3. **PostgreSQL Connection Issues**:
   - Install PostgreSQL client: `sudo apt install postgresql-client`

4. **SSL Certificate Errors**:
   - Update certificates: `sudo apt install ca-certificates`

## Recommended Installation Sequence

```bash
# Complete installation script
#!/bin/bash

# Step 1: System preparation
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev libpq-dev build-essential

# Step 2: Create and activate virtual environment
cd /opt/legal-doc-processor
python3 -m venv venv
source venv/bin/activate

# Step 3: Upgrade pip and install packages
pip install --upgrade pip
pip install -r requirements.txt

# Step 4: Post-installation setup
python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords')"
mkdir -p input_docs document_intake s3_downloads

echo "Installation complete! Remember to activate the virtual environment:"
echo "source /opt/legal-doc-processor/venv/bin/activate"
```

## Summary

The environment requires a complete Python package setup. Using a virtual environment is strongly recommended to maintain isolation and manage dependencies effectively. The total installation time should be approximately 10-15 minutes depending on network speed.