#!/usr/bin/env python3
"""
CELL xApp Monitor - Comprehensive 5G Metrics Collector

This xApp collects meaningful 5G network performance metrics from:
1. FlexRIC KPM Service Model (E2SM-KPM)
2. OAI gNB MAC layer statistics

Metrics collected:
- RSRP (Reference Signal Received Power)
- RSRQ (Reference Signal Received Quality) - estimated
- SINR (Signal-to-Interference-plus-Noise Ratio) - estimated from BLER
- CQI (Channel Quality Indicator) - derived from MCS
- PRB_Usage_DL/UL (Physical Resource Block utilization)
- UE_Throughput_DL/UL (User Equipment throughput)
- RLC_Buffer_Occupancy (RLC layer buffer status)
- BLER_DL/UL (Block Error Rate)
- MCS_DL/UL (Modulation and Coding Scheme)
- HARQ_Retx_DL/UL (HARQ retransmission count)

Output: cell_monitoring_dataset.csv

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
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict


@dataclass
class CellMetricsSample:
    """Comprehensive 5G cell metrics sample."""
    # Timestamp and identification
    timestamp: str = ""
    sample_id: int = 0
    ue_rnti: str = ""
    ue_id: int = 0
    
    # Radio Quality Metrics (Most Important!)
    rsrp_dbm: float = -999.0          # Reference Signal Received Power (dBm)
    rsrq_db: float = -999.0           # Reference Signal Received Quality (dB)
    sinr_db: float = -999.0           # Signal-to-Interference-plus-Noise Ratio (dB)
    cqi: int = 0                       # Channel Quality Indicator (0-15)
    
    # Physical Layer Metrics
    prb_usage_dl: int = 0             # PRB Usage Downlink
    prb_usage_ul: int = 0             # PRB Usage Uplink
    mcs_dl: int = 0                   # Modulation Coding Scheme DL
    mcs_ul: int = 0                   # Modulation Coding Scheme UL
    
    # Throughput Metrics
    ue_throughput_dl_kbps: float = 0.0
    ue_throughput_ul_kbps: float = 0.0
    mac_tx_bytes: int = 0
    mac_rx_bytes: int = 0
    
    # Error Metrics
    bler_dl: float = 0.0              # Block Error Rate DL (%)
    bler_ul: float = 0.0              # Block Error Rate UL (%)
    dlsch_errors: int = 0
    ulsch_errors: int = 0
    
    # HARQ Metrics
    harq_retx_dl: int = 0             # HARQ Retransmissions DL
    harq_retx_ul: int = 0             # HARQ Retransmissions UL
    
    # RLC/PDCP Metrics  
    rlc_buffer_occupancy: int = 0     # RLC Buffer Occupancy (bytes)
    rlc_sdu_delay_dl_us: float = 0.0  # RLC SDU Delay (microseconds)
    pdcp_sdu_volume_dl_kb: int = 0
    pdcp_sdu_volume_ul_kb: int = 0
    
    # Power Control Metrics
    power_headroom_db: int = 0        # Power Headroom (dB)
    pcmax_dbm: int = 0                # Max Transmit Power (dBm)
    
    # Sync Status
    sync_status: str = "unknown"      # in-sync / out-of-sync
    
    # Experiment metadata
    experiment_phase: str = "baseline"


class CELLxAppMonitor:
    """
    CELL xApp Monitor - Comprehensive 5G Metrics Collector
    
    Collects metrics from multiple sources:
    1. FlexRIC KPM xApp (PRB, Throughput, PDCP/RLC stats)
    
    Computes throughput from MAC byte counter differences.
    2. gNB logs (RSRP, BLER, MCS, HARQ, Power Control)
    """
    
    VERSION = "2.0.0"
    XAPP_NAME = "cell_xapp_monitor"
    DATASET_NAME = "cell_monitoring_dataset.csv"
    
    # Kubernetes configuration
    NAMESPACE = "blueprint"
    FLEXRIC_LABEL = "app.kubernetes.io/name=oai-flexric"
    GNB_LABEL = "app.kubernetes.io/name=oai-gnb"
    UE_LABEL = "app.kubernetes.io/name=oai-nr-ue"
    
    # FlexRIC xApp binary
    XAPP_BINARY = "/flexric/build/examples/xApp/c/monitor/xapp_kpm_moni"
    
    def __init__(self, output_dir: str = "./data", duration: int = 60):
        self.output_dir = Path(output_dir)
        self.duration = duration
        self.samples: List[CellMetricsSample] = []
        self.running = True
        self.current_phase = "baseline"
        self.sample_counter = 0
        
        # Latest metrics cache
        self.latest_gnb_metrics = {}
        self.latest_kpm_metrics = {}
        
        # For throughput computation from MAC byte counters
        self.prev_mac_tx_bytes = 0
        self.prev_mac_rx_bytes = 0
        self.last_mac_update_time = time.time()
        self.last_throughput_dl = 0.0
        self.last_throughput_ul = 0.0
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Get pod names
        self.flexric_pod = self._get_pod_name(self.FLEXRIC_LABEL)
        self.gnb_pod = self._get_pod_name(self.GNB_LABEL)
        self.ue_pod = self._get_pod_name(self.UE_LABEL)
        
        self._print_banner()
        
    def _print_banner(self):
        print(f"\n{'='*65}")
        print(f"   CELL xApp Monitor v{self.VERSION}")
        print(f"   Comprehensive 5G Metrics Collector for FlexRIC")
        print(f"{'='*65}")
        print(f"  FlexRIC Pod: {self.flexric_pod}")
        print(f"  gNB Pod:     {self.gnb_pod}")
        print(f"  UE Pod:      {self.ue_pod}")
        print(f"  Duration:    {self.duration} seconds")
        print(f"  Output:      {self.output_dir / self.DATASET_NAME}")
        print(f"{'='*65}")
        print(f"\n  Metrics: RSRP, RSRQ, SINR, CQI, PRB, Throughput,")
        print(f"           BLER, MCS, HARQ, RLC_Buffer, Power_Headroom")
        print(f"{'='*65}\n")
        
    def _signal_handler(self, signum, frame):
        print(f"\n[{self.XAPP_NAME}] Stopping collection...")
        self.running = False
        
    def _get_pod_name(self, label: str) -> Optional[str]:
        try:
            cmd = f"kubectl get pods -n {self.NAMESPACE} -l {label} -o jsonpath='{{.items[0].metadata.name}}'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            print(f"[Warning] Failed to get pod for {label}: {e}")
        return None
    
    def _parse_gnb_log_line(self, line: str) -> Dict:
        """Parse a gNB log line and extract metrics."""
        metrics = {}
        
        # Parse RSRP and sync status
        rsrp_match = re.search(
            r'UE RNTI (\w+).*?(in-sync|out-of-sync).*?PH\s+(-?\d+)\s*dB.*?PCMAX\s+(-?\d+)\s*dBm.*?RSRP\s+(-?\d+)',
            line
        )
        if rsrp_match:
            metrics['ue_rnti'] = rsrp_match.group(1)
            metrics['sync_status'] = rsrp_match.group(2)
            metrics['power_headroom_db'] = int(rsrp_match.group(3))
            metrics['pcmax_dbm'] = int(rsrp_match.group(4))
            metrics['rsrp_dbm'] = float(rsrp_match.group(5))
            # Estimate RSRQ (RSRP relative to noise floor)
            metrics['rsrq_db'] = metrics['rsrp_dbm'] + 100 - 90
            
        # Parse DL stats with BLER and MCS
        dl_match = re.search(
            r'dlsch_rounds\s+(\d+)/(\d+)/(\d+)/(\d+).*?dlsch_errors\s+(\d+).*?BLER\s+([\d.]+)\s+MCS\s+\(\d+\)\s+(\d+)',
            line
        )
        if dl_match:
            rounds = [int(dl_match.group(i)) for i in range(1, 5)]
            metrics['harq_retx_dl'] = sum(rounds[1:])
            metrics['dlsch_errors'] = int(dl_match.group(5))
            metrics['bler_dl'] = float(dl_match.group(6)) * 100
            metrics['mcs_dl'] = int(dl_match.group(7))
            # Estimate CQI from MCS
            metrics['cqi'] = min(15, max(1, metrics['mcs_dl'] + 6))
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
        ul_match = re.search(
            r'ulsch_rounds\s+(\d+)/(\d+)/(\d+)/(\d+).*?ulsch_errors\s+(\d+).*?BLER\s+([\d.]+)\s+MCS\s+\(\d+\)\s+(\d+)',
            line
        )
        if ul_match:
            rounds = [int(ul_match.group(i)) for i in range(1, 5)]
            metrics['harq_retx_ul'] = sum(rounds[1:])
            metrics['ulsch_errors'] = int(ul_match.group(5))
            metrics['bler_ul'] = float(ul_match.group(6)) * 100
            metrics['mcs_ul'] = int(ul_match.group(7))
            
        # Parse MAC bytes
        mac_match = re.search(r'MAC:\s+TX\s+(\d+)\s+RX\s+(\d+)\s+bytes', line)
        if mac_match:
            metrics['mac_tx_bytes'] = int(mac_match.group(1))
            metrics['mac_rx_bytes'] = int(mac_match.group(2))
            
        return metrics
    
    def _parse_kpm_output(self, line: str) -> Dict:
        """Parse FlexRIC KPM xApp output."""
        metrics = {}
        
        # Check for new sample
        match = re.match(r'\s*(\d+)\s+KPM ind_msg', line)
        if match:
            metrics['_new_sample'] = True
            metrics['kpm_sample_id'] = int(match.group(1))
            
        # Parse UE ID
        match = re.search(r'amf_ue_ngap_id\s*=\s*(\d+)', line)
        if match:
            metrics['ue_id'] = int(match.group(1))
            
        # Parse metrics
        patterns = [
            (r'DRB\.PdcpSduVolumeDL\s*=\s*(\d+)', 'pdcp_sdu_volume_dl_kb', int),
            (r'DRB\.PdcpSduVolumeUL\s*=\s*(\d+)', 'pdcp_sdu_volume_ul_kb', int),
            (r'DRB\.RlcSduDelayDl\s*=\s*([\d.]+)', 'rlc_sdu_delay_dl_us', float),
            (r'DRB\.UEThpDl\s*=\s*([\d.]+)', 'ue_throughput_dl_kbps', float),
            (r'DRB\.UEThpUl\s*=\s*([\d.]+)', 'ue_throughput_ul_kbps', float),
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
                    self.latest_gnb_metrics.update(metrics)
                    
            process.terminate()
        except Exception as e:
            print(f"[Warning] gNB collection error: {e}")
    
    def _collect_kpm_metrics(self):
        """Background thread for KPM metrics."""
        if not self.flexric_pod:
            return
            
        cmd = f"kubectl exec {self.flexric_pod} -n {self.NAMESPACE} -- {self.XAPP_BINARY}"
        
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
                
                if metrics.get('_new_sample'):
                    self._create_sample()
                    metrics.pop('_new_sample', None)
                    
                if metrics:
                    self.latest_kpm_metrics.update(metrics)
                    
            process.terminate()
        except Exception as e:
            print(f"[Warning] KPM collection error: {e}")
    
    def _create_sample(self):
        """Create a new sample from current metrics."""
        self.sample_counter += 1
        
        sample = CellMetricsSample(
            timestamp=datetime.now().isoformat(),
            sample_id=self.sample_counter,
            experiment_phase=self.current_phase,
        )
        
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
            # Compute DL throughput (TX from gNB perspective = DL to UE)
            tx_bytes_diff = sample.mac_tx_bytes - self.prev_mac_tx_bytes
            if tx_bytes_diff > 0:
                self.last_throughput_dl = (tx_bytes_diff * 8) / (time_diff * 1000)
            
            # Compute UL throughput (RX from gNB perspective = UL from UE)
            rx_bytes_diff = sample.mac_rx_bytes - self.prev_mac_rx_bytes
            if rx_bytes_diff > 0:
                self.last_throughput_ul = (rx_bytes_diff * 8) / (time_diff * 1000)
            
            # Update previous counters only when MAC bytes change
            self.prev_mac_tx_bytes = sample.mac_tx_bytes
            self.prev_mac_rx_bytes = sample.mac_rx_bytes
            self.last_mac_update_time = current_time
        elif self.prev_mac_tx_bytes == 0:
            self.prev_mac_tx_bytes = sample.mac_tx_bytes
            self.prev_mac_rx_bytes = sample.mac_rx_bytes
            self.last_mac_update_time = current_time
        
        # Use the last computed throughput
        sample.ue_throughput_dl_kbps = self.last_throughput_dl
        sample.ue_throughput_ul_kbps = self.last_throughput_ul
        
        # Estimate RLC buffer from throughput difference
        sample.rlc_buffer_occupancy = max(0, int(
            (sample.pdcp_sdu_volume_dl_kb - sample.ue_throughput_dl_kbps/8) * 1024
        ))
                
        self.samples.append(sample)
        
        # Print progress every 5 samples
        if self.sample_counter % 5 == 0:
            print(f"[Sample {self.sample_counter:4d}] "
                  f"RSRP={sample.rsrp_dbm:6.1f}dBm  "
                  f"SINR={sample.sinr_db:5.1f}dB  "
                  f"CQI={sample.cqi:2d}  "
                  f"BLER={sample.bler_dl:6.3f}%  "
                  f"Thp_DL={sample.ue_throughput_dl_kbps:8.1f}kbps  "
                  f"PRB={sample.prb_usage_dl:4d}")
    
    def set_phase(self, phase: str):
        """Set the current experiment phase."""
        self.current_phase = phase
        print(f"\n[Phase] >>> {phase} <<<")
        
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
    
    def collect(self) -> str:
        """Main collection routine."""
        print(f"[Starting] Collecting metrics for {self.duration} seconds...\n")
        
        # Start background threads
        gnb_thread = threading.Thread(target=self._collect_gnb_metrics, daemon=True)
        kpm_thread = threading.Thread(target=self._collect_kpm_metrics, daemon=True)
        
        gnb_thread.start()
        kpm_thread.start()
        
        start_time = time.time()
        
        try:
            while self.running and (time.time() - start_time) < self.duration:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
            
        self.running = False
        
        gnb_thread.join(timeout=2)
        kpm_thread.join(timeout=2)
        
        return self.save_dataset()
    
    def print_summary(self):
        """Print dataset summary statistics."""
        if not self.samples:
            return
            
        print(f"\n{'='*65}")
        print("                    DATASET SUMMARY")
        print(f"{'='*65}")
        print(f"  Total samples:   {len(self.samples)}")
        print(f"  Duration:        {self.duration} seconds")
        print(f"  Sampling rate:   {len(self.samples)/self.duration:.2f} samples/sec")
        
        def stats(values, name, unit=""):
            if values:
                print(f"  {name:18s} min={min(values):8.2f}  avg={sum(values)/len(values):8.2f}  max={max(values):8.2f} {unit}")
        
        print(f"\n  {'─'*60}")
        print("  RADIO QUALITY METRICS:")
        stats([s.rsrp_dbm for s in self.samples if s.rsrp_dbm > -999], "RSRP", "dBm")
        stats([s.rsrq_db for s in self.samples if s.rsrq_db > -999], "RSRQ", "dB")
        stats([s.sinr_db for s in self.samples if s.sinr_db > -999], "SINR", "dB")
        stats([float(s.cqi) for s in self.samples if s.cqi > 0], "CQI", "")
        
        print(f"\n  {'─'*60}")
        print("  THROUGHPUT & PRB METRICS:")
        stats([s.ue_throughput_dl_kbps for s in self.samples], "UE_Throughput_DL", "kbps")
        stats([s.ue_throughput_ul_kbps for s in self.samples], "UE_Throughput_UL", "kbps")
        stats([float(s.prb_usage_dl) for s in self.samples], "PRB_Usage_DL", "PRBs")
        stats([float(s.prb_usage_ul) for s in self.samples], "PRB_Usage_UL", "PRBs")
        
        print(f"\n  {'─'*60}")
        print("  ERROR & RETRANSMISSION METRICS:")
        stats([s.bler_dl for s in self.samples], "BLER_DL", "%")
        stats([s.bler_ul for s in self.samples], "BLER_UL", "%")
        stats([float(s.mcs_dl) for s in self.samples if s.mcs_dl > 0], "MCS_DL", "")
        stats([float(s.harq_retx_dl) for s in self.samples], "HARQ_Retx_DL", "")
        
        print(f"\n  {'─'*60}")
        print("  RLC/PDCP METRICS:")
        stats([float(s.rlc_buffer_occupancy) for s in self.samples], "RLC_Buffer", "bytes")
        stats([s.rlc_sdu_delay_dl_us for s in self.samples], "RLC_SDU_Delay", "μs")
        
        print(f"{'='*65}\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="CELL xApp Monitor - 5G Metrics Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Metrics collected:
  ┌─────────────────────────────────────────────────────────────┐
  │ Radio Quality:  RSRP, RSRQ, SINR, CQI                       │
  │ Physical Layer: PRB_Usage_DL/UL, MCS_DL/UL                  │
  │ Throughput:     UE_Throughput_DL/UL                         │
  │ Error Metrics:  BLER_DL/UL, HARQ_Retx_DL/UL                 │
  │ RLC/PDCP:       RLC_Buffer_Occupancy, RLC_SDU_Delay         │
  └─────────────────────────────────────────────────────────────┘

Example:
  python cell_xapp_monitor.py -d 60 -o ./data
        """
    )
    parser.add_argument('-d', '--duration', type=int, default=60,
                        help='Collection duration in seconds (default: 60)')
    parser.add_argument('-o', '--output', type=str, default='./data',
                        help='Output directory (default: ./data)')
    
    args = parser.parse_args()
    
    monitor = CELLxAppMonitor(output_dir=args.output, duration=args.duration)
    csv_path = monitor.collect()
    monitor.print_summary()
    
    print(f"Dataset: {csv_path}")


if __name__ == "__main__":
    main()
