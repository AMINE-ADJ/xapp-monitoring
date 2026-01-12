#!/bin/bash
#
# KPM Experiment Runner
# Runs traffic experiments while collecting KPM metrics
#

NAMESPACE="blueprint"
DURATION=${1:-60}  # Default 60 seconds
OUTPUT_DIR="/tmp/kpm_dataset"
EXPERIMENT_NAME=${2:-"experiment"}

echo "=============================================="
echo "KPM Experiment Runner"
echo "=============================================="
echo "Namespace: $NAMESPACE"
echo "Duration: $DURATION seconds"
echo "Output: $OUTPUT_DIR"
echo ""

# Get pod names
UE_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-nr-ue -o jsonpath='{.items[0].metadata.name}')
FLEXRIC_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-flexric -o jsonpath='{.items[0].metadata.name}')

echo "UE Pod: $UE_POD"
echo "FlexRIC Pod: $FLEXRIC_POD"
echo ""

# Create output directory
mkdir -p $OUTPUT_DIR

# Timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
CSV_FILE="$OUTPUT_DIR/kpm_${EXPERIMENT_NAME}_${TIMESTAMP}.csv"
LOG_FILE="$OUTPUT_DIR/kpm_${EXPERIMENT_NAME}_${TIMESTAMP}.log"

echo "Starting data collection..."
echo "CSV output: $CSV_FILE"
echo ""

# Write CSV header
echo "sample_id,timestamp,ue_id,pdcp_sdu_volume_dl_kb,pdcp_sdu_volume_ul_kb,rlc_sdu_delay_dl_us,ue_throughput_dl_kbps,ue_throughput_ul_kbps,prb_total_dl,prb_total_ul,traffic_type" > $CSV_FILE

# Function to parse xApp output and write to CSV
parse_xapp_output() {
    local traffic_type=$1
    local sample_id=0
    
    while IFS= read -r line; do
        # Skip non-data lines
        if [[ $line =~ ^[[:space:]]*([0-9]+)[[:space:]]+KPM ]]; then
            sample_id=${BASH_REMATCH[1]}
            timestamp=$(date +%Y-%m-%dT%H:%M:%S)
        fi
        
        if [[ $line =~ amf_ue_ngap_id[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            ue_id=${BASH_REMATCH[1]}
        fi
        
        if [[ $line =~ DRB\.PdcpSduVolumeDL[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            pdcp_dl=${BASH_REMATCH[1]}
        fi
        
        if [[ $line =~ DRB\.PdcpSduVolumeUL[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            pdcp_ul=${BASH_REMATCH[1]}
        fi
        
        if [[ $line =~ DRB\.RlcSduDelayDl[[:space:]]*=[[:space:]]*([0-9.]+) ]]; then
            rlc_delay=${BASH_REMATCH[1]}
        fi
        
        if [[ $line =~ DRB\.UEThpDl[[:space:]]*=[[:space:]]*([0-9.]+) ]]; then
            thp_dl=${BASH_REMATCH[1]}
        fi
        
        if [[ $line =~ DRB\.UEThpUl[[:space:]]*=[[:space:]]*([0-9.]+) ]]; then
            thp_ul=${BASH_REMATCH[1]}
        fi
        
        if [[ $line =~ RRU\.PrbTotDl[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            prb_dl=${BASH_REMATCH[1]}
        fi
        
        if [[ $line =~ RRU\.PrbTotUl[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            prb_ul=${BASH_REMATCH[1]}
            # Write complete record
            echo "$sample_id,$timestamp,$ue_id,$pdcp_dl,$pdcp_ul,$rlc_delay,$thp_dl,$thp_ul,$prb_dl,$prb_ul,$traffic_type" >> $CSV_FILE
        fi
        
        # Echo to log
        echo "$line"
    done
}

# Start xApp in background and capture output
echo "Starting KPM xApp..."
timeout $DURATION kubectl exec -it $FLEXRIC_POD -n $NAMESPACE -- /flexric/build/examples/xApp/c/monitor/xapp_kpm_moni 2>&1 | parse_xapp_output "baseline" &
XAPP_PID=$!

# Wait a few seconds for xApp to initialize
sleep 5

# Run different traffic patterns
echo ""
echo "=============================================="
echo "Phase 1: Baseline (idle) - 10 seconds"
echo "=============================================="
sleep 10

echo ""
echo "=============================================="
echo "Phase 2: Ping traffic - 15 seconds"
echo "=============================================="
kubectl exec -it $UE_POD -n $NAMESPACE -- ping -c 15 -I oaitun_ue1 12.1.1.1 &
PING_PID=$!
sleep 15
kill $PING_PID 2>/dev/null || true

echo ""
echo "=============================================="
echo "Phase 3: iperf3 DL traffic - 15 seconds"
echo "=============================================="
# Note: This requires iperf3 server running on UPF side
kubectl exec -it $UE_POD -n $NAMESPACE -- iperf3 -c 12.1.1.1 -t 15 -R 2>/dev/null || echo "iperf3 DL skipped (server not available)"

echo ""
echo "=============================================="
echo "Phase 4: iperf3 UL traffic - 15 seconds"
echo "=============================================="
kubectl exec -it $UE_POD -n $NAMESPACE -- iperf3 -c 12.1.1.1 -t 15 2>/dev/null || echo "iperf3 UL skipped (server not available)"

# Wait for remaining time
REMAINING=$((DURATION - 55))
if [ $REMAINING -gt 0 ]; then
    echo ""
    echo "=============================================="
    echo "Collecting remaining data - $REMAINING seconds"
    echo "=============================================="
    sleep $REMAINING
fi

# Wait for xApp to finish
wait $XAPP_PID 2>/dev/null || true

# Count records
RECORD_COUNT=$(wc -l < $CSV_FILE)
RECORD_COUNT=$((RECORD_COUNT - 1))  # Subtract header

echo ""
echo "=============================================="
echo "EXPERIMENT COMPLETE"
echo "=============================================="
echo "Total samples collected: $RECORD_COUNT"
echo "Dataset saved to: $CSV_FILE"
echo ""

# Show sample of data
echo "Sample data (first 5 records):"
head -6 $CSV_FILE | column -t -s,
