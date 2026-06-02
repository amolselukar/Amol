#!/bin/bash
set -e

PA_USER="Selukar"
PA_HOST="ssh.pythonanywhere.com"
KEY_PATH="$HOME/.ssh/pythonanywhere_ed25519"

echo "=== PythonAnywhere SSH Setup ==="

# Generate SSH key if it doesn't exist
if [ -f "$KEY_PATH" ]; then
    echo "SSH key already exists at $KEY_PATH"
else
    echo "Generating SSH key..."
    mkdir -p "$HOME/.ssh"
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" -C "pythonanywhere-${PA_USER}"
    echo "Key generated."
fi

# Copy public key to PythonAnywhere (will prompt for password one last time)
echo ""
echo "Copying public key to PythonAnywhere..."
echo "You will be prompted for your PythonAnywhere password ONE LAST TIME."
echo ""
ssh-copy-id -i "$KEY_PATH.pub" "${PA_USER}@${PA_HOST}"

# Add SSH config entry
SSH_CONFIG="$HOME/.ssh/config"
if grep -q "Host pythonanywhere" "$SSH_CONFIG" 2>/dev/null; then
    echo "SSH config entry already exists."
else
    echo "" >> "$SSH_CONFIG"
    cat >> "$SSH_CONFIG" <<EOF

Host pythonanywhere
    HostName ${PA_HOST}
    User ${PA_USER}
    IdentityFile ${KEY_PATH}
    ControlMaster auto
    ControlPath ~/.ssh/control-%r@%h:%p
    ControlPersist 10m
EOF
    chmod 600 "$SSH_CONFIG"
    echo "SSH config entry added."
fi

echo ""
echo "=== Setup Complete ==="
echo "Connect with:  ssh pythonanywhere"
echo "Copy files:    scp file.py pythonanywhere:~/"
