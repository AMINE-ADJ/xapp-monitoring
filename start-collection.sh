#!/bin/bash
# start-collection.sh
# Automates Traffic Generation (iperf3) AND KPM xApp Collection

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="blueprint"
DURATION=${1:-60}  # Default 60 seconds
BANDWIDTH=${2:-20M}

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║      5G Traffic Generation & xApp Data Collection             ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo "Duration: ${DURATION}s | Bandwidth: ${BANDWIDTH}"
echo ""

# 1. Infrastructure Checks
# ------------------------------------------------------------------
echo "[INFO] Checking infrastructure..."
UE_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-nr-ue -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
UPF_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-upf -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
FLEXRIC_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-flexric -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [[ -z "$UE_POD" || -z "$UPF_POD" || -z "$FLEXRIC_POD" ]]; then
    echo "[ERROR] Pods not found. Is the network deployed?"
    exit 1
fi

UPF_IP="12.1.1.1" # Fixed OAI UPF IP
echo "UE: $UE_POD"
echo "UPF: $UPF_POD ($UPF_IP)"
echo "RIC: $FLEXRIC_POD"

# Check UE Tunnel
if ! kubectl exec -n $NAMESPACE $UE_POD -c nr-ue -- ip addr show oaitun_ue1 | grep -q "inet"; then
    echo "[ERROR] UE tunnel (oaitun_ue1) is NOT active. Traffic will fail."
    exit 1
fi

# 2. Setup iperf3 on UPF
# ------------------------------------------------------------------
echo ""
echo "[INFO] Setting up iperf3 Server on UPF..."
if ! kubectl exec -n $NAMESPACE $UPF_POD -- which iperf3 >/dev/null 2>&1; then
    echo "       Installing iperf3..."
    kubectl exec -n $NAMESPACE $UPF_POD -- bash -c "apt-get update && apt-get install -y iperf3" >/dev/null 2>&1
fi
kubectl exec -n $NAMESPACE $UPF_POD -- pkill iperf3 2>/dev/null || true
kubectl exec -n $NAMESPACE $UPF_POD -- iperf3 -s -p 5201 -D 2>/dev/null

# 3. Deploy & Compile xApp on FlexRIC
# ------------------------------------------------------------------
echo ""
echo "[INFO] Deploying KPM xApp to FlexRIC..."
XAPP_SRC="$SCRIPT_DIR/flexric_xapp/xapp_kpm_metrics_collector_v2.c"
REMOTE_DIR="/flexric/examples/xApp/c/monitor"

if [ ! -f "$XAPP_SRC" ]; then
    echo "[ERROR] Source file not found: $XAPP_SRC"
    exit 1
fi

# Copy Source
kubectl cp "$XAPP_SRC" "$NAMESPACE/$FLEXRIC_POD:$REMOTE_DIR/xapp_kpm_metrics_collector_v2.c"

# Compile
echo "[INFO] Compiling xApp..."
kubectl exec -n $NAMESPACE $FLEXRIC_POD -- bash -c "
cd $REMOTE_DIR
gcc -o xapp_kpm_v2 xapp_kpm_metrics_collector_v2.c \
    -I/flexric/src -I/flexric/build/src \
    -DKPM_V3_00 -DE2AP_V3 \
    -L/flexric/build/src/xApp -le42_xapp_shared -lpthread -lsctp
cp xapp_kpm_v2 /flexric/build/examples/xApp/c/monitor/
"

# 4. Start Collection & Traffic
# ------------------------------------------------------------------
echo ""
echo "[INFO] Starting Collection & Traffic (Duration: ${DURATION}s)..."

# Output file path in pod
POD_OUTPUT="/tmp/kpm_metrics.csv"

# Start xApp (Background)
# We use stdbuf to avoid buffering issues and timeout to stop it automatically
kubectl exec -n $NAMESPACE $FLEXRIC_POD -- bash -c "
    export LD_LIBRARY_PATH=/flexric/build/src/xApp:/usr/local/lib:\$LD_LIBRARY_PATH
    timeout $((DURATION + 5)) /flexric/build/examples/xApp/c/monitor/xapp_kpm_v2 > $POD_OUTPUT 2>&1
" &
XAPP_PID=$!

# Start Traffic (Background)
sleep 2 # Give xApp a moment to subscribe
kubectl exec -n $NAMESPACE $UE_POD -c nr-ue -- iperf3 -c $UPF_IP -p 5201 -t $DURATION -b $BANDWIDTH >/dev/null &
TRAFFIC_PID=$!

echo "       xApp PID: $XAPP_PID"
echo "       Traffic PID: $TRAFFIC_PID"
echo "       Waiting for test to complete..."

# Wait for xApp to finish (it controls the duration via timeout)
wait $XAPP_PID 2>/dev/null || true

# 5. Retrieve Results
# ------------------------------------------------------------------
echo ""
echo "[INFO] Retrieving Dataset..."
DATA_DIR="$SCRIPT_DIR/xapp-dataset"
mkdir -p "$DATA_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOCAL_FILE="$DATA_DIR/kpm_metrics_${TIMESTAMP}.csv"
LOG_FILE="$DATA_DIR/gnb_logs_${TIMESTAMP}.txt"
FINAL_FILE="$DATA_DIR/dataset_full_${TIMESTAMP}.csv"

# Start Log Capture
echo "[INFO] Capturing gNB and Core Network logs..."
GNB_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-gnb -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
AMF_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-amf -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
SMF_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-smf -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
# UPF_POD is already defined at start

# Define CN Log Files
LOG_AMF="$DATA_DIR/cn_logs_amf_${TIMESTAMP}.txt"
LOG_SMF="$DATA_DIR/cn_logs_smf_${TIMESTAMP}.txt"
LOG_UPF="$DATA_DIR/cn_logs_upf_${TIMESTAMP}.txt"

# Start background captures
kubectl logs -f -n $NAMESPACE $GNB_POD > "$LOG_FILE" 2>&1 &
PID_GNB=$!
kubectl logs -f -n $NAMESPACE $AMF_POD > "$LOG_AMF" 2>&1 &
PID_AMF=$!
kubectl logs -f -n $NAMESPACE $SMF_POD > "$LOG_SMF" 2>&1 &
PID_SMF=$!
kubectl logs -f -n $NAMESPACE $UPF_POD > "$LOG_UPF" 2>&1 &
PID_UPF=$!

if kubectl cp "$NAMESPACE/$FLEXRIC_POD:/tmp/kpm_metrics_dataset.csv" "$LOCAL_FILE" 2>/dev/null; then
    ROWS=$(wc -l < "$LOCAL_FILE")
    echo "[SUCCESS] Data saved to: $LOCAL_FILE"
    echo "          Rows collected: $ROWS"
    
    # Stop Log Captures
    kill $PID_GNB $PID_AMF $PID_SMF $PID_UPF 2>/dev/null || true
    
    # Merge Data
    echo ""
    echo "[INFO] Merging with gNB and Core Network logs..."
    # Pass all log files to the python script
    python3 "$SCRIPT_DIR/merge_metrics.py" "$LOCAL_FILE" "$LOG_FILE" "$FINAL_FILE" "--amf" "$LOG_AMF" "--smf" "$LOG_SMF" "--upf" "$LOG_UPF"
    
    echo ""
    echo "Sample Data (Final):"
    if [ -f "$FINAL_FILE" ]; then
        head -n 5 "$FINAL_FILE"
    else
        head -n 5 "$LOCAL_FILE"
    fi
else
    kill $LOG_PID 2>/dev/null || true
    echo "[WARN] Could not retrieve data file. xApp might have failed or produced no output."
    echo "       Checking xApp logs..."
    kubectl exec -n $NAMESPACE $FLEXRIC_POD -- cat $POD_OUTPUT
fi
