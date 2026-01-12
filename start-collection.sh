#!/bin/bash
#===============================================================================
# Start Data Collection with Traffic Generation
# Run this after the 5G infrastructure is up
#===============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="blueprint"
DURATION=${1:-300}  # Default 5 minutes
BANDWIDTH=${2:-20M}  # Default 20 Mbps

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║         Start Data Collection                                 ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "Duration: ${DURATION}s, Bandwidth: ${BANDWIDTH}"
echo ""

# Check if infrastructure is running
UE_POD=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep "oai-nr-ue" | grep "Running" | awk '{print $1}' | head -1)
GNB_POD=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep "oai-gnb" | grep "Running" | awk '{print $1}' | head -1)

if [ -z "$UE_POD" ] || [ -z "$GNB_POD" ]; then
    echo "[ERROR] 5G infrastructure not running. Please run ./quick-start.sh first"
    exit 1
fi

# Get gNB IP (we'll use gNB as iperf server since it has iperf3)
GNB_IP=$(kubectl get pods -n $NAMESPACE -o wide | grep "oai-gnb" | awk '{print $6}')

# Check UE tunnel
TUNNEL_IP=$(kubectl exec -n $NAMESPACE $UE_POD -c nr-ue -- ip addr show oaitun_ue1 2>/dev/null | grep "inet " | awk '{print $2}' | cut -d'/' -f1)

if [ -z "$TUNNEL_IP" ]; then
    echo "[ERROR] UE tunnel not ready. Wait a moment and try again."
    exit 1
fi

echo "[INFO] UE Pod: $UE_POD"
echo "[INFO] UE Tunnel IP: $TUNNEL_IP"
echo "[INFO] gNB Pod: $GNB_POD"
echo "[INFO] gNB IP: $GNB_IP"
echo ""

# Clear old data
rm -f "$SCRIPT_DIR/cell_xapp_monitor/data/cell_monitoring_dataset.csv"

# Start iperf3 server on gNB
echo "[INFO] Starting iperf3 server on gNB..."
kubectl exec -n $NAMESPACE $GNB_POD -- pkill iperf3 2>/dev/null || true
kubectl exec -n $NAMESPACE $GNB_POD -- iperf3 -s -p 5201 -D 2>/dev/null &
sleep 2

# Start data collector
echo "[INFO] Starting data collector (duration: ${DURATION}s)..."
cd "$SCRIPT_DIR/cell_xapp_monitor"
python3 cell_xapp_monitor.py -d $DURATION -o ./data &
COLLECTOR_PID=$!
sleep 5

# Start traffic generation
echo "[INFO] Starting traffic generation (${BANDWIDTH} for ${DURATION}s)..."
kubectl exec -n $NAMESPACE $UE_POD -c nr-ue -- iperf3 -c $GNB_IP -p 5201 -t $DURATION -b $BANDWIDTH &
TRAFFIC_PID=$!

echo ""
echo "[INFO] Data collection and traffic generation started!"
echo "[INFO] Collector PID: $COLLECTOR_PID"
echo "[INFO] Traffic PID: $TRAFFIC_PID"
echo ""
echo "Data will be saved to: $SCRIPT_DIR/cell_xapp_monitor/data/cell_monitoring_dataset.csv"
echo ""
echo "To monitor progress:"
echo "  watch -n 5 'wc -l $SCRIPT_DIR/cell_xapp_monitor/data/cell_monitoring_dataset.csv'"
echo ""
echo "To stop early:"
echo "  kill $COLLECTOR_PID $TRAFFIC_PID"
