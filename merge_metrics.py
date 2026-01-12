import pandas as pd
import re
import sys
import os

def parse_gnb_logs(log_file):
    """
    Parses gNB logs to extract RSRP mapped by Frame/Slot.
    Returns a dict: {(frame, slot, rnti): {'rsrp': value, 'ph': value}}
    """
    metrics = {}
    current_frame = None
    current_slot = None
    
    # Regex patterns
    # [NR_MAC] I Frame.Slot 512.0
    frame_pat = re.compile(r"Frame\.Slot\s+(\d+)\.(\d+)")
    
    # UE RNTI 1d6d ... PH 0 dB PCMAX 0 dBm ...
    ue_stats_pat = re.compile(r"UE RNTI ([0-9a-fA-F]+).*?(in-sync|out-of-sync).*?PH.*?(-?\d+)\s*dB.*?PCMAX.*?(-?\d+)\s*dBm.*?average RSRP (-?\d+)")

    # UE 1d6d: dlsch_rounds 355767/1/0/0, dlsch_errors 0, ...
    dlsch_pat = re.compile(r"UE ([0-9a-fA-F]+): dlsch_rounds (\d+)/(\d+)/(\d+)/(\d+), dlsch_errors (\d+)")
    
    # UE 1d6d: ulsch_rounds 554388/88/36/3, ulsch_errors 1, ...
    ulsch_pat = re.compile(r"UE ([0-9a-fA-F]+): ulsch_rounds (\d+)/(\d+)/(\d+)/(\d+), ulsch_errors (\d+)")

    current_rnti = None

    try:
        with open(log_file, 'r') as f:
            for line in f:
                # 1. Check Frame/Slot context
                m_frame = frame_pat.search(line)
                if m_frame:
                    current_frame = int(m_frame.group(1))
                    current_slot = int(m_frame.group(2))
                    continue
                
                if current_frame is not None:
                    # 2. Check UE Main Stats (RSRP, PH, Sync)
                    m_stat = ue_stats_pat.search(line)
                    if m_stat:
                        rnti_hex = m_stat.group(1)
                        current_rnti = int(rnti_hex, 16)
                        
                        sync = m_stat.group(2)
                        ph = int(m_stat.group(3))
                        pcmax = int(m_stat.group(4))
                        rsrp = int(m_stat.group(5))
                        
                        key = (current_frame, current_slot, current_rnti)
                        if key not in metrics: metrics[key] = {}
                        metrics[key].update({
                            'rsrp': rsrp, 'ph': ph, 'pcmax': pcmax, 'sync': sync
                        })
                        continue

                    # 3. Check DLSCH (HARQ DL)
                    m_dl = dlsch_pat.search(line)
                    if m_dl:
                        # Ensure we are attributing to correct UE. 
                        # Log format: "UE <rnti>: ..."
                        rnti_hex = m_dl.group(1)
                        rnti = int(rnti_hex, 16)
                        
                        # Rounds: r0, r1, r2, r3. Retx = r1+r2+r3
                        rounds = [int(m_dl.group(i)) for i in range(2, 6)]
                        harq_dl = sum(rounds[1:])
                        dlsch_err = int(m_dl.group(6))
                        
                        key = (current_frame, current_slot, rnti)
                        if key not in metrics: metrics[key] = {}
                        metrics[key].update({
                            'harq_dl': harq_dl, 'dlsch_err': dlsch_err
                        })
                        continue

                    # 4. Check ULSCH (HARQ UL)
                    m_ul = ulsch_pat.search(line)
                    if m_ul:
                        rnti_hex = m_ul.group(1)
                        rnti = int(rnti_hex, 16)
                        
                        rounds = [int(m_ul.group(i)) for i in range(2, 6)]
                        harq_ul = sum(rounds[1:])
                        ulsch_err = int(m_ul.group(6))
                        
                        key = (current_frame, current_slot, rnti)
                        if key not in metrics: metrics[key] = {}
                        metrics[key].update({
                            'harq_ul': harq_ul, 'ulsch_err': ulsch_err
                        })
                        continue

    except Exception as e:
        print(f"[WARN] Failed to read log file {log_file}: {e}")
    
    return metrics

def merge_data(csv_file, log_file, output_file):
    print(f"[INFO] Merging {csv_file} with metrics from {log_file}...")
    
    # 1. Load xApp CSV
    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        print(f"[ERROR] Could not read CSV: {e}")
        return

    # 2. Parse Logs
    log_metrics = parse_gnb_logs(log_file)
    print(f"[INFO] Extracted {len(log_metrics)} log data points.")

    # 3. Merge with Lookback
    # Logs are sparse (e.g. every 128 slots). xApp is frequent (every 10ms).
    # Strategy: For CSV frame F, look for Log frame L in [F, F-1, ..., F-200].
    # We ignore slot matching for now as RSRP changes slowly.
    
    # Flatten log_metrics to just frame -> data
    # (Choosing the last slot seen for a frame if multiple existence)
    log_map = {}
    for (f, s, r), data in log_metrics.items():
        log_map[f] = data
        
    rsrp_list = []
    ph_list = []
    pcmax_list = []
    sync_list = []
    harq_dl_list = []
    harq_ul_list = []
    dlsch_err_list = []
    ulsch_err_list = []
    
    rsrq_list = []
    sinr_dl_list = []
    
    for index, row in df.iterrows():
        # 1. Fill from Logs (Lookback)
        try:
            current_f = int(row['frame'])
            match = None
            for offset in range(200):
                check_f = (current_f - offset) % 1024
                if check_f in log_map:
                    match = log_map[check_f]
                    break
            
            if match:
                rsrp = match.get('rsrp')
                ph = match.get('ph')
                pcmax = match.get('pcmax')
                sync = match.get('sync')
                harq_dl = match.get('harq_dl')
                harq_ul = match.get('harq_ul')
                dlsch_err = match.get('dlsch_err')
                ulsch_err = match.get('ulsch_err')
                
                rsrp_list.append(rsrp)
                ph_list.append(ph)
                pcmax_list.append(pcmax)
                sync_list.append(sync)
                harq_dl_list.append(harq_dl)
                harq_ul_list.append(harq_ul)
                dlsch_err_list.append(dlsch_err)
                ulsch_err_list.append(ulsch_err)
                
                # Estimate RSRQ: RSRP + 100 - 90 (from reference script)
                if rsrp is not None:
                    rsrq_list.append(rsrp + 10.0)
                else:
                    rsrq_list.append(None)
            else:
                rsrp_list.append(None)
                ph_list.append(None)
                pcmax_list.append(None)
                sync_list.append(None)
                harq_dl_list.append(None)
                harq_ul_list.append(None)
                dlsch_err_list.append(None)
                ulsch_err_list.append(None)
                rsrq_list.append(None)
                
        except Exception:
            rsrp_list.append(None)
            ph_list.append(None)
            pcmax_list.append(None)
            sync_list.append(None)
            harq_dl_list.append(None)
            harq_ul_list.append(None)
            dlsch_err_list.append(None)
            ulsch_err_list.append(None)
            rsrq_list.append(None)

        # 2. Estimate DL SINR from DL BLER (xApp data)
        try:
            bler = float(row['dl_bler'])
            if bler < 0.001:
                sinr_dl_list.append(25.0)
            elif bler < 0.01:
                sinr_dl_list.append(20.0)
            elif bler < 0.1:
                sinr_dl_list.append(15.0)
            else:
                sinr_dl_list.append(10.0)
        except Exception:
            sinr_dl_list.append(None)

    df['log_rsrp'] = rsrp_list
    df['log_ph'] = ph_list
    df['log_pcmax'] = pcmax_list
    df['log_sync'] = sync_list
    df['log_harq_dl'] = harq_dl_list
    df['log_harq_ul'] = harq_ul_list
    df['log_dlsch_err'] = dlsch_err_list
    df['log_ulsch_err'] = ulsch_err_list
    
    df['est_rsrq'] = rsrq_list
    df['est_sinr_dl'] = sinr_dl_list

    # 4. Reorder Columns for better readability
    # Logical Grouping: ID -> Radio -> Throughput -> Errors -> MCS -> Buffers -> Raw Counters
    desired_order = [
        # ID & Time
        'timestamp', 'frame', 'slot', 'rnti', 'log_sync',
        
        # Radio Quality
        'log_rsrp', 'est_rsrq', 'est_sinr_dl', 'pusch_snr', 'pucch_snr', 'cqi', 'log_ph', 'log_pcmax',
        
        # Throughput & Load
        'dl_thp_kbps', 'ul_thp_kbps', 'prb_tot_dl', 'prb_tot_ul', 'dl_prb', 'ul_prb',
        
        # Errors & Reliability
        'dl_bler', 'ul_bler', 'log_dlsch_err', 'log_ulsch_err', 'log_harq_dl', 'log_harq_ul', 'rlc_retx',
        
        # MCS & TBS
        'dl_mcs1', 'ul_mcs1', 'dl_tbs', 'ul_tbs',
        
        # Latency & Buffers
        'rlc_sdu_delay_us', 'rlc_txbuf', 'bsr'
    ]
    
    # Get all existing columns
    existing_cols = df.columns.tolist()
    
    # Construct final order: desired columns (that exist) + remaining columns
    final_order = [c for c in desired_order if c in existing_cols]
    remaining = [c for c in existing_cols if c not in final_order]
    final_order.extend(remaining)
    
    df = df[final_order]

    # 5. Save
    df.to_csv(output_file, index=False)
    print(f"[SUCCESS] Merged data saved to {output_file}")
    
    # Preview
    print(df[final_order[:15]].head())

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 merge_metrics.py <kpm_csv> <gnb_log> [output_csv]")
        sys.exit(1)
        
    kpm_csv = sys.argv[1]
    gnb_log = sys.argv[2]
    out_csv = sys.argv[3] if len(sys.argv) > 3 else kpm_csv.replace(".csv", "_final.csv")
    
    merge_data(kpm_csv, gnb_log, out_csv)
