# FlexRIC KPM Metrics Collector - Documentation

## Overview

This xApp collects comprehensive 5G RAN metrics from OAI gNB via FlexRIC's E2 interface using multiple Service Models (SM). The data is exported to CSV for analysis, machine learning, and network optimization research.

## Data Collection Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   OAI UE    │────▶│   OAI gNB   │────▶│  FlexRIC    │────▶│   xApp      │
│             │     │  (E2 Agent) │     │ (nearRT-RIC)│     │  Collector  │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                           │                   │                   │
                     MAC/RLC/PDCP        E2AP Protocol        CSV Dataset
                       Stats              (SCTP)
```

## Service Models Used

| SM ID | Service Model | Description |
|-------|--------------|-------------|
| 142 | MAC_STATS_V0 | MAC layer statistics (scheduling, signal quality) |
| 143 | RLC_STATS_V0 | RLC layer statistics (retransmissions, buffers) |
| 144 | PDCP_STATS_V0 | PDCP layer statistics (encryption/integrity) |
| 148 | GTP_STATS_V0 | GTP tunnel statistics (core network) |
| 2 | ORAN-E2SM-KPM | O-RAN KPM (throughput, PRB usage) |

---

## Collected Metrics Reference

### 1. Signal Quality Metrics

| Metric | Unit | Range | Description | Interpretation |
|--------|------|-------|-------------|----------------|
| **pusch_snr** | dB | -10 to 60 | PUSCH Signal-to-Noise Ratio | **Best proxy for RSRP**. Higher = better UL signal. >30dB excellent, 20-30dB good, <15dB poor |
| **pucch_snr** | dB | -10 to 60 | PUCCH Signal-to-Noise Ratio | Control channel quality. Should be similar to PUSCH SNR |
| **cqi** | index | 0-15 | Channel Quality Indicator | UE-reported channel quality. 15=best (64QAM), 0=out of range. Related to achievable MCS |
| **dl_bler** | ratio | 0.0-1.0 | Downlink Block Error Rate | Fraction of failed DL transmissions. <1% normal, >10% indicates problems |
| **ul_bler** | ratio | 0.0-1.0 | Uplink Block Error Rate | Fraction of failed UL transmissions. Used for link adaptation |

#### Why These Matter:
- **SNR** is the most direct measure of radio link quality from gNB perspective
- **CQI** determines what modulation/coding the UE can decode
- **BLER** triggers MCS adaptation and HARQ retransmissions

#### RSRP Relationship:
```
RSRP is not directly available from FlexRIC/OAI, but:
- PUSCH_SNR ∝ UL_RSRP (correlated with uplink signal strength)
- CQI ∝ SINR ∝ RSRP - Interference (channel quality depends on RSRP)

For ML models, PUSCH_SNR + CQI together provide equivalent information.
```

---

### 2. Modulation & Coding Metrics

| Metric | Unit | Range | Description | Interpretation |
|--------|------|-------|-------------|----------------|
| **dl_mcs1** | index | 0-28 | DL MCS for codeword 0 | Higher MCS = higher spectral efficiency |
| **dl_mcs2** | index | 0-28 | DL MCS for codeword 1 | Used in MIMO spatial multiplexing |
| **ul_mcs1** | index | 0-28 | UL MCS for codeword 0 | Adapted based on UL BLER |
| **ul_mcs2** | index | 0-28 | UL MCS for codeword 1 | Secondary codeword |

#### MCS to Modulation Mapping (5G NR):
| MCS Range | Modulation | Target BLER | Typical SNR Required |
|-----------|------------|-------------|---------------------|
| 0-9 | QPSK | 10% | 0-10 dB |
| 10-16 | 16QAM | 10% | 10-17 dB |
| 17-28 | 64QAM | 10% | 17-25+ dB |

#### Why These Matter:
- MCS determines throughput capacity
- Rapid MCS changes indicate unstable channel
- Low MCS with high SNR → interference or misconfiguration

---

### 3. Transport Block Metrics

| Metric | Unit | Description | Interpretation |
|--------|------|-------------|----------------|
| **dl_tbs** | bytes | Current DL Transport Block Size | Size of current transmission |
| **ul_tbs** | bytes | Current UL Transport Block Size | Depends on MCS and PRB allocation |
| **dl_aggr_tbs** | bytes | Aggregated DL TBS (cumulative) | Total DL data transmitted |
| **ul_aggr_tbs** | bytes | Aggregated UL TBS (cumulative) | Total UL data transmitted |

#### Calculating Throughput:
```
Instantaneous Throughput ≈ TBS × (1000 / slot_duration_ms) × (1 - BLER)

For 30kHz SCS (slot = 0.5ms):
  Throughput_Mbps ≈ TBS_bytes × 8 × 2000 / 1e6 × (1 - BLER)
```

---

### 4. Physical Resource Block (PRB) Metrics

| Metric | Unit | Description | Interpretation |
|--------|------|-------------|----------------|
| **dl_prb** | PRBs | Aggregated DL PRB allocation | Total PRBs used for DL |
| **ul_prb** | PRBs | Aggregated UL PRB allocation | Total PRBs used for UL |
| **dl_sched_rb** | PRBs | Currently scheduled DL RBs | Instantaneous allocation |
| **ul_sched_rb** | PRBs | Currently scheduled UL RBs | Instantaneous allocation |

#### PRB Usage Analysis:
```
PRB Utilization = scheduled_rb / total_bandwidth_rb × 100%

For 40 MHz bandwidth (106 PRBs with 30kHz SCS):
- PRB util > 80%: High load, potential congestion
- PRB util 30-80%: Normal operation
- PRB util < 30%: Under-utilized or idle UE
```

---

### 5. Buffer Status & Power Headroom

| Metric | Unit | Description | Interpretation |
|--------|------|-------------|----------------|
| **bsr** | bytes | Buffer Status Report | UE's pending UL data. 0=empty, high=congestion |
| **phr** | dB | Power Headroom Report | UE's remaining TX power. Negative=power limited |

#### Why These Matter:
- **BSR** indicates UL traffic demand and queuing
- **PHR** shows if UE can increase TX power (cell edge issues)

| PHR Value | Meaning |
|-----------|---------|
| > 20 dB | Plenty of power headroom |
| 10-20 dB | Normal operation |
| 0-10 dB | Getting close to max power |
| < 0 dB | Power limited, may need handover |

---

### 6. RLC Layer Metrics

| Metric | Unit | Description | Interpretation |
|--------|------|-------------|----------------|
| **rlc_tx_pkts** | packets | RLC TX PDUs sent | Cumulative packet count |
| **rlc_tx_bytes** | bytes | RLC TX data volume | Total bytes sent |
| **rlc_rx_pkts** | packets | RLC RX PDUs received | Cumulative packet count |
| **rlc_rx_bytes** | bytes | RLC RX data volume | Total bytes received |
| **rlc_txbuf** | bytes | RLC TX buffer occupancy | Queued data awaiting TX |
| **rlc_rxbuf** | bytes | RLC RX buffer occupancy | Data awaiting reassembly |
| **rlc_retx** | packets | RLC retransmissions | Lost/corrupted packets |

#### Key Indicators:
```
Retransmission Rate = rlc_retx / rlc_tx_pkts × 100%

- < 1%: Excellent link quality
- 1-5%: Normal operation
- 5-10%: Degraded conditions
- > 10%: Significant problems (interference, mobility)
```

---

### 7. PDCP Layer Metrics

| Metric | Unit | Description | Interpretation |
|--------|------|-------------|----------------|
| **pdcp_tx_pkts** | packets | PDCP TX packets | IP packets sent |
| **pdcp_tx_bytes** | bytes | PDCP TX volume | IP data volume |
| **pdcp_rx_pkts** | packets | PDCP RX packets | IP packets received |
| **pdcp_rx_bytes** | bytes | PDCP RX volume | IP data volume |

#### PDCP vs RLC Comparison:
```
PDCP packets = IP packets (user data)
RLC packets = Radio segments (may be fragmented)

If PDCP_TX >> RLC_TX: Large IP packets being segmented
If RLC_TX >> PDCP_TX: Small packets or heavy retransmissions
```

---

### 8. Timing & Identification

| Metric | Unit | Description | Interpretation |
|--------|------|-------------|----------------|
| **timestamp** | µs | Collection timestamp | Microseconds since epoch |
| **rnti** | ID | Radio Network Temp ID | UE identifier (unique per cell) |
| **frame** | 0-1023 | Radio frame number | 10ms cycle |
| **slot** | 0-19 | Slot within frame | For 30kHz SCS |

---

## Use Cases & Applications

### 1. Machine Learning for RAN Optimization

**Predictive Models:**
- Predict BLER from SNR + CQI → proactive MCS adjustment
- Predict congestion from BSR + PRB trends → load balancing
- Anomaly detection using RLC retransmission spikes

**Feature Engineering:**
```python
# Derived features for ML
df['spectral_efficiency'] = df['dl_aggr_tbs'] / df['dl_prb'] / 1000  # kbps/PRB
df['retx_rate'] = df['rlc_retx'] / df['rlc_tx_pkts'].clip(lower=1)
df['prb_utilization'] = df['dl_sched_rb'] / 106  # assuming 40MHz
df['power_limited'] = df['phr'] < 0
```

### 2. Network Performance Monitoring

**KPIs to Track:**
| KPI | Formula | Target |
|-----|---------|--------|
| DL Throughput | Δdl_aggr_tbs / Δtime | Application dependent |
| Reliability | 1 - BLER | > 99% |
| Latency proxy | rlc_txbuf / throughput | < 10ms |
| Spectral Efficiency | throughput / PRBs | > 5 bps/Hz |

### 3. Troubleshooting Guide

| Symptom | Check These Metrics | Likely Cause |
|---------|--------------------|--------------| 
| Low throughput | CQI, MCS, PRB | Poor signal or congestion |
| High latency | rlc_txbuf, bsr | Buffer bloat, congestion |
| Dropped calls | BLER, phr, SNR | Coverage hole, interference |
| Variable quality | SNR variance, BLER | Mobility, fading |

---

## Data Quality Notes

### Known Limitations:
1. **CQI = 0**: In simulator/RF conditions, CQI may not be properly reported
2. **RSRP unavailable**: OAI gNB doesn't expose UE RSRP via FlexRIC
3. **Timing granularity**: 10ms reporting interval, some fast variations missed

### Data Validation:
```python
# Sanity checks
assert (df['pusch_snr'] > -20).all() and (df['pusch_snr'] < 70).all()
assert (df['dl_bler'] >= 0).all() and (df['dl_bler'] <= 1).all()
assert (df['cqi'] >= 0).all() and (df['cqi'] <= 15).all()
```

---

## Sample Data Analysis

```python
import pandas as pd
import matplotlib.pyplot as plt

# Load dataset
df = pd.read_csv('kpm_dataset.csv')

# Time series of signal quality
fig, axes = plt.subplots(3, 1, figsize=(12, 8))

axes[0].plot(df['pusch_snr'], label='PUSCH SNR')
axes[0].set_ylabel('SNR (dB)')
axes[0].legend()

axes[1].plot(df['dl_bler'], label='DL BLER', color='red')
axes[1].set_ylabel('BLER')
axes[1].legend()

axes[2].plot(df['dl_prb'], label='DL PRB')
axes[2].set_ylabel('PRBs')
axes[2].set_xlabel('Sample')
axes[2].legend()

plt.tight_layout()
plt.savefig('metrics_timeseries.png')

# Correlation analysis
corr_cols = ['pusch_snr', 'cqi', 'dl_bler', 'dl_mcs1', 'dl_prb']
print(df[corr_cols].corr())
```

---

## References

- [O-RAN E2SM-KPM Specification](https://orandownloadsweb.azurewebsites.net/specifications)
- [3GPP TS 38.331 - RRC Protocol](https://www.3gpp.org/DynaReport/38331.htm)
- [FlexRIC Documentation](https://gitlab.eurecom.fr/mosaic5g/flexric)
- [OAI 5G RAN](https://gitlab.eurecom.fr/oai/openairinterface5g)

---

*Generated by KPM Metrics Collector xApp - FlexRIC*
