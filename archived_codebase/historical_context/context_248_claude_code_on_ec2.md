# Context 248: Running Claude Code on EC2 Server

## Overview
This document explains how to set up and use Claude Code directly on the EC2 server for continued development.

## Option 1: Claude Code CLI on EC2 (Recommended)

### Installation Steps
```bash
# SSH into EC2
ssh -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205

# Install Node.js (required for Claude Code)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Verify installation
claude-code --version
```

### Configuration
```bash
# Set up Claude Code configuration
claude-code configure

# You'll need:
# 1. Your Anthropic API key
# 2. Choose working directory: /opt/legal-doc-processor
```

### Usage
```bash
# Start Claude Code in the project directory
cd /opt/legal-doc-processor
claude-code

# Claude Code will now have direct access to:
# - All scripts in the EC2 environment
# - Direct database connection (no SSH tunnel)
# - Local file system
# - Ability to execute commands directly
```

## Option 2: VS Code + Claude Extension

### Setup
```bash
# If using VS Code Server (from previous setup)
# 1. Connect to EC2 via VS Code Remote SSH
# 2. Install Claude extension in VS Code
# 3. Configure with your API key
```

## Important Considerations

### 1. Context Transfer
To continue the conversation:

```bash
# Copy AI docs to EC2
scp -r -i resources/aws/legal-doc-processor-bastion.pem \
    ai_docs/ \
    ubuntu@54.162.223.205:/opt/legal-doc-processor/

# Copy CLAUDE.md
scp -i resources/aws/legal-doc-processor-bastion.pem \
    CLAUDE.md \
    ubuntu@54.162.223.205:/opt/legal-doc-processor/
```

### 2. Environment Advantages on EC2

When running Claude Code directly on EC2, you get:

- **Direct Database Access**: No SSH tunnel complexity
- **Faster File Operations**: Local disk access
- **Real-time Testing**: Execute scripts immediately
- **Production Environment**: Test in actual deployment environment

### 3. Conversation Continuity

To continue this exact conversation:

1. Reference the latest context documents (245-248)
2. Mention you're now running on EC2
3. Claude Code will have access to the actual deployed files

### 4. Example First Message on EC2

```
I'm now running Claude Code directly on the EC2 instance at /opt/legal-doc-processor. 
This is a continuation of our conversation about migrating the preprocessing pipeline 
to EC2 (see context_245 through context_248). 

The database connection now works directly without SSH tunnels. Please help me verify 
the preprocessing pipeline is working correctly on this EC2 instance.
```

## Security Notes

1. **API Key Storage**: Store your Anthropic API key securely
2. **Access Control**: Claude Code on EC2 has full system access
3. **Audit Trail**: All commands are executed as the ubuntu user

## Limitations

1. **No GUI**: EC2 is headless, so no browser-based features
2. **Resource Constraints**: Depending on EC2 instance size
3. **Cost**: Running Claude Code counts against your API usage

## Alternative: Hybrid Approach

You can also:
1. Keep Claude Code on your local machine
2. Use VS Code Remote SSH to edit files on EC2
3. Execute commands on EC2 via SSH from Claude Code locally

This gives you the best of both worlds:
- Local Claude Code interface
- Direct EC2 file access via VS Code
- No need to transfer contexts

## Recommended Approach

For your use case, I recommend:

1. **Continue using Claude Code locally**
2. **Connect to EC2 via VS Code Remote SSH** (already configured)
3. **Execute commands on EC2** through the VS Code terminal

This way you:
- Keep your existing conversation context
- Edit files directly on EC2 through VS Code
- Run commands in the EC2 environment
- Avoid setting up Claude Code on EC2

The files are already accessible through your VS Code Remote SSH connection, giving you full IDE capabilities while the preprocessing runs with direct database access on EC2.