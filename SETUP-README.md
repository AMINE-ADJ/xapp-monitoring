# 5G Infrastructure Auto-Setup

This directory contains scripts to automatically deploy and manage a complete 5G infrastructure with FlexRIC for xApp development and KPM monitoring.

## Components

- **OAI 5G Core**: MySQL, AMF, SMF, UPF, NRF, UDM, UDR, AUSF
- **FlexRIC**: Near-RT RIC with E2 interface
- **OAI gNB**: 5G base station with RF simulator
- **OAI NR-UE**: 5G User Equipment

## Quick Start

After rebooting your PC, simply run:

```bash
cd /mnt/Studies/Sorbonne/CELL/xapp-monitoring
./quick-start.sh
```

This will:
1. Check if minikube is running (start if needed)
2. Deploy all 5G components in correct order
3. Wait for UE to establish PDU session
4. Verify connectivity

## Scripts

| Script | Description |
|--------|-------------|
| `quick-start.sh` | Quick start - checks status and runs setup if needed |
| `setup-5g-infrastructure.sh` | Full setup script with all steps |
| `start-collection.sh` | Start data collection with traffic generation |
| `install-autostart.sh` | Install as systemd service for auto-start on boot |

## Usage

### Manual Start (after reboot)

```bash
# Quick start
./quick-start.sh

# Or full setup with verbose output
./setup-5g-infrastructure.sh
```

### Check Status

```bash
./setup-5g-infrastructure.sh --status
```

### Restart UE Only

```bash
./setup-5g-infrastructure.sh --restart-ue
```

### Stop Infrastructure

```bash
./setup-5g-infrastructure.sh --stop
# Or simply
minikube stop
```

### Start Data Collection

```bash
# Default: 5 minutes, 20 Mbps
./start-collection.sh

# Custom: 10 minutes, 50 Mbps
./start-collection.sh 600 50M
```

## Auto-Start on Boot (Optional)

To automatically start the 5G infrastructure when your PC boots:

```bash
# Install the systemd service
sudo ./install-autostart.sh

# Enable auto-start
sudo systemctl enable 5g-infrastructure

# Check status
sudo systemctl status 5g-infrastructure

# View logs
journalctl -u 5g-infrastructure -f
```

**Note:** First boot takes ~5-10 minutes. Subsequent boots are faster.

## Manual Data Collection

```bash
# Start the collector (runs for 2 minutes)
cd cell_xapp_monitor
python3 cell_xapp_monitor.py -d 120 -o ./data &

# Generate traffic from UE to UPF
kubectl exec -n blueprint <ue-pod> -c nr-ue -- iperf3 -c <upf-ip> -t 120 -b 20M

# Check collected data
wc -l ./data/cell_monitoring_dataset.csv
head -5 ./data/cell_monitoring_dataset.csv
```

## Troubleshooting

### UE Tunnel Not Coming Up

```bash
# Restart UE
./setup-5g-infrastructure.sh --restart-ue

# Or manually
kubectl delete pod -n blueprint $(kubectl get pods -n blueprint | grep oai-nr-ue | awk '{print $1}')
```

### Check Logs

```bash
# AMF (registration)
kubectl logs -n blueprint $(kubectl get pods -n blueprint | grep oai-amf | awk '{print $1}') --tail=50

# gNB
kubectl logs -n blueprint $(kubectl get pods -n blueprint | grep oai-gnb | awk '{print $1}') --tail=50

# UE
kubectl logs -n blueprint $(kubectl get pods -n blueprint | grep oai-nr-ue | awk '{print $1}') --tail=50

# FlexRIC
kubectl logs -n blueprint $(kubectl get pods -n blueprint | grep oai-flexric | awk '{print $1}') --tail=50
```

### Complete Reset

```bash
# Delete namespace and recreate
kubectl delete namespace blueprint
./setup-5g-infrastructure.sh
```

## Expected Setup Time

| Scenario | Time |
|----------|------|
| Fresh install (first time) | ~10-15 minutes |
| After reboot (cached) | ~3-5 minutes |
| UE restart only | ~1-2 minutes |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Minikube                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                   5G Core Network                    │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐   │   │
│  │  │ NRF │ │ AMF │ │ SMF │ │ UPF │ │ UDM │ │ UDR │   │   │
│  │  └─────┘ └──┬──┘ └──┬──┘ └──┬──┘ └─────┘ └─────┘   │   │
│  └─────────────┼───────┼───────┼─────────────────────────┘   │
│                │       │       │                            │
│  ┌─────────────┼───────┼───────┼─────────────────────────┐   │
│  │             │    FlexRIC    │                         │   │
│  │        ┌────┴───────┴───────┴────┐                    │   │
│  │        │      Near-RT RIC        │◄──── xApps        │   │
│  │        └────────────┬────────────┘                    │   │
│  └─────────────────────┼─────────────────────────────────┘   │
│                        │ E2                                 │
│  ┌─────────────────────┼─────────────────────────────────┐   │
│  │                     ▼                                 │   │
│  │              ┌──────────┐                             │   │
│  │              │   gNB    │ (RF Simulator)              │   │
│  │              └────┬─────┘                             │   │
│  │                   │                                   │   │
│  │              ┌────▼─────┐                             │   │
│  │              │    UE    │ (IP: 12.1.1.2)              │   │
│  │              └──────────┘                             │   │
│  └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```
