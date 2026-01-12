#!/bin/bash
#
# Build and Deploy KPM Metrics Collector xApp
#
# This script:
# 1. Copies the xApp source to the FlexRIC pod
# 2. Compiles it inside the pod
# 3. Runs the xApp to collect metrics
# 4. Retrieves the dataset
#

set -e

NAMESPACE="${NAMESPACE:-blueprint}"
FLEXRIC_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=oai-flexric -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || \
              kubectl get pods -n $NAMESPACE | grep flexric | awk '{print $1}' | head -1)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XAPP_NAME="xapp_kpm_metrics_collector"
OUTPUT_DIR="${SCRIPT_DIR}/data"
TARGET_SAMPLES="${1:-1000}"

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║     KPM Metrics Collector - Build and Deploy Script           ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "FlexRIC Pod: $FLEXRIC_POD"
echo "Namespace: $NAMESPACE"
echo "Target Samples: $TARGET_SAMPLES"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Step 1: Copy source files to FlexRIC pod
echo "[1/5] Copying source files to FlexRIC pod..."
kubectl cp "${SCRIPT_DIR}/${XAPP_NAME}.c" "$NAMESPACE/$FLEXRIC_POD:/flexric/examples/xApp/c/monitor/${XAPP_NAME}.c"

# Step 2: Compile the xApp inside the pod
echo "[2/5] Compiling xApp inside FlexRIC pod..."
kubectl exec -n $NAMESPACE $FLEXRIC_POD -- bash -c "
cd /flexric/examples/xApp/c/monitor

# Create a simple Makefile for our xApp
cat > Makefile.kpm << 'EOF'
CC = gcc
CFLAGS = -Wall -Wextra -O2 -I/flexric/src -I/flexric/build/src
LDFLAGS = -L/flexric/build/src/xApp -le42_xapp_shared -lpthread -lsctp

xapp_kpm_metrics_collector: xapp_kpm_metrics_collector.c
	\$(CC) \$(CFLAGS) -o \$@ \$< \$(LDFLAGS)

clean:
	rm -f xapp_kpm_metrics_collector
EOF

# Compile
make -f Makefile.kpm clean 2>/dev/null || true
make -f Makefile.kpm

# Move to build directory
cp xapp_kpm_metrics_collector /flexric/build/examples/xApp/c/monitor/
"

echo "[3/5] xApp compiled successfully!"

# Step 3: Verify the compilation
echo "[4/5] Verifying compiled xApp..."
kubectl exec -n $NAMESPACE $FLEXRIC_POD -- ls -la /flexric/build/examples/xApp/c/monitor/xapp_kpm_metrics_collector

# Step 4: Run the xApp
echo "[5/5] Running xApp to collect $TARGET_SAMPLES samples..."
echo ""

# Run the xApp with timeout
TIMEOUT=$((TARGET_SAMPLES * 2 + 60))  # Rough estimate: 2 seconds per sample + buffer
kubectl exec -n $NAMESPACE $FLEXRIC_POD -- timeout $TIMEOUT /flexric/build/examples/xApp/c/monitor/xapp_kpm_metrics_collector -n $TARGET_SAMPLES -o /tmp/kpm_dataset.csv || true

# Copy the dataset back
echo ""
echo "Copying dataset from pod..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="${OUTPUT_DIR}/kpm_metrics_${TIMESTAMP}.csv"
kubectl cp "$NAMESPACE/$FLEXRIC_POD:/tmp/kpm_dataset.csv" "$OUTPUT_FILE"

# Show results
if [ -f "$OUTPUT_FILE" ]; then
    LINES=$(wc -l < "$OUTPUT_FILE")
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                  Dataset Collection Complete                   ║"
    echo "╠═══════════════════════════════════════════════════════════════╣"
    echo "║  Samples collected: $(printf '%-10s' $((LINES-1)))                              ║"
    echo "║  Output file: $(printf '%-47s' "$OUTPUT_FILE")║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "First 5 data rows:"
    head -6 "$OUTPUT_FILE" | tail -5 | cut -c1-100
    echo ""
else
    echo "ERROR: Failed to retrieve dataset"
    exit 1
fi
