#!/usr/bin/env python3
"""
KPM xApp Dataset Collector
===========================
This xApp utilizes the KPM (Key Performance Metrics) service model within FlexRIC
to monitor and observe different KPM metrics from the 5G RAN.

The xApp wraps the FlexRIC C-based KPM monitor (xapp_kpm_moni) and parses its
output to create structured datasets for machine learning and analysis.

KPM Metrics Collected (O-RAN E2SM-KPM v02.03):
- DRB.PdcpSduVolumeDL: PDCP SDU Volume Downlink [kb]
- DRB.PdcpSduVolumeUL: PDCP SDU Volume Uplink [kb]
- DRB.RlcSduDelayDl: RLC SDU Delay Downlink [μs]
- DRB.UEThpDl: UE Throughput Downlink [kbps]
- DRB.UEThpUl: UE Throughput Uplink [kbps]
- RRU.PrbTotDl: Total PRBs Downlink
- RRU.PrbTotUl: Total PRBs Uplink

Author: KPM xApp for FlexRIC
Version: 1.0.0
"""

import subprocess
import re
import csv
import time
import argparse
import os
import sys
import signal
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
import threading
import json

# =============================================================================
# Configuration
# =============================================================================

@dataclass
class KPMConfig:
    """Configuration for KPM xApp"""
    flexric_pod: str = "oai-flexric"
    namespace: str = "blueprint"
    kpm_xapp_path: str = "/flexric/build/examples/xApp/c/monitor/xapp_kpm_moni"
    mac_xapp_path: str = "/flexric/build/examples/xApp/c/monitor/xapp_gtp_mac_rlc_pdcp_moni"
    output_dir: str = "./data"
    collection_duration: int = 300  # seconds
    sample_interval: float = 1.0  # seconds between samples
    target_samples: int = 1000
    experiment_name: str = "kpm_experiment"
    
# =============================================================================
# KPM Metrics Data Structures
# =============================================================================

@dataclass
class KPMSample:
    """Single KPM sample from FlexRIC"""
    timestamp: str
    sample_id: int
    ue_id_type: str
    amf_ue_ngap_id: int
    # KPM Metrics
    pdcp_sdu_volume_dl_kb: float
    pdcp_sdu_volume_ul_kb: float
    rlc_sdu_delay_dl_us: float
    ue_thp_dl_kbps: float
    ue_thp_ul_kbps: float
    prb_tot_dl: int
    prb_tot_ul: int
    # Latency
    kpm_latency_us: float
    # Experiment metadata
    experiment_id: str = ""
    traffic_type: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'sample_id': self.sample_id,
            'ue_id_type': self.ue_id_type,
            'amf_ue_ngap_id': self.amf_ue_ngap_id,
            'DRB.PdcpSduVolumeDL_kb': self.pdcp_sdu_volume_dl_kb,
            'DRB.PdcpSduVolumeUL_kb': self.pdcp_sdu_volume_ul_kb,
            'DRB.RlcSduDelayDl_us': self.rlc_sdu_delay_dl_us,
            'DRB.UEThpDl_kbps': self.ue_thp_dl_kbps,
            'DRB.UEThpUl_kbps': self.ue_thp_ul_kbps,
            'RRU.PrbTotDl': self.prb_tot_dl,
            'RRU.PrbTotUl': self.prb_tot_ul,
            'kpm_latency_us': self.kpm_latency_us,
            'experiment_id': self.experiment_id,
            'traffic_type': self.traffic_type
        }

# =============================================================================
# KPM Parser
# =============================================================================

class KPMParser:
    """Parser for KPM xApp output"""
    
    # Regex patterns for KPM output
    SAMPLE_PATTERN = re.compile(r'^\s*(\d+)\s+KPM ind_msg latency\s*=\s*(\d+)\s*\[μs\]')
    UE_ID_PATTERN = re.compile(r'UE ID type\s*=\s*(\w+),\s*amf_ue_ngap_id\s*=\s*(\d+)')
    PDCP_DL_PATTERN = re.compile(r'DRB\.PdcpSduVolumeDL\s*=\s*([\d.]+)\s*\[kb\]')
    PDCP_UL_PATTERN = re.compile(r'DRB\.PdcpSduVolumeUL\s*=\s*([\d.]+)\s*\[kb\]')
    RLC_DELAY_PATTERN = re.compile(r'DRB\.RlcSduDelayDl\s*=\s*([\d.]+)\s*\[μs\]')
    UE_THP_DL_PATTERN = re.compile(r'DRB\.UEThpDl\s*=\s*([\d.]+)\s*\[kbps\]')
    UE_THP_UL_PATTERN = re.compile(r'DRB\.UEThpUl\s*=\s*([\d.]+)\s*\[kbps\]')
    PRB_DL_PATTERN = re.compile(r'RRU\.PrbTotDl\s*=\s*(\d+)\s*\[PRBs?\]')
    PRB_UL_PATTERN = re.compile(r'RRU\.PrbTotUl\s*=\s*(\d+)\s*\[PRBs?\]')
    
    def __init__(self):
        self.current_sample: Dict = {}
        self.samples: List[KPMSample] = []
        
    def parse_line(self, line: str, experiment_id: str = "", traffic_type: str = "") -> Optional[KPMSample]:
        """Parse a single line from KPM xApp output"""
        line = line.strip()
        
        # Check for new sample
        sample_match = self.SAMPLE_PATTERN.match(line)
        if sample_match:
            # Save previous sample if complete
            if self.current_sample and 'sample_id' in self.current_sample:
                sample = self._create_sample(experiment_id, traffic_type)
                if sample:
                    self.samples.append(sample)
            # Start new sample
            self.current_sample = {
                'sample_id': int(sample_match.group(1)),
                'kpm_latency_us': float(sample_match.group(2)),
                'timestamp': datetime.now().isoformat()
            }
            return None
            
        # Parse UE ID
        ue_match = self.UE_ID_PATTERN.search(line)
        if ue_match:
            self.current_sample['ue_id_type'] = ue_match.group(1)
            self.current_sample['amf_ue_ngap_id'] = int(ue_match.group(2))
            return None
            
        # Parse metrics
        for pattern, key in [
            (self.PDCP_DL_PATTERN, 'pdcp_sdu_volume_dl_kb'),
            (self.PDCP_UL_PATTERN, 'pdcp_sdu_volume_ul_kb'),
            (self.RLC_DELAY_PATTERN, 'rlc_sdu_delay_dl_us'),
            (self.UE_THP_DL_PATTERN, 'ue_thp_dl_kbps'),
            (self.UE_THP_UL_PATTERN, 'ue_thp_ul_kbps'),
        ]:
            match = pattern.search(line)
            if match:
                self.current_sample[key] = float(match.group(1))
                return None
                
        # Parse PRB (integer values)
        for pattern, key in [
            (self.PRB_DL_PATTERN, 'prb_tot_dl'),
            (self.PRB_UL_PATTERN, 'prb_tot_ul'),
        ]:
            match = pattern.search(line)
            if match:
                self.current_sample[key] = int(match.group(1))
                # Check if sample is complete after PRB_UL
                if key == 'prb_tot_ul' and self._is_sample_complete():
                    sample = self._create_sample(experiment_id, traffic_type)
                    if sample:
                        self.samples.append(sample)
                        return sample
                return None
                
        return None
    
    def _is_sample_complete(self) -> bool:
        """Check if current sample has all required fields"""
        required = ['sample_id', 'ue_id_type', 'amf_ue_ngap_id', 
                   'pdcp_sdu_volume_dl_kb', 'pdcp_sdu_volume_ul_kb',
                   'rlc_sdu_delay_dl_us', 'ue_thp_dl_kbps', 'ue_thp_ul_kbps',
                   'prb_tot_dl', 'prb_tot_ul']
        return all(k in self.current_sample for k in required)
    
    def _create_sample(self, experiment_id: str, traffic_type: str) -> Optional[KPMSample]:
        """Create KPMSample from current_sample dict"""
        if not self._is_sample_complete():
            return None
        try:
            return KPMSample(
                timestamp=self.current_sample.get('timestamp', datetime.now().isoformat()),
                sample_id=self.current_sample['sample_id'],
                ue_id_type=self.current_sample['ue_id_type'],
                amf_ue_ngap_id=self.current_sample['amf_ue_ngap_id'],
                pdcp_sdu_volume_dl_kb=self.current_sample['pdcp_sdu_volume_dl_kb'],
                pdcp_sdu_volume_ul_kb=self.current_sample['pdcp_sdu_volume_ul_kb'],
                rlc_sdu_delay_dl_us=self.current_sample['rlc_sdu_delay_dl_us'],
                ue_thp_dl_kbps=self.current_sample['ue_thp_dl_kbps'],
                ue_thp_ul_kbps=self.current_sample['ue_thp_ul_kbps'],
                prb_tot_dl=self.current_sample['prb_tot_dl'],
                prb_tot_ul=self.current_sample['prb_tot_ul'],
                kpm_latency_us=self.current_sample.get('kpm_latency_us', 0),
                experiment_id=experiment_id,
                traffic_type=traffic_type
            )
        except KeyError as e:
            print(f"[KPM Parser] Missing key: {e}")
            return None

# =============================================================================
# KPM xApp
# =============================================================================

class KPMxApp:
    """
    KPM xApp for FlexRIC
    
    This xApp subscribes to KPM (Key Performance Metrics) service model
    and collects metrics for dataset creation.
    """
    
    def __init__(self, config: KPMConfig):
        self.config = config
        self.parser = KPMParser()
        self.samples: List[KPMSample] = []
        self.running = False
        self.process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        
        # Ensure output directory exists
        os.makedirs(config.output_dir, exist_ok=True)
        
    def get_flexric_pod(self) -> str:
        """Get the FlexRIC pod name"""
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'pods', '-n', self.config.namespace, 
                 '-l', 'app.kubernetes.io/name=oai-flexric', '-o', 'jsonpath={.items[0].metadata.name}'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            print(f"[KPM xApp] Error getting FlexRIC pod: {e}")
        
        # Fallback: search by name pattern
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'pods', '-n', self.config.namespace, '-o', 'name'],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split('\n'):
                if 'flexric' in line.lower():
                    return line.replace('pod/', '')
        except:
            pass
            
        return self.config.flexric_pod
        
    def start_kpm_collection(self, duration: int, experiment_id: str = "", 
                             traffic_type: str = "") -> List[KPMSample]:
        """
        Start KPM metric collection from FlexRIC
        
        Args:
            duration: Collection duration in seconds
            experiment_id: Identifier for this experiment
            traffic_type: Type of traffic being generated
            
        Returns:
            List of KPM samples collected
        """
        pod_name = self.get_flexric_pod()
        print(f"\n{'='*60}")
        print(f"[KPM xApp] Starting KPM Collection")
        print(f"{'='*60}")
        print(f"  FlexRIC Pod: {pod_name}")
        print(f"  Namespace: {self.config.namespace}")
        print(f"  Duration: {duration} seconds")
        print(f"  Experiment: {experiment_id}")
        print(f"  Traffic Type: {traffic_type}")
        print(f"{'='*60}\n")
        
        # Command to run KPM xApp
        cmd = [
            'kubectl', 'exec', '-n', self.config.namespace, pod_name, '--',
            'timeout', str(duration), self.config.kpm_xapp_path
        ]
        
        self.running = True
        self._stop_event.clear()
        samples_collected = []
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            start_time = time.time()
            
            for line in iter(self.process.stdout.readline, ''):
                if self._stop_event.is_set():
                    break
                    
                # Parse the line
                sample = self.parser.parse_line(line, experiment_id, traffic_type)
                if sample:
                    samples_collected.append(sample)
                    self.samples.append(sample)
                    
                    # Progress update
                    if len(samples_collected) % 10 == 0:
                        elapsed = time.time() - start_time
                        print(f"[KPM xApp] Collected {len(samples_collected)} samples in {elapsed:.1f}s")
                        
                        # Show latest sample
                        print(f"  Latest: PRB_DL={sample.prb_tot_dl}, PRB_UL={sample.prb_tot_ul}, "
                              f"Thp_DL={sample.ue_thp_dl_kbps:.2f}kbps, Thp_UL={sample.ue_thp_ul_kbps:.2f}kbps")
                
            self.process.wait()
            
        except Exception as e:
            print(f"[KPM xApp] Error during collection: {e}")
        finally:
            self.running = False
            if self.process:
                self.process.terminate()
                
        print(f"\n[KPM xApp] Collection complete: {len(samples_collected)} samples")
        return samples_collected
    
    def stop(self):
        """Stop the KPM collection"""
        self._stop_event.set()
        if self.process:
            self.process.terminate()
        self.running = False
        
    def save_dataset(self, filename: str = None, samples: List[KPMSample] = None):
        """Save collected samples to CSV"""
        if samples is None:
            samples = self.samples
            
        if not samples:
            print("[KPM xApp] No samples to save")
            return
            
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(self.config.output_dir, f'kpm_dataset_{timestamp}.csv')
        elif not filename.startswith('/'):
            filename = os.path.join(self.config.output_dir, filename)
            
        # Get headers from first sample
        headers = list(samples[0].to_dict().keys())
        
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for sample in samples:
                writer.writerow(sample.to_dict())
                
        print(f"[KPM xApp] Saved {len(samples)} samples to {filename}")
        return filename

# =============================================================================
# Experiment Runner
# =============================================================================

class ExperimentRunner:
    """
    Run multiple experiments with different traffic patterns
    """
    
    def __init__(self, config: KPMConfig):
        self.config = config
        self.xapp = KPMxApp(config)
        self.all_samples: List[KPMSample] = []
        
    def get_ue_pod(self) -> str:
        """Get UE pod name"""
        result = subprocess.run(
            ['kubectl', 'get', 'pods', '-n', self.config.namespace, '-o', 'name'],
            capture_output=True, text=True
        )
        for line in result.stdout.split('\n'):
            if 'nr-ue' in line.lower():
                return line.replace('pod/', '')
        return None
        
    def get_gnb_pod(self) -> str:
        """Get gNB pod name"""
        result = subprocess.run(
            ['kubectl', 'get', 'pods', '-n', self.config.namespace, '-o', 'name'],
            capture_output=True, text=True
        )
        for line in result.stdout.split('\n'):
            if 'gnb' in line.lower() and 'flexric' not in line.lower():
                return line.replace('pod/', '')
        return None
        
    def start_traffic(self, traffic_type: str, duration: int, bitrate: str = "10M") -> subprocess.Popen:
        """Start traffic generation"""
        ue_pod = self.get_ue_pod()
        if not ue_pod:
            print("[Experiment] Could not find UE pod")
            return None
            
        # Get UPF IP (destination for traffic)
        upf_ip = "12.1.1.1"  # Default UPF tunnel IP
        
        if traffic_type == "udp_dl":
            # UDP Downlink: iperf3 client on UPF, server on UE
            cmd = ['kubectl', 'exec', '-n', self.config.namespace, ue_pod, '-c', 'nr-ue', '--',
                   'iperf3', '-s', '-p', '5201', '-1']  # One-shot server
        elif traffic_type == "udp_ul":
            # UDP Uplink: iperf3 client on UE
            cmd = ['kubectl', 'exec', '-n', self.config.namespace, ue_pod, '-c', 'nr-ue', '--',
                   'iperf3', '-c', upf_ip, '-p', '5201', '-u', '-b', bitrate, '-t', str(duration)]
        elif traffic_type == "tcp_dl":
            cmd = ['kubectl', 'exec', '-n', self.config.namespace, ue_pod, '-c', 'nr-ue', '--',
                   'iperf3', '-s', '-p', '5201', '-1']
        elif traffic_type == "tcp_ul":
            cmd = ['kubectl', 'exec', '-n', self.config.namespace, ue_pod, '-c', 'nr-ue', '--',
                   'iperf3', '-c', upf_ip, '-p', '5201', '-t', str(duration)]
        elif traffic_type == "ping":
            cmd = ['kubectl', 'exec', '-n', self.config.namespace, ue_pod, '-c', 'nr-ue', '--',
                   'ping', '-c', str(duration), upf_ip]
        elif traffic_type == "idle":
            return None  # No traffic
        else:
            print(f"[Experiment] Unknown traffic type: {traffic_type}")
            return None
            
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(f"[Experiment] Started {traffic_type} traffic (bitrate={bitrate})")
            return process
        except Exception as e:
            print(f"[Experiment] Failed to start traffic: {e}")
            return None
            
    def run_experiment(self, experiment_name: str, traffic_type: str, 
                       duration: int, bitrate: str = "10M") -> List[KPMSample]:
        """Run a single experiment"""
        print(f"\n{'#'*60}")
        print(f"# EXPERIMENT: {experiment_name}")
        print(f"# Traffic: {traffic_type}, Bitrate: {bitrate}, Duration: {duration}s")
        print(f"{'#'*60}\n")
        
        # Start traffic generation in background
        traffic_proc = self.start_traffic(traffic_type, duration, bitrate)
        time.sleep(2)  # Let traffic stabilize
        
        # Collect KPM metrics
        samples = self.xapp.start_kpm_collection(
            duration=duration,
            experiment_id=experiment_name,
            traffic_type=traffic_type
        )
        
        # Stop traffic
        if traffic_proc:
            traffic_proc.terminate()
            traffic_proc.wait()
            
        self.all_samples.extend(samples)
        return samples
        
    def run_multi_experiment(self, target_samples: int = 1000) -> str:
        """
        Run multiple experiments with different traffic patterns to collect target samples
        """
        print(f"\n{'='*60}")
        print(f"[Experiment Runner] Starting Multi-Experiment Collection")
        print(f"  Target Samples: {target_samples}")
        print(f"{'='*60}\n")
        
        experiments = [
            # (name, traffic_type, duration, bitrate)
            ("idle_baseline", "idle", 30, "0"),
            ("udp_ul_5M", "udp_ul", 60, "5M"),
            ("udp_ul_10M", "udp_ul", 60, "10M"),
            ("udp_ul_15M", "udp_ul", 60, "15M"),
            ("udp_ul_20M", "udp_ul", 60, "20M"),
            ("tcp_ul_burst", "tcp_ul", 60, "0"),
            ("ping_test", "ping", 30, "0"),
            ("idle_recovery", "idle", 30, "0"),
            ("udp_ul_variable", "udp_ul", 90, "8M"),
            ("udp_ul_high", "udp_ul", 90, "25M"),
        ]
        
        collected = 0
        exp_idx = 0
        
        while collected < target_samples and exp_idx < len(experiments) * 3:
            exp = experiments[exp_idx % len(experiments)]
            name, traffic, duration, bitrate = exp
            
            # Adjust experiment name for repetitions
            repeat = exp_idx // len(experiments)
            if repeat > 0:
                name = f"{name}_r{repeat}"
                
            samples = self.run_experiment(name, traffic, duration, bitrate)
            collected += len(samples)
            exp_idx += 1
            
            print(f"\n[Progress] Total samples: {collected}/{target_samples}")
            
            # Brief pause between experiments
            time.sleep(5)
            
        # Save all samples
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = os.path.join(self.config.output_dir, f'kpm_multi_experiment_{timestamp}.csv')
        self.xapp.save_dataset(filename, self.all_samples)
        
        # Also save experiment summary
        summary = {
            'total_samples': len(self.all_samples),
            'experiments_run': exp_idx,
            'timestamp': timestamp,
            'dataset_file': filename
        }
        summary_file = os.path.join(self.config.output_dir, f'experiment_summary_{timestamp}.json')
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
            
        print(f"\n{'='*60}")
        print(f"[Experiment Runner] Collection Complete!")
        print(f"  Total Samples: {len(self.all_samples)}")
        print(f"  Dataset: {filename}")
        print(f"  Summary: {summary_file}")
        print(f"{'='*60}\n")
        
        return filename

# =============================================================================
# Main Entry Point
# =============================================================================

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\n[KPM xApp] Received interrupt signal, stopping...")
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(
        description='KPM xApp Dataset Collector for FlexRIC',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simple collection for 60 seconds
  python kpm_dataset_collector.py -d 60
  
  # Collect 1000 samples with multi-experiment
  python kpm_dataset_collector.py -n 1000 --multi-experiment
  
  # Custom output directory
  python kpm_dataset_collector.py -d 120 -o ./my_data
        """
    )
    
    parser.add_argument('-d', '--duration', type=int, default=60,
                        help='Collection duration in seconds (default: 60)')
    parser.add_argument('-n', '--num-samples', type=int, default=100,
                        help='Target number of samples (default: 100)')
    parser.add_argument('-o', '--output', type=str, default='./data',
                        help='Output directory (default: ./data)')
    parser.add_argument('--namespace', type=str, default='blueprint',
                        help='Kubernetes namespace (default: blueprint)')
    parser.add_argument('--multi-experiment', action='store_true',
                        help='Run multiple experiments with different traffic patterns')
    parser.add_argument('--traffic', type=str, default='idle',
                        choices=['idle', 'udp_ul', 'udp_dl', 'tcp_ul', 'tcp_dl', 'ping'],
                        help='Traffic type for single experiment (default: idle)')
    parser.add_argument('--bitrate', type=str, default='10M',
                        help='Traffic bitrate (default: 10M)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    
    args = parser.parse_args()
    
    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    # Create config
    config = KPMConfig(
        output_dir=args.output,
        namespace=args.namespace,
        collection_duration=args.duration,
        target_samples=args.num_samples
    )
    
    # Ensure output directory exists
    os.makedirs(config.output_dir, exist_ok=True)
    
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║            KPM xApp Dataset Collector for FlexRIC             ║
╠═══════════════════════════════════════════════════════════════╣
║  Utilizing O-RAN E2SM-KPM Service Model v02.03                ║
║  Metrics: PRB, Throughput, PDCP Volume, RLC Delay             ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    if args.multi_experiment:
        # Run multiple experiments
        runner = ExperimentRunner(config)
        dataset_file = runner.run_multi_experiment(target_samples=args.num_samples)
    else:
        # Single collection
        xapp = KPMxApp(config)
        samples = xapp.start_kpm_collection(
            duration=args.duration,
            experiment_id=config.experiment_name,
            traffic_type=args.traffic
        )
        dataset_file = xapp.save_dataset()
        
    print(f"\n[KPM xApp] Dataset saved to: {dataset_file}")

if __name__ == '__main__':
    main()
