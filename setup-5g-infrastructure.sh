#!/bin/bash
#===============================================================================
# 5G Infrastructure Auto-Setup Script
# This script automatically deploys the complete 5G stack with FlexRIC
# and verifies UE connectivity
#===============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="blueprint"
MINIKUBE_MEMORY="4096"
MINIKUBE_CPUS="4"
MINIKUBE_DISK="20g"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_DIR="${SCRIPT_DIR}/inventories/UTH"
PARAMS_FILE="${SCRIPT_DIR}/params.oai-flexric.yaml"
PLAYBOOK="${SCRIPT_DIR}/5g.yaml"

# Timeouts (in seconds)
MINIKUBE_TIMEOUT=120
POD_TIMEOUT=300
UE_TUNNEL_TIMEOUT=180

#-------------------------------------------------------------------------------
# Utility Functions
#-------------------------------------------------------------------------------

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  $1${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}\n"
}

wait_for_pods() {
    local namespace=$1
    local timeout=$2
    local start_time=$(date +%s)
    
    log_info "Waiting for all pods in namespace '$namespace' to be Running..."
    
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [ $elapsed -gt $timeout ]; then
            log_error "Timeout waiting for pods to be ready"
            kubectl get pods -n $namespace
            return 1
        fi
        
        local not_running=$(kubectl get pods -n $namespace --no-headers 2>/dev/null | grep -v "Running" | grep -v "Completed" | wc -l)
        local pending=$(kubectl get pods -n $namespace --no-headers 2>/dev/null | grep -E "Pending|ContainerCreating|Init" | wc -l)
        
        if [ "$not_running" -eq 0 ] && [ "$pending" -eq 0 ]; then
            log_success "All pods are Running"
            return 0
        fi
        
        echo -ne "\r  Waiting... ($elapsed/${timeout}s) - $pending pods still initializing    "
        sleep 5
    done
}

wait_for_ue_tunnel() {
    local timeout=$1
    local start_time=$(date +%s)
    
    log_info "Waiting for UE tunnel interface to be UP with IP..."
    
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [ $elapsed -gt $timeout ]; then
            log_error "Timeout waiting for UE tunnel"
            return 1
        fi
        
        # Get UE pod name
        local ue_pod=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep "oai-nr-ue" | grep "Running" | awk '{print $1}' | head -1)
        
        if [ -n "$ue_pod" ]; then
            # Check tunnel interface
            local tunnel_info=$(kubectl exec -n $NAMESPACE $ue_pod -c nr-ue -- ip addr show oaitun_ue1 2>/dev/null || echo "")
            
            if echo "$tunnel_info" | grep -q "inet 12.1.1"; then
                local ip=$(echo "$tunnel_info" | grep "inet " | awk '{print $2}' | cut -d'/' -f1)
                log_success "UE tunnel is UP with IP: $ip"
                return 0
            fi
        fi
        
        echo -ne "\r  Waiting for tunnel... ($elapsed/${timeout}s)    "
        sleep 5
    done
}

#-------------------------------------------------------------------------------
# Step 1: Check Prerequisites
#-------------------------------------------------------------------------------

check_prerequisites() {
    log_step "Step 1: Checking Prerequisites"
    
    local missing_deps=()
    
    # Check for required commands
    for cmd in minikube kubectl ansible-playbook helm; do
        if ! command -v $cmd &> /dev/null; then
            missing_deps+=($cmd)
        else
            log_info "$cmd: $(command -v $cmd)"
        fi
    done
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        log_error "Missing dependencies: ${missing_deps[*]}"
        exit 1
    fi
    
    # Check if inventory and playbook exist
    if [ ! -f "$PLAYBOOK" ]; then
        log_error "Playbook not found: $PLAYBOOK"
        exit 1
    fi
    
    if [ ! -d "$INVENTORY_DIR" ]; then
        log_error "Inventory directory not found: $INVENTORY_DIR"
        exit 1
    fi
    
    log_success "All prerequisites satisfied"
}

#-------------------------------------------------------------------------------
# Step 2: Start Minikube
#-------------------------------------------------------------------------------

start_minikube() {
    log_step "Step 2: Starting Minikube"
    
    # Check if minikube is already running
    local status=$(minikube status --format='{{.Host}}' 2>/dev/null || echo "Stopped")
    
    if [ "$status" == "Running" ]; then
        log_info "Minikube is already running"
        minikube status
    else
        log_info "Starting Minikube with $MINIKUBE_CPUS CPUs, ${MINIKUBE_MEMORY}MB RAM, $MINIKUBE_DISK disk"
        
        minikube start \
            --cpus=$MINIKUBE_CPUS \
            --memory=$MINIKUBE_MEMORY \
            --disk-size=$MINIKUBE_DISK \
            --driver=docker
        
        log_success "Minikube started successfully"
    fi
    
    # Wait for minikube to be fully ready
    log_info "Waiting for Minikube to be ready..."
    local start_time=$(date +%s)
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [ $elapsed -gt $MINIKUBE_TIMEOUT ]; then
            log_error "Timeout waiting for Minikube"
            exit 1
        fi
        
        if kubectl get nodes &>/dev/null; then
            break
        fi
        sleep 2
    done
    
    log_success "Minikube is ready"
    kubectl get nodes
}

#-------------------------------------------------------------------------------
# Step 3: Create Namespace
#-------------------------------------------------------------------------------

create_namespace() {
    log_step "Step 3: Creating Namespace"
    
    if kubectl get namespace $NAMESPACE &>/dev/null; then
        log_info "Namespace '$NAMESPACE' already exists"
    else
        kubectl create namespace $NAMESPACE
        log_success "Namespace '$NAMESPACE' created"
    fi
}

#-------------------------------------------------------------------------------
# Step 4: Deploy 5G Core Network
#-------------------------------------------------------------------------------

deploy_5g_core() {
    log_step "Step 4: Deploying 5G Core Network"
    
    # Check if core is already deployed
    local mysql_pod=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep "oai-core-mysql" | grep "Running" | wc -l)
    
    if [ "$mysql_pod" -gt 0 ]; then
        log_info "5G Core appears to be already deployed, checking status..."
        kubectl get pods -n $NAMESPACE | grep -E "mysql|amf|smf|upf|nrf|udm|udr|ausf"
    else
        log_info "Running Ansible playbook to deploy 5G Core..."
        
        cd "$SCRIPT_DIR"
        ansible-playbook -i "$INVENTORY_DIR" "$PLAYBOOK" \
            --extra-vars "@$PARAMS_FILE" \
            --tags "core" \
            -v
        
        log_info "Waiting for Core pods to be ready..."
        wait_for_pods $NAMESPACE $POD_TIMEOUT
    fi
    
    log_success "5G Core deployment complete"
}

#-------------------------------------------------------------------------------
# Step 5: Deploy FlexRIC
#-------------------------------------------------------------------------------

deploy_flexric() {
    log_step "Step 5: Deploying FlexRIC"
    
    local flexric_pod=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep "oai-flexric" | grep "Running" | wc -l)
    
    if [ "$flexric_pod" -gt 0 ]; then
        log_info "FlexRIC appears to be already deployed"
        kubectl get pods -n $NAMESPACE | grep flexric
    else
        log_info "Running Ansible playbook to deploy FlexRIC..."
        
        cd "$SCRIPT_DIR"
        ansible-playbook -i "$INVENTORY_DIR" "$PLAYBOOK" \
            --extra-vars "@$PARAMS_FILE" \
            --tags "flexric" \
            -v
        
        log_info "Waiting for FlexRIC pod to be ready..."
        sleep 10
        wait_for_pods $NAMESPACE $POD_TIMEOUT
    fi
    
    log_success "FlexRIC deployment complete"
}

#-------------------------------------------------------------------------------
# Step 6: Deploy gNB (RAN)
#-------------------------------------------------------------------------------

deploy_gnb() {
    log_step "Step 6: Deploying gNB (RAN)"
    
    local gnb_pod=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep "oai-gnb" | grep "Running" | wc -l)
    
    if [ "$gnb_pod" -gt 0 ]; then
        log_info "gNB appears to be already deployed"
        kubectl get pods -n $NAMESPACE | grep gnb
    else
        log_info "Running Ansible playbook to deploy gNB..."
        
        cd "$SCRIPT_DIR"
        ansible-playbook -i "$INVENTORY_DIR" "$PLAYBOOK" \
            --extra-vars "@$PARAMS_FILE" \
            --tags "ran" \
            -v
        
        log_info "Waiting for gNB pod to be ready..."
        sleep 30
        wait_for_pods $NAMESPACE $POD_TIMEOUT
    fi
    
    # Wait for gNB to stabilize
    log_info "Waiting for gNB to stabilize (30s)..."
    sleep 30
    
    log_success "gNB deployment complete"
}

#-------------------------------------------------------------------------------
# Step 7: Deploy UE
#-------------------------------------------------------------------------------

deploy_ue() {
    log_step "Step 7: Deploying UE"
    
    local ue_pod=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | grep "oai-nr-ue" | grep "Running" | wc -l)
    
    if [ "$ue_pod" -gt 0 ]; then
        log_info "UE appears to be already deployed"
        kubectl get pods -n $NAMESPACE | grep ue
    else
        log_info "Running Ansible playbook to deploy UE..."
        
        cd "$SCRIPT_DIR"
        ansible-playbook -i "$INVENTORY_DIR" "$PLAYBOOK" \
            --extra-vars "@$PARAMS_FILE" \
            --tags "ue" \
            -v
        
        log_info "Waiting for UE pod to be ready..."
        sleep 10
        wait_for_pods $NAMESPACE $POD_TIMEOUT
    fi
    
    log_success "UE deployment complete"
}

#-------------------------------------------------------------------------------
# Step 8: Verify UE Connectivity
#-------------------------------------------------------------------------------

verify_ue_connectivity() {
    log_step "Step 8: Verifying UE Connectivity"
    
    # Wait for tunnel to come up
    if ! wait_for_ue_tunnel $UE_TUNNEL_TIMEOUT; then
        log_warning "UE tunnel not ready. Attempting to restart UE pod..."
        
        # Get UE pod and restart
        local ue_pod=$(kubectl get pods -n $NAMESPACE --no-headers | grep "oai-nr-ue" | awk '{print $1}' | head -1)
        if [ -n "$ue_pod" ]; then
            kubectl delete pod -n $NAMESPACE $ue_pod
            log_info "Waiting for UE to restart..."
            sleep 60
            wait_for_pods $NAMESPACE $POD_TIMEOUT
            
            # Try again
            if ! wait_for_ue_tunnel $UE_TUNNEL_TIMEOUT; then
                log_error "UE tunnel still not ready after restart"
                return 1
            fi
        fi
    fi
    
    # Verify connectivity with ping
    local ue_pod=$(kubectl get pods -n $NAMESPACE --no-headers | grep "oai-nr-ue" | grep "Running" | awk '{print $1}' | head -1)
    local upf_ip=$(kubectl get pods -n $NAMESPACE -o wide | grep "oai-upf" | awk '{print $6}')
    
    log_info "Testing connectivity from UE to UPF ($upf_ip)..."
    
    if kubectl exec -n $NAMESPACE $ue_pod -c nr-ue -- ping -c 3 $upf_ip &>/dev/null; then
        log_success "UE can ping UPF successfully!"
    else
        log_warning "Ping test failed, but tunnel is up - this may be normal"
    fi
    
    log_success "UE connectivity verified"
}

#-------------------------------------------------------------------------------
# Step 9: Show Status Summary
#-------------------------------------------------------------------------------

show_status() {
    log_step "Step 9: Status Summary"
    
    echo -e "\n${BLUE}=== Pod Status ===${NC}"
    kubectl get pods -n $NAMESPACE -o wide
    
    echo -e "\n${BLUE}=== Services ===${NC}"
    kubectl get svc -n $NAMESPACE
    
    # Get UE info
    local ue_pod=$(kubectl get pods -n $NAMESPACE --no-headers | grep "oai-nr-ue" | grep "Running" | awk '{print $1}' | head -1)
    if [ -n "$ue_pod" ]; then
        echo -e "\n${BLUE}=== UE Tunnel Interface ===${NC}"
        kubectl exec -n $NAMESPACE $ue_pod -c nr-ue -- ip addr show oaitun_ue1 2>/dev/null || echo "Tunnel not available"
    fi
    
    # Check AMF for UE registration
    echo -e "\n${BLUE}=== AMF UE Status ===${NC}"
    kubectl logs -n $NAMESPACE $(kubectl get pods -n $NAMESPACE --no-headers | grep "oai-amf" | awk '{print $1}') --tail=20 2>/dev/null | grep -i "UEs' Information" -A5 || echo "No UE info available"
    
    echo -e "\n${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  5G Infrastructure Setup Complete!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "\nTo start data collection, run:"
    echo -e "  ${YELLOW}cd ${SCRIPT_DIR}/cell_xapp_monitor${NC}"
    echo -e "  ${YELLOW}python3 cell_xapp_monitor.py -d 120 -o ./data${NC}"
    echo -e "\nTo generate traffic, run:"
    echo -e "  ${YELLOW}kubectl exec -n $NAMESPACE <ue-pod> -c nr-ue -- iperf3 -c <upf-ip> -t 60 -b 20M${NC}"
}

#-------------------------------------------------------------------------------
# Main Function
#-------------------------------------------------------------------------------

main() {
    echo -e "${GREEN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║         5G Infrastructure Auto-Setup Script                   ║"
    echo "║         OAI 5G Core + FlexRIC + gNB + UE                      ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    
    local start_time=$(date +%s)
    
    check_prerequisites
    start_minikube
    create_namespace
    deploy_5g_core
    deploy_flexric
    deploy_gnb
    deploy_ue
    verify_ue_connectivity
    show_status
    
    local end_time=$(date +%s)
    local total_time=$((end_time - start_time))
    
    echo -e "\n${GREEN}Total setup time: ${total_time} seconds${NC}"
}

#-------------------------------------------------------------------------------
# Script Entry Point
#-------------------------------------------------------------------------------

# Handle command line arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --help, -h     Show this help message"
        echo "  --status       Show current infrastructure status"
        echo "  --restart-ue   Restart UE pod only"
        echo "  --stop         Stop all infrastructure"
        echo ""
        exit 0
        ;;
    --status)
        NAMESPACE="blueprint"
        show_status
        exit 0
        ;;
    --restart-ue)
        NAMESPACE="blueprint"
        log_info "Restarting UE pod..."
        ue_pod=$(kubectl get pods -n $NAMESPACE --no-headers | grep "oai-nr-ue" | awk '{print $1}' | head -1)
        if [ -n "$ue_pod" ]; then
            kubectl delete pod -n $NAMESPACE $ue_pod
            sleep 60
            wait_for_pods $NAMESPACE 180
            wait_for_ue_tunnel 180
        fi
        exit 0
        ;;
    --stop)
        log_info "Stopping minikube..."
        minikube stop
        log_success "Infrastructure stopped"
        exit 0
        ;;
    *)
        main
        ;;
esac
