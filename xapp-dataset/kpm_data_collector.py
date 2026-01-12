#!/usr/bin/env python3
"""
KPM Data Collector for FlexRIC
Collects KPM metrics from FlexRIC xApp and exports to CSV for dataset creation.

This script runs the xapp_kpm_moni binary and parses its output to create
a structured dataset of 5G network performance metrics.
"""

import subprocess
import re
import csv
import time
import sys
import signal
import os
from datetime import datetime
from collections import defaultdict

# Configuration
XAPP_BINARY = "/flexric/build/examples/xApp/c/monitor/xapp_kpm_moni"
OUTPUT_DIR = "/tmp/kpm_dataset"
COLLECTION_DURATION = 300  # 5 minutes default

class KPMDataCollector:
    def __init__(self, output_dir=OUTPUT_DIR, duration=COLLECTION_DURATION):
        self.output_dir = output_dir
        self.duration = duration
        self.data = []
        self.running = True
        self.csv_file = None
        self.csv_writer = None
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
    def signal_handler(self, signum, frame):
        print("\n[Collector] Received signal, stopping collection...")
        self.running = False
        
    def parse_kpm_output(self, line, current_record):
        """Parse a single line from xapp_kpm_moni output."""
        
        # Parse KPM indication header
        kpm_match = re.match(r'\s*(\d+)\s+KPM ind_msg latency = (\d+)', line)
        if kpm_match:
            if current_record.get('sample_id'):
                self.save_record(current_record)
            current_record.clear()
            current_record['sample_id'] = int(kpm_match.group(1))
            current_record['timestamp'] = datetime.now().isoformat()
            current_record['latency_us'] = int(kpm_match.group(2))
            return current_record
        
        # Parse UE ID
        ue_match = re.match(r'UE ID type = .*, amf_ue_ngap_id = (\d+)', line)
        if ue_match:
            current_record['ue_id'] = int(ue_match.group(1))
            return current_record
            
        # Parse metrics
        metrics = [
            (r'DRB\.PdcpSduVolumeDL = (\d+)', 'pdcp_sdu_volume_dl_kb'),
            (r'DRB\.PdcpSduVolumeUL = (\d+)', 'pdcp_sdu_volume_ul_kb'),
            (r'DRB\.RlcSduDelayDl = ([\d.]+)', 'rlc_sdu_delay_dl_us'),
            (r'DRB\.UEThpDl = ([\d.]+)', 'ue_throughput_dl_kbps'),
            (r'DRB\.UEThpUl = ([\d.]+)', 'ue_throughput_ul_kbps'),
            (r'RRU\.PrbTotDl = (\d+)', 'prb_total_dl'),
            (r'RRU\.PrbTotUl = (\d+)', 'prb_total_ul'),
        ]
        
        for pattern, field_name in metrics:
            match = re.search(pattern, line)
            if match:
                value = float(match.group(1))
                current_record[field_name] = value
                
        return current_record
    
    def save_record(self, record):
        """Save a complete KPM record to CSV."""
        if not self.csv_writer:
            return
            
        # Define expected fields with defaults
        fields = [
            'sample_id', 'timestamp', 'latency_us', 'ue_id',
            'pdcp_sdu_volume_dl_kb', 'pdcp_sdu_volume_ul_kb',
            'rlc_sdu_delay_dl_us', 'ue_throughput_dl_kbps', 
            'ue_throughput_ul_kbps', 'prb_total_dl', 'prb_total_ul'
        ]
        
        row = [record.get(f, 0) for f in fields]
        self.csv_writer.writerow(row)
        self.csv_file.flush()
        self.data.append(record.copy())
        
    def collect(self):
        """Main collection loop."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(self.output_dir, f"kpm_dataset_{timestamp}.csv")
        
        print(f"[Collector] Starting KPM data collection")
        print(f"[Collector] Output file: {csv_path}")
        print(f"[Collector] Duration: {self.duration} seconds")
        print(f"[Collector] Press Ctrl+C to stop early\n")
        
        # Open CSV file
        self.csv_file = open(csv_path, 'w', newline='')
        headers = [
            'sample_id', 'timestamp', 'latency_us', 'ue_id',
            'pdcp_sdu_volume_dl_kb', 'pdcp_sdu_volume_ul_kb',
            'rlc_sdu_delay_dl_us', 'ue_throughput_dl_kbps',
            'ue_throughput_ul_kbps', 'prb_total_dl', 'prb_total_ul'
        ]
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(headers)
        
        start_time = time.time()
        current_record = {}
        
        try:
            # Start xApp process
            process = subprocess.Popen(
                [XAPP_BINARY],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            while self.running and (time.time() - start_time) < self.duration:
                line = process.stdout.readline()
                if not line:
                    break
                    
                line = line.strip()
                if line:
                    # Print original output
                    print(line)
                    # Parse and save
                    current_record = self.parse_kpm_output(line, current_record)
                    
            # Save last record
            if current_record.get('sample_id'):
                self.save_record(current_record)
                
            process.terminate()
            process.wait(timeout=5)
            
        except Exception as e:
            print(f"[Collector] Error: {e}")
        finally:
            if self.csv_file:
                self.csv_file.close()
                
        print(f"\n[Collector] Collection complete!")
        print(f"[Collector] Total samples collected: {len(self.data)}")
        print(f"[Collector] Dataset saved to: {csv_path}")
        
        return csv_path


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else COLLECTION_DURATION
    output_dir = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_DIR
    
    collector = KPMDataCollector(output_dir=output_dir, duration=duration)
    csv_path = collector.collect()
    
    # Print summary statistics
    if collector.data:
        print("\n" + "="*60)
        print("DATASET SUMMARY")
        print("="*60)
        
        dl_thp = [d['ue_throughput_dl_kbps'] for d in collector.data if 'ue_throughput_dl_kbps' in d]
        ul_thp = [d['ue_throughput_ul_kbps'] for d in collector.data if 'ue_throughput_ul_kbps' in d]
        prb_dl = [d['prb_total_dl'] for d in collector.data if 'prb_total_dl' in d]
        prb_ul = [d['prb_total_ul'] for d in collector.data if 'prb_total_ul' in d]
        
        if dl_thp:
            print(f"DL Throughput: avg={sum(dl_thp)/len(dl_thp):.2f} kbps, max={max(dl_thp):.2f} kbps")
        if ul_thp:
            print(f"UL Throughput: avg={sum(ul_thp)/len(ul_thp):.2f} kbps, max={max(ul_thp):.2f} kbps")
        if prb_dl:
            print(f"PRB DL: avg={sum(prb_dl)/len(prb_dl):.1f}, max={max(prb_dl)}")
        if prb_ul:
            print(f"PRB UL: avg={sum(prb_ul)/len(prb_ul):.1f}, max={max(prb_ul)}")


if __name__ == "__main__":
    main()
