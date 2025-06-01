# Context 249: Cursor/VS Code Remote SSH Connection Guide to EC2

## Overview
This guide provides step-by-step instructions for connecting Cursor (or VS Code) to the EC2 instance using Remote SSH, allowing you to edit files directly on the server with full IDE features.

## Prerequisites
- Cursor or VS Code installed on your local machine
- SSH key file: `~/Documents/phase_1_2_3_process_v5/resources/aws/legal-doc-processor-bastion.pem`
- EC2 instance IP: `54.162.223.205`

## Step-by-Step Connection Guide

### Step 1: Install Remote-SSH Extension
1. Open Cursor (or VS Code)
2. Click the Extensions icon in the left sidebar (or press `Cmd+Shift+X`)
3. Search for "Remote - SSH"
4. Install the "Remote - SSH" extension by Microsoft

### Step 2: Add SSH Host
1. Press `Cmd+Shift+P` (Mac) or `Ctrl+Shift+P` (Windows/Linux) to open Command Palette
2. Type: `Remote-SSH: Connect to Host...`
3. Select `+ Add New SSH Host...`
4. Enter the complete SSH command:
   ```
   ssh -i ~/Documents/phase_1_2_3_process_v5/resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205
   ```
5. Select SSH configuration file to update (typically `~/.ssh/config`)

### Step 3: Connect to EC2
1. Press `Cmd+Shift+P` again to open Command Palette
2. Type: `Remote-SSH: Connect to Host...`
3. You should now see `54.162.223.205` in the list
4. Click on it to connect
5. If prompted about the platform, select "Linux"
6. If prompted about fingerprint, select "Continue"

### Step 4: Open Project Folder
1. Once connected (new window opens), you'll see "SSH: 54.162.223.205" in the bottom-left corner
2. Click "Open Folder" button (or `File → Open Folder`)
3. In the folder dialog, type: `/opt/legal-doc-processor`
4. Click "OK"

## Alternative: Manual SSH Config Setup

If you prefer to manually configure SSH:

### Step 1: Edit SSH Config
```bash
# On your local machine
nano ~/.ssh/config
```

### Step 2: Add Configuration
```
Host legal-doc-ec2
    HostName 54.162.223.205
    User ubuntu
    IdentityFile ~/Documents/phase_1_2_3_process_v5/resources/aws/legal-doc-processor-bastion.pem
    ForwardAgent yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

### Step 3: Connect Using Alias
1. In Cursor Command Palette (`Cmd+Shift+P`)
2. Type: `Remote-SSH: Connect to Host...`
3. Select `legal-doc-ec2`

## Verifying Connection

You'll know you're successfully connected when:
- Bottom-left corner shows "SSH: 54.162.223.205" or "SSH: legal-doc-ec2"
- Terminal opens to `ubuntu@ip-172-31-33-106:~$`
- Explorer sidebar shows `/opt/legal-doc-processor` contents

## Working on EC2

### Terminal Access
- Open integrated terminal: `` Ctrl+` `` (backtick) or `View → Terminal`
- You're now working directly on EC2
- All commands execute on the server

### File Editing
- All file changes are made directly on EC2
- No need to upload/download files
- Full IDE features available (syntax highlighting, IntelliSense, etc.)

### Running Scripts
```bash
# Activate Python environment
cd /opt/legal-doc-processor
source venv/bin/activate

# Run Python scripts
python scripts/test_connection.py

# Start Celery workers
./start_workers.sh
```

## Common Issues and Solutions

### Issue: Permission Denied
```bash
# Fix SSH key permissions on local machine
chmod 600 ~/Documents/phase_1_2_3_process_v5/resources/aws/legal-doc-processor-bastion.pem
```

### Issue: Connection Timeout
- Check EC2 instance is running
- Verify security group allows SSH from your IP
- Ensure you're using the correct IP address

### Issue: Host Key Verification Failed
```bash
# Clear known hosts entry
ssh-keygen -R 54.162.223.205
```

### Issue: Can't Open Folder
- Ensure `/opt/legal-doc-processor` exists
- Check permissions: folder should be owned by ubuntu user

## Useful Remote SSH Commands

In Command Palette (`Cmd+Shift+P`):
- `Remote-SSH: Connect to Host...` - Connect to server
- `Remote-SSH: Close Remote Connection` - Disconnect
- `Remote-SSH: Kill VS Code Server on Host...` - Force restart remote server
- `Remote-SSH: Show Remote SSH Log` - Debug connection issues

## Working with Multiple Windows

You can have multiple Cursor/VS Code windows connected to EC2:
1. Connect to EC2 as normal
2. `File → New Window`
3. Connect the new window to EC2
4. Open different folders or work on different parts of the project

## Port Forwarding

To access services running on EC2 (like web servers):

1. In Command Palette: `Remote-SSH: Forward Port from Active Host...`
2. Enter port number (e.g., 8080)
3. Access via `localhost:8080` on your local machine

## Tips for Productivity

1. **Use integrated terminal** instead of separate SSH session
2. **Install extensions** on remote - they'll run on EC2
3. **Use Source Control** tab for Git operations
4. **Set up debugging** - Python debugging works remotely
5. **Use Tasks** (`Terminal → Run Task`) for common operations

## Disconnecting

To disconnect:
- Close the Cursor/VS Code window
- Or: `File → Close Remote Connection`
- Or: Click "SSH: 54.162.223.205" in bottom-left and select "Close Remote Connection"

The EC2 instance and any running processes continue running after you disconnect.