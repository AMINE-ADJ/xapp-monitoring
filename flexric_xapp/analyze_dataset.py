#!/usr/bin/env python3
"""
FlexRIC KPM Dataset Analyzer
============================
Analyzes the metrics collected from the xApp and generates summary statistics
and visualizations.
"""

import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime

def analyze_dataset(csv_path):
    """Analyze the collected KPM metrics dataset."""
    
    print("\n" + "="*60)
    print("  FlexRIC KPM Metrics Dataset Analysis")
    print("="*60)
    
    # Load data
    df = pd.read_csv(csv_path)
    print(f"\n📁 Dataset: {csv_path}")
    print(f"📊 Shape: {df.shape[0]} samples × {df.shape[1]} features")
    
    # Time analysis
    if 'timestamp' in df.columns:
        duration_us = df['timestamp'].max() - df['timestamp'].min()
        duration_s = duration_us / 1e6
        sample_rate = df.shape[0] / duration_s if duration_s > 0 else 0
        print(f"⏱️  Duration: {duration_s:.2f} seconds")
        print(f"📈 Sample Rate: {sample_rate:.1f} samples/sec")
    
    # Signal Quality Metrics
    print("\n" + "-"*60)
    print("📡 SIGNAL QUALITY METRICS")
    print("-"*60)
    
    signal_metrics = {
        'pusch_snr': ('PUSCH SNR', 'dB', 'Uplink signal quality (proxy for RSRP)'),
        'pucch_snr': ('PUCCH SNR', 'dB', 'Control channel quality'),
        'cqi': ('CQI', 'index', 'Channel Quality Indicator (0-15)'),
        'dl_bler': ('DL BLER', '%', 'Downlink Block Error Rate'),
        'ul_bler': ('UL BLER', '%', 'Uplink Block Error Rate'),
    }
    
    for col, (name, unit, desc) in signal_metrics.items():
        if col in df.columns:
            val = df[col].mean()
            std = df[col].std()
            if 'bler' in col:
                val *= 100  # Convert to percentage
                std *= 100
            print(f"  {name}: {val:.2f} ± {std:.2f} {unit}")
            print(f"    → {desc}")
    
    # MCS and Modulation
    print("\n" + "-"*60)
    print("📶 MODULATION & CODING")
    print("-"*60)
    
    mcs_metrics = ['dl_mcs1', 'dl_mcs2', 'ul_mcs1', 'ul_mcs2']
    for col in mcs_metrics:
        if col in df.columns:
            val = df[col].mean()
            direction = 'Downlink' if 'dl' in col else 'Uplink'
            cw = col[-1]
            mod = "QPSK" if val < 10 else ("16QAM" if val < 17 else "64QAM")
            print(f"  {direction} MCS{cw}: {val:.1f} → {mod}")
    
    # Transport Block Stats
    print("\n" + "-"*60)
    print("📦 TRANSPORT BLOCK STATISTICS")
    print("-"*60)
    
    for direction in ['dl', 'ul']:
        aggr_col = f'{direction}_aggr_tbs'
        if aggr_col in df.columns:
            # Calculate throughput from aggregated TBS
            tbs_diff = df[aggr_col].diff().dropna()
            tbs_diff = tbs_diff[tbs_diff >= 0]  # Remove negative diffs (rollover)
            if len(tbs_diff) > 0:
                avg_tbs_per_sample = tbs_diff.mean()
                throughput_kbps = avg_tbs_per_sample * sample_rate * 8 / 1000
                dir_name = 'Downlink' if direction == 'dl' else 'Uplink'
                print(f"  {dir_name} Throughput: {throughput_kbps:.2f} kbps")
                print(f"    Total Data: {df[aggr_col].max() - df[aggr_col].min():.0f} bytes")
    
    # PRB Usage
    print("\n" + "-"*60)
    print("📊 PHYSICAL RESOURCE BLOCK (PRB) USAGE")
    print("-"*60)
    
    for direction in ['dl', 'ul']:
        prb_col = f'{direction}_prb'
        sched_col = f'{direction}_sched_rb'
        if prb_col in df.columns:
            prb_diff = df[prb_col].diff().dropna()
            prb_diff = prb_diff[prb_diff >= 0]
            avg_prb = prb_diff.mean() if len(prb_diff) > 0 else 0
            dir_name = 'Downlink' if direction == 'dl' else 'Uplink'
            print(f"  {dir_name} PRBs/sample: {avg_prb:.2f}")
        if sched_col in df.columns:
            print(f"    Scheduled RBs: {df[sched_col].mean():.2f}")
    
    # RLC Layer
    print("\n" + "-"*60)
    print("📨 RLC LAYER STATISTICS")
    print("-"*60)
    
    if 'rlc_tx_pkts' in df.columns and 'rlc_retx' in df.columns:
        total_tx = df['rlc_tx_pkts'].max()
        total_retx = df['rlc_retx'].max()
        retx_rate = (total_retx / total_tx * 100) if total_tx > 0 else 0
        print(f"  TX Packets: {total_tx}")
        print(f"  Retransmissions: {total_retx}")
        print(f"  Retx Rate: {retx_rate:.2f}%")
        
        if retx_rate < 1:
            quality = "Excellent ✅"
        elif retx_rate < 5:
            quality = "Good ✓"
        elif retx_rate < 10:
            quality = "Degraded ⚠️"
        else:
            quality = "Poor ❌"
        print(f"    → Link Quality: {quality}")
    
    if 'rlc_txbuf' in df.columns:
        print(f"  TX Buffer: {df['rlc_txbuf'].mean():.0f} bytes avg")
    
    # PDCP Layer
    print("\n" + "-"*60)
    print("🔐 PDCP LAYER STATISTICS")
    print("-"*60)
    
    for direction in ['tx', 'rx']:
        pkts_col = f'pdcp_{direction}_pkts'
        bytes_col = f'pdcp_{direction}_bytes'
        if pkts_col in df.columns:
            total_pkts = df[pkts_col].max()
            total_bytes = df[bytes_col].max() if bytes_col in df.columns else 0
            dir_name = 'Transmitted' if direction == 'tx' else 'Received'
            print(f"  {dir_name}: {total_pkts} packets, {total_bytes} bytes")
    
    # Data Quality Assessment
    print("\n" + "-"*60)
    print("✅ DATA QUALITY ASSESSMENT")
    print("-"*60)
    
    # Check for constant values (potential issues)
    constant_cols = []
    varying_cols = []
    for col in df.columns:
        if df[col].nunique() == 1:
            constant_cols.append(col)
        else:
            varying_cols.append(col)
    
    print(f"  Varying metrics: {len(varying_cols)}/{len(df.columns)}")
    print(f"  Constant metrics: {len(constant_cols)}")
    
    if constant_cols:
        print("\n  ⚠️  Constant columns (no variation):")
        for col in constant_cols[:10]:  # Show first 10
            print(f"    - {col}: {df[col].iloc[0]}")
        if len(constant_cols) > 10:
            print(f"    ... and {len(constant_cols) - 10} more")
    
    # Interpretation Guide
    print("\n" + "="*60)
    print("📚 INTERPRETATION GUIDE")
    print("="*60)
    
    snr = df['pusch_snr'].mean() if 'pusch_snr' in df.columns else 0
    bler = df['dl_bler'].mean() * 100 if 'dl_bler' in df.columns else 0
    mcs = df['dl_mcs1'].mean() if 'dl_mcs1' in df.columns else 0
    
    print(f"""
  📡 Signal Quality (SNR = {snr:.1f} dB):
    {'Excellent (>40dB)' if snr > 40 else 'Good (30-40dB)' if snr > 30 else 'Fair (20-30dB)' if snr > 20 else 'Poor (<20dB)'}
    
  📉 Error Rate (BLER = {bler:.2f}%):
    {'Excellent (<1%)' if bler < 1 else 'Acceptable (1-5%)' if bler < 5 else 'Degraded (>5%)'}
    
  📶 Modulation (MCS = {mcs:.0f}):
    {'QPSK (robust)' if mcs < 10 else '16QAM (balanced)' if mcs < 17 else '64QAM (high throughput)'}
    
  💡 RSRP Note:
    RSRP is not directly available from FlexRIC/OAI.
    Use PUSCH_SNR as a proxy for uplink signal strength.
    CQI correlates with SINR which depends on RSRP.
""")
    
    return df


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '/mnt/Studies/Sorbonne/CELL/xapp-monitoring/flexric_xapp/kpm_dataset_v2.csv'
    
    if not os.path.exists(csv_path):
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)
    
    analyze_dataset(csv_path)


if __name__ == '__main__':
    main()
