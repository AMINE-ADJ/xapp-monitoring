/*
 * KPM Metrics Collector xApp for FlexRIC (v2.0)
 * ==============================================
 *
 * Collects comprehensive metrics from MAC, RLC, PDCP, GTP + KPM service models
 * and outputs them to a CSV file for dataset creation.
 *
 * Metrics: CQI, SNR (proxy for RSRP), BLER, MCS, TBS, PRB, Throughput, Buffer
 * stats
 *
 * Author: KPM Metrics Collector
 * License: OAI Public License, Version 1.1
 */

#include "../../../../src/util/alg_ds/alg/defer.h"
#include "../../../../src/util/alg_ds/ds/lock_guard/lock_guard.h"
#include "../../../../src/util/time_now_us.h"
#include "../../../../src/xApp/e42_xapp_api.h"

#include "../../../../src/sm/gtp_sm/gtp_sm_id.h"
#include "../../../../src/sm/kpm_sm/kpm_sm_v03.00/ie/kpm_data_ie.h"
#include "../../../../src/sm/kpm_sm/kpm_sm_v03.00/kpm_sm_id.h"
#include "../../../../src/sm/mac_sm/mac_sm_id.h"
#include "../../../../src/sm/pdcp_sm/pdcp_sm_id.h"
#include "../../../../src/sm/rlc_sm/rlc_sm_id.h"
#include "../../../../src/util/ngran_types.h"

#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

// Configuration
#define CSV_FILE "/tmp/kpm_metrics_dataset.csv"
#define PRINT_INTERVAL 100

// Global state
static FILE *csv_file = NULL;
static pthread_mutex_t csv_mutex = PTHREAD_MUTEX_INITIALIZER;
static volatile int running = 1;
static uint64_t sample_count = 0;
static uint64_t target_samples = 1000;

// Latest metrics from each SM
static struct {
  int64_t timestamp;
  // MAC metrics
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
  // RLC metrics
  uint32_t rlc_tx_pkts, rlc_tx_bytes;
  uint32_t rlc_rx_pkts, rlc_rx_bytes;
  uint32_t rlc_txbuf, rlc_rxbuf;
  uint32_t rlc_retx;
  int rlc_valid;
  // PDCP metrics
  uint32_t pdcp_tx_pkts, pdcp_tx_bytes;
  uint32_t pdcp_rx_pkts, pdcp_rx_bytes;
  int pdcp_valid;
  // KPM throughput metrics
  double dl_thp_kbps;
  double ul_thp_kbps;
  double rlc_sdu_delay_us;
  int32_t pdcp_sdu_vol_dl_kb;
  int32_t pdcp_sdu_vol_ul_kb;
  int32_t prb_tot_dl;
  int32_t prb_tot_ul;
  int kpm_valid;
} metrics = {0};

static void signal_handler(int sig) {
  (void)sig;
  running = 0;
}

static void write_csv_header(void) {
  fprintf(csv_file, "timestamp,rnti,cqi,pusch_snr,pucch_snr,"
                    "dl_bler,ul_bler,dl_mcs1,dl_mcs2,ul_mcs1,ul_mcs2,"
                    "dl_tbs,ul_tbs,dl_aggr_tbs,ul_aggr_tbs,"
                    "dl_prb,ul_prb,dl_sched_rb,ul_sched_rb,"
                    "bsr,phr,frame,slot,"
                    "rlc_tx_pkts,rlc_tx_bytes,rlc_rx_pkts,rlc_rx_bytes,"
                    "rlc_txbuf,rlc_rxbuf,rlc_retx,"
                    "pdcp_tx_pkts,pdcp_tx_bytes,pdcp_rx_pkts,pdcp_rx_bytes,"
                    "dl_thp_kbps,ul_thp_kbps,rlc_sdu_delay_us,"
                    "pdcp_vol_dl_kb,pdcp_vol_ul_kb,prb_tot_dl,prb_tot_ul\n");
  fflush(csv_file);
}

static void write_csv_row(void) {
  if (!csv_file || !metrics.mac_valid)
    return;

  pthread_mutex_lock(&csv_mutex);

  fprintf(csv_file,
          "%ld,%u,%u,%.2f,%.2f,"
          "%.4f,%.4f,%u,%u,%u,%u,"
          "%lu,%lu,%lu,%lu,"
          "%u,%u,%u,%u,"
          "%u,%d,%u,%u,"
          "%u,%u,%u,%u,"
          "%u,%u,%u,"
          "%u,%u,%u,%u,"
          "%.2f,%.2f,%.2f,"
          "%d,%d,%d,%d\n",
          metrics.timestamp, metrics.rnti, metrics.cqi, metrics.pusch_snr,
          metrics.pucch_snr, metrics.dl_bler, metrics.ul_bler, metrics.dl_mcs1,
          metrics.dl_mcs2, metrics.ul_mcs1, metrics.ul_mcs2, metrics.dl_tbs,
          metrics.ul_tbs, metrics.dl_aggr_tbs, metrics.ul_aggr_tbs,
          metrics.dl_prb, metrics.ul_prb, metrics.dl_sched_rb,
          metrics.ul_sched_rb, metrics.bsr, metrics.phr, metrics.frame,
          metrics.slot, metrics.rlc_tx_pkts, metrics.rlc_tx_bytes,
          metrics.rlc_rx_pkts, metrics.rlc_rx_bytes, metrics.rlc_txbuf,
          metrics.rlc_rxbuf, metrics.rlc_retx, metrics.pdcp_tx_pkts,
          metrics.pdcp_tx_bytes, metrics.pdcp_rx_pkts, metrics.pdcp_rx_bytes,
          metrics.dl_thp_kbps, metrics.ul_thp_kbps, metrics.rlc_sdu_delay_us,
          metrics.pdcp_sdu_vol_dl_kb, metrics.pdcp_sdu_vol_ul_kb,
          metrics.prb_tot_dl, metrics.prb_tot_ul);

  sample_count++;
  metrics.mac_valid = 0;

  if (sample_count % PRINT_INTERVAL == 0) {
    printf("[%lu] SNR=%.1fdB BLER=%.3f MCS=%u DL_Thp=%.1fkbps UL_Thp=%.1fkbps "
           "PRB=%u/%u\n",
           sample_count, metrics.pusch_snr, metrics.dl_bler, metrics.dl_mcs1,
           metrics.dl_thp_kbps, metrics.ul_thp_kbps, metrics.dl_prb,
           metrics.ul_prb);
    fflush(csv_file);
  }

  if (sample_count >= target_samples) {
    printf("\nReached target of %lu samples\n", target_samples);
    running = 0;
  }

  pthread_mutex_unlock(&csv_mutex);
}

// MAC callback
static void sm_cb_mac(sm_ag_if_rd_t const *rd) {
  assert(rd != NULL);
  assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
  assert(rd->ind.type == MAC_STATS_V0);

  mac_ind_msg_t const *msg = &rd->ind.mac.msg;
  if (msg->len_ue_stats == 0)
    return;

  mac_ue_stats_impl_t const *ue = &msg->ue_stats[0];

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
static void sm_cb_rlc(sm_ag_if_rd_t const *rd) {
  assert(rd != NULL);
  assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
  assert(rd->ind.type == RLC_STATS_V0);

  rlc_ind_msg_t const *msg = &rd->ind.rlc.msg;
  if (msg->len == 0)
    return;

  rlc_radio_bearer_stats_t const *rb = &msg->rb[0];

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
static void sm_cb_pdcp(sm_ag_if_rd_t const *rd) {
  assert(rd != NULL);
  assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
  assert(rd->ind.type == PDCP_STATS_V0);

  pdcp_ind_msg_t const *msg = &rd->ind.pdcp.msg;
  if (msg->len == 0)
    return;

  pdcp_radio_bearer_stats_t const *rb = &msg->rb[0];

  pthread_mutex_lock(&csv_mutex);
  metrics.pdcp_tx_pkts = rb->txpdu_pkts;
  metrics.pdcp_tx_bytes = rb->txpdu_bytes;
  metrics.pdcp_rx_pkts = rb->rxpdu_pkts;
  metrics.pdcp_rx_bytes = rb->rxpdu_bytes;
  metrics.pdcp_valid = 1;
  pthread_mutex_unlock(&csv_mutex);
}

// GTP callback
static void sm_cb_gtp(sm_ag_if_rd_t const *rd) {
  assert(rd != NULL);
  assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
  assert(rd->ind.type == GTP_STATS_V0);
  // GTP stats monitored but not saved
}

// KPM callback - for throughput metrics
static void sm_cb_kpm(sm_ag_if_rd_t const *rd) {
  assert(rd != NULL);
  assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
  assert(rd->ind.type == KPM_STATS_V3_0);

  kpm_ind_data_t const *ind = &rd->ind.kpm.ind;
  kpm_ind_msg_format_3_t const *msg_frm_3 = &ind->msg.frm_3;

  if (msg_frm_3->ue_meas_report_lst_len == 0)
    return;

  pthread_mutex_lock(&csv_mutex);

  for (size_t i = 0; i < msg_frm_3->ue_meas_report_lst_len; i++) {
    kpm_ind_msg_format_1_t const *msg_frm_1 =
        &msg_frm_3->meas_report_per_ue[i].ind_msg_format_1;

    for (size_t j = 0; j < msg_frm_1->meas_data_lst_len; j++) {
      for (size_t z = 0; z < msg_frm_1->meas_data_lst[j].meas_record_len; z++) {
        if (msg_frm_1->meas_info_lst_len == 0)
          continue;
        if (msg_frm_1->meas_info_lst[z].meas_type.type != NAME_MEAS_TYPE)
          continue;

        // Get measurement name
        char name[64] = {0};
        size_t len = msg_frm_1->meas_info_lst[z].meas_type.name.len;
        if (len >= sizeof(name))
          len = sizeof(name) - 1;
        memcpy(name, msg_frm_1->meas_info_lst[z].meas_type.name.buf, len);

        // Extract values
        meas_record_lst_t const *rec =
            &msg_frm_1->meas_data_lst[j].meas_record_lst[z];

        if (rec->value == REAL_MEAS_VALUE) {
          if (strcmp(name, "DRB.UEThpDl") == 0) {
            metrics.dl_thp_kbps = rec->real_val;
          } else if (strcmp(name, "DRB.UEThpUl") == 0) {
            metrics.ul_thp_kbps = rec->real_val;
          } else if (strcmp(name, "DRB.RlcSduDelayDl") == 0) {
            metrics.rlc_sdu_delay_us = rec->real_val;
          }
        } else if (rec->value == INTEGER_MEAS_VALUE) {
          if (strcmp(name, "DRB.PdcpSduVolumeDL") == 0) {
            metrics.pdcp_sdu_vol_dl_kb = rec->int_val;
          } else if (strcmp(name, "DRB.PdcpSduVolumeUL") == 0) {
            metrics.pdcp_sdu_vol_ul_kb = rec->int_val;
          } else if (strcmp(name, "RRU.PrbTotDl") == 0) {
            metrics.prb_tot_dl = rec->int_val;
          } else if (strcmp(name, "RRU.PrbTotUl") == 0) {
            metrics.prb_tot_ul = rec->int_val;
          }
        }
      }
    }
  }
  metrics.kpm_valid = 1;
  pthread_mutex_unlock(&csv_mutex);
}

// Generate measurement info with label
static meas_info_format_1_lst_t gen_meas_info(const char *name) {
  meas_info_format_1_lst_t dst = {0};
  dst.meas_type.type = NAME_MEAS_TYPE;
  dst.meas_type.name = cp_str_to_ba(name);

  // Required: Label info
  dst.label_info_lst_len = 1;
  dst.label_info_lst = calloc(1, sizeof(label_info_lst_t));
  dst.label_info_lst[0].noLabel = calloc(1, sizeof(enum_value_e));
  *dst.label_info_lst[0].noLabel = TRUE_ENUM_VALUE;

  return dst;
}

// Generate filter predicate for S-NSSAI
static test_info_lst_t gen_filter_predicate(void) {
  test_info_lst_t dst = {0};
  dst.test_cond_type = S_NSSAI_TEST_COND_TYPE;
  dst.S_NSSAI = TRUE_TEST_COND_TYPE;
  dst.test_cond = calloc(1, sizeof(test_cond_e));
  *dst.test_cond = EQUAL_TEST_COND;
  dst.test_cond_value = calloc(1, sizeof(test_cond_value_t));
  dst.test_cond_value->type = INTEGER_TEST_COND_VALUE;
  dst.test_cond_value->int_value = calloc(1, sizeof(int64_t));
  *dst.test_cond_value->int_value = 1; // SST = 1
  return dst;
}

// Generate KPM subscription action definition
static kpm_act_def_t gen_kpm_act_def(void) {
  kpm_act_def_t act_def = {0};

  // Format 4 for UE-level measurements
  act_def.type = FORMAT_4_ACTION_DEFINITION;

  // Matching condition for S-NSSAI
  act_def.frm_4.matching_cond_lst_len = 1;
  act_def.frm_4.matching_cond_lst =
      calloc(1, sizeof(matching_condition_format_4_lst_t));
  act_def.frm_4.matching_cond_lst[0].test_info_lst = gen_filter_predicate();

  // Request measurements
  const char *meas_names[] = {"DRB.UEThpDl",         "DRB.UEThpUl",
                              "DRB.RlcSduDelayDl",   "DRB.PdcpSduVolumeDL",
                              "DRB.PdcpSduVolumeUL", "RRU.PrbTotDl",
                              "RRU.PrbTotUl"};
  size_t num_meas = sizeof(meas_names) / sizeof(meas_names[0]);

  act_def.frm_4.action_def_format_1.gran_period_ms = 100;
  act_def.frm_4.action_def_format_1.meas_info_lst_len = num_meas;
  act_def.frm_4.action_def_format_1.meas_info_lst =
      calloc(num_meas, sizeof(meas_info_format_1_lst_t));

  for (size_t i = 0; i < num_meas; i++) {
    act_def.frm_4.action_def_format_1.meas_info_lst[i] =
        gen_meas_info(meas_names[i]);
  }

  return act_def;
}

int main(int argc, char *argv[]) {
  // Hard-coded settings
  const char *output = "/tmp/kpm_metrics_dataset.csv";
  target_samples = 1000;

  printf("\n========================================\n");
  printf("  KPM Metrics Collector xApp v2.0\n");
  printf("  (MAC + RLC + PDCP + KPM Throughput)\n");
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

  const char *interval = "10_ms";
  sm_ans_xapp_t *mac_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));
  sm_ans_xapp_t *rlc_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));
  sm_ans_xapp_t *pdcp_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));
  sm_ans_xapp_t *gtp_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));
  sm_ans_xapp_t *kpm_h = calloc(nodes.len, sizeof(sm_ans_xapp_t));

  for (int i = 0; i < (int)nodes.len; i++) {
    e2_node_connected_xapp_t *n = &nodes.n[i];

    printf("Node %d RAN Functions: ", i);
    for (size_t j = 0; j < n->len_rf; j++)
      printf("%d ", n->rf[j].id);
    printf("\n");

    if (n->id.type == ngran_gNB || n->id.type == ngran_eNB) {
      // Subscribe to MAC
      mac_h[i] = report_sm_xapp_api(&n->id, 142, (void *)interval, sm_cb_mac);
      printf("  MAC (142): %s\n", mac_h[i].success ? "OK" : "FAIL");

      // Subscribe to RLC
      rlc_h[i] = report_sm_xapp_api(&n->id, 143, (void *)interval, sm_cb_rlc);
      printf("  RLC (143): %s\n", rlc_h[i].success ? "OK" : "FAIL");

      // Subscribe to PDCP
      pdcp_h[i] = report_sm_xapp_api(&n->id, 144, (void *)interval, sm_cb_pdcp);
      printf("  PDCP (144): %s\n", pdcp_h[i].success ? "OK" : "FAIL");

      // Subscribe to GTP
      gtp_h[i] = report_sm_xapp_api(&n->id, 148, (void *)interval, sm_cb_gtp);
      printf("  GTP (148): %s\n", gtp_h[i].success ? "OK" : "FAIL");

      // Subscribe to KPM for throughput
      kpm_sub_data_t kpm_sub = {0};
      kpm_sub.ev_trg_def.type = FORMAT_1_RIC_EVENT_TRIGGER;
      kpm_sub.ev_trg_def.kpm_ric_event_trigger_format_1.report_period_ms = 100;
      kpm_sub.sz_ad = 1;
      kpm_sub.ad = calloc(1, sizeof(kpm_act_def_t));
      kpm_sub.ad[0] = gen_kpm_act_def();

      kpm_h[i] = report_sm_xapp_api(&n->id, 2, &kpm_sub, sm_cb_kpm);
      printf("  KPM (2): %s\n", kpm_h[i].success ? "OK" : "FAIL");

      free_kpm_sub_data(&kpm_sub);
    }
  }

  printf("\nCollecting metrics...\n\n");

  while (running && sample_count < target_samples)
    sleep(1);

  printf("\nStopping...\n");

  for (int i = 0; i < (int)nodes.len; i++) {
    if (mac_h[i].success)
      rm_report_sm_xapp_api(mac_h[i].u.handle);
    if (rlc_h[i].success)
      rm_report_sm_xapp_api(rlc_h[i].u.handle);
    if (pdcp_h[i].success)
      rm_report_sm_xapp_api(pdcp_h[i].u.handle);
    if (gtp_h[i].success)
      rm_report_sm_xapp_api(gtp_h[i].u.handle);
    if (kpm_h[i].success)
      rm_report_sm_xapp_api(kpm_h[i].u.handle);
  }

  free(mac_h);
  free(rlc_h);
  free(pdcp_h);
  free(gtp_h);
  free(kpm_h);

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
