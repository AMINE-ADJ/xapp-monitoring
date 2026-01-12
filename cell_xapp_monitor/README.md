# CELL xApp Monitor

## Cloud-based 5G Environment KPM Monitoring xApp

This xApp leverages the **KPM (Key Performance Measurement) Service Model** within **FlexRIC** to monitor and observe various performance metrics in a cloud-based 5G environment. It collects data through experiments and creates datasets for further analysis.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         5G Cloud Environment                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐          │
│  │   UE    │────│   gNB   │────│   AMF   │────│   SMF   │          │
│  │ (RFSIM) │    │(E2 Node)│    │         │    │         │          │
│  └─────────┘    └────┬────┘    └─────────┘    └────┬────┘          │
│                      │                              │               │
│                      │ E2 Interface                 │               │
│                      │                              │               │
│                 ┌────┴────┐                    ┌────┴────┐          │
│                 │ FlexRIC │                    │   UPF   │          │
│                 │Near-RT  │                    │         │          │
│                 │   RIC   │                    └─────────┘          │
│                 └────┬────┘                                         │
│                      │                                              │
│              ┌───────┴───────┐                                      │
│              │ CELL xApp     │                                      │
│              │  Monitor      │                                      │
│              │               │                                      │
│              │ ┌───────────┐ │                                      │
│              │ │KPM Service│ │                                      │
│              │ │  Model    │ │                                      │
│              │ └───────────┘ │                                      │
│              └───────┬───────┘                                      │
│                      │                                              │
│              ┌───────┴───────┐                                      │
│              │  CSV Dataset  │                                      │
│              │   Export      │                                      │
│              └───────────────┘                                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### KPM Metrics Collected

| Metric Name | Description | Unit | Source |
|-------------|-------------|------|--------|
| `DRB.PdcpSduVolumeDL` | PDCP SDU Volume Downlink | kb | gNB |
| `DRB.PdcpSduVolumeUL` | PDCP SDU Volume Uplink | kb | gNB |
| `DRB.RlcSduDelayDl` | RLC SDU Delay Downlink | μs | gNB |
| `DRB.UEThpDl` | UE Throughput Downlink | kbps | gNB |
| `DRB.UEThpUl` | UE Throughput Uplink | kbps | gNB |
| `RRU.PrbTotDl` | Total PRB Usage Downlink | PRBs | gNB |
| `RRU.PrbTotUl` | Total PRB Usage Uplink | PRBs | gNB |

### O-RAN Compliance

This xApp implements the **O-RAN E2SM-KPM** (E2 Service Model for Key Performance Measurement) specification:
- **3GPP TS 28.552**: Performance measurements for 5G NR
- **O-RAN.WG3.E2SM-KPM-v02.00**: E2 Service Model for KPM

### Quick Start

```bash
# 1. Run the data collector
./cell_xapp_monitor.py --duration 300 --output ./data

# 2. Run with traffic generation experiment
./run_experiment.sh 300 full_experiment

# 3. Analyze collected data
python3 analyze_dataset.py ./data/kpm_dataset_*.csv
```

### Output Format

The collected data is exported to CSV with the following schema:

```csv
timestamp,sample_id,ue_id,pdcp_dl_kb,pdcp_ul_kb,rlc_delay_us,thp_dl_kbps,thp_ul_kbps,prb_dl,prb_ul,experiment_phase
2026-01-11T23:00:00,1,2,3,5,0.00,3.86,7.35,9437,9630,baseline
```

### Project Structure

```
cell_xapp_monitor/
├── README.md                 # This file
├── cell_xapp_monitor.py      # Main xApp data collector
├── run_experiment.sh         # Traffic experiment runner
├── analyze_dataset.py        # Dataset analysis tool
├── config.yaml               # Configuration file
└── data/                     # Output datasets
```

### Authors

CELL Lab - Sorbonne University
5G Network Monitoring Research Project

### License

OpenAirInterface Public License v1.1
