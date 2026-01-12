#!/usr/bin/env python3
"""
Parse KPM xApp raw output and convert to CSV dataset.
"""

import re
import csv
import sys
from datetime import datetime

def parse_kpm_log(input_file, output_file):
    """Parse KPM log file and create CSV dataset."""
    
    records = []
    current = {}
    
    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            
            # Parse sample header
            match = re.match(r'\s*(\d+)\s+KPM ind_msg latency\s*=\s*(\d+)', line)
            if match:
                if current.get('sample_id'):
                    current['timestamp'] = datetime.now().isoformat()
                    records.append(current.copy())
                current = {
                    'sample_id': int(match.group(1)),
                    'latency_us': int(match.group(2))
                }
                continue
            
            # Parse UE ID
            match = re.search(r'amf_ue_ngap_id\s*=\s*(\d+)', line)
            if match:
                current['ue_id'] = int(match.group(1))
                continue
            
            # Parse metrics
            patterns = [
                (r'DRB\.PdcpSduVolumeDL\s*=\s*(\d+)', 'pdcp_sdu_volume_dl_kb', int),
                (r'DRB\.PdcpSduVolumeUL\s*=\s*(\d+)', 'pdcp_sdu_volume_ul_kb', int),
                (r'DRB\.RlcSduDelayDl\s*=\s*([\d.]+)', 'rlc_sdu_delay_dl_us', float),
                (r'DRB\.UEThpDl\s*=\s*([\d.]+)', 'ue_throughput_dl_kbps', float),
                (r'DRB\.UEThpUl\s*=\s*([\d.]+)', 'ue_throughput_ul_kbps', float),
                (r'RRU\.PrbTotDl\s*=\s*(\d+)', 'prb_total_dl', int),
                (r'RRU\.PrbTotUl\s*=\s*(\d+)', 'prb_total_ul', int),
            ]
            
            for pattern, field, converter in patterns:
                match = re.search(pattern, line)
                if match:
                    current[field] = converter(match.group(1))
    
    # Don't forget last record
    if current.get('sample_id'):
        current['timestamp'] = datetime.now().isoformat()
        records.append(current)
    
    # Write CSV
    if records:
        fieldnames = [
            'sample_id', 'timestamp', 'latency_us', 'ue_id',
            'pdcp_sdu_volume_dl_kb', 'pdcp_sdu_volume_ul_kb',
            'rlc_sdu_delay_dl_us', 'ue_throughput_dl_kbps',
            'ue_throughput_ul_kbps', 'prb_total_dl', 'prb_total_ul'
        ]
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(records)
    
    return len(records)


def main():
    if len(sys.argv) < 3:
        print("Usage: parse_kpm_log.py <input_log> <output_csv>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    count = parse_kpm_log(input_file, output_file)
    print(f"Parsed {count} records to {output_file}")
    
    # Show preview
    if count > 0:
        print("\nFirst 5 records:")
        with open(output_file, 'r') as f:
            for i, line in enumerate(f):
                if i > 5:
                    break
                print(line.strip())


if __name__ == "__main__":
    main()
