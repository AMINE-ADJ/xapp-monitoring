#!/bin/bash
#
# Simple KPM Data Collector
# Captures xApp output and converts to CSV
#

NAMESPACE="blueprint"
DURATION=${1:-30}
OUTPUT_DIR="/mnt/Studies/Sorbonne/CELL/xapp-monitoring/xapp-dataset/data"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p $OUTPUT_DIR

CSV_FILE="$OUTPUT_DIR/kpm_data_${TIMESTAMP}.csv"
RAW_FILE="$OUTPUT_DIR/kpm_raw_${TIMESTAMP}.log"

FLEXRIC_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-flexric -o jsonpath='{.items[0].metadata.name}')

echo "=============================================="
echo "KPM Data Collector"
echo "=============================================="
echo "FlexRIC Pod: $FLEXRIC_POD"
echo "Duration: $DURATION seconds"
echo "Output: $CSV_FILE"
echo ""

# Write CSV header
echo "timestamp,sample_id,ue_id,pdcp_sdu_volume_dl_kb,pdcp_sdu_volume_ul_kb,rlc_sdu_delay_dl_us,ue_throughput_dl_kbps,ue_throughput_ul_kbps,prb_total_dl,prb_total_ul" > $CSV_FILE

echo "Starting data collection (press Ctrl+C to stop)..."
echo ""

# Capture and process xApp output
timeout $DURATION kubectl exec -it $FLEXRIC_POD -n $NAMESPACE -- /flexric/build/examples/xApp/c/monitor/xapp_kpm_moni 2>&1 | tee $RAW_FILE | awk '
BEGIN {
    sample_id = 0
    ue_id = 0
    pdcp_dl = 0
    pdcp_ul = 0
    rlc_delay = 0
    thp_dl = 0
    thp_ul = 0
    prb_dl = 0
    prb_ul = 0
}
/KPM ind_msg latency/ {
    match($0, /([0-9]+)[[:space:]]+KPM/, arr)
    sample_id = arr[1]
}
/amf_ue_ngap_id =/ {
    match($0, /amf_ue_ngap_id = ([0-9]+)/, arr)
    ue_id = arr[1]
}
/DRB\.PdcpSduVolumeDL =/ {
    match($0, /= ([0-9]+)/, arr)
    pdcp_dl = arr[1]
}
/DRB\.PdcpSduVolumeUL =/ {
    match($0, /= ([0-9]+)/, arr)
    pdcp_ul = arr[1]
}
/DRB\.RlcSduDelayDl =/ {
    match($0, /= ([0-9.]+)/, arr)
    rlc_delay = arr[1]
}
/DRB\.UEThpDl =/ {
    match($0, /= ([0-9.]+)/, arr)
    thp_dl = arr[1]
}
/DRB\.UEThpUl =/ {
    match($0, /= ([0-9.]+)/, arr)
    thp_ul = arr[1]
}
/RRU\.PrbTotDl =/ {
    match($0, /= ([0-9]+)/, arr)
    prb_dl = arr[1]
}
/RRU\.PrbTotUl =/ {
    match($0, /= ([0-9]+)/, arr)
    prb_ul = arr[1]
    # Print complete record
    timestamp = strftime("%Y-%m-%dT%H:%M:%S")
    print timestamp "," sample_id "," ue_id "," pdcp_dl "," pdcp_ul "," rlc_delay "," thp_dl "," thp_ul "," prb_dl "," prb_ul >> "'$CSV_FILE'"
    fflush("'$CSV_FILE'")
}
'

echo ""
echo "=============================================="
echo "COLLECTION COMPLETE"
echo "=============================================="

# Count records
if [ -f "$CSV_FILE" ]; then
    RECORD_COUNT=$(wc -l < $CSV_FILE)
    RECORD_COUNT=$((RECORD_COUNT - 1))
    echo "Total samples collected: $RECORD_COUNT"
    echo "CSV file: $CSV_FILE"
    echo "Raw log: $RAW_FILE"
    echo ""
    echo "Sample data:"
    head -6 $CSV_FILE | column -t -s,
else
    echo "No data collected"
fi
