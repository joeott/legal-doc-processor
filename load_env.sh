#!/bin/bash
# Load environment variables from .env file, ignoring comments
set -a
source <(grep -v '^#' .env | grep '=')
set +a