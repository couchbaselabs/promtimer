#!/usr/bin/env python3
#
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

import argparse
import glob
import os
from os import path
import time
import json
import datetime
import webbrowser
import sys
import getpass
import logging

# local imports
import util
import templating
import dashboard
import annotations
import cbstats

PROMETHEUS_BIN = 'prometheus'
PROMTIMER_DIR = '.promtimer'
PROMTIMER_LOGS_DIR = path.join(PROMTIMER_DIR, 'logs')
GRAFANA_BIN = 'grafana-server'

def is_executable_file(candidate_file):
    return os.path.isfile(candidate_file) and os.access(candidate_file, os.X_OK)

def get_data_source_template():
    with open(path.join(util.get_root_dir(), 'data-source.yaml'), 'r') as file:
        return file.read()

def get_provisioning_dir():
    return path.join(PROMTIMER_DIR, 'provisioning')

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
    os.makedirs(PROMTIMER_DIR, exist_ok=True)
    replacements = {'absolute-path-to-cwd': os.path.abspath('.'),
                    'grafana-http-port': str(grafana_http_port)}
    template = get_custom_ini_template()
    contents = templating.replace(template, replacements)
    with open(path.join(PROMTIMER_DIR, 'custom.ini'), 'w') as file:
        file.write(contents)

def make_home_dashboard():
    dash = get_home_dashboard()
    with open(path.join(PROMTIMER_DIR, 'home.json'), 'w') as file:
        file.write(dash)

def make_dashboards_yaml():
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    with open(path.join(util.get_root_dir(), 'dashboards.yaml'), 'r') as file:
        replacements = {'absolute-path-to-cwd': os.path.abspath('.')}
        contents = templating.replace(file.read(), replacements)
        with open(path.join(get_dashboards_dir(), 'dashboards.yaml'), 'w') as file_to_write:
            file_to_write.write(contents)

def make_dashboards(stats_sources, buckets, min_time_string, max_time_string, refresh_string):
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    data_sources = [s.short_name() for s in stats_sources]
    template_params = \
        [{'type': 'data-source-name', 'values': data_sources},
         {'type': 'bucket', 'values': buckets}]
    meta_file_names = glob.glob(path.join(util.get_root_dir(), 'dashboards', '*.json'))
    for meta_file_name in meta_file_names:
        with open(meta_file_name, 'r') as meta_file:
            meta = json.loads(meta_file.read())
            base_file_name = path.basename(meta_file_name)
            dash = dashboard.make_dashboard(meta,
                                            template_params,
                                            min_time_string,
                                            max_time_string,
                                            refresh_string)
            dash['uid'] = base_file_name[:-len('.json')]
            with open(path.join(get_dashboards_dir(), base_file_name), 'w') as file:
                file.write(json.dumps(dash, indent=2))

def make_data_sources(stats_sources):
    datasources_dir = path.join(get_provisioning_dir(), 'datasources')
    os.makedirs(datasources_dir, exist_ok=True)
    template = get_data_source_template()
    for i, stats_source in enumerate(stats_sources):
        auth_required = stats_source.requires_auth()
        user = ''
        password = ''
        if auth_required:
            user = stats_source.basic_auth_user()
            # https://github.com/grafana/grafana/issues/17986
            password = stats_source.basic_auth_password().replace("$", "$$")
        data_source_name = stats_source.short_name()
        replacement_map = {'data-source-name': data_source_name,
                           'data-source-host': stats_source.host(),
                           'data-source-port': str(stats_source.port()),
                           'data-source-path': stats_source.stats_url_path(),
                           'data-source-basic-auth': str(auth_required),
                           'data-source-basic-auth-user': user,
                           'data-source-basic-auth-password': password}
        filename = 'ds-{}.yaml'.format(data_source_name).replace(':', '_')
        fullname = path.join(datasources_dir, filename)
        with open(fullname, 'w') as file:
            file.write(templating.replace(template, replacement_map))

def prepare_grafana(grafana_port,
                    stats_sources,
                    buckets,
                    min_time_string,
                    max_time_string,
                    refresh):
    os.makedirs(PROMTIMER_DIR, exist_ok=True)
    os.makedirs(PROMTIMER_LOGS_DIR, exist_ok=True)
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    os.makedirs(get_plugins_dir(), exist_ok=True)
    os.makedirs(get_notifiers_dir(), exist_ok=True)
    make_custom_ini(grafana_port)
    make_home_dashboard()
    make_data_sources(stats_sources)
    make_dashboards_yaml()
    make_dashboards(stats_sources, buckets, min_time_string, max_time_string, refresh)

def start_grafana(grafana_home_path, grafana_port):
    args = [GRAFANA_BIN,
            '--homepath', grafana_home_path,
            '--config','custom.ini']
    log_path = path.join(PROMTIMER_DIR, 'logs/grafana.log')
    logging.info('starting grafana server (on localhost:{}; logging to {})'
                 .format(grafana_port, log_path))
    # Don't specify a log file as it is done within the custom.ini file
    # otherwise the output is duplicated.
    return util.start_process(args, None, PROMTIMER_DIR)

def maybe_open_browser(grafana_http_port, dont_open_browser):
    url = 'http://localhost:{}/dashboards'.format(grafana_http_port)
    # Helpful for those who accidently close the browser
    if not dont_open_browser:
        logging.info('starting browser using {}'.format(url))
        try:
            # For some reason this sometimes throws an OSError with no
            # apparent side-effects. Probably related to forking processes
            webbrowser.open_new_tab(url)
        except OSError:
            logging.error("Hit `OSError` opening web browser")
            pass
    else:
        logging.info('not opening browser; navigate to {}'.format(url))

def main():
    parser = argparse.ArgumentParser()
    grafana_home_default = None
    if sys.platform == 'darwin':
        grafana_home_default = '/usr/local/share/grafana'
    elif sys.platform == 'linux':
        grafana_home_default = '/usr/share/grafana'

    parser.add_argument('-g', '--grafana-home', dest='grafana_home_path',
                        default=grafana_home_default,
                        help='''
                        Grafana configuration "homepath"; should be set to the
                        out-of-the-box Grafana config path. On brew-installed Grafana on
                        Macs this is something like:
                            /usr/local/share/grafana
                        On linux systems the homepath should usually be:
                            /usr/share/grafana
                        ''')
    parser.add_argument('-p', '--prometheus', dest='prom_bin',
                        help='path to prometheus binary if it\'s not available on $PATH')
    parser.add_argument('--grafana-port', dest='grafana_port', type=int,
                        help='http port on which Grafana should listen (default: 13300)',
                        default=13300)
    parser.add_argument('-c', '--cluster', dest='cluster',
                        help='URL of Couchbase Server cluster to connect to; if specified '
                             'then this instance of Promtimer does not run against cbcollect '
                             'snapshots and runs against Couchbase Server cluster '
                             'directly')
    parser.add_argument('--user', dest='user',
                        help='user to authenticate with when running against a Couchbase '
                             'Server cluster (and required in this case)')
    parser.add_argument('--password', dest='password',
                        help='password of user when running against a Couchbase Server '
                             'cluster; will be prompted for if not specified')
    parser.add_argument('--buckets', dest='buckets',
                        help='comma-separated list of buckets to build bucket dashboards '
                             'for; if this option is provided, auto-detection of the '
                             'buckets by parsing couchbase.log (or by querying a running '
                             'Couchbase Server node directly) will be skipped')
    parser.add_argument('--dont-open-browser', dest='dont_open_browser', default=False,
                        action='store_true',
                        help='don\'t open browser tab automatically on start')
    parser.add_argument("--verbose", dest='verbose', action='store_true',
                        default=False, help="verbose output")
    parser.add_argument('--refresh', dest='refresh',
                        help='grafana refresh interval; '
                             'only valid when connecting to live cluster')
    args = parser.parse_args()

    os.makedirs(PROMTIMER_LOGS_DIR, exist_ok=True)

    stream_handler = logging.StreamHandler(sys.stdout)
    level = logging.DEBUG if args.verbose else logging.INFO
    stream_handler.setLevel(level)
    logging.basicConfig(level=logging.DEBUG,
                        format='%(message)s',
                        handlers=[
                            logging.FileHandler(path.join(PROMTIMER_LOGS_DIR,
                                'promtimer.log')),
                            stream_handler
                            ]
                        )
    if args.cluster and not args.user:
        logging.error('User must be specified when running Promtimer directly '
                      'against a Couchbase Server cluster')
        sys.exit(1)

    if args.cluster and args.user and not args.password:
        args.password = getpass.getpass(prompt='Password: ')
    if args.grafana_home_path is None:
        logging.error('Please specify the Grafana home directory as it '
                      'cant\'t be defaulted on this platform')
        sys.exit(1)
    if not os.path.isdir(args.grafana_home_path):
        logging.error('Invalid grafana path: {}'.format(args.grafana_home_path))
        sys.exit(1)

    grafana_port = args.grafana_port
    prometheus_base_port = grafana_port + 1

    if not args.cluster:
        stats_sources = cbstats.CBCollect.get_stats_sources(prometheus_base_port)
        if not stats_sources:
            sys.exit(1)
        times = cbstats.CBCollect.compute_min_and_max_times(stats_sources)
        min_time = datetime.datetime.fromtimestamp(times[0]).isoformat()
        max_time = datetime.datetime.fromtimestamp(times[1]).isoformat()
        refresh = ''
    else:
        stats_sources = cbstats.ServerNode.get_stats_sources(args.cluster,
                                                             args.user,
                                                             args.password)
        if not stats_sources:
            sys.exit(1)
        min_time = 'now-30m'
        max_time = 'now'
        refresh = args.refresh or '5s'

    if not args.buckets:
        buckets = stats_sources[0].get_buckets()
    else:
        buckets = sorted(args.buckets.split(','))

    logging.info('using grafana home path:{} '.format(args.grafana_home_path))
    prepare_grafana(grafana_port,
                    stats_sources,
                    buckets,
                    min_time,
                    max_time,
                    refresh)

    if args.prom_bin:
        global PROMETHEUS_BIN
        PROMETHEUS_BIN = args.prom_bin

    if not args.cluster and not is_executable_file(PROMETHEUS_BIN):
        logging.error('Invalid prometheus executable path: {}'.format(
            PROMETHEUS_BIN))
        sys.exit(1)

    cbstats.Source.PROMETHEUS_BIN = PROMETHEUS_BIN
    processes = cbstats.Source.maybe_start_stats_servers(stats_sources,
                                                         PROMTIMER_LOGS_DIR)
    processes.append(start_grafana(args.grafana_home_path, grafana_port))

    time.sleep(0.1)
    result = util.poll_processes(processes, 1)
    if result is None:
        maybe_open_browser(grafana_port, args.dont_open_browser)
        annotations.get_and_create_annotations(grafana_port, stats_sources, not args.cluster)
        util.poll_processes(processes)

if __name__ == '__main__':
    main()
