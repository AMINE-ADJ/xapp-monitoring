#!/bin/bash

# start_5g.sh
# One-click script to deploy the 5G network
# ROBUST VERSION: Handles Minikube failures and cleanups automatically.

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_info() { echo -e "${BLUE}[INFO] $1${NC}"; }
log_success() { echo -e "${GREEN}[SUCCESS] $1${NC}"; }
log_error() { echo -e "${RED}[ERROR] $1${NC}"; }
log_warn() { echo -e "\033[0;33m[WARN] $1${NC}"; }

# Function to check if Minikube is responsive
check_minikube_health() {
    log_info "Checking Minikube API server health..."
    if kubectl get nodes --request-timeout=5s >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Function to repair Minikube
repair_minikube() {
    log_warn "Minikube appears unresponsive or broken."
    log_info "Attempting to restart Minikube..."
    minikube stop 2>/dev/null || true
    
    # Try simple start first
    if minikube start; then
         log_info "Waiting for API server..."
         sleep 10
         if check_minikube_health; then
            log_success "Minikube recovered!"
            return 0
         fi
    fi

    # If simple start fails, do hard reset
    log_warn "Standard restart failed. Performing HARD RESET (delete & recreate)..."
    minikube delete --all --purge
    # Ensure no zombie processes
    pkill -f "minikube" || true
    
    log_info "Starting fresh Minikube cluster..."
    if minikube start; then
        log_success "Minikube hard reset successful!"
        return 0
    else
        log_error "Failed to start Minikube even after hard reset."
        exit 1
    fi
}

# 1. Minikube Health Check & Repair
if ! check_minikube_health; then
    repair_minikube
else
    log_success "Minikube is healthy."
fi

# 2. Fix Environment
log_info "Refreshing kubectl context..."
minikube update-context
eval $(minikube docker-env)

# 3. Robust Cleanup
log_info "Cleaning up old deployments..."
HELMS=("oai-core" "oai-flexric" "oai-gnb" "oai-nr-ue")
for release in "${HELMS[@]}"; do
    if helm list -n blueprint -q | grep -q "^$release$"; then
        log_info "Uninstalling $release..."
        helm uninstall $release -n blueprint --wait --timeout 1m 2>/dev/null || true
    fi
done

# Force delete namespace if stuck (optional, but safer to just clean resources)
# We avoid deleting the namespace if possible to speed things up, but ensure it's clean.
log_info "Ensuring 'blueprint' namespace exists..."
kubectl create namespace blueprint --dry-run=client -o yaml | kubectl apply -f -

# 4. Wait for Node Readiness (Double Check)
log_info "Verifying Node Readiness..."
kubectl wait --for=condition=Ready node --all --timeout=60s

# 5. Run Ansible Deployment
log_info "Starting Ansible Deployment..."
cd "$SCRIPT_DIR"

# Ensure Ansible Galaxy dependencies if needed (though locally we assume they are there)
# ansible-galaxy collection install -r requirements.yml 2>/dev/null || true

ansible-playbook -i inventories/UTH 5g.yaml --extra-vars "@params.oai-flexric.yaml"

log_success "Deployment commands sent!"
log_info "Monitor status with: kubectl get pods -n blueprint -w"
