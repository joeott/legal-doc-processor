# Redis Model Context Protocol (MCP) Server Implementation Guide

## Overview

This guide provides step-by-step instructions for implementing and configuring a Redis MCP server that Claude Code can connect to, using the credentials from your `.env` file. The MCP server enables natural language interaction with Redis, allowing AI agents to manage and search data efficiently.

## Prerequisites

- Python 3.13+
- Redis Cloud instance (credentials from .env)
- UV package manager
- Claude Desktop or VS Code with MCP support

## Environment Configuration

Based on your `.env` file, here are the Redis credentials to use:

```bash
REDIS_HOST=redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com
REDIS_PORT=12696
REDIS_USERNAME=joe_ott
REDIS_PWD="BHMbnJHyf&9!4TT"
REDIS_DB=0
REDIS_SSL=true
```

## Installation Steps

### 1. Clone and Set Up the MCP Redis Server

```bash
# Clone the repository
git clone https://github.com/redis/mcp-redis.git
cd mcp-redis

# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv sync
```

### 2. Create Environment Configuration File

Create a `.env` file in the `mcp-redis` directory with your Redis credentials:

```bash
# Redis Configuration
REDIS_HOST=redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com
REDIS_PORT=12696
REDIS_USERNAME=joe_ott
REDIS_PWD="BHMbnJHyf&9!4TT"
REDIS_DB=0
REDIS_SSL=true
REDIS_CLUSTER_MODE=false

# MCP Transport (stdio for local, sse for network)
MCP_TRANSPORT=stdio
```

## Claude Desktop Configuration

### 1. Locate Configuration File

On macOS:
```bash
~/Library/Application Support/Claude/claude_desktop_config.json
```

On Windows:
```
%APPDATA%\Claude\claude_desktop_config.json
```

### 2. Configure MCP Server

Edit the `claude_desktop_config.json` file to add the Redis MCP server:

```json
{
    "mcpServers": {
        "redis-legal-docs": {
            "command": "/Users/josephott/.local/bin/uv",
            "args": [
                "--directory",
                "/path/to/mcp-redis",
                "run",
                "src/main.py"
            ],
            "env": {
                "REDIS_HOST": "redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com",
                "REDIS_PORT": "12696",
                "REDIS_USERNAME": "joe_ott",
                "REDIS_PWD": "BHMbnJHyf&9!4TT",
                "REDIS_SSL": "true",
                "REDIS_DB": "0",
                "REDIS_CLUSTER_MODE": "false"
            }
        }
    }
}
```

### 3. Restart Claude Desktop

After saving the configuration, restart Claude Desktop to load the MCP server.

## VS Code Configuration

### 1. Enable Agent Mode

Add to your VS Code `settings.json`:

```json
{
    "chat.agent.enabled": true
}
```

### 2. Configure MCP Server

Create `.vscode/mcp.json` in your project:

```json
{
    "servers": {
        "redis-legal-docs": {
            "type": "stdio",
            "command": "/Users/josephott/.local/bin/uv",
            "args": [
                "--directory",
                "/path/to/mcp-redis",
                "run",
                "src/main.py"
            ],
            "env": {
                "REDIS_HOST": "redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com",
                "REDIS_PORT": "12696",
                "REDIS_USERNAME": "joe_ott",
                "REDIS_PWD": "BHMbnJHyf&9!4TT",
                "REDIS_SSL": "true",
                "REDIS_DB": "0"
            }
        }
    }
}
```

## Available MCP Tools

The Redis MCP server provides these tools for interacting with your pipeline data:

### 1. Document State Management
```
- hash tools: Store and retrieve document processing states
- Example: "Get the processing state for document UUID xyz"
```

### 2. Cache Operations
```
- string tools: Manage cached OCR results and LLM responses
- Example: "Cache this entity extraction result with a 24-hour expiration"
```

### 3. Queue Management
```
- list tools: Manage document processing queues
- sorted set tools: Priority-based queue operations
- Example: "Add this document to the processing queue with high priority"
```

### 4. Rate Limiting
```
- sorted set tools: Track API call rates
- Example: "Check if we're within the OpenAI rate limit"
```

### 5. Distributed Locking
```
- string tools with expiration: Implement distributed locks
- Example: "Lock queue item 123 for processing"
```

### 6. Real-time Monitoring
```
- pub/sub tools: Subscribe to processing events
- streams tools: Track document processing history
- Example: "Subscribe to document completion events"
```

## Integration with Legal Document Pipeline

### Natural Language Queries

Once configured, you can use natural language to interact with your Redis data:

1. **Check Document Processing State**
   ```
   "Show me the processing state for document <uuid>"
   "Which documents are currently in the OCR phase?"
   ```

2. **Manage Caches**
   ```
   "Clear the OCR cache for document <uuid>"
   "Show all cached entity extraction results"
   ```

3. **Monitor Queue**
   ```
   "How many documents are pending in the queue?"
   "Show failed documents from the last hour"
   ```

4. **Rate Limit Management**
   ```
   "Check current OpenAI API usage rate"
   "Reset the rate limit counter for testing"
   ```

## Testing the Connection

### 1. Using MCP Inspector

```bash
cd /path/to/mcp-redis
npx @modelcontextprotocol/inspector uv run src/main.py
```

### 2. Test Commands in Claude

After configuration, test with these commands:
- "Connect to Redis and show database info"
- "List all keys matching pattern 'doc_state:*'"
- "Get the value of key 'textract:result:<document_uuid>'"

### 3. Monitor Logs

```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp-server-redis-legal-docs.log

# Or check MCP Redis logs
tail -f /path/to/mcp-redis/logs/*.log
```

## Docker Deployment (Optional)

For production deployment, use Docker:

### 1. Build Docker Image

```bash
cd /path/to/mcp-redis
docker build -t mcp-redis-legal .
```

### 2. Update Claude Configuration

```json
{
    "mcpServers": {
        "redis-legal-docs": {
            "command": "docker",
            "args": [
                "run",
                "--rm",
                "--name", "redis-mcp-legal",
                "-i",
                "-e", "REDIS_HOST=redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com",
                "-e", "REDIS_PORT=12696",
                "-e", "REDIS_USERNAME=joe_ott",
                "-e", "REDIS_PWD=BHMbnJHyf&9!4TT",
                "-e", "REDIS_SSL=true",
                "mcp-redis-legal"
            ]
        }
    }
}
```

## Security Best Practices

1. **Never commit credentials**: Keep `.env` files in `.gitignore`
2. **Use environment variables**: Don't hardcode credentials in config files
3. **SSL/TLS**: Always use SSL for Redis Cloud connections
4. **Access control**: Limit Redis user permissions to necessary operations
5. **Key namespacing**: Use consistent prefixes to organize data

## Troubleshooting

### Common Issues

1. **Connection Failed**
   - Verify Redis Cloud endpoint is accessible
   - Check SSL is enabled in configuration
   - Ensure credentials are correct

2. **MCP Server Not Found**
   - Verify full path to UV command: `which uv`
   - Check directory paths are absolute
   - Ensure virtual environment is activated

3. **Permission Errors**
   - Check Redis user has necessary permissions
   - Verify SSL certificates if using custom CA

### Debug Commands

```bash
# Test Redis connection
redis-cli -h redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com \
          -p 12696 \
          --tls \
          -a "BHMbnJHyf&9!4TT" \
          --user joe_ott \
          ping

# Check MCP server status
cd /path/to/mcp-redis
uv run src/main.py --test
```

## Advanced Usage

### Custom Tools

You can extend the MCP server with custom tools for your pipeline:

1. Create new tool in `tools/legal_pipeline.py`
2. Register tool in `src/main.py`
3. Implement Redis operations specific to your needs

Example custom tool:
```python
@mcp.tool()
async def get_document_processing_stats(timeframe: str = "1h"):
    """Get statistics about document processing in the specified timeframe"""
    # Implementation using Redis sorted sets and hashes
    pass
```

### Integration with Pipeline Monitoring

Create a monitoring dashboard by combining MCP queries:
- Real-time queue status
- Processing performance metrics
- Cache hit rates
- Error tracking

## Conclusion

The Redis MCP server provides a powerful natural language interface to your Redis data, enabling efficient management and monitoring of your legal document processing pipeline. With proper configuration, you can query processing states, manage caches, monitor queues, and analyze performance metrics using simple conversational commands in Claude Desktop or VS Code.