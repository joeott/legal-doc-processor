#!/bin/bash
# Script to run batch processing tests

echo "Running Batch Processing Tests..."
echo "================================"

# Set up environment
export PYTHONPATH=/opt/legal-doc-processor:$PYTHONPATH

# Run the batch processing tests
echo -e "\n1. Running unit tests..."
python -m pytest tests/test_batch_processing.py -v -k "TestBatchTasks" --tb=short

echo -e "\n2. Running recovery tests..."
python -m pytest tests/test_batch_processing.py -v -k "TestBatchRecovery" --tb=short

echo -e "\n3. Running metrics tests..."
python -m pytest tests/test_batch_processing.py -v -k "TestBatchMetrics" --tb=short

echo -e "\n4. Running cache warmer tests..."
python -m pytest tests/test_batch_processing.py -v -k "TestCacheWarmer" --tb=short

echo -e "\n5. Running integration tests..."
python -m pytest tests/test_batch_processing.py -v -k "TestBatchProcessingIntegration" --tb=short

echo -e "\nTest Summary:"
echo "============="
python -m pytest tests/test_batch_processing.py --tb=no -q

echo -e "\nDone!"