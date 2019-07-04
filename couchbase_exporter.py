#!/usr/bin/env python

from prometheus_client import start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, REGISTRY
from functools import reduce
from operator import getitem
from requests.auth import HTTPBasicAuth
import json, requests, sys, time, os, ast, signal, re, argparse

class CouchbaseCollector(object):
    METRIC_PREFIX = 'couchbase_'
    #metrics = get_metrics()
    gauges = {}

    def __init__(self, target, metrics):
        self.BASE_URL = target.rstrip("/")
        self.metrics = metrics

    """
    Split dots in metric name and search for it in obj dict
    """
    def _dot_get(self, metric, obj):
        try:
            return reduce(getitem, metric.split('.'), obj)
        except Exception as e:
            return False

    """
    Request data via CURL with or without authentication.
    Auth username and password can be defined as environment variables
    :rtype JSON
    """
    def _request_data(self, url):
        try:
            if set(["COUCHBASE_USERNAME","COUCHBASE_PASSWORD"]).issubset(os.environ):
                response = requests.get(url, auth=HTTPBasicAuth(os.environ["COUCHBASE_USERNAME"], os.environ["COUCHBASE_PASSWORD"]))
            else:
                response = requests.get(url)
        except Exception as e:
            print('Failed to establish a new connection. Is {0} correct?'.format(self.BASE_URL))
            sys.exit(1)

        if response.status_code != requests.codes.ok:
            print('Response Status ({0}): {1}'.format(response.status_code, response.text))
            sys.exit(1)

        result = response.json()
        return result

    """
    Add metrics in GaugeMetricFamily format
    """
    def _add_metrics(self, metrics, metric_name, metric_gauges, data):
        metric_id = re.sub('(\.)', '_', metrics['id']).lower()
        metric_id = re.sub('(\+)', '_plus_', metric_id)          
        metric_value = self._dot_get(metrics['id'], data)
        gauges = [metric_id]
        for gauge in metric_gauges:
            gauges.append(gauge)
        if metric_value is not False:
            if isinstance(metric_value, list):
                metric_value = sum(metric_value) / float(len(metric_value))
            if not metric_id in self.gauges:
                self.gauges[metric_id] = GaugeMetricFamily('%s_%s' % (metric_name, metric_id), '%s' % metric_id, value=None, labels=metrics['labels'])
            self.gauges[metric_id].add_metric(gauges, value=metric_value)

    """
    Collect cluster, nodes, bucket and bucket details metrics
    """
    def _collect_metrics(self, key, values,uri_path, couchbase_data):
        if key == 'cluster':
            for metrics in values['metrics']:
                self._add_metrics(metrics, self.METRIC_PREFIX + 'cluster', [], couchbase_data)
        elif key == 'nodes':
            for node in couchbase_data['nodes']:
                for metrics in values['metrics']:
                    self._add_metrics(metrics, self.METRIC_PREFIX + 'node', [node['hostname']], node)
        elif key == 'buckets':
            for bucket in couchbase_data:
                for metrics in values['metrics']:
                    self._add_metrics(metrics, self.METRIC_PREFIX + 'bucket', [bucket['name']], bucket)
               
                # Get detailed stats for each bucket
                bucket_stats = self._request_data(self.BASE_URL + bucket['stats']['uri'])
                for bucket_metrics in values['bucket_stats']:
                    self._add_metrics(bucket_metrics, self.METRIC_PREFIX + 'bucket_stats', [bucket['name']], bucket_stats["op"]["samples"])
                
                # Get detailed replication stats for each bucket                    
                bucket_xdcr_stats = self._request_data(self.BASE_URL + uri_path + '@xdcr-' + bucket['name'] + '/stats' )
                for bucket_xdcr_metrics in values['bucket_xdcr_stats']:
                    match = [xm for xm in bucket_xdcr_stats['op']['samples'] if bucket_xdcr_metrics['id'] in xm]
                    if len(match) > 0:
                        data = {}
                        match = match[0]
                        data[bucket_xdcr_metrics['id']] = bucket_xdcr_stats['op']['samples'][match][0]
                        self._add_metrics(bucket_xdcr_metrics, self.METRIC_PREFIX + 'bucket_xdcr_stats', [bucket['name']], data)

    """
    Clear gauges
    """
    def _clear_gauges(self):
        self.gauges = {}

    """
    Collect each metric defined in external module statsmetrics
    """
    def collect(self):
        self._clear_gauges()
        for api_key,api_values in self.metrics.items():
            # Request data for each url
            couchbase_data = self._request_data(self.BASE_URL + api_values['url'])
            self._collect_metrics(api_key, api_values, api_values['url'], couchbase_data)

        for gauge_name, gauge in self.gauges.items():
            yield gauge

"""
Parse optional arguments
:couchase_host:port
:port
"""
def parse_args():
    parser = argparse.ArgumentParser(
        description='couchbase exporter args couchbase address and port'
    )
    parser.add_argument(
        '-c', '--couchbase',
        metavar='couchbase',
        required=False,
        help='server url from the couchbase api',
        default='http://127.0.0.1:8091'
    )
    parser.add_argument(
        '-p', '--port',
        metavar='port',
        required=False,
        type=int,
        help='Listen to this port',
        default=9420
    )
    return parser.parse_args()

def get_metrics():
    return {
        'cluster': {
            'url': '/pools/default/',
            'metrics': [
                {'name':'storageTotals.ram.total','id':'storageTotals.ram.total','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.ram.used','id':'storageTotals.ram.used','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.ram.usedByData','id':'storageTotals.ram.usedByData','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.ram.quotaTotal','id':'storageTotals.ram.quotaTotal','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.ram.quotaUsed','id':'storageTotals.ram.quotaUsed','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.ram.quotaUsedPerNode','id':'storageTotals.ram.quotaUsedPerNode','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.ram.quotaTotalPerNode','id':'storageTotals.ram.quotaTotalPerNode','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.hdd.total','id':'storageTotals.hdd.total','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.hdd.used','id':'storageTotals.hdd.used','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.hdd.usedByData','id':'storageTotals.hdd.usedByData','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.hdd.quotaTotal','id':'storageTotals.hdd.quotaTotal','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.hdd.free','id':'storageTotals.hdd.free','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.hdd.quotaUsed','id':'storageTotals.hdd.quotaUsed','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.hdd.quotaUsedPerNode','id':'storageTotals.hdd.quotaUsedPerNode','suffix':'bytes','labels':['name']},
                {'name':'storageTotals.hdd.quotaTotalPerNode','id':'storageTotals.hdd.quotaTotalPerNode','suffix':'bytes','labels':['name']},
                {'name':'counters.rebalance_success','id':'counters.rebalance_success','suffix':'count','labels':['name']},
                {'name':'counters.rebalance_start','id':'counters.rebalance_start','suffix':'count','labels':['name']},
                {'name':'counters.rebalance_fail','id':'counters.rebalance_fail','suffix':'count','labels':['name']},
                {'name':'counters.rebalance_node','id':'counters.rebalance_node','suffix':'count','labels':['name']}
            ]
        },
        'nodes': {
            'url': '/pools/nodes/',
            'metrics': [
                {'name':'systemStats.cpu_utilization_rate','id':'systemStats.cpu_utilization_rate','suffix':'percent','labels':['name','hostname']},
                {'name':'systemStats.swap_total','id':'systemStats.swap_total','suffix':'bytes','labels':['name','hostname']},
                {'name':'systemStats.swap_used','id':'systemStats.swap_used','suffix':'bytes','labels':['name','hostname']},
                {'name':'systemStats.mem_total','id':'systemStats.mem_total','suffix':'bytes','labels':['name','hostname']},
                {'name':'systemStats.mem_free','id':'systemStats.mem_free','suffix':'bytes','labels':['name','hostname']},
                {'name':'interestingStats.couch_docs_actual_disk_size','id':'interestingStats.couch_docs_actual_disk_size','suffix':'bytes','labels':['name','hostname']},
                {'name':'interestingStats.couch_docs_data_size','id':'interestingStats.couch_docs_data_size','suffix':'bytes','labels':['name','hostname']},
                {'name':'interestingStats.couch_views_actual_disk_size','id':'interestingStats.couch_views_actual_disk_size','suffix':'bytes','labels':['name','hostname']},
                {'name':'interestingStats.couch_views_data_size','id':'interestingStats.couch_views_data_size','suffix':'bytes','labels':['name','hostname']},
                {'name':'interestingStats.mem_used','id':'interestingStats.mem_used','suffix':'bytes','labels':['name','hostname']},
                {'name':'interestingStats.ops','id':'interestingStats.ops','suffix':'count','labels':['name','hostname']},
                {'name':'interestingStats.curr_items','id':'interestingStats.curr_items','suffix':'count','labels':['name','hostname']},
                {'name':'interestingStats.curr_items_tot','id':'interestingStats.curr_items_tot','suffix':'count','labels':['name','hostname']},
                {'name':'interestingStats.vb_replica_curr_items','id':'interestingStats.vb_replica_curr_items','suffix':'count','labels':['name','hostname']},
                {'name':'interestingStats.couch_spatial_disk_size','id':'interestingStats.couch_spatial_disk_size','suffix':'bytes','labels':['name','hostname']},
                {'name':'interestingStats.couch_spatial_data_size','id':'interestingStats.couch_spatial_data_size','suffix':'bytes','labels':['name','hostname']},
                {'name':'interestingStats.cmd_get','id':'interestingStats.cmd_get','suffix':'count','labels':['name','hostname']},
                {'name':'interestingStats.get_hits','id':'interestingStats.get_hits','suffix':'count','labels':['name','hostname']},
                {'name':'interestingStats.ep_bg_fetched','id':'interestingStats.ep_bg_fetched','suffix':'count','labels':['name','hostname']}
            ]
        },
        'buckets': {
            'url': '/pools/default/buckets/',
            'metrics': [
                {'name':'basicStats.quotaPercentUsed','id':'basicStats.quotaPercentUsed','suffix':'percent','labels':['name','bucket']},
                {'name':'basicStats.opsPerSec','id':'basicStats.opsPerSec','suffix':'count','labels':['name','bucket']},
                {'name':'basicStats.diskFetches','id':'basicStats.diskFetches','suffix':'percent','labels':['name','bucket']},
                {'name':'basicStats.itemCount','id':'basicStats.itemCount','suffix':'percent','labels':['name','bucket']},
                {'name':'basicStats.diskUsed','id':'basicStats.diskUsed','suffix':'bytes','labels':['name','bucket']},
                {'name':'basicStats.dataUsed','id':'basicStats.dataUsed','suffix':'bytes','labels':['name','bucket']},
                {'name':'basicStats.memUsed','id':'basicStats.memUsed','suffix':'bytes','labels':['name','bucket']}
            ],
            'bucket_xdcr_stats': [
                {'name':'percent_completeness','id':'percent_completeness','suffix':'percent','labels':['name','bucket']},
                {'name':'replication_changes_left','id':'replication_changes_left','suffix':'count','labels':['name','bucket']},
            ],
            'bucket_stats': [
                {'name':'avg_bg_wait_time','id':'avg_bg_wait_time','suffix':'seconds','labels':['name','bucket']},
                {'name':'avg_disk_commit_time','id':'avg_disk_commit_time','suffix':'seconds','labels':['name','bucket']},
                {'name':'avg_disk_update_time','id':'avg_disk_update_time','suffix':'seconds','labels':['name','bucket']},
                {'name':'bg_wait_count','id':'bg_wait_count','suffix':'count','labels':['name','bucket']},
                {'name':'bg_wait_total','id':'bg_wait_total','suffix':'count','labels':['name','bucket']},
                {'name':'bytes_read','id':'bytes_read','suffix':'bytes','labels':['name','bucket']},
                {'name':'bytes_written','id':'bytes_written','suffix':'bytes','labels':['name','bucket']},
                {'name':'cas_badval','id':'cas_badval','suffix':'count','labels':['name','bucket']},
                {'name':'cas_hits','id':'cas_hits','suffix':'count','labels':['name','bucket']},
                {'name':'cas_misses','id':'cas_misses','suffix':'count','labels':['name','bucket']},
                {'name':'cmd_get','id':'cmd_get','suffix':'count','labels':['name','bucket']},
                {'name':'cmd_set','id':'cmd_set','suffix':'count','labels':['name','bucket']},
                {'name':'couch_docs_data_size','id':'couch_docs_data_size','suffix':'bytes','labels':['name','bucket']},
                {'name':'couch_docs_disk_size','id':'couch_docs_disk_size','suffix':'bytes','labels':['name','bucket']},
                {'name':'cpu_idle_ms','id':'cpu_idle_ms','suffix':'milliseconds','labels':['name','bucket']},
                {'name':'cpu_local_ms','id':'cpu_local_ms','suffix':'milliseconds','labels':['name','bucket']},
                {'name':'cpu_utilization_rate','id':'cpu_utilization_rate','suffix':'percent','labels':['name','bucket']},
                {'name':'curr_connections','id':'curr_connections','suffix':'count','labels':['name','bucket']},
                {'name':'curr_items','id':'curr_items','suffix':'count','labels':['name','bucket']},
                {'name':'curr_items_tot','id':'curr_items_tot','suffix':'count','labels':['name','bucket']},
                {'name':'decr_hits','id':'decr_hits','suffix':'count','labels':['name','bucket']},
                {'name':'decr_misses','id':'decr_misses','suffix':'count','labels':['name','bucket']},
                {'name':'delete_hits','id':'delete_hits','suffix':'count','labels':['name','bucket']},
                {'name':'delete_misses','id':'delete_misses','suffix':'count','labels':['name','bucket']},
                {'name':'disk_commit_count','id':'disk_commit_count','suffix':'count','labels':['name','bucket']},
                {'name':'disk_commit_total','id':'disk_commit_total','suffix':'count','labels':['name','bucket']},
                {'name':'disk_update_count','id':'disk_update_count','suffix':'count','labels':['name','bucket']},
                {'name':'disk_update_total','id':'disk_update_total','suffix':'count','labels':['name','bucket']},
                {'name':'disk_write_queue','id':'disk_write_queue','suffix':'count','labels':['name','bucket']},
                {'name':'ep_bg_fetched','id':'ep_bg_fetched','suffix':'fetches/second','labels':['name','bucket']},
                {'name':'ep_cache_miss_rate','id':'ep_cache_miss_rate','suffix':'percent','labels':['name','bucket']},
                {'name':'ep_dcp_2i_backoff','id':'ep_dcp_2i_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_2i_count','id':'ep_dcp_2i_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_2i_items_remaining','id':'ep_dcp_2i_items_remaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_2i_items_sent','id':'ep_dcp_2i_items_sent','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_2i_producer_count','id':'ep_dcp_2i_producer_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_2i_total_backlog_size','id':'ep_dcp_2i_total_backlog_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_2i_total_bytes','id':'ep_dcp_2i_total_bytes','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_other_backoff','id':'ep_dcp_other_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_other_count','id':'ep_dcp_other_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_other_items_remaining','id':'ep_dcp_other_items_remaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_other_items_sent','id':'ep_dcp_other_items_sent','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_other_producer_count','id':'ep_dcp_other_producer_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_other_total_backlog_size','id':'ep_dcp_other_total_backlog_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_other_total_bytes','id':'ep_dcp_other_total_bytes','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_replica_backoff','id':'ep_dcp_replica_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_replica_count','id':'ep_dcp_replica_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_replica_items_remaining','id':'ep_dcp_replica_items_remaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_replica_items_sent','id':'ep_dcp_replica_items_sent','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_replica_producer_count','id':'ep_dcp_replica_producer_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_replica_total_backlog_size','id':'ep_dcp_replica_total_backlog_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_replica_total_bytes','id':'ep_dcp_replica_total_bytes','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_views_backoff','id':'ep_dcp_views_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_views_count','id':'ep_dcp_views_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_views_items_remaining','id':'ep_dcp_views_items_remaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_views_items_sent','id':'ep_dcp_views_items_sent','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_views_producer_count','id':'ep_dcp_views_producer_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_views_total_backlog_size','id':'ep_dcp_views_total_backlog_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_views_total_bytes','id':'ep_dcp_views_total_bytes','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_xdcr_backoff','id':'ep_dcp_xdcr_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_xdcr_count','id':'ep_dcp_xdcr_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_xdcr_items_remaining','id':'ep_dcp_xdcr_items_remaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_xdcr_items_sent','id':'ep_dcp_xdcr_items_sent','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_xdcr_producer_count','id':'ep_dcp_xdcr_producer_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_xdcr_total_backlog_size','id':'ep_dcp_xdcr_total_backlog_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_dcp_xdcr_total_bytes','id':'ep_dcp_xdcr_total_bytes','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_diskqueue_drain','id':'ep_diskqueue_drain','suffix':'count','labels':['name','bucket']},
                {'name':'ep_diskqueue_fill','id':'ep_diskqueue_fill','suffix':'count','labels':['name','bucket']},
                {'name':'ep_diskqueue_items','id':'ep_diskqueue_items','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_flusher_todo','id':'ep_flusher_todo','suffix':'count','labels':['name','bucket']},
                {'name':'ep_item_commit_failed','id':'ep_item_commit_failed','suffix':'count','labels':['name','bucket']},
                {'name':'ep_kv_size','id':'ep_kv_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_max_size','id':'ep_max_size','suffix':'bytes','labels':['name','bucket']},
                {'name':'ep_mem_high_wat','id':'ep_mem_high_wat','suffix':'bytes','labels':['name','bucket']},
                {'name':'ep_mem_low_wat','id':'ep_mem_low_wat','suffix':'bytes','labels':['name','bucket']},
                {'name':'ep_meta_data_memory','id':'ep_meta_data_memory','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_num_non_resident','id':'ep_num_non_resident','suffix':'count','labels':['name','bucket']},
                {'name':'ep_num_ops_del_meta','id':'ep_num_ops_del_meta','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_num_ops_del_ret_meta','id':'ep_num_ops_del_ret_meta','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_num_ops_get_meta','id':'ep_num_ops_get_meta','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_num_ops_set_meta','id':'ep_num_ops_set_meta','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_num_ops_set_ret_meta','id':'ep_num_ops_set_ret_meta','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_num_value_ejects','id':'ep_num_value_ejects','suffix':'count','labels':['name','bucket']},
                {'name':'ep_oom_errors','id':'ep_oom_errors','suffix':'count','labels':['name','bucket']},
                {'name':'ep_ops_create','id':'ep_ops_create','suffix':'count','labels':['name','bucket']},
                {'name':'ep_ops_update','id':'ep_ops_update','suffix':'count','labels':['name','bucket']},
                {'name':'ep_overhead','id':'ep_overhead','suffix':'bytes','labels':['name','bucket']},
                {'name':'ep_queue_size','id':'ep_queue_size','suffix':'count','labels':['name','bucket']},
                {'name':'ep_resident_items_rate','id':'ep_resident_items_rate','suffix':'count','labels':['name','bucket']},
                {'name':'ep_tap_rebalance_count','id':'ep_tap_rebalance_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_rebalance_qlen','id':'ep_tap_rebalance_qlen','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_rebalance_queue_backfillremaining','id':'ep_tap_rebalance_queue_backfillremaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_rebalance_queue_backoff','id':'ep_tap_rebalance_queue_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_rebalance_queue_drain','id':'ep_tap_rebalance_queue_drain','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_rebalance_queue_fill','id':'ep_tap_rebalance_queue_fill','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_rebalance_queue_itemondisk','id':'ep_tap_rebalance_queue_itemondisk','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_rebalance_total_backlog_size','id':'ep_tap_rebalance_total_backlog_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_replica_count','id':'ep_tap_replica_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_replica_qlen','id':'ep_tap_replica_qlen','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_replica_queue_backfillremaining','id':'ep_tap_replica_queue_backfillremaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_replica_queue_backoff','id':'ep_tap_replica_queue_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_replica_queue_drain','id':'ep_tap_replica_queue_drain','suffix':'count','labels':['name','bucket']},
                {'name':'ep_tap_replica_queue_fill','id':'ep_tap_replica_queue_fill','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_replica_queue_itemondisk','id':'ep_tap_replica_queue_itemondisk','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_replica_total_backlog_size','id':'ep_tap_replica_total_backlog_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_total_count','id':'ep_tap_total_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_total_qlen','id':'ep_tap_total_qlen','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_total_queue_backfillremaining','id':'ep_tap_total_queue_backfillremaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_total_queue_backoff','id':'ep_tap_total_queue_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_total_queue_drain','id':'ep_tap_total_queue_drain','suffix':'count','labels':['name','bucket']},
                {'name':'ep_tap_total_queue_fill','id':'ep_tap_total_queue_fill','suffix':'count','labels':['name','bucket']},
                {'name':'ep_tap_total_queue_itemondisk','id':'ep_tap_total_queue_itemondisk','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_total_total_backlog_size','id':'ep_tap_total_total_backlog_size','suffix':'count','labels':['name','bucket']},
                {'name':'ep_tap_user_count','id':'ep_tap_user_count','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_user_qlen','id':'ep_tap_user_qlen','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_user_queue_backfillremaining','id':'ep_tap_user_queue_backfillremaining','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_user_queue_backoff','id':'ep_tap_user_queue_backoff','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_user_queue_drain','id':'ep_tap_user_queue_drain','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_user_queue_fill','id':'ep_tap_user_queue_fill','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_user_queue_itemondisk','id':'ep_tap_user_queue_itemondisk','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tap_user_total_backlog_size','id':'ep_tap_user_total_backlog_size','suffix':'NA','labels':['name','bucket']},
                {'name':'ep_tmp_oom_errors','id':'ep_tmp_oom_errors','suffix':'count','labels':['name','bucket']},
                {'name':'ep_vb_total','id':'ep_vb_total','suffix':'NA','labels':['name','bucket']},
                {'name':'evictions','id':'evictions','suffix':'count','labels':['name','bucket']},
                {'name':'get_hits','id':'get_hits','suffix':'count','labels':['name','bucket']},
                {'name':'get_misses','id':'get_misses','suffix':'count','labels':['name','bucket']},
                {'name':'hibernated_requests','id':'hibernated_requests','suffix':'NA','labels':['name','bucket']},
                {'name':'hibernated_waked','id':'hibernated_waked','suffix':'NA','labels':['name','bucket']},
                {'name':'hit_ratio','id':'hit_ratio','suffix':'percent','labels':['name','bucket']},
                {'name':'incr_hits','id':'incr_hits','suffix':'count','labels':['name','bucket']},
                {'name':'incr_misses','id':'incr_misses','suffix':'count','labels':['name','bucket']},
                {'name':'mem_actual_free','id':'mem_actual_free','suffix':'NA','labels':['name','bucket']},
                {'name':'mem_actual_used','id':'mem_actual_used','suffix':'NA','labels':['name','bucket']},
                {'name':'mem_free','id':'mem_free','suffix':'bytes','labels':['name','bucket']},
                {'name':'mem_total','id':'mem_total','suffix':'bytes','labels':['name','bucket']},
                {'name':'mem_used','id':'mem_used','suffix':'bytes','labels':['name','bucket']},
                {'name':'mem_used_sys','id':'mem_used_sys','suffix':'bytes','labels':['name','bucket']},
                {'name':'misses','id':'misses','suffix':'count','labels':['name','bucket']},
                {'name':'ops','id':'ops','suffix':'count','labels':['name','bucket']},
                {'name':'rest_requests','id':'rest_requests','suffix':'NA','labels':['name','bucket']},
                {'name':'swap_total','id':'swap_total','suffix':'NA','labels':['name','bucket']},
                {'name':'swap_used','id':'swap_used','suffix':'NA','labels':['name','bucket']},
                {'name':'timestamp','id':'timestamp','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_eject','id':'vb_active_eject','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_itm_memory','id':'vb_active_itm_memory','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_meta_data_memory','id':'vb_active_meta_data_memory','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_num','id':'vb_active_num','suffix':'count','labels':['name','bucket']},
                {'name':'vb_active_num_non_resident','id':'vb_active_num_non_resident','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_ops_create','id':'vb_active_ops_create','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_ops_update','id':'vb_active_ops_update','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_queue_age','id':'vb_active_queue_age','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_queue_drain','id':'vb_active_queue_drain','suffix':'count','labels':['name','bucket']},
                {'name':'vb_active_queue_fill','id':'vb_active_queue_fill','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_active_queue_size','id':'vb_active_queue_size','suffix':'count','labels':['name','bucket']},
                {'name':'vb_active_resident_items_ratio','id':'vb_active_resident_items_ratio','suffix':'count','labels':['name','bucket']},
                {'name':'vb_avg_active_queue_age','id':'vb_avg_active_queue_age','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_avg_pending_queue_age','id':'vb_avg_pending_queue_age','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_avg_replica_queue_age','id':'vb_avg_replica_queue_age','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_avg_total_queue_age','id':'vb_avg_total_queue_age','suffix':'seconds','labels':['name','bucket']},
                {'name':'vb_pending_curr_items','id':'vb_pending_curr_items','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_eject','id':'vb_pending_eject','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_itm_memory','id':'vb_pending_itm_memory','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_meta_data_memory','id':'vb_pending_meta_data_memory','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_num','id':'vb_pending_num','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_num_non_resident','id':'vb_pending_num_non_resident','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_ops_create','id':'vb_pending_ops_create','suffix':'count','labels':['name','bucket']},
                {'name':'vb_pending_ops_update','id':'vb_pending_ops_update','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_queue_age','id':'vb_pending_queue_age','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_queue_drain','id':'vb_pending_queue_drain','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_queue_fill','id':'vb_pending_queue_fill','suffix':'count','labels':['name','bucket']},
                {'name':'vb_pending_queue_size','id':'vb_pending_queue_size','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_pending_resident_items_ratio','id':'vb_pending_resident_items_ratio','suffix':'count','labels':['name','bucket']},
                {'name':'vb_replica_curr_items','id':'vb_replica_curr_items','suffix':'count','labels':['name','bucket']},
                {'name':'vb_replica_eject','id':'vb_replica_eject','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_replica_itm_memory','id':'vb_replica_itm_memory','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_replica_meta_data_memory','id':'vb_replica_meta_data_memory','suffix':'bytes','labels':['name','bucket']},
                {'name':'vb_replica_num','id':'vb_replica_num','suffix':'bytes','labels':['name','bucket']},
                {'name':'vb_replica_num_non_resident','id':'vb_replica_num_non_resident','suffix':'bytes','labels':['name','bucket']},
                {'name':'vb_replica_ops_create','id':'vb_replica_ops_create','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_replica_ops_update','id':'vb_replica_ops_update','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_replica_queue_age','id':'vb_replica_queue_age','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_replica_queue_drain','id':'vb_replica_queue_drain','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_replica_queue_fill','id':'vb_replica_queue_fill','suffix':'NA','labels':['name','bucket']},
                {'name':'vb_replica_queue_size','id':'vb_replica_queue_size','suffix':'count','labels':['name','bucket']},
                {'name':'vb_replica_resident_items_ratio','id':'vb_replica_resident_items_ratio','suffix':'count','labels':['name','bucket']},
                {'name':'vb_total_queue_age','id':'vb_total_queue_age','suffix':'NA','labels':['name','bucket']},
                {'name':'xdc_ops','id':'xdc_ops','suffix':'count','labels':['name','bucket']}
            ]
        }
    }

if __name__ == '__main__':
	try:
		args = parse_args()
		port = int(args.port)
		REGISTRY.register(CouchbaseCollector(args.couchbase, get_metrics()))
		start_http_server(port)
		print("Serving at port: %s" % port)
		while True: time.sleep(0.25)
	except KeyboardInterrupt:
		print(" Interrupted")
		exit(0)
