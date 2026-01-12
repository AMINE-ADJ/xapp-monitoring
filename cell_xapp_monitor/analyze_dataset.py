#!/usr/bin/env python3
"""
CELL xApp Monitor - Dataset Analysis Tool

Analyzes KPM datasets collected from FlexRIC and generates
statistical reports and visualizations.

Author: CELL Lab - Sorbonne University
"""

import csv
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import statistics


def load_dataset(csv_path: str) -> list:
    """Load KPM dataset from CSV file."""
    data = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            for key in row:
                if key in ['sample_id', 'ue_id', 'prb_total_dl', 'prb_total_ul', 'prb_dl', 'prb_ul']:
                    try:
                        row[key] = int(row[key]) if row[key] else 0
                    except ValueError:
                        row[key] = 0
                elif key in ['pdcp_sdu_volume_dl_kb', 'pdcp_sdu_volume_ul_kb', 
                            'pdcp_dl_kb', 'pdcp_ul_kb',
                            'rlc_sdu_delay_dl_us', 'rlc_delay_us',
                            'ue_throughput_dl_kbps', 'ue_throughput_ul_kbps',
                            'thp_dl_kbps', 'thp_ul_kbps', 'latency_us']:
                    try:
                        row[key] = float(row[key]) if row[key] else 0.0
                    except ValueError:
                        row[key] = 0.0
            data.append(row)
    return data


def get_metric_values(data: list, metric: str) -> list:
    """Extract metric values from dataset, handling different column names."""
    values = []
    for row in data:
        val = row.get(metric) or row.get(metric.replace('_', ''))
        if val is not None:
            values.append(val)
    return values


def calculate_stats(values: list) -> dict:
    """Calculate statistics for a list of values."""
    if not values:
        return {'count': 0, 'mean': 0, 'std': 0, 'min': 0, 'max': 0, 'median': 0}
    
    return {
        'count': len(values),
        'mean': statistics.mean(values),
        'std': statistics.stdev(values) if len(values) > 1 else 0,
        'min': min(values),
        'max': max(values),
        'median': statistics.median(values)
    }


def analyze_by_phase(data: list) -> dict:
    """Analyze metrics grouped by experiment phase."""
    phases = defaultdict(list)
    
    for row in data:
        phase = row.get('experiment_phase') or row.get('phase', 'unknown')
        phases[phase].append(row)
    
    analysis = {}
    for phase, rows in phases.items():
        thp_dl = [r.get('ue_throughput_dl_kbps') or r.get('thp_dl_kbps', 0) for r in rows]
        thp_ul = [r.get('ue_throughput_ul_kbps') or r.get('thp_ul_kbps', 0) for r in rows]
        prb_dl = [r.get('prb_total_dl') or r.get('prb_dl', 0) for r in rows]
        prb_ul = [r.get('prb_total_ul') or r.get('prb_ul', 0) for r in rows]
        
        analysis[phase] = {
            'sample_count': len(rows),
            'throughput_dl': calculate_stats(thp_dl),
            'throughput_ul': calculate_stats(thp_ul),
            'prb_dl': calculate_stats(prb_dl),
            'prb_ul': calculate_stats(prb_ul)
        }
    
    return analysis


def print_report(data: list, csv_path: str):
    """Print analysis report."""
    print("=" * 80)
    print("  CELL xApp Monitor - Dataset Analysis Report")
    print("=" * 80)
    print(f"\n  Dataset: {csv_path}")
    print(f"  Total Samples: {len(data)}")
    
    if not data:
        print("\n  No data to analyze!")
        return
    
    # Time range
    timestamps = [row.get('timestamp', '') for row in data if row.get('timestamp')]
    if timestamps:
        print(f"  Time Range: {timestamps[0]} to {timestamps[-1]}")
    
    # Unique UEs
    ue_ids = set(row.get('ue_id', 0) for row in data)
    print(f"  Unique UEs: {len(ue_ids)} ({', '.join(map(str, ue_ids))})")
    
    # Overall Statistics
    print("\n" + "-" * 80)
    print("  OVERALL STATISTICS")
    print("-" * 80)
    
    metrics = [
        ('Throughput DL (kbps)', ['ue_throughput_dl_kbps', 'thp_dl_kbps']),
        ('Throughput UL (kbps)', ['ue_throughput_ul_kbps', 'thp_ul_kbps']),
        ('PRB DL', ['prb_total_dl', 'prb_dl']),
        ('PRB UL', ['prb_total_ul', 'prb_ul']),
        ('PDCP DL (kb)', ['pdcp_sdu_volume_dl_kb', 'pdcp_dl_kb']),
        ('PDCP UL (kb)', ['pdcp_sdu_volume_ul_kb', 'pdcp_ul_kb']),
        ('RLC Delay (μs)', ['rlc_sdu_delay_dl_us', 'rlc_delay_us']),
    ]
    
    print(f"\n  {'Metric':<25} {'Mean':>12} {'Std':>12} {'Min':>12} {'Max':>12} {'Median':>12}")
    print("  " + "-" * 85)
    
    for name, keys in metrics:
        values = []
        for key in keys:
            values = [row.get(key, 0) for row in data if row.get(key) is not None]
            if values:
                break
        
        if values:
            stats = calculate_stats(values)
            print(f"  {name:<25} {stats['mean']:>12.2f} {stats['std']:>12.2f} "
                  f"{stats['min']:>12.2f} {stats['max']:>12.2f} {stats['median']:>12.2f}")
    
    # Phase Analysis
    phase_analysis = analyze_by_phase(data)
    
    if len(phase_analysis) > 1:
        print("\n" + "-" * 80)
        print("  ANALYSIS BY EXPERIMENT PHASE")
        print("-" * 80)
        
        for phase, stats in sorted(phase_analysis.items()):
            print(f"\n  Phase: {phase.upper()} ({stats['sample_count']} samples)")
            print(f"    Throughput DL: mean={stats['throughput_dl']['mean']:.2f} kbps, "
                  f"max={stats['throughput_dl']['max']:.2f} kbps")
            print(f"    Throughput UL: mean={stats['throughput_ul']['mean']:.2f} kbps, "
                  f"max={stats['throughput_ul']['max']:.2f} kbps")
            print(f"    PRB Usage DL:  mean={stats['prb_dl']['mean']:.1f}, "
                  f"max={stats['prb_dl']['max']}")
            print(f"    PRB Usage UL:  mean={stats['prb_ul']['mean']:.1f}, "
                  f"max={stats['prb_ul']['max']}")
    
    # Traffic Summary
    print("\n" + "-" * 80)
    print("  TRAFFIC SUMMARY")
    print("-" * 80)
    
    total_pdcp_dl = sum(row.get('pdcp_sdu_volume_dl_kb') or row.get('pdcp_dl_kb', 0) for row in data)
    total_pdcp_ul = sum(row.get('pdcp_sdu_volume_ul_kb') or row.get('pdcp_ul_kb', 0) for row in data)
    
    print(f"\n  Total PDCP Volume DL: {total_pdcp_dl:.2f} kb ({total_pdcp_dl/1024:.2f} MB)")
    print(f"  Total PDCP Volume UL: {total_pdcp_ul:.2f} kb ({total_pdcp_ul/1024:.2f} MB)")
    print(f"  Total Traffic:        {(total_pdcp_dl + total_pdcp_ul):.2f} kb ({(total_pdcp_dl + total_pdcp_ul)/1024:.2f} MB)")
    
    print("\n" + "=" * 80)
    print("  Analysis Complete")
    print("=" * 80)


def export_summary(data: list, output_path: str):
    """Export summary statistics to CSV."""
    phase_analysis = analyze_by_phase(data)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['phase', 'sample_count', 
                        'thp_dl_mean', 'thp_dl_max', 'thp_dl_std',
                        'thp_ul_mean', 'thp_ul_max', 'thp_ul_std',
                        'prb_dl_mean', 'prb_dl_max',
                        'prb_ul_mean', 'prb_ul_max'])
        
        for phase, stats in sorted(phase_analysis.items()):
            writer.writerow([
                phase,
                stats['sample_count'],
                f"{stats['throughput_dl']['mean']:.2f}",
                f"{stats['throughput_dl']['max']:.2f}",
                f"{stats['throughput_dl']['std']:.2f}",
                f"{stats['throughput_ul']['mean']:.2f}",
                f"{stats['throughput_ul']['max']:.2f}",
                f"{stats['throughput_ul']['std']:.2f}",
                f"{stats['prb_dl']['mean']:.1f}",
                stats['prb_dl']['max'],
                f"{stats['prb_ul']['mean']:.1f}",
                stats['prb_ul']['max']
            ])
    
    print(f"\nSummary exported to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='CELL xApp Monitor - Dataset Analysis Tool'
    )
    parser.add_argument('csv_file', help='Path to KPM dataset CSV file')
    parser.add_argument('-s', '--summary', help='Export summary to CSV file')
    
    args = parser.parse_args()
    
    if not Path(args.csv_file).exists():
        print(f"Error: File not found: {args.csv_file}")
        return 1
    
    data = load_dataset(args.csv_file)
    print_report(data, args.csv_file)
    
    if args.summary:
        export_summary(data, args.summary)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
