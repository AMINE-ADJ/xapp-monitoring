#!/bin/bash
#===============================================================================
# Quick Start - 5G Infrastructure
# Use this script to quickly bring up the 5G stack after a reboot
# without installing as a systemd service
#===============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║         5G Quick Start                                        ║"
echo "╚═══════════════════════════════════════════════════════════════╝"

# Check if minikube is running
if minikube status --format='{{.Host}}' 2>/dev/null | grep -q "Running"; then
    echo "[INFO] Minikube is already running"
    
    # Check if pods exist
    if kubectl get pods -n blueprint 2>/dev/null | grep -q "Running"; then
        echo "[INFO] 5G pods are already running"
        echo ""
        echo "Current status:"
        kubectl get pods -n blueprint
        
        # Check UE tunnel
        UE_POD=$(kubectl get pods -n blueprint --no-headers | grep "oai-nr-ue" | grep "Running" | awk '{print $1}' | head -1)
        if [ -n "$UE_POD" ]; then
            echo ""
            echo "UE Tunnel:"
            kubectl exec -n blueprint $UE_POD -c nr-ue -- ip addr show oaitun_ue1 2>/dev/null | grep "inet " || echo "  Tunnel not ready yet"
        fi
        
        echo ""
        echo "To restart everything, run: $SCRIPT_DIR/setup-5g-infrastructure.sh"
        exit 0
    fi
fi

# Run full setup
echo "[INFO] Starting full 5G infrastructure setup..."
exec "$SCRIPT_DIR/setup-5g-infrastructure.sh"
