---
name: ubuntu-ssh-client
description: >-
  Operational runbook and guidance for executing remote commands, inspecting system health,
  managing systemd services, and editing files on Ubuntu Linux servers via SSH using the Open WebUI Tools client
  OR directly via OpenSSH CLI in Open Terminal when tool calling is unavailable.
---

# Ubuntu Linux SSH Management Skill

This skill guides remote management, diagnostics, and operational procedures on Ubuntu Linux servers. It supports two execution environments:
1. **Mode A: Open WebUI Tool Client** — When the `ubuntu_ssh_client` Python tool is active in the chat.
2. **Mode B: Open Terminal / Shell Substrate** — When Open WebUI is using `open-terminal` and cannot invoke tools directly, allowing execution via native `ssh`, `scp`, and `sshpass` commands in the terminal container.

---

## 1. Execution Mode Detection

Before attempting remote server operations, determine your execution context:

```mermaid
flowchart TD
    Start["Request to manage Ubuntu server via SSH"] --> CheckTools{"Are Open WebUI Tools accessible?"}
    CheckTools -->|Yes| ModeA["Mode A: Invoke ubuntu_ssh_client tool methods"]
    CheckTools -->|No / Open-Terminal| ModeB["Mode B: Run native OpenSSH commands in terminal"]
```

- **Use Mode A** if the model has access to the function-calling interface (`execute_command`, `get_system_status`, `read_file`, `write_file`, `manage_service`).
- **Use Mode B** if you are operating inside an **Open Terminal** container/shell, or if tool calling fails with `Tool not found` or `Tools disabled`.

---

## 2. Mode A: Open WebUI Tool Reference

When tools are bound and accessible, call the Python tool functions directly:

### 1. Remote Shell Commands
- **Method**: `execute_command(command, host=None)`
- **Behavior**: Executes command with strict timeouts (`SSH_TIMEOUT`) and bounds output to `MAX_OUTPUT_CHARS`.

### 2. Structured System Status
- **Method**: `get_system_status(host=None)`
- **Behavior**: Runs a composite diagnostic probe returning structured OS version, uptime, load, memory, and root disk metrics.

### 3. File Operations
- **Method**: `read_file(remote_path, host=None, max_lines=200)`
  - Reads configuration files (e.g. `/etc/nginx/nginx.conf`, `/etc/netplan/01-netcfg.yaml`).
- **Method**: `write_file(remote_path, content, host=None)`
  - Safely writes remote files using Base64 encoding and shell quoting.

### 4. Systemd Service Management
- **Method**: `manage_service(service_name, action, host=None)`
- **Allowed Actions**: `status`, `start`, `stop`, `restart`, `reload`, `is-active`, `enable`, `disable`.

### Configuration (Valves & UserValves)
- **Tool Valves (`Valves`)**: Set by admin under **Workspace > Tools > Settings** (`SSH_HOST`, `SSH_PORT`, `SSH_TIMEOUT`, `MAX_OUTPUT_CHARS`, `SSH_USERNAME`, `SSH_PASSWORD`, `SSH_KEY`).
- **User Valves (`UserValves`)**: Set by individual users under chat **Controls > Valves** (`SSH_HOST`, `SSH_PORT`, `SSH_USERNAME`, `SSH_PASSWORD`, `SSH_KEY`).

---

## 3. Mode B: Open Terminal / Shell Playbook (Native OpenSSH)

When operating inside an **Open Terminal** container/shell without access to Open WebUI tools, execute SSH commands directly using the system OpenSSH suite.

### 1. Setup Environment Variables & Keys

Configure connection parameters:

```bash
export SSH_HOST="${SSH_HOST:-192.168.1.50}"
export SSH_PORT="${SSH_PORT:-22}"
export SSH_USERNAME="${SSH_USERNAME:-ubuntu}"
export SSH_KEY_FILE="${SSH_KEY_FILE:-$HOME/.ssh/id_rsa}"
export SSH_TIMEOUT="15"

# If using password authentication instead of private key:
export SSH_PASSWORD="${SSH_PASSWORD:-}"
```

If an SSH private key is provided as a raw string:
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cat << 'EOF' > ~/.ssh/remote_key
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
EOF
chmod 600 ~/.ssh/remote_key
export SSH_KEY_FILE="$HOME/.ssh/remote_key"
```

### 2. Define Reusable SSH Execution Helper

Add this helper function to your Open Terminal session for clean, non-blocking execution:

```bash
ssh_exec() {
  local remote_cmd="$1"

  if [ -n "$SSH_PASSWORD" ] && command -v sshpass >/dev/null 2>&1; then
    SSHPASS="$SSH_PASSWORD" sshpass -e ssh \
      -p "$SSH_PORT" \
      -o ConnectTimeout="$SSH_TIMEOUT" \
      -o StrictHostKeyChecking=accept-new \
      -n \
      "$SSH_USERNAME@$SSH_HOST" "$remote_cmd"
  else
    ssh \
      -i "$SSH_KEY_FILE" \
      -p "$SSH_PORT" \
      -o ConnectTimeout="$SSH_TIMEOUT" \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new \
      -n \
      "$SSH_USERNAME@$SSH_HOST" "$remote_cmd"
  fi
}
```

> [!TIP]
> Notice the `-n` flag: it redirects `stdin` from `/dev/null`, preventing background commands or loops from hanging Open Terminal waiting for input.

---

### 3. Structured System Status Probe

Inspect overall server health in a single network round-trip:

```bash
ssh_exec '
echo "<<<SECTION:OS>>>"
cat /etc/os-release 2>/dev/null | grep -E "^(PRETTY_NAME|VERSION_ID)="
echo "<<<SECTION:UPTIME>>>"
uptime
echo "<<<SECTION:MEMORY>>>"
free -h
echo "<<<SECTION:DISK>>>"
df -h /
'
```

---

### 4. Running Shell Commands & Diagnostics

```bash
# Check CPU architecture and kernel
ssh_exec "uname -a"

# List top 10 memory-consuming processes
ssh_exec "ps aux --sort=-%mem | head -n 11"

# Check active listening network ports
ssh_exec "ss -tulpn"

# Check Docker containers (if installed)
ssh_exec "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
```

---

### 5. File Operations

#### Read Remote Files
```bash
REMOTE_FILE="/etc/nginx/nginx.conf"

# Read first 100 lines
ssh_exec "head -n 100 -- '$REMOTE_FILE'"

# Search for directives in configuration
ssh_exec "grep -rn 'server_name' /etc/nginx/sites-enabled/ 2>/dev/null"
```

#### Safely Write Remote Files (Stdin Stream)
To write files safely without escaping quotes or breaking formatting:

```bash
REMOTE_DEST="/tmp/custom_app.conf"
CONTENT="server {
    listen 80;
    server_name example.local;
}"

# Safely transmit content via SSH stdin without shell escaping issues:
printf '%s' "$CONTENT" | ssh \
  -i "$SSH_KEY_FILE" \
  -p "$SSH_PORT" \
  -o ConnectTimeout="$SSH_TIMEOUT" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  "$SSH_USERNAME@$SSH_HOST" "cat > $(printf '%q' "$REMOTE_DEST")"
echo "[+] Successfully wrote $REMOTE_DEST"
```

#### Upload via SCP (if local file exists in Open Terminal)
```bash
scp -i "$SSH_KEY_FILE" -P "$SSH_PORT" local_file.txt "$SSH_USERNAME@$SSH_HOST:/tmp/"
```

---

### 6. Systemd Service Management

Always pass `--no-pager` to prevent `systemctl` from hanging in a `less` view:

```bash
SERVICE="nginx"

# Check status
ssh_exec "systemctl status $SERVICE --no-pager"

# Check if active (returns active / inactive)
ssh_exec "systemctl is-active $SERVICE"

# Restart service (requires sudo if not running as root)
ssh_exec "sudo systemctl restart $SERVICE"

# Inspect latest 30 lines of service journal
ssh_exec "journalctl -u $SERVICE -n 30 --no-pager"
```

---

### 7. Interactive / Long-Running Command Precautions

When executing commands over SSH from Open Terminal:
1. **Never run interactive prompts**: Always add non-interactive flags (e.g. `DEBIAN_FRONTEND=noninteractive apt-get update -y`).
2. **Handle sudo passwords**: Stream the password securely via stdin rather than interpolating into command strings:
   ```bash
   printf '%s\n' "$SSH_PASSWORD" | ssh \
     -i "$SSH_KEY_FILE" \
     -p "$SSH_PORT" \
     -o ConnectTimeout="$SSH_TIMEOUT" \
     -o StrictHostKeyChecking=accept-new \
     "$SSH_USERNAME@$SSH_HOST" "sudo -S -p '' systemctl restart nginx"
   ```
3. **Bound Output**: Prevent log flooding by piping commands to `head -n 50` or `tail -n 50`.

---

## 4. Troubleshooting Common Issues

| Symptom / Error | Root Cause | Solution |
| :--- | :--- | :--- |
| **`Tools disabled / Tool not found`** | Open WebUI is using `open-terminal` without Python tool bindings. | Switch to **Mode B** and use the `ssh_exec` helper or native `ssh` commands. |
| **`Permission denied (publickey)`** | Private key not matching server's `authorized_keys` or wrong username. | Verify `SSH_USERNAME` and ensure the public key is in `~/.ssh/authorized_keys` on Ubuntu. |
| **`Host key verification failed`** | Host key mismatch or strict checking on new container. | Pass `-o StrictHostKeyChecking=accept-new` in SSH options. |
| **`Command hangs indefinitely`** | Process is waiting for `stdin` or interactive pager. | Pass `-n` to SSH, and pass `--no-pager` to `systemctl` and `journalctl`. |
| **`sudo: a terminal is required to read the password`** | Remote `sudoers` requires a tty (`requiretty`). | Pass `-t` or `-tt` to SSH for a pseudo-terminal: `ssh -tt -i ...`. |
