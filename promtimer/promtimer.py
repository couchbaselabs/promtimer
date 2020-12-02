#!/usr/bin/env python3
#
# Copyright (c) 2020 Couchbase, Inc All rights reserved.
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

import argparse
import glob
import os
from os import path
import time
import json
import datetime
import re
import webbrowser
import logging
import sys

# local imports
import util
import templating
import dashboard

PROMETHEUS_BIN = 'prometheus'
GRAFANA_DIR = '.grafana'
GRAFANA_LOGS_DIR = path.join(GRAFANA_DIR, 'logs')
GRAFANA_BIN = 'grafana-server'

def get_cbcollect_dirs():
    cbcollect_files = sorted(glob.glob('cbcollect_info*'))
    result = []
    for file in cbcollect_files:
        if path.isdir(file) and path.isdir(path.join(file, 'stats_snapshot')):
            result.append(file)
    return result

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

def get_prometheus_min_and_max_times(cbcollects):
    times = [get_prometheus_times(c) for c in cbcollects]
    return min([t[0] for t in times]), max([t[1] for t in times])

def start_prometheuses(cbcollects, base_port, log_dir):
    nodes = []
    for i, cbcollect in enumerate(cbcollects):
        log_path = path.join(log_dir, 'prom-{}.log'.format(i))
        listen_addr = '0.0.0.0:{}'.format(base_port + i)
        args = [PROMETHEUS_BIN,
                '--config.file', path.join(util.get_root_dir(), 'noscrape.yml'),
                '--storage.tsdb.path', path.join(cbcollect, 'stats_snapshot'),
                '--storage.tsdb.retention.time', '10y',
                '--web.listen-address', listen_addr]
        logging.info('starting prometheus server {} (on {}; logging to {})'
                     .format(i, listen_addr, log_path))
        node = util.start_process(args, log_path)
        nodes.append(node)

    return nodes

def get_data_source_template():
    with open(path.join(util.get_root_dir(), 'data-source.yaml'), 'r') as file:
        return file.read()

def get_provisioning_dir():
    return path.join(GRAFANA_DIR, 'provisioning')

def get_dashboards_dir():
    return path.join(get_provisioning_dir(), 'dashboards')

def get_plugins_dir():
    return path.join(get_provisioning_dir(), 'plugins')

def get_notifiers_dir():
    return path.join(get_provisioning_dir(), 'notifiers')

def get_custom_ini_template():
    with open(path.join(util.get_root_dir(), 'custom.ini'), 'r') as file:
        return file.read()

def get_home_dashboard():
    with open(path.join(util.get_root_dir(), 'home.json'), 'r') as file:
        return file.read()

def make_custom_ini(grafana_http_port):
    os.makedirs(GRAFANA_DIR, exist_ok=True)
    replacements = {'absolute-path-to-cwd': os.path.abspath('.'),
                    'grafana-http-port': str(grafana_http_port)}
    template = get_custom_ini_template()
    contents = templating.replace(template, replacements)
    with open(path.join(GRAFANA_DIR, 'custom.ini'), 'w') as file:
        file.write(contents)

def make_home_dashboard():
    dash = get_home_dashboard()
    with open(path.join(GRAFANA_DIR, 'home.json'), 'w') as file:
        file.write(dash)

def make_dashboards_yaml():
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    with open(path.join(util.get_root_dir(), 'dashboards.yaml'), 'r') as file:
        replacements = {'absolute-path-to-cwd': os.path.abspath('.')}
        contents = templating.replace(file.read(), replacements)
        with open(path.join(get_dashboards_dir(), 'dashboards.yaml'), 'w') as file_to_write:
            file_to_write.write(contents)

def get_dashboard_metas():
    files = glob.glob(path.join(util.get_root_dir(), 'dashboards', '*.json'))
    result = []
    for f in files:
        with open(f, 'r') as file:
            result.append(file.read())
    return result

def make_dashboards(data_sources, buckets, times):
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    min_time = datetime.datetime.fromtimestamp(times[0] / 1000.0)
    max_time = datetime.datetime.fromtimestamp(times[1] / 1000.0)
    dashboard_meta_strings = get_dashboard_metas()
    template_params = \
        [{'type': 'data-source-name', 'values': data_sources},
         {'type': 'bucket', 'values': buckets}]
    for meta_string in dashboard_meta_strings:
        meta = json.loads(meta_string)
        dash = dashboard.make_dashboard(meta, template_params, min_time, max_time)
        file_name = meta['title'].replace(' ', '-').lower() + '.json'
        with open(path.join(get_dashboards_dir(), file_name), 'w') as file:
            file.write(json.dumps(dash, indent=2))

def make_data_sources(data_sources_names, base_port):
    datasources_dir = path.join(get_provisioning_dir(), 'datasources')
    os.makedirs(datasources_dir, exist_ok=True)
    template = get_data_source_template()
    for i, data_source_name in enumerate(data_sources_names):
        data_source_name = data_sources_names[i]
        replacement_map = {'data-source-name': data_source_name,
                           'data-source-port' : str(base_port + i)}
        filename = path.join(datasources_dir, 'ds-{}.yaml'.format(data_source_name))
        with open(filename, 'w') as file:
            file.write(templating.replace(template, replacement_map))

def try_get_data_source_names(cbcollect_dirs, pattern, name_format):
    data_sources = []
    for cbcollect in cbcollect_dirs:
        m = re.match(pattern, cbcollect)
        name = cbcollect
        if m:
            name = name_format.format(*m.groups())
        data_sources.append(name)
    if len(set(data_sources)) == len(data_sources):
        return data_sources
    return None

def get_data_source_names(cbcollect_dirs):
    regex = re.compile('cbcollect_info_ns_(\d+)\@(.*)_(\d+)-(\d+)')
    formats = ['{1}', 'ns_{0}@{1}', '{1}-{2}-{3}', 'ns_{0}-{1}-{2}-{3}']
    for fmt in formats:
        result = try_get_data_source_names(cbcollect_dirs, regex, fmt)
        if result:
            return result
    return cbcollect_dirs

def prepare_grafana(grafana_port, prometheus_base_port, cbcollect_dirs, buckets, times):
    os.makedirs(GRAFANA_DIR, exist_ok=True)
    os.makedirs(GRAFANA_LOGS_DIR, exist_ok=True)
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    os.makedirs(get_plugins_dir(), exist_ok=True)
    os.makedirs(get_notifiers_dir(), exist_ok=True)
    data_sources = get_data_source_names(cbcollect_dirs)
    make_custom_ini(grafana_port)
    make_home_dashboard()
    make_data_sources(data_sources, prometheus_base_port)
    make_dashboards_yaml()
    make_dashboards(data_sources, buckets, times)

def start_grafana(grafana_home_path, grafana_port):
    log_path = path.join(GRAFANA_LOGS_DIR, 'grafana.log')
    args = [GRAFANA_BIN,
            '--homepath', grafana_home_path,
            '--config','custom.ini']
    logging.info('starting grafana server (on localhost:{}; logging to {})'
                 .format(grafana_port, log_path))
    return util.start_process(args, log_path, GRAFANA_DIR)

def open_browser(grafana_http_port):
    url = 'http://localhost:{}/dashboards'.format(grafana_http_port)
    # Helpful for those who accidently close the browser
    logging.info('starting browser using {}'.format(url))
    try:
        # For some reason this sometimes throws an OSError with no
        # apparent side-effects. Probably related to forking processes
        webbrowser.open_new(url)
    except OSError:
        logging.error("Hit `OSError` opening web browser")
        pass

def parse_couchbase_log(cbcollect_dir):
    logging.debug('parsing couchbase.log')
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--grafana-home', dest='grafana_home_path', required=True,
                        help='''
                        Grafana configuration "homepath"; should be set to the
                        out-of-the-box Grafana config path. On brew-installed Grafana on
                        Macs this is something like:
                            /usr/local/Cellar/grafana/x.y.z/share/grafana
                        On linux systems the homepath should usually be:
                            /usr/share/grafana
                        ''')
    parser.add_argument('--prometheus', dest='prom_bin',
                        help='path to prometheus binary if it\'s not available on $PATH')
    parser.add_argument('--grafana-port', dest='grafana_port', type=int,
                        help='http port on which Grafana should listen (default: 13000)',
                        default=13000)
    parser.add_argument("--verbose", dest='verbose', action='store_true',
                        default=False, help="verbose output")
    args = parser.parse_args()

    os.makedirs(GRAFANA_LOGS_DIR, exist_ok=True)

    stream_handler = logging.StreamHandler(sys.stdout)
    level = logging.DEBUG if args.verbose else logging.INFO
    stream_handler.setLevel(level)
    logging.basicConfig(level=logging.DEBUG,
                        format='%(message)s',
                        handlers=[
                            logging.FileHandler(path.join(GRAFANA_LOGS_DIR,
                                'promtimer.log')),
                            stream_handler
                            ]
                        )

    cbcollects = get_cbcollect_dirs()
    config = parse_couchbase_log(cbcollects[0])
    times = get_prometheus_min_and_max_times(cbcollects)

    grafana_port = args.grafana_port
    prometheus_base_port = grafana_port + 1
    prepare_grafana(grafana_port,
                    prometheus_base_port,
                    cbcollects,
                    config['buckets'],
                    times)

    if args.prom_bin:
        global PROMETHEUS_BIN
        PROMETHEUS_BIN = args.prom_bin

    processes = start_prometheuses(cbcollects, prometheus_base_port,
            GRAFANA_LOGS_DIR)
    processes.append(start_grafana(args.grafana_home_path, grafana_port))

    time.sleep(0.1)
    result = util.poll_processes(processes, 1)
    if result is None:
        open_browser(grafana_port)
        util.poll_processes(processes)

if __name__ == '__main__':
    main()
