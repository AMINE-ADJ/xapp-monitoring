# 5G/KPM xApp Experimentation Platform

This project implements a complete 5G experimentation platform using OAI (OpenAirInterface) and FlexRIC, designed for developing and monitoring KPM (Key Performance Metric) xApps.

## Project Overview

The system deploys a full 5G network (Core, RAN, UE) and a Near-RT RIC (FlexRIC) on a Kubernetes cluster (Minikube). It includes a custom xApp for monitoring real-time network metrics.

### Components

- **OAI 5G Core**: AMF, SMF, UPF, NRF, UDM, UDR, AUSF, MySQL.
- **FlexRIC**: Near-RT RIC with E2 interface support.
- **OAI gNB**: 5G Base Station (simulated RF).
- **OAI NR-UE**: 5G User Equipment (simulated).
- **KPM xApp**: Custom xApp for metric collection.

## Quick Start

### 1. Prerequisite
- Linux OS (Ubuntu/Arch/Fedora)
- Minikube & Docker
- Ansible (for deployment orchestration)

### 2. Deploy Network
To deploy the entire 5G infrastructure (fresh start):

```bash
./start_5g.sh
```

This script will:
1. Start/Check Minikube.
2. Clean up any stale deployments.
3. specific Ansible playbook to deploy all components in the correct order.

_Deployment takes approximately 3-5 minutes._

### 3. Verify Deployment
Check the status of the pods:

```bash
kubectl get pods -n blueprint -w
```
Wait until all pods (Core, gNB, UE, FlexRIC) are in `Running` state.

## Data Collection

To generate traffic (iperf3) and collect KPM metrics:

```bash
./start-collection.sh <duration_in_seconds> <bandwidth>
```

**Example:** Run for 60 seconds with 20Mbps traffic:
```bash
./start-collection.sh 60 20M
```

This script handles:
1. Verifying UPF and UE connectivity.
2. Auto-installing `iperf3` on the UPF if missing.
3. Starting the xApp monitor.
4. Generating traffic from UE -> UPF.
5. Saving results to `cell_xapp_monitor/data/`.

## Architecture

```
+-------------------------------------------------------------------------+
|                                Minikube                                 |
|                                                                         |
|   +-----------------------------------------------------------------+   |
|   |                        5G Core Network                          |   |
|   |                                                                 |   |
|   |  +-----+  +-----+  +-----+  +-----+  +-----+  +-----+           |   |
|   |  | NRF |  | AMF |  | SMF |  | UPF |  | UDM |  | UDR |           |   |
|   |  +-----+  +--+--+  +--+--+  +--+--+  +-----+  +-----+           |   |
|   |              |        |        |                                |   |
|   +--------------+--------+--------+--------------------------------+   |
|                  |        |        |                                    |
|   +--------------+--------+--------+--------------------------------+   |
|   |              |     FlexRIC     |                                |   |
|   |              |        |        |                                |   |
|   |        +-----+--------+--------+----+                           |   |
|   |        |        Near-RT RIC         | <----------- xApps        |   |
|   |        +------------+-+-------------+                           |   |
|   |                     | | E2                                      |   |
|   +---------------------+-+-----------------------------------------+   |
|                         | |                                             |
|   +---------------------+-+-----------------------------------------+   |
|   |              +------v------+                                    |   |
|   |              |     gNB     |  (RF Simulator)                    |   |
|   |              +------+------+                                    |   |
|   |                     |                                           |   |
|   |              +------v------+                                    |   |
|   |              |     UE      |  (IP: 12.1.1.2)                    |   |
|   |              +-------------+                                    |   |
|   +-----------------------------------------------------------------+   |
|                                                                         |
+-------------------------------------------------------------------------+
```

## Directory Structure

- `start_5g.sh`: Main deployment script.
- `start-collection.sh`: Traffic generation and data collection script.
- `roles/`: Ansible roles for component deployment.
- `inventories/`: Ansible inventory configurations.
- `cell_xapp_monitor/`: Python scripts for xApp monitoring and data storage.
