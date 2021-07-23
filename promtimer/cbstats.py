# Copyright (c) 2020-2021 Couchbase, Inc All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import logging
import re
import glob
import json
from os import path

import util

class Source:
    """
    Represents a source of stats data for a Couchbase Server node.

    Currently the only type of source that is supported is a cbcollect directory (which
    contains a snapshot of the Prometheus metrics for the node from which the cbcollect
    was taken.)
    """
    def __init__(self, cbcollect_dir, short_name, prometheus_port):
        self._short_name = short_name
        self._cbcollect_dir = cbcollect_dir
        self._prometheus_port = prometheus_port
        self._config = None

    def short_name(self):
        """
        :return: a convenient short name for this source which
        """
        return self._short_name

    def port(self):
        """
        Returns the port for the Prometheus (or Prometheus-like) instance that serves
        the stats associated with this source.
        :return: the port number
        """
        return self._prometheus_port

    def start(self, log_dir):
        """
        Starts the Prometheus instance that serves stats for this source.
        :param log_dir: the directory in which logs should be written
        :return: the process handle associated with the stats server
        """
        log_path = path.join(log_dir, 'prom-{}.log'.format(self._short_name))
        listen_addr = '0.0.0.0:{}'.format(self._prometheus_port)
        args = [Source.PROMETHEUS_BIN,
                '--config.file', path.join(util.get_root_dir(), 'noscrape.yml'),
                '--storage.tsdb.path', path.join(self._cbcollect_dir, 'stats_snapshot'),
                '--storage.tsdb.no-lockfile',
                '--storage.tsdb.retention.time', '10y',
                '--query.lookback-delta', '600s',
                '--web.listen-address', listen_addr]
        logging.info('starting prometheus server on {} against {}; logging to {}'
                     .format(listen_addr,
                             path.join(self._cbcollect_dir, 'stats_snapshot'),
                             log_path))
        return util.start_process(args, log_path)

    def get_buckets(self):
        """
        Returns the list of buckets associated with this stats Source
        :return: list of buckets
        """
        if self._config is None:
            self._config = parse_couchbase_log(self._cbcollect_dir)
        return self._config['buckets']

    def get_min_and_max_times(self):
        """
        Returns a 2-tuple containing an estimate of the min and max POSIX timestamps
        times associated with this stats Source
        :return: 2-tuple (min time, max time)
        """
        return get_prometheus_times(self._cbcollect_dir)

    @staticmethod
    def compute_min_and_max_times(sources):
        times = [s.get_min_and_max_times() for s in sources]
        return min([t[0] for t in times]), max([t[1] for t in times])

    @staticmethod
    def start_stats_servers(stats_sources, log_dir):
        nodes = []
        for stats_source in stats_sources:
            node = stats_source.start(log_dir)
            nodes.append(node)
        return nodes


def parse_couchbase_ns_config(cbcollect_dir):
    logging.debug('parsing couchbase.log (Couchbase config)')
    in_config = False
    in_buckets = False
    buckets = []
    section_divider_count = 0
    with open(path.join(cbcollect_dir, 'couchbase.log'), "r") as file:
        for full_line in file:
            line = full_line.rstrip()
            config_line = 'Couchbase config'
            if not in_config and line.rstrip() == config_line:
                in_config = True
            elif in_config:
                if line.strip().startswith('=================='):
                    section_divider_count += 1
                    if section_divider_count == 2:
                        break
                if not in_buckets and line == ' {buckets,':
                    in_buckets = True
                elif in_buckets:
                    if re.match('^ \{.*,$', line):
                        break
                    else:
                        m = re.match('^    [ \[]\{\"(.*)\",$', line)
                        if m:
                            bucket = m.groups()[0]
                            logging.debug('found bucket:{}'.format(bucket))
                            buckets.append(bucket)
    return {'buckets': sorted(buckets)}

def parse_couchbase_chronicle_older_version(cbcollect_dir):
    logging.debug('parsing couchbase.log (Chronicle config)')
    in_config = False
    in_buckets = False
    bucket_list = ''
    with open(path.join(cbcollect_dir, 'couchbase.log'), 'r') as file:
        for full_line in file:
            line = full_line.rstrip()
            if not in_config and line == 'Chronicle config':
                in_config = True
            elif in_config:
                # Names of bucket can be on a single or multiple lines
                end_of_list = False
                possible_buckets = ''
                if not in_buckets:
                    if line.startswith(' {bucket_names,'):
                        in_buckets = True
                        possible_buckets = line.replace(' {bucket_names,[', '')
                elif in_buckets:
                    possible_buckets = line

                if possible_buckets != '':
                    if possible_buckets.endswith(']},'):
                        possible_buckets = possible_buckets[:-3]
                        end_of_list = True

                    bucket_list += possible_buckets

                    if end_of_list:
                        break

    buckets = []
    if bucket_list != '':
        for b in bucket_list.replace(' ','').replace('"','').split(','):
            buckets.append(b)

    return {'buckets': sorted(buckets)}

def parse_couchbase_chronicle(cbcollect_dir):
    logging.debug('parsing couchbase.log (Chronicle config)')
    in_config = False
    in_buckets = False
    bucket_list = ''
    with open(path.join(cbcollect_dir, 'couchbase.log'), 'r') as file:
        for full_line in file:
            line = full_line.rstrip()
            if not in_config and line == 'Chronicle dump':
                in_config = True
            elif in_config:
                # Names of bucket can be on a single or multiple lines
                bucket_list = ''
                possible_buckets = ''
                if not in_buckets:
                    m = re.match('(^\s*{bucket_names,{\[)(.*)', line)
                    if m:
                        in_buckets = True
                        possible_buckets = m.group(2)
                elif in_buckets:
                    possible_buckets = line
                if possible_buckets != '':
                    m = re.match('^([^\]]*)\].*', possible_buckets)
                    if m:
                        bucket_list += m.group(1)
                        break
                    bucket_list += possible_buckets
    buckets = []
    if bucket_list != '':
        for b in bucket_list.replace(' ','').replace('"','').split(','):
            buckets.append(b)
    logging.debug('found buckets:{}'.format(buckets))
    return {'buckets': sorted(buckets)}

def parse_couchbase_log(cbcollect_dir):
    config = parse_couchbase_chronicle(cbcollect_dir)
    if config['buckets'] == []:
        config = parse_couchbase_chronicle_older_version(cbcollect_dir)
        if config['buckets'] == []:
            config = parse_couchbase_ns_config(cbcollect_dir)
    return config

def get_prometheus_times(cbcollect_dir):
    min_times = []
    max_times = []
    meta_files = glob.glob(path.join(cbcollect_dir, 'stats_snapshot', '*', 'meta.json'))
    for meta_file in meta_files:
        with open(meta_file, 'r') as file:
            meta = json.loads(file.read())
            min_times.append(meta['minTime'])
            max_times.append(meta['maxTime'])
    return min(min_times), max(max_times)

