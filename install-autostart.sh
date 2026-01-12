#!/bin/bash
#===============================================================================
# Install 5G Infrastructure as a Systemd Service
# Run this script once to enable auto-start on boot
#===============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="5g-infrastructure"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Installing 5G Infrastructure Auto-Start Service..."

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "This script requires sudo privileges to install the systemd service."
    echo "Please run: sudo $0"
    exit 1
fi

# Get the actual user (not root when using sudo)
ACTUAL_USER="${SUDO_USER:-$USER}"
ACTUAL_HOME=$(eval echo "~$ACTUAL_USER")

echo "Installing service for user: $ACTUAL_USER"
echo "Script directory: $SCRIPT_DIR"

# Create the service file from template
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=5G Infrastructure Auto-Setup (OAI + FlexRIC)
After=network.target docker.service
Wants=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=$ACTUAL_USER
Environment="HOME=$ACTUAL_HOME"
Environment="PATH=/usr/local/bin:/usr/bin:/bin:$ACTUAL_HOME/.local/bin"
Environment="KUBECONFIG=$ACTUAL_HOME/.kube/config"
WorkingDirectory=$SCRIPT_DIR
ExecStart=/bin/bash $SCRIPT_DIR/setup-5g-infrastructure.sh
ExecStop=/usr/local/bin/minikube stop
TimeoutStartSec=900
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Make setup script executable
chmod +x "$SCRIPT_DIR/setup-5g-infrastructure.sh"

# Reload systemd
systemctl daemon-reload

echo ""
echo "Service installed successfully!"
echo ""
echo "Available commands:"
echo "  Enable auto-start on boot:"
echo "    sudo systemctl enable $SERVICE_NAME"
echo ""
echo "  Start the service now:"
echo "    sudo systemctl start $SERVICE_NAME"
echo ""
echo "  Check service status:"
echo "    sudo systemctl status $SERVICE_NAME"
echo ""
echo "  View logs:"
echo "    journalctl -u $SERVICE_NAME -f"
echo ""
echo "  Disable auto-start:"
echo "    sudo systemctl disable $SERVICE_NAME"
echo ""
echo "  Stop the service:"
echo "    sudo systemctl stop $SERVICE_NAME"
echo ""
echo "NOTE: The first boot after enabling will take ~5-10 minutes to deploy everything."
echo "      Subsequent boots will be faster as containers are cached."
