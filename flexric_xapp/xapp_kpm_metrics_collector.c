/*
 * KPM Metrics Collector xApp for FlexRIC
 * ======================================
 * 
 * Collects comprehensive metrics from MAC, RLC, PDCP, GTP service models
 * and outputs them to a CSV file for dataset creation.
 * 
 * Metrics: CQI, SNR (proxy for RSRP), BLER, MCS, TBS, PRB, Buffer stats
 * 
 * Author: KPM Metrics Collector
 * License: OAI Public License, Version 1.1
 */

#include "../../../../src/xApp/e42_xapp_api.h"
#include "../../../../src/util/alg_ds/alg/defer.h"
#include "../../../../src/util/time_now_us.h"

#include <pthread.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <unistd.h>
#include <sys/time.h>

// Configuration
#define CSV_FILE "/tmp/kpm_metrics_dataset.csv"
#define PRINT_INTERVAL 100

// Global state
static FILE* csv_file = NULL;
static pthread_mutex_t csv_mutex = PTHREAD_MUTEX_INITIALIZER;
static volatile int running = 1;
static uint64_t sample_count = 0;
static uint64_t target_samples = 1000;

// Latest metrics from each SM
static struct {
    int64_t timestamp;
    // MAC
    uint32_t rnti;
    uint8_t cqi;
    float pusch_snr;
    float pucch_snr;
    float dl_bler;
    float ul_bler;
    uint8_t dl_mcs1, dl_mcs2, ul_mcs1, ul_mcs2;
    uint64_t dl_tbs, ul_tbs;
    uint64_t dl_aggr_tbs, ul_aggr_tbs;
    uint32_t dl_prb, ul_prb;
    uint32_t dl_sched_rb, ul_sched_rb;
    uint32_t bsr;
    int8_t phr;
    uint16_t frame, slot;
    int mac_valid;
    // RLC
    uint32_t rlc_tx_pkts, rlc_tx_bytes;
    uint32_t rlc_rx_pkts, rlc_rx_bytes;
    uint32_t rlc_txbuf, rlc_rxbuf;
    uint32_t rlc_retx;
    int rlc_valid;
    // PDCP
    uint32_t pdcp_tx_pkts, pdcp_tx_bytes;
    uint32_t pdcp_rx_pkts, pdcp_rx_bytes;
    int pdcp_valid;
} metrics = {0};

static void signal_handler(int sig) {
    (void)sig;
    running = 0;
}

static void write_csv_header(void) {
    fprintf(csv_file,
        "timestamp,rnti,cqi,pusch_snr,pucch_snr,"
        "dl_bler,ul_bler,dl_mcs1,dl_mcs2,ul_mcs1,ul_mcs2,"
        "dl_tbs,ul_tbs,dl_aggr_tbs,ul_aggr_tbs,"
        "dl_prb,ul_prb,dl_sched_rb,ul_sched_rb,"
        "bsr,phr,frame,slot,"
        "rlc_tx_pkts,rlc_tx_bytes,rlc_rx_pkts,rlc_rx_bytes,"
        "rlc_txbuf,rlc_rxbuf,rlc_retx,"
        "pdcp_tx_pkts,pdcp_tx_bytes,pdcp_rx_pkts,pdcp_rx_bytes\n"
    );
    fflush(csv_file);
}

static void write_csv_row(void) {
    if (!csv_file || !metrics.mac_valid) return;
    
    pthread_mutex_lock(&csv_mutex);
    
    fprintf(csv_file,
        "%ld,%u,%u,%.2f,%.2f,"
        "%.4f,%.4f,%u,%u,%u,%u,"
        "%lu,%lu,%lu,%lu,"
        "%u,%u,%u,%u,"
        "%u,%d,%u,%u,"
        "%u,%u,%u,%u,"
        "%u,%u,%u,"
        "%u,%u,%u,%u\n",
        metrics.timestamp,
        metrics.rnti, metrics.cqi, metrics.pusch_snr, metrics.pucch_snr,
        metrics.dl_bler, metrics.ul_bler,
        metrics.dl_mcs1, metrics.dl_mcs2, metrics.ul_mcs1, metrics.ul_mcs2,
        metrics.dl_tbs, metrics.ul_tbs, metrics.dl_aggr_tbs, metrics.ul_aggr_tbs,
        metrics.dl_prb, metrics.ul_prb, metrics.dl_sched_rb, metrics.ul_sched_rb,
        metrics.bsr, metrics.phr, metrics.frame, metrics.slot,
        metrics.rlc_tx_pkts, metrics.rlc_tx_bytes,
        metrics.rlc_rx_pkts, metrics.rlc_rx_bytes,
        metrics.rlc_txbuf, metrics.rlc_rxbuf, metrics.rlc_retx,
        metrics.pdcp_tx_pkts, metrics.pdcp_tx_bytes,
        metrics.pdcp_rx_pkts, metrics.pdcp_rx_bytes
    );
    
    sample_count++;
    metrics.mac_valid = 0;
    
    if (sample_count % PRINT_INTERVAL == 0) {
        printf("[%lu] CQI=%u SNR=%.1fdB BLER=%.3f DL_TBS=%lu PRB=%u/%u\n",
               sample_count, metrics.cqi, metrics.pusch_snr,
               metrics.dl_bler, metrics.dl_tbs, metrics.dl_prb, metrics.ul_prb);
        fflush(csv_file);
    }
    
    if (sample_count >= target_samples) {
        printf("\nReached target of %lu samples\n", target_samples);
        running = 0;
    }
    
    pthread_mutex_unlock(&csv_mutex);
}

// MAC callback
static void sm_cb_mac(sm_ag_if_rd_t const* rd) {
    assert(rd != NULL);
    assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
    assert(rd->ind.type == MAC_STATS_V0);
    
    mac_ind_msg_t const* msg = &rd->ind.mac.msg;
    if (msg->len_ue_stats == 0) return;
    
    mac_ue_stats_impl_t const* ue = &msg->ue_stats[0];
    
    pthread_mutex_lock(&csv_mutex);
    
    metrics.timestamp = time_now_us();
    metrics.rnti = ue->rnti;
    metrics.cqi = ue->wb_cqi;
    metrics.pusch_snr = ue->pusch_snr;
    metrics.pucch_snr = ue->pucch_snr;
    metrics.dl_bler = ue->dl_bler;
    metrics.ul_bler = ue->ul_bler;
    metrics.dl_mcs1 = ue->dl_mcs1;
    metrics.dl_mcs2 = ue->dl_mcs2;
    metrics.ul_mcs1 = ue->ul_mcs1;
    metrics.ul_mcs2 = ue->ul_mcs2;
    metrics.dl_tbs = ue->dl_curr_tbs;
    metrics.ul_tbs = ue->ul_curr_tbs;
    metrics.dl_aggr_tbs = ue->dl_aggr_tbs;
    metrics.ul_aggr_tbs = ue->ul_aggr_tbs;
    metrics.dl_prb = ue->dl_aggr_prb;
    metrics.ul_prb = ue->ul_aggr_prb;
    metrics.dl_sched_rb = ue->dl_sched_rb;
    metrics.ul_sched_rb = ue->ul_sched_rb;
    metrics.bsr = ue->bsr;
    metrics.phr = ue->phr;
    metrics.frame = ue->frame;
    metrics.slot = ue->slot;
    metrics.mac_valid = 1;
    
    pthread_mutex_unlock(&csv_mutex);
    
    write_csv_row();
}

// RLC callback
static void sm_cb_rlc(sm_ag_if_rd_t const* rd) {
    assert(rd != NULL);
    assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
    assert(rd->ind.type == RLC_STATS_V0);
    
    rlc_ind_msg_t const* msg = &rd->ind.rlc.msg;
    if (msg->len == 0) return;
    
    rlc_radio_bearer_stats_t const* rb = &msg->rb[0];
    
    pthread_mutex_lock(&csv_mutex);
    metrics.rlc_tx_pkts = rb->txpdu_pkts;
    metrics.rlc_tx_bytes = rb->txpdu_bytes;
    metrics.rlc_rx_pkts = rb->rxpdu_pkts;
    metrics.rlc_rx_bytes = rb->rxpdu_bytes;
    metrics.rlc_txbuf = rb->txbuf_occ_bytes;
    metrics.rlc_rxbuf = rb->rxbuf_occ_bytes;
    metrics.rlc_retx = rb->txpdu_retx_pkts;
    metrics.rlc_valid = 1;
    pthread_mutex_unlock(&csv_mutex);
}

// PDCP callback
static void sm_cb_pdcp(sm_ag_if_rd_t const* rd) {
    assert(rd != NULL);
    assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
    assert(rd->ind.type == PDCP_STATS_V0);
    
    pdcp_ind_msg_t const* msg = &rd->ind.pdcp.msg;
    if (msg->len == 0) return;
    
    pdcp_radio_bearer_stats_t const* rb = &msg->rb[0];
    
    pthread_mutex_lock(&csv_mutex);
    metrics.pdcp_tx_pkts = rb->txpdu_pkts;
    metrics.pdcp_tx_bytes = rb->txpdu_bytes;
    metrics.pdcp_rx_pkts = rb->rxpdu_pkts;
    metrics.pdcp_rx_bytes = rb->rxpdu_bytes;
    metrics.pdcp_valid = 1;
    pthread_mutex_unlock(&csv_mutex);
}

// GTP callback (just for latency tracking)
static void sm_cb_gtp(sm_ag_if_rd_t const* rd) {
    assert(rd != NULL);
    assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
    assert(rd->ind.type == GTP_STATS_V0);
    // GTP stats logged but not saved to CSV
}

int main(int argc, char *argv[]) {
    // Hard-coded settings (FlexRIC arg parser is limited)
    const char* output = "/tmp/kpm_dataset.csv";
    target_samples = 1000;
    
    printf("\n========================================\n");
    printf("  KPM Metrics Collector xApp\n");
    printf("========================================\n");
    printf("Target: %lu samples\n", target_samples);
    printf("Output: %s\n\n", output);
    
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    csv_file = fopen(output, "w");
    if (!csv_file) {
        perror("Failed to open output file");
        return 1;
    }
    write_csv_header();
    
    fr_args_t args = init_fr_args(argc, argv);
    init_xapp_api(&args);
    sleep(1);
    
    e2_node_arr_xapp_t nodes = e2_nodes_xapp_api();
    defer({ free_e2_node_arr_xapp(&nodes); });
    
    if (nodes.len == 0) {
        printf("ERROR: No E2 nodes connected!\n");
        fclose(csv_file);
        return 1;
    }
    
    printf("Connected E2 nodes: %d\n", nodes.len);
    
    const char* interval = "10_ms";
    sm_ans_xapp_t* mac_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));
    sm_ans_xapp_t* rlc_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));
    sm_ans_xapp_t* pdcp_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));
    sm_ans_xapp_t* gtp_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));
    
    for (int i = 0; i < nodes.len; i++) {
        e2_node_connected_xapp_t* n = &nodes.n[i];
        
        for (size_t j = 0; j < n->len_rf; j++)
            printf("  RAN Func ID: %d\n", n->rf[j].id);
        
        if (n->id.type == ngran_gNB || n->id.type == ngran_eNB) {
            mac_h[i] = report_sm_xapp_api(&n->id, 142, (void*)interval, sm_cb_mac);
            printf("Subscribed to MAC: %s\n", mac_h[i].success ? "OK" : "FAIL");
            
            rlc_h[i] = report_sm_xapp_api(&n->id, 143, (void*)interval, sm_cb_rlc);
            printf("Subscribed to RLC: %s\n", rlc_h[i].success ? "OK" : "FAIL");
            
            pdcp_h[i] = report_sm_xapp_api(&n->id, 144, (void*)interval, sm_cb_pdcp);
            printf("Subscribed to PDCP: %s\n", pdcp_h[i].success ? "OK" : "FAIL");
            
            gtp_h[i] = report_sm_xapp_api(&n->id, 148, (void*)interval, sm_cb_gtp);
            printf("Subscribed to GTP: %s\n", gtp_h[i].success ? "OK" : "FAIL");
        }
    }
    
    printf("\nCollecting metrics...\n\n");
    
    while (running && sample_count < target_samples)
        sleep(1);
    
    printf("\nStopping...\n");
    
    for (int i = 0; i < nodes.len; i++) {
        if (mac_h[i].u.handle) rm_report_sm_xapp_api(mac_h[i].u.handle);
        if (rlc_h[i].u.handle) rm_report_sm_xapp_api(rlc_h[i].u.handle);
        if (pdcp_h[i].u.handle) rm_report_sm_xapp_api(pdcp_h[i].u.handle);
        if (gtp_h[i].u.handle) rm_report_sm_xapp_api(gtp_h[i].u.handle);
    }
    
    free(mac_h); free(rlc_h); free(pdcp_h); free(gtp_h);
    
    if (csv_file) {
        fflush(csv_file);
        fclose(csv_file);
    }
    
    printf("\n========================================\n");
    printf("  Collection Complete\n");
    printf("  Samples: %lu\n", sample_count);
    printf("  Output: %s\n", output);
    printf("========================================\n\n");
    
    while (try_stop_xapp_api() == false)
        usleep(1000);
    
    return 0;
}
