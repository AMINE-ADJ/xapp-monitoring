#!/usr/bin/env python3
"""
CELL KPM Dataset Collector - Real-time 5G Metrics Dataset Generator

This script collects comprehensive 5G metrics by:
1. Parsing OAI gNB logs for MAC layer stats (CQI, BLER, MCS, RSRP, etc.)
2. Parsing FlexRIC KPM xApp output for throughput and PRB metrics

Generates a unified CSV dataset with ~1000+ samples.

Author: CELL Lab - Sorbonne University  
Date: January 2026
"""

import subprocess
import re
import csv
import time
import sys
import os
import signal
import threading
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict
from collections import deque
import argparse


@dataclass
class CellMetricsSample:
    """Comprehensive 5G cell metrics sample."""
    # Timestamp and identification
    timestamp: str = ""
    sample_id: int = 0
    ue_rnti: str = ""
    ue_id: int = 0
    
    # Radio Quality Metrics
    rsrp_dbm: float = -999.0
    rsrq_db: float = -999.0
    sinr_db: float = -999.0
    cqi: int = 0
    wb_cqi: int = 0
    
    # Physical Layer Metrics
    prb_usage_dl: int = 0
    prb_usage_ul: int = 0
    mcs_dl: int = 0
    mcs_ul: int = 0
    
    # Throughput Metrics (kbps)
    ue_throughput_dl_kbps: float = 0.0
    ue_throughput_ul_kbps: float = 0.0
    dl_curr_tbs: int = 0
    ul_curr_tbs: int = 0
    
    # MAC Layer Cumulative Stats
    mac_tx_bytes: int = 0
    mac_rx_bytes: int = 0
    
    # Error Metrics
    bler_dl: float = 0.0
    bler_ul: float = 0.0
    dlsch_errors: int = 0
    ulsch_errors: int = 0
    
    # HARQ Metrics
    dlsch_rounds_0: int = 0
    dlsch_rounds_1: int = 0
    dlsch_rounds_2: int = 0
    dlsch_rounds_3: int = 0
    ulsch_rounds_0: int = 0
    ulsch_rounds_1: int = 0
    ulsch_rounds_2: int = 0
    ulsch_rounds_3: int = 0
    harq_retx_dl: int = 0
    harq_retx_ul: int = 0
    
    # RLC/PDCP Metrics
    rlc_buffer_occupancy: int = 0
    pdcp_sdu_volume_dl_kb: int = 0
    pdcp_sdu_volume_ul_kb: int = 0
    
    # Power Control Metrics
    power_headroom_db: int = 0
    pcmax_dbm: int = 0
    pusch_snr_db: float = 0.0
    
    # DTX counters
    pucch0_dtx: int = 0
    ulsch_dtx: int = 0
    
    # Sync Status
    sync_status: str = "unknown"
    
    # LCID traffic (logical channel)
    lcid1_tx_bytes: int = 0
    lcid1_rx_bytes: int = 0
    lcid4_tx_bytes: int = 0
    lcid4_rx_bytes: int = 0


class CELLDatasetCollector:
    """
    CELL Dataset Collector - Comprehensive 5G Metrics
    
    Collects from:
    1. gNB logs (RSRP, BLER, MCS, HARQ, Power Control)
    2. KPM xApp (PRB, Throughput)
    """
    
    VERSION = "2.1.0"
    XAPP_NAME = "cell_dataset_collector"
    DATASET_NAME = "cell_monitoring_dataset.csv"
    
    # Kubernetes configuration
    NAMESPACE = "blueprint"
    
    def __init__(self, output_dir: str = "./data", target_samples: int = 1000):
        self.output_dir = Path(output_dir)
        self.target_samples = target_samples
        self.samples: List[CellMetricsSample] = []
        self.running = True
        self.sample_counter = 0
        
        # Latest metrics cache
        self.latest_gnb_metrics: Dict = {}
        self.latest_kpm_metrics: Dict = {}
        
        # For throughput computation
        self.prev_mac_tx_bytes = 0
        self.prev_mac_rx_bytes = 0
        self.last_mac_update_time = time.time()
        self.last_throughput_dl = 0.0
        self.last_throughput_ul = 0.0
        
        # Thread synchronization
        self.metrics_lock = threading.Lock()
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Get pod names
        self.gnb_pod = self._get_pod_name("oai-gnb")
        self.flexric_pod = self._get_pod_name("oai-flexric")
        
        self._print_banner()
        
    def _print_banner(self):
        print(f"\n{'='*70}")
        print(f"   CELL Dataset Collector v{self.VERSION}")
        print(f"   Comprehensive 5G Metrics Dataset Generator")
        print(f"{'='*70}")
        print(f"  gNB Pod:        {self.gnb_pod}")
        print(f"  FlexRIC Pod:    {self.flexric_pod}")
        print(f"  Target Samples: {self.target_samples}")
        print(f"  Output:         {self.output_dir / self.DATASET_NAME}")
        print(f"{'='*70}")
        print(f"\n  Metrics: RSRP, CQI, SINR, BLER, MCS, Throughput,")
        print(f"           PRB, HARQ, RLC Buffer, Power Control")
        print(f"{'='*70}\n")
        
    def _signal_handler(self, signum, frame):
        print(f"\n[{self.XAPP_NAME}] Stopping collection...")
        self.running = False
        
    def _get_pod_name(self, app_name: str) -> Optional[str]:
        try:
            cmd = f"kubectl get pods -n {self.NAMESPACE} -o name | grep {app_name} | head -1"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().replace('pod/', '')
        except Exception:
            pass
        return None
    
    def _parse_gnb_log_line(self, line: str) -> Dict:
        """Parse OAI gNB log lines for UE statistics."""
        metrics = {}
        
        # Parse RNTI and sync status line
        # UE RNTI e9b4 CU-UE-ID 2 in-sync PH 0 dB PCMAX 0 dBm, average RSRP -44 (16 meas)
        rnti_match = re.search(
            r'UE RNTI\s+([0-9a-fA-F]+)\s+CU-UE-ID\s+(\d+)\s+(in-sync|out-of-sync)\s+PH\s+(-?\d+)\s+dB\s+PCMAX\s+(-?\d+)\s+dBm.*?RSRP\s+(-?\d+)',
            line
        )
        if rnti_match:
            metrics['ue_rnti'] = rnti_match.group(1)
            metrics['ue_id'] = int(rnti_match.group(2))
            metrics['sync_status'] = rnti_match.group(3)
            metrics['power_headroom_db'] = int(rnti_match.group(4))
            metrics['pcmax_dbm'] = int(rnti_match.group(5))
            metrics['rsrp_dbm'] = float(rnti_match.group(6))
            # Estimate RSRQ from RSRP (simplified)
            metrics['rsrq_db'] = metrics['rsrp_dbm'] + 10
            
        # Parse DL stats
        # UE e9b4: dlsch_rounds 34407/1/0/0, dlsch_errors 0, pucch0_DTX 0, BLER 0.00000 MCS (0) 9
        dl_match = re.search(
            r'dlsch_rounds\s+(\d+)/(\d+)/(\d+)/(\d+).*?dlsch_errors\s+(\d+).*?pucch0_DTX\s+(\d+).*?BLER\s+([\d.]+)\s+MCS\s+\(\d+\)\s+(\d+)',
            line
        )
        if dl_match:
            metrics['dlsch_rounds_0'] = int(dl_match.group(1))
            metrics['dlsch_rounds_1'] = int(dl_match.group(2))
            metrics['dlsch_rounds_2'] = int(dl_match.group(3))
            metrics['dlsch_rounds_3'] = int(dl_match.group(4))
            metrics['harq_retx_dl'] = sum([int(dl_match.group(i)) for i in range(2, 5)])
            metrics['dlsch_errors'] = int(dl_match.group(5))
            metrics['pucch0_dtx'] = int(dl_match.group(6))
            metrics['bler_dl'] = float(dl_match.group(7)) * 100
            metrics['mcs_dl'] = int(dl_match.group(8))
            # Estimate CQI from MCS
            metrics['cqi'] = min(15, max(1, metrics['mcs_dl'] + 6))
            metrics['wb_cqi'] = metrics['cqi']
            # Estimate SINR from BLER
            if metrics['bler_dl'] < 0.001:
                metrics['sinr_db'] = 25.0
            elif metrics['bler_dl'] < 0.01:
                metrics['sinr_db'] = 20.0
            elif metrics['bler_dl'] < 0.1:
                metrics['sinr_db'] = 15.0
            else:
                metrics['sinr_db'] = 10.0
            
        # Parse UL stats
        # UE e9b4: ulsch_rounds 48951/0/0/0, ulsch_errors 0, ulsch_DTX 0, BLER 0.00000 MCS (0) 9
        ul_match = re.search(
            r'ulsch_rounds\s+(\d+)/(\d+)/(\d+)/(\d+).*?ulsch_errors\s+(\d+).*?ulsch_DTX\s+(\d+).*?BLER\s+([\d.]+)\s+MCS\s+\(\d+\)\s+(\d+)',
            line
        )
        if ul_match:
            metrics['ulsch_rounds_0'] = int(ul_match.group(1))
            metrics['ulsch_rounds_1'] = int(ul_match.group(2))
            metrics['ulsch_rounds_2'] = int(ul_match.group(3))
            metrics['ulsch_rounds_3'] = int(ul_match.group(4))
            metrics['harq_retx_ul'] = sum([int(ul_match.group(i)) for i in range(2, 5)])
            metrics['ulsch_errors'] = int(ul_match.group(5))
            metrics['ulsch_dtx'] = int(ul_match.group(6))
            metrics['bler_ul'] = float(ul_match.group(7)) * 100
            metrics['mcs_ul'] = int(ul_match.group(8))
            
        # Parse MAC bytes
        # UE e9b4: MAC:    TX       12609596 RX       11164591 bytes
        mac_match = re.search(r'MAC:\s+TX\s+(\d+)\s+RX\s+(\d+)\s+bytes', line)
        if mac_match:
            metrics['mac_tx_bytes'] = int(mac_match.group(1))
            metrics['mac_rx_bytes'] = int(mac_match.group(2))
            
        # Parse LCID traffic
        # UE e9b4: LCID 1: TX 960 RX 326 bytes
        lcid1_match = re.search(r'LCID\s+1:\s+TX\s+(\d+)\s+RX\s+(\d+)', line)
        if lcid1_match:
            metrics['lcid1_tx_bytes'] = int(lcid1_match.group(1))
            metrics['lcid1_rx_bytes'] = int(lcid1_match.group(2))
            
        # UE e9b4: LCID 4: TX 7832698 RX 7948462 bytes
        lcid4_match = re.search(r'LCID\s+4:\s+TX\s+(\d+)\s+RX\s+(\d+)', line)
        if lcid4_match:
            metrics['lcid4_tx_bytes'] = int(lcid4_match.group(1))
            metrics['lcid4_rx_bytes'] = int(lcid4_match.group(2))
            
        return metrics
    
    def _parse_kpm_output(self, line: str) -> Dict:
        """Parse FlexRIC KPM xApp output."""
        metrics = {}
        
        # Parse PRB metrics
        patterns = [
            (r'DRB\.PdcpSduVolumeDL\s*=\s*(\d+)', 'pdcp_sdu_volume_dl_kb', int),
            (r'DRB\.PdcpSduVolumeUL\s*=\s*(\d+)', 'pdcp_sdu_volume_ul_kb', int),
            (r'RRU\.PrbTotDl\s*=\s*(\d+)', 'prb_usage_dl', int),
            (r'RRU\.PrbTotUl\s*=\s*(\d+)', 'prb_usage_ul', int),
        ]
        
        for pattern, field, converter in patterns:
            match = re.search(pattern, line)
            if match:
                metrics[field] = converter(match.group(1))
                
        return metrics
    
    def _collect_gnb_metrics(self):
        """Background thread for gNB log metrics."""
        if not self.gnb_pod:
            print("[Warning] gNB pod not found")
            return
            
        cmd = f"kubectl logs -f {self.gnb_pod} -n {self.NAMESPACE}"
        
        try:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            
            while self.running:
                line = process.stdout.readline()
                if not line:
                    break
                metrics = self._parse_gnb_log_line(line.strip())
                if metrics:
                    with self.metrics_lock:
                        self.latest_gnb_metrics.update(metrics)
                    
            process.terminate()
        except Exception as e:
            print(f"[Warning] gNB collection error: {e}")
    
    def _collect_kpm_metrics(self):
        """Background thread for KPM metrics."""
        if not self.flexric_pod:
            print("[Warning] FlexRIC pod not found")
            return
            
        cmd = f"kubectl exec {self.flexric_pod} -n {self.NAMESPACE} -- /flexric/build/examples/xApp/c/monitor/xapp_kpm_moni"
        
        try:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            
            while self.running:
                line = process.stdout.readline()
                if not line:
                    break
                    
                metrics = self._parse_kpm_output(line.strip())
                if metrics:
                    with self.metrics_lock:
                        self.latest_kpm_metrics.update(metrics)
                    
            process.terminate()
        except Exception as e:
            print(f"[Warning] KPM collection error: {e}")
    
    def _create_sample(self) -> CellMetricsSample:
        """Create a new sample from current metrics."""
        self.sample_counter += 1
        
        sample = CellMetricsSample(
            timestamp=datetime.now().isoformat(),
            sample_id=self.sample_counter,
        )
        
        with self.metrics_lock:
            # Merge gNB metrics
            for key, value in self.latest_gnb_metrics.items():
                if hasattr(sample, key):
                    setattr(sample, key, value)
                    
            # Merge KPM metrics
            for key, value in self.latest_kpm_metrics.items():
                if hasattr(sample, key):
                    setattr(sample, key, value)
        
        # Compute throughput from MAC byte counter difference
        current_time = time.time()
        time_diff = current_time - self.last_mac_update_time
        
        if time_diff > 0.5 and self.prev_mac_tx_bytes > 0 and sample.mac_tx_bytes != self.prev_mac_tx_bytes:
            tx_bytes_diff = sample.mac_tx_bytes - self.prev_mac_tx_bytes
            if tx_bytes_diff > 0:
                self.last_throughput_dl = (tx_bytes_diff * 8) / (time_diff * 1000)
            
            rx_bytes_diff = sample.mac_rx_bytes - self.prev_mac_rx_bytes
            if rx_bytes_diff > 0:
                self.last_throughput_ul = (rx_bytes_diff * 8) / (time_diff * 1000)
            
            self.prev_mac_tx_bytes = sample.mac_tx_bytes
            self.prev_mac_rx_bytes = sample.mac_rx_bytes
            self.last_mac_update_time = current_time
        elif self.prev_mac_tx_bytes == 0:
            self.prev_mac_tx_bytes = sample.mac_tx_bytes
            self.prev_mac_rx_bytes = sample.mac_rx_bytes
            self.last_mac_update_time = current_time
        
        sample.ue_throughput_dl_kbps = round(self.last_throughput_dl, 2)
        sample.ue_throughput_ul_kbps = round(self.last_throughput_ul, 2)
                
        self.samples.append(sample)
        
        return sample
    
    def save_dataset(self) -> str:
        """Save collected samples to CSV."""
        csv_path = self.output_dir / self.DATASET_NAME
        
        if not self.samples:
            print("[Warning] No samples to save!")
            return str(csv_path)
            
        fieldnames = list(asdict(self.samples[0]).keys())
        
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for sample in self.samples:
                writer.writerow(asdict(sample))
                
        print(f"\n✓ Saved {len(self.samples)} samples to {csv_path}")
        return str(csv_path)
    
    def print_summary(self):
        """Print dataset statistics."""
        if not self.samples:
            return
            
        print(f"\n{'='*70}")
        print("                      DATASET SUMMARY")
        print(f"{'='*70}")
        print(f"  Total samples:   {len(self.samples)}")
        
        # Calculate statistics
        metrics_to_summarize = [
            ('rsrp_dbm', 'dBm'),
            ('sinr_db', 'dB'),
            ('cqi', ''),
            ('bler_dl', '%'),
            ('bler_ul', '%'),
            ('mcs_dl', ''),
            ('mcs_ul', ''),
            ('ue_throughput_dl_kbps', 'kbps'),
            ('ue_throughput_ul_kbps', 'kbps'),
            ('prb_usage_dl', 'PRBs'),
            ('prb_usage_ul', 'PRBs'),
            ('harq_retx_dl', ''),
            ('harq_retx_ul', ''),
        ]
        
        print(f"\n  {'Metric':<25s} {'Min':>10s}  {'Avg':>10s}  {'Max':>10s}  {'Unit':<6s}")
        print(f"  {'-'*60}")
        
        for metric, unit in metrics_to_summarize:
            values = [getattr(s, metric, 0) for s in self.samples]
            values = [v for v in values if v is not None and v != -999.0]
            if values:
                avg = sum(values) / len(values)
                min_v = min(values)
                max_v = max(values)
                print(f"  {metric:<25s} {min_v:>10.2f}  {avg:>10.2f}  {max_v:>10.2f}  {unit:<6s}")
        
        print(f"{'='*70}")
    
    def collect(self) -> str:
        """Main collection routine."""
        print(f"[Starting] Collecting {self.target_samples} samples...\n")
        
        # Start background threads
        gnb_thread = threading.Thread(target=self._collect_gnb_metrics, daemon=True)
        kpm_thread = threading.Thread(target=self._collect_kpm_metrics, daemon=True)
        
        gnb_thread.start()
        kpm_thread.start()
        
        # Wait for initial metrics
        time.sleep(2)
        
        try:
            while self.running and self.sample_counter < self.target_samples:
                sample = self._create_sample()
                
                # Progress report every 50 samples
                if self.sample_counter % 50 == 0:
                    print(f"[Sample {self.sample_counter:5d}/{self.target_samples}] "
                          f"RSRP={sample.rsrp_dbm:6.1f}dBm  "
                          f"CQI={sample.cqi:2d}  "
                          f"BLER_DL={sample.bler_dl:6.3f}%  "
                          f"Thp_DL={sample.ue_throughput_dl_kbps:8.1f}kbps  "
                          f"PRB_DL={sample.prb_usage_dl:4d}")
                
                # Sleep to achieve ~1 sample per second
                time.sleep(1.0)
                
        except KeyboardInterrupt:
            print("\n[Interrupted] Stopping collection...")
        
        finally:
            self.running = False
            
            # Save and print summary
            csv_path = self.save_dataset()
            self.print_summary()
            
            print(f"\nDataset: {csv_path}")
            
        return csv_path


def main():
    parser = argparse.ArgumentParser(description='CELL Dataset Collector - 5G Metrics')
    parser.add_argument('-n', '--samples', type=int, default=1000,
                       help='Number of samples to collect (default: 1000)')
    parser.add_argument('-o', '--output', type=str, default='./data',
                       help='Output directory (default: ./data)')
    
    args = parser.parse_args()
    
    collector = CELLDatasetCollector(
        output_dir=args.output,
        target_samples=args.samples
    )
    collector.collect()


if __name__ == '__main__':
    main()
