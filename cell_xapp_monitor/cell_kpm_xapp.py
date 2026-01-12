#!/usr/bin/env python3
"""
CELL KPM xApp - Real-time 5G Metrics Collector

This xApp uses the FlexRIC Python SDK to collect comprehensive 5G metrics
via MAC, RLC, and PDCP service models with real-time callbacks.

Metrics collected:
- MAC: CQI, PUSCH SNR, UL/DL BLER, UL/DL MCS, UL/DL Throughput, RNTI
- RLC: Buffer occupancy, retransmissions, SDU packets
- PDCP: SDU volumes, packet counts

Output: cell_monitoring_dataset.csv (unified dataset)

Author: CELL Lab - Sorbonne University
Date: January 2026
"""

import time
import os
import csv
import sys
import signal
import threading

# Import FlexRIC SDK
cur_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(cur_dir)

import xapp_sdk as ric

# Configuration
OUTPUT_FILE = 'cell_monitoring_dataset.csv'
TARGET_SAMPLES = 1000
REPORT_INTERVAL_SEC = 1.0  # Collect 1 sample per second

# CSV Headers
CSV_HEADERS = [
    'timestamp',
    'sample_id',
    # MAC Layer Metrics
    'rnti',
    'frame',
    'slot',
    'wb_cqi',
    'dl_mcs1',
    'dl_mcs2',
    'ul_mcs1',
    'ul_mcs2',
    'dl_bler',
    'ul_bler',
    'dl_curr_tbs',
    'ul_curr_tbs',
    'dl_aggr_tbs',
    'ul_aggr_tbs',
    'dl_aggr_prb',
    'ul_aggr_prb',
    'pusch_snr',
    'pucch_snr',
    'bsr',
    'dl_num_harq',
    'ul_num_harq',
    # RLC Layer Metrics
    'rlc_mode',
    'rlc_txpdu_pkts',
    'rlc_txpdu_bytes',
    'rlc_txpdu_wt_ms',
    'rlc_txpdu_dd_pkts',
    'rlc_txpdu_dd_bytes',
    'rlc_txpdu_retx_pkts',
    'rlc_txpdu_retx_bytes',
    'rlc_txpdu_segmented',
    'rlc_txpdu_status_pkts',
    'rlc_txpdu_status_bytes',
    'rlc_txbuf_occ_bytes',
    'rlc_txbuf_occ_pkts',
    'rlc_rxpdu_pkts',
    'rlc_rxpdu_bytes',
    'rlc_rxpdu_dup_pkts',
    'rlc_rxpdu_dup_bytes',
    'rlc_rxpdu_dd_pkts',
    'rlc_rxpdu_dd_bytes',
    'rlc_rxpdu_ow_pkts',
    'rlc_rxpdu_ow_bytes',
    'rlc_rxpdu_status_pkts',
    'rlc_rxpdu_status_bytes',
    'rlc_rxbuf_occ_bytes',
    'rlc_rxbuf_occ_pkts',
    'rlc_txsdu_pkts',
    'rlc_txsdu_bytes',
    'rlc_rxsdu_pkts',
    'rlc_rxsdu_bytes',
    # PDCP Layer Metrics
    'pdcp_txpdu_pkts',
    'pdcp_txpdu_bytes',
    'pdcp_txpdu_sn',
    'pdcp_rxpdu_pkts',
    'pdcp_rxpdu_bytes',
    'pdcp_rxpdu_sn',
    'pdcp_rxpdu_oo_pkts',
    'pdcp_rxpdu_oo_bytes',
    'pdcp_rxpdu_dd_pkts',
    'pdcp_rxpdu_dd_bytes',
    'pdcp_rxpdu_ro_count',
    'pdcp_txsdu_pkts',
    'pdcp_txsdu_bytes',
    'pdcp_rxsdu_pkts',
    'pdcp_rxsdu_bytes',
    # Derived Metrics
    'dl_throughput_mbps',
    'ul_throughput_mbps',
]


class CellKPMxApp:
    """CELL KPM xApp - Collects 5G metrics using FlexRIC SDK."""
    
    def __init__(self, target_samples=TARGET_SAMPLES, output_file=OUTPUT_FILE):
        self.target_samples = target_samples
        self.output_file = output_file
        self.sample_counter = 0
        self.running = True
        
        # Latest metrics from callbacks
        self.latest_mac = {}
        self.latest_rlc = {}
        self.latest_pdcp = {}
        self.lock = threading.Lock()
        
        # For throughput calculation
        self.prev_dl_tbs = 0
        self.prev_ul_tbs = 0
        self.last_tbs_time = time.time()
        
        # Handlers
        self.mac_hndlr = []
        self.rlc_hndlr = []
        self.pdcp_hndlr = []
        
        # Initialize CSV
        self._init_csv()
        
        # Signal handler
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        print("\n[CELL xApp] Stopping...")
        self.running = False
        
    def _init_csv(self):
        """Initialize CSV file with headers."""
        with open(self.output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
        print(f"[CELL xApp] Initialized {self.output_file}")
    
    def _create_sample(self):
        """Create and save a sample from current metrics."""
        self.sample_counter += 1
        current_time = time.time()
        
        with self.lock:
            mac = self.latest_mac.copy()
            rlc = self.latest_rlc.copy()
            pdcp = self.latest_pdcp.copy()
        
        # Calculate throughput
        dl_tbs = mac.get('dl_aggr_tbs', 0)
        ul_tbs = mac.get('ul_aggr_tbs', 0)
        time_diff = current_time - self.last_tbs_time
        
        dl_throughput = 0.0
        ul_throughput = 0.0
        if time_diff > 0 and self.prev_dl_tbs > 0:
            dl_diff = dl_tbs - self.prev_dl_tbs
            ul_diff = ul_tbs - self.prev_ul_tbs
            if dl_diff > 0:
                dl_throughput = (dl_diff * 8) / (time_diff * 1000000)  # Mbps
            if ul_diff > 0:
                ul_throughput = (ul_diff * 8) / (time_diff * 1000000)  # Mbps
        
        self.prev_dl_tbs = dl_tbs
        self.prev_ul_tbs = ul_tbs
        self.last_tbs_time = current_time
        
        # Build row
        row = [
            time.strftime('%Y-%m-%d %H:%M:%S'),
            self.sample_counter,
            # MAC
            mac.get('rnti', 0),
            mac.get('frame', 0),
            mac.get('slot', 0),
            mac.get('wb_cqi', 0),
            mac.get('dl_mcs1', 0),
            mac.get('dl_mcs2', 0),
            mac.get('ul_mcs1', 0),
            mac.get('ul_mcs2', 0),
            mac.get('dl_bler', 0),
            mac.get('ul_bler', 0),
            mac.get('dl_curr_tbs', 0),
            mac.get('ul_curr_tbs', 0),
            mac.get('dl_aggr_tbs', 0),
            mac.get('ul_aggr_tbs', 0),
            mac.get('dl_aggr_prb', 0),
            mac.get('ul_aggr_prb', 0),
            mac.get('pusch_snr', 0),
            mac.get('pucch_snr', 0),
            mac.get('bsr', 0),
            mac.get('dl_num_harq', 0),
            mac.get('ul_num_harq', 0),
            # RLC
            rlc.get('mode', 0),
            rlc.get('txpdu_pkts', 0),
            rlc.get('txpdu_bytes', 0),
            rlc.get('txpdu_wt_ms', 0),
            rlc.get('txpdu_dd_pkts', 0),
            rlc.get('txpdu_dd_bytes', 0),
            rlc.get('txpdu_retx_pkts', 0),
            rlc.get('txpdu_retx_bytes', 0),
            rlc.get('txpdu_segmented', 0),
            rlc.get('txpdu_status_pkts', 0),
            rlc.get('txpdu_status_bytes', 0),
            rlc.get('txbuf_occ_bytes', 0),
            rlc.get('txbuf_occ_pkts', 0),
            rlc.get('rxpdu_pkts', 0),
            rlc.get('rxpdu_bytes', 0),
            rlc.get('rxpdu_dup_pkts', 0),
            rlc.get('rxpdu_dup_bytes', 0),
            rlc.get('rxpdu_dd_pkts', 0),
            rlc.get('rxpdu_dd_bytes', 0),
            rlc.get('rxpdu_ow_pkts', 0),
            rlc.get('rxpdu_ow_bytes', 0),
            rlc.get('rxpdu_status_pkts', 0),
            rlc.get('rxpdu_status_bytes', 0),
            rlc.get('rxbuf_occ_bytes', 0),
            rlc.get('rxbuf_occ_pkts', 0),
            rlc.get('txsdu_pkts', 0),
            rlc.get('txsdu_bytes', 0),
            rlc.get('rxsdu_pkts', 0),
            rlc.get('rxsdu_bytes', 0),
            # PDCP
            pdcp.get('txpdu_pkts', 0),
            pdcp.get('txpdu_bytes', 0),
            pdcp.get('txpdu_sn', 0),
            pdcp.get('rxpdu_pkts', 0),
            pdcp.get('rxpdu_bytes', 0),
            pdcp.get('rxpdu_sn', 0),
            pdcp.get('rxpdu_oo_pkts', 0),
            pdcp.get('rxpdu_oo_bytes', 0),
            pdcp.get('rxpdu_dd_pkts', 0),
            pdcp.get('rxpdu_dd_bytes', 0),
            pdcp.get('rxpdu_ro_count', 0),
            pdcp.get('txsdu_pkts', 0),
            pdcp.get('txsdu_bytes', 0),
            pdcp.get('rxsdu_pkts', 0),
            pdcp.get('rxsdu_bytes', 0),
            # Derived
            round(dl_throughput, 3),
            round(ul_throughput, 3),
        ]
        
        # Write to CSV
        with open(self.output_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(row)
        
        # Progress
        if self.sample_counter % 50 == 0:
            print(f"[Sample {self.sample_counter:5d}/{self.target_samples}] "
                  f"CQI={mac.get('wb_cqi', 0):2d}  "
                  f"SNR={mac.get('pusch_snr', 0):5.1f}dB  "
                  f"BLER_DL={mac.get('dl_bler', 0):.4f}  "
                  f"Thp_DL={dl_throughput:6.2f}Mbps  "
                  f"RLC_Buf={rlc.get('txbuf_occ_bytes', 0):6d}B")
    
    def run(self):
        """Main xApp loop."""
        print("\n" + "="*65)
        print("   CELL KPM xApp v1.0.0")
        print("   Real-time 5G Metrics Collector using FlexRIC SDK")
        print("="*65)
        print(f"  Target Samples: {self.target_samples}")
        print(f"  Output File:    {self.output_file}")
        print("="*65)
        print("\n  Metrics: MAC (CQI, SNR, BLER, MCS, TBS)")
        print("           RLC (Buffer, Retx, SDU)")
        print("           PDCP (PDU/SDU volumes)")
        print("="*65 + "\n")
        
        # Initialize RIC
        print("[CELL xApp] Initializing FlexRIC SDK...")
        ric.init()
        
        # Get E2 nodes
        conn = ric.conn_e2_nodes()
        if len(conn) == 0:
            print("[ERROR] No E2 nodes connected!")
            return
        
        print(f"[CELL xApp] Connected to {len(conn)} E2 node(s)")
        for i, node in enumerate(conn):
            print(f"  Node [{i}]: PLMN MCC={node.id.plmn.mcc} MNC={node.id.plmn.mnc}")
        
        # Reference to self for callbacks
        xapp = self
        
        ####################
        # MAC Callback
        ####################
        class MACCallback(ric.mac_cb):
            def __init__(self):
                ric.mac_cb.__init__(self)
                
            def handle(self, ind):
                if len(ind.ue_stats) > 0:
                    ue = ind.ue_stats[0]
                    with xapp.lock:
                        xapp.latest_mac = {
                            'rnti': ue.rnti,
                            'frame': ind.tstamp // 1000000,
                            'slot': ind.tstamp % 1000000,
                            'wb_cqi': ue.wb_cqi,
                            'dl_mcs1': ue.dl_mcs1,
                            'dl_mcs2': ue.dl_mcs2,
                            'ul_mcs1': ue.ul_mcs1,
                            'ul_mcs2': ue.ul_mcs2,
                            'dl_bler': ue.dl_bler,
                            'ul_bler': ue.ul_bler,
                            'dl_curr_tbs': ue.dl_curr_tbs,
                            'ul_curr_tbs': ue.ul_curr_tbs,
                            'dl_aggr_tbs': getattr(ue, 'dl_aggr_tbs', 0),
                            'ul_aggr_tbs': getattr(ue, 'ul_aggr_tbs', 0),
                            'dl_aggr_prb': getattr(ue, 'dl_aggr_prb', 0),
                            'ul_aggr_prb': getattr(ue, 'ul_aggr_prb', 0),
                            'pusch_snr': ue.pusch_snr,
                            'pucch_snr': getattr(ue, 'pucch_snr', 0),
                            'bsr': getattr(ue, 'bsr', 0),
                            'dl_num_harq': getattr(ue, 'dl_num_harq', 0),
                            'ul_num_harq': getattr(ue, 'ul_num_harq', 0),
                        }
        
        ####################
        # RLC Callback
        ####################
        class RLCCallback(ric.rlc_cb):
            def __init__(self):
                ric.rlc_cb.__init__(self)
                
            def handle(self, ind):
                if len(ind.rb_stats) > 0:
                    rb = ind.rb_stats[0]
                    with xapp.lock:
                        xapp.latest_rlc = {
                            'mode': getattr(rb, 'mode', 0),
                            'txpdu_pkts': getattr(rb, 'txpdu_pkts', 0),
                            'txpdu_bytes': getattr(rb, 'txpdu_bytes', 0),
                            'txpdu_wt_ms': rb.txpdu_wt_ms,
                            'txpdu_dd_pkts': rb.txpdu_dd_pkts,
                            'txpdu_dd_bytes': getattr(rb, 'txpdu_dd_bytes', 0),
                            'txpdu_retx_pkts': rb.txpdu_retx_pkts,
                            'txpdu_retx_bytes': getattr(rb, 'txpdu_retx_bytes', 0),
                            'txpdu_segmented': rb.txpdu_segmented,
                            'txpdu_status_pkts': getattr(rb, 'txpdu_status_pkts', 0),
                            'txpdu_status_bytes': getattr(rb, 'txpdu_status_bytes', 0),
                            'txbuf_occ_bytes': rb.txbuf_occ_bytes,
                            'txbuf_occ_pkts': getattr(rb, 'txbuf_occ_pkts', 0),
                            'rxpdu_pkts': getattr(rb, 'rxpdu_pkts', 0),
                            'rxpdu_bytes': getattr(rb, 'rxpdu_bytes', 0),
                            'rxpdu_dup_pkts': rb.rxpdu_dup_pkts,
                            'rxpdu_dup_bytes': getattr(rb, 'rxpdu_dup_bytes', 0),
                            'rxpdu_dd_pkts': rb.rxpdu_dd_pkts,
                            'rxpdu_dd_bytes': getattr(rb, 'rxpdu_dd_bytes', 0),
                            'rxpdu_ow_pkts': getattr(rb, 'rxpdu_ow_pkts', 0),
                            'rxpdu_ow_bytes': getattr(rb, 'rxpdu_ow_bytes', 0),
                            'rxpdu_status_pkts': rb.rxpdu_status_pkts,
                            'rxpdu_status_bytes': getattr(rb, 'rxpdu_status_bytes', 0),
                            'rxbuf_occ_bytes': rb.rxbuf_occ_bytes,
                            'rxbuf_occ_pkts': getattr(rb, 'rxbuf_occ_pkts', 0),
                            'txsdu_pkts': rb.txsdu_pkts,
                            'txsdu_bytes': getattr(rb, 'txsdu_bytes', 0),
                            'rxsdu_pkts': rb.rxsdu_pkts,
                            'rxsdu_bytes': getattr(rb, 'rxsdu_bytes', 0),
                        }
        
        ####################
        # PDCP Callback
        ####################
        class PDCPCallback(ric.pdcp_cb):
            def __init__(self):
                ric.pdcp_cb.__init__(self)
                
            def handle(self, ind):
                if len(ind.rb_stats) > 0:
                    rb = ind.rb_stats[0]
                    with xapp.lock:
                        xapp.latest_pdcp = {
                            'txpdu_pkts': rb.txpdu_pkts,
                            'txpdu_bytes': rb.txpdu_bytes,
                            'txpdu_sn': getattr(rb, 'txpdu_sn', 0),
                            'rxpdu_pkts': rb.rxpdu_pkts,
                            'rxpdu_bytes': rb.rxpdu_bytes,
                            'rxpdu_sn': getattr(rb, 'rxpdu_sn', 0),
                            'rxpdu_oo_pkts': rb.rxpdu_oo_pkts,
                            'rxpdu_oo_bytes': rb.rxpdu_oo_bytes,
                            'rxpdu_dd_pkts': rb.rxpdu_dd_pkts,
                            'rxpdu_dd_bytes': rb.rxpdu_dd_bytes,
                            'rxpdu_ro_count': rb.rxpdu_ro_count,
                            'txsdu_pkts': rb.txsdu_pkts,
                            'txsdu_bytes': rb.txsdu_bytes,
                            'rxsdu_pkts': rb.rxsdu_pkts,
                            'rxsdu_bytes': rb.rxsdu_bytes,
                        }
        
        # Subscribe to service models
        print("\n[CELL xApp] Subscribing to MAC, RLC, PDCP...")
        
        for node in conn:
            # MAC - 100ms interval
            mac_cb = MACCallback()
            hndlr = ric.report_mac_sm(node.id, ric.Interval_ms_100, mac_cb)
            self.mac_hndlr.append(hndlr)
            
            # RLC - 100ms interval
            rlc_cb = RLCCallback()
            hndlr = ric.report_rlc_sm(node.id, ric.Interval_ms_100, rlc_cb)
            self.rlc_hndlr.append(hndlr)
            
            # PDCP - 100ms interval
            pdcp_cb = PDCPCallback()
            hndlr = ric.report_pdcp_sm(node.id, ric.Interval_ms_100, pdcp_cb)
            self.pdcp_hndlr.append(hndlr)
        
        print(f"[CELL xApp] Collecting {self.target_samples} samples (1/sec)...\n")
        
        # Collection loop
        try:
            while self.running and self.sample_counter < self.target_samples:
                self._create_sample()
                time.sleep(REPORT_INTERVAL_SEC)
                
        except KeyboardInterrupt:
            print("\n[CELL xApp] Interrupted")
        
        finally:
            # Cleanup
            print("\n[CELL xApp] Cleaning up subscriptions...")
            
            for h in self.mac_hndlr:
                ric.rm_report_mac_sm(h)
            for h in self.rlc_hndlr:
                ric.rm_report_rlc_sm(h)
            for h in self.pdcp_hndlr:
                ric.rm_report_pdcp_sm(h)
            
            # Summary
            print(f"\n{'='*65}")
            print("                    COLLECTION COMPLETE")
            print(f"{'='*65}")
            print(f"  Total samples: {self.sample_counter}")
            print(f"  Output file:   {self.output_file}")
            print(f"{'='*65}")
            
            # Wait for RIC cleanup
            while ric.try_stop == 0:
                time.sleep(0.5)
            
            print("[CELL xApp] Done.")


####################
# Main
####################
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='CELL KPM xApp')
    parser.add_argument('-n', '--samples', type=int, default=1000,
                       help='Number of samples (default: 1000)')
    parser.add_argument('-o', '--output', type=str, default='cell_monitoring_dataset.csv',
                       help='Output CSV file')
    
    args = parser.parse_args()
    
    xapp = CellKPMxApp(target_samples=args.samples, output_file=args.output)
    xapp.run()
