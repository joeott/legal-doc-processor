-- RDS PostgreSQL Setup Script for Legal Document Processing
-- Run this as the master user (postgres or admin user)

-- Create application database
CREATE DATABASE legal_doc_processing;

-- Create application user
CREATE USER app_user WITH PASSWORD 'LegalDoc2025!Secure';

-- Grant initial permissions
GRANT CONNECT ON DATABASE legal_doc_processing TO app_user;

-- Connect to the new database
\c legal_doc_processing

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- Grant schema permissions to app_user
GRANT ALL ON SCHEMA public TO app_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO app_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_user;

-- Create custom types
CREATE TYPE processing_status AS ENUM (
    'pending',
    'processing', 
    'completed',
    'failed',
    'reprocessing'
);

CREATE TYPE task_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'failed',
    'retrying'
);

-- Grant usage on types
GRANT USAGE ON TYPE processing_status TO app_user;
GRANT USAGE ON TYPE task_status TO app_user;

-- Verify setup
SELECT current_database(), current_user;
\du
SELECT * FROM pg_extension;