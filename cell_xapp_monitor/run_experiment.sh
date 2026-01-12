#!/bin/bash
#
# CELL xApp Monitor - Experiment Runner
# Runs traffic experiments while collecting KPM metrics
#
# Author: CELL Lab - Sorbonne University
#

set -e

# Configuration
NAMESPACE="blueprint"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/data"
DURATION=${1:-120}
EXPERIMENT_NAME=${2:-"experiment"}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "\n${BLUE}======================================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}======================================================================${NC}\n"
}

print_phase() {
    echo -e "\n${GREEN}>>> Phase: $1${NC}\n"
}

print_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get pod names
get_pods() {
    UE_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-nr-ue -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    FLEXRIC_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-flexric -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    GNB_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-gnb -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -z "$UE_POD" ] || [ -z "$FLEXRIC_POD" ]; then
        print_error "Required pods not found!"
        exit 1
    fi
}

# Check connectivity
check_connectivity() {
    print_info "Checking UE connectivity..."
    if kubectl exec $UE_POD -n $NAMESPACE -- ping -c 1 -W 2 -I oaitun_ue1 12.1.1.1 &>/dev/null; then
        print_info "UE connectivity: OK"
        return 0
    else
        print_error "UE connectivity: FAILED"
        return 1
    fi
}

# Main experiment function
run_experiment() {
    print_header "CELL xApp Monitor - Experiment Runner"
    
    echo "Configuration:"
    echo "  Namespace      : $NAMESPACE"
    echo "  Duration       : $DURATION seconds"
    echo "  Experiment     : $EXPERIMENT_NAME"
    echo "  Output Dir     : $OUTPUT_DIR"
    echo ""
    
    get_pods
    
    echo "Pods:"
    echo "  FlexRIC Pod    : $FLEXRIC_POD"
    echo "  UE Pod         : $UE_POD"
    echo "  gNB Pod        : $GNB_POD"
    echo ""
    
    # Check connectivity
    if ! check_connectivity; then
        print_error "UE not connected. Aborting experiment."
        exit 1
    fi
    
    # Create output directory
    mkdir -p "$OUTPUT_DIR"
    
    # Timestamp for this experiment
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    CSV_FILE="$OUTPUT_DIR/kpm_${EXPERIMENT_NAME}_${TIMESTAMP}.csv"
    LOG_FILE="$OUTPUT_DIR/kpm_${EXPERIMENT_NAME}_${TIMESTAMP}.log"
    RAW_FILE="$OUTPUT_DIR/kpm_${EXPERIMENT_NAME}_${TIMESTAMP}_raw.log"
    
    print_info "Output files:"
    print_info "  CSV  : $CSV_FILE"
    print_info "  Log  : $LOG_FILE"
    
    # Write CSV header
    echo "timestamp,sample_id,ue_id,pdcp_dl_kb,pdcp_ul_kb,rlc_delay_us,thp_dl_kbps,thp_ul_kbps,prb_dl,prb_ul,phase" > "$CSV_FILE"
    
    # Calculate phase durations
    PHASE_BASELINE=$((DURATION / 6))
    PHASE_PING=$((DURATION / 6))
    PHASE_DL=$((DURATION / 6))
    PHASE_UL=$((DURATION / 6))
    PHASE_BIDIR=$((DURATION / 6))
    PHASE_FINAL=$((DURATION - PHASE_BASELINE - PHASE_PING - PHASE_DL - PHASE_UL - PHASE_BIDIR))
    
    print_header "Starting KPM Data Collection"
    
    # Start xApp and process output
    {
        timeout $DURATION kubectl exec -it $FLEXRIC_POD -n $NAMESPACE -- \
            /flexric/build/examples/xApp/c/monitor/xapp_kpm_moni 2>&1
    } | tee "$RAW_FILE" | while IFS= read -r line; do
        echo "$line" >> "$LOG_FILE"
        
        # Parse and extract data
        if [[ $line =~ ^[[:space:]]*([0-9]+)[[:space:]]+KPM ]]; then
            SAMPLE_ID="${BASH_REMATCH[1]}"
            TIMESTAMP_NOW=$(date +%Y-%m-%dT%H:%M:%S)
        fi
        
        [[ $line =~ amf_ue_ngap_id[[:space:]]*=[[:space:]]*([0-9]+) ]] && UE_ID="${BASH_REMATCH[1]}"
        [[ $line =~ DRB\.PdcpSduVolumeDL[[:space:]]*=[[:space:]]*([0-9]+) ]] && PDCP_DL="${BASH_REMATCH[1]}"
        [[ $line =~ DRB\.PdcpSduVolumeUL[[:space:]]*=[[:space:]]*([0-9]+) ]] && PDCP_UL="${BASH_REMATCH[1]}"
        [[ $line =~ DRB\.RlcSduDelayDl[[:space:]]*=[[:space:]]*([0-9.]+) ]] && RLC_DELAY="${BASH_REMATCH[1]}"
        [[ $line =~ DRB\.UEThpDl[[:space:]]*=[[:space:]]*([0-9.]+) ]] && THP_DL="${BASH_REMATCH[1]}"
        [[ $line =~ DRB\.UEThpUl[[:space:]]*=[[:space:]]*([0-9.]+) ]] && THP_UL="${BASH_REMATCH[1]}"
        [[ $line =~ RRU\.PrbTotDl[[:space:]]*=[[:space:]]*([0-9]+) ]] && PRB_DL="${BASH_REMATCH[1]}"
        
        if [[ $line =~ RRU\.PrbTotUl[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
            PRB_UL="${BASH_REMATCH[1]}"
            # Determine phase based on sample ID
            if [ -n "$SAMPLE_ID" ]; then
                if [ "$SAMPLE_ID" -le "$PHASE_BASELINE" ]; then
                    PHASE="baseline"
                elif [ "$SAMPLE_ID" -le "$((PHASE_BASELINE + PHASE_PING))" ]; then
                    PHASE="ping"
                elif [ "$SAMPLE_ID" -le "$((PHASE_BASELINE + PHASE_PING + PHASE_DL))" ]; then
                    PHASE="download"
                elif [ "$SAMPLE_ID" -le "$((PHASE_BASELINE + PHASE_PING + PHASE_DL + PHASE_UL))" ]; then
                    PHASE="upload"
                elif [ "$SAMPLE_ID" -le "$((PHASE_BASELINE + PHASE_PING + PHASE_DL + PHASE_UL + PHASE_BIDIR))" ]; then
                    PHASE="bidirectional"
                else
                    PHASE="cooldown"
                fi
            fi
            # Write complete record
            echo "$TIMESTAMP_NOW,$SAMPLE_ID,$UE_ID,$PDCP_DL,$PDCP_UL,$RLC_DELAY,$THP_DL,$THP_UL,$PRB_DL,$PRB_UL,$PHASE" >> "$CSV_FILE"
        fi
    done &
    COLLECTOR_PID=$!
    
    # Give xApp time to initialize
    sleep 8
    
    # Phase 1: Baseline (idle)
    print_phase "BASELINE (Idle Network) - ${PHASE_BASELINE}s"
    sleep $PHASE_BASELINE
    
    # Phase 2: Ping traffic
    print_phase "PING Traffic - ${PHASE_PING}s"
    kubectl exec $UE_POD -n $NAMESPACE -- ping -c $PHASE_PING -i 1 -I oaitun_ue1 12.1.1.1 &>/dev/null &
    PING_PID=$!
    sleep $PHASE_PING
    kill $PING_PID 2>/dev/null || true
    
    # Phase 3: Download traffic (high rate ping flood)
    print_phase "DOWNLOAD Traffic - ${PHASE_DL}s"
    kubectl exec $UE_POD -n $NAMESPACE -- ping -f -c 5000 -I oaitun_ue1 12.1.1.1 &>/dev/null &
    sleep $PHASE_DL
    
    # Phase 4: Upload traffic
    print_phase "UPLOAD Traffic - ${PHASE_UL}s"
    kubectl exec $UE_POD -n $NAMESPACE -- ping -f -c 5000 -s 1400 -I oaitun_ue1 12.1.1.1 &>/dev/null &
    sleep $PHASE_UL
    
    # Phase 5: Bidirectional traffic
    print_phase "BIDIRECTIONAL Traffic - ${PHASE_BIDIR}s"
    kubectl exec $UE_POD -n $NAMESPACE -- ping -c $PHASE_BIDIR -i 0.5 -s 1000 -I oaitun_ue1 12.1.1.1 &>/dev/null &
    sleep $PHASE_BIDIR
    
    # Phase 6: Cooldown
    print_phase "COOLDOWN - ${PHASE_FINAL}s"
    sleep $PHASE_FINAL
    
    # Wait for collector to finish
    wait $COLLECTOR_PID 2>/dev/null || true
    
    # Print summary
    print_header "EXPERIMENT COMPLETE"
    
    if [ -f "$CSV_FILE" ]; then
        RECORD_COUNT=$(wc -l < "$CSV_FILE")
        RECORD_COUNT=$((RECORD_COUNT - 1))
        
        echo "Results:"
        echo "  Total samples collected: $RECORD_COUNT"
        echo "  CSV file: $CSV_FILE"
        echo ""
        
        if [ $RECORD_COUNT -gt 0 ]; then
            echo "Sample data (first 5 records):"
            head -6 "$CSV_FILE" | column -t -s,
            echo ""
            
            echo "Phase distribution:"
            tail -n +2 "$CSV_FILE" | cut -d, -f11 | sort | uniq -c
        fi
    else
        print_error "No data collected"
    fi
}

# Run the experiment
run_experiment
