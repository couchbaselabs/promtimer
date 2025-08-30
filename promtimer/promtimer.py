#!/usr/bin/env python3
#
# Copyright (c) 2020-Present Couchbase, Inc All rights reserved.
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
import json
import datetime
import webbrowser
import sys
import getpass
import logging

# Local Imports
import annotations
import backupstats
import cbstats
import dashboard
import templating
import util

PROMETHEUS_BIN = os.environ.get('PROM_BIN', 'prometheus')
PROMTIMER_DIR = '.promtimer'
PROMTIMER_LOGS_DIR = path.join(PROMTIMER_DIR, 'logs')
CBMSTATPARSER_BIN = 'cbmstatparser'
BACKUPMGR_STATS = 'cbbackupmgr-stats'


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


def make_dashboards(stats_sources,
                    buckets,
                    min_time_string,
                    max_time_string,
                    refresh_string,
                    timezone_string,
                    dashboard_name_predicate):
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    data_source_names = [s.short_name() for s in stats_sources]
    data_source_uids = [s.uid() for s in stats_sources]

    template_params = \
        [(templating.Parameter('data-source', ['name', 'uid']),
            [{'name': s.short_name(), 'uid': s.uid()} for s in stats_sources]),
         (templating.Parameter('bucket'), buckets if buckets else [])]
    meta_file_names = glob.glob(path.join(util.get_root_dir(), 'dashboards', '*.json'))
    for meta_file_name in meta_file_names:
        with open(meta_file_name, 'r') as meta_file:
            meta = json.loads(meta_file.read())
            base_file_name = path.basename(meta_file_name)
            if dashboard_name_predicate and not dashboard_name_predicate(base_file_name):
                continue
            dash = dashboard.make_dashboard(meta,
                                            template_params,
                                            min_time_string,
                                            max_time_string,
                                            refresh_string,
                                            timezone_string)
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
                           'data-source-uid': stats_source.uid(),
                           'data-source-scheme': stats_source.scheme(),
                           'data-source-host': stats_source.host(),
                           'data-source-port': str(stats_source.port()),
                           'data-source-path': stats_source.stats_url_path(),
                           'data-source-basic-auth': str(auth_required),
                           'data-source-basic-auth-user': user,
                           'data-source-basic-auth-password': password,
                           'data-source-time-interval': stats_source.time_interval()}

        filename = 'ds-{}.yaml'.format(data_source_name).replace(':', '_')
        fullname = path.join(datasources_dir, filename)
        with open(fullname, 'w') as file:
            file.write(templating.replace(template, replacement_map))


def prepare_grafana(grafana_port,
                    grafana_timezone,
                    stats_sources,
                    buckets,
                    min_time_string,
                    max_time_string,
                    refresh,
                    dashboard_name_predicate):
    os.makedirs(PROMTIMER_DIR, exist_ok=True)
    os.makedirs(PROMTIMER_LOGS_DIR, exist_ok=True)
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    os.makedirs(get_plugins_dir(), exist_ok=True)
    os.makedirs(get_notifiers_dir(), exist_ok=True)
    make_custom_ini(grafana_port)
    make_home_dashboard()
    make_data_sources(stats_sources)
    make_dashboards_yaml()
    make_dashboards(
        stats_sources, buckets,
        min_time_string, max_time_string, refresh,
        grafana_timezone, dashboard_name_predicate
    )


def start_grafana(grafana_bin, grafana_home_path, grafana_port):
    """
    Starts grafana-server wthe the specified home path listening to the specfied
    port.

    :param grafana_home_path: the Grafana home path to use
    :param grafana_port: the port to listen to
    :return: a Process instance wrapping the underlying process handle
    """
    name = 'grafana-server'
    args = [grafana_bin,
            '--homepath', grafana_home_path,
            '--config', 'custom.ini']
    log_path = path.join(PROMTIMER_DIR, 'logs/grafana.log')
    logging.info('starting {} on localhost:{}; logging to {}'
                 .format(name, grafana_port, log_path))
    # Don't specify a log file as it is done within the custom.ini file
    # otherwise the output is duplicated.
    result = util.Process.start(name, args, None, PROMTIMER_DIR)
    result.set_log_filename(log_path)
    return result


def connect_to_grafana(grafana_port):
    """
    Connects to the Grafana REST API
    :param grafana_port: the port on which grafana-server is listening
    :return: the REST API response
    """
    url = 'http://localhost:{}'.format(grafana_port)
    resp = util.execute_request(url, 'api/datasources', retries=50)
    logging.debug('connected to grafana at {}; response status: {}'.format(
                  grafana_port, resp.status))
    return resp


def maybe_open_browser(grafana_http_port, dont_open_browser, url_path):
    url = f'http://localhost:{grafana_http_port}/{url_path}'  # noqa: E231

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


def setup_logging(verbose):
    os.makedirs(PROMTIMER_LOGS_DIR, exist_ok=True)
    stream_handler = logging.StreamHandler(sys.stdout)
    level = logging.DEBUG if verbose else logging.INFO
    stream_handler.setLevel(level)
    stream_handler.setFormatter(logging.Formatter('%(message)s'))
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s:%(levelname)s: %(message)s',
                        datefmt='%Y-%m-%dT%H:%M:%S%z',
                        handlers=[
                            logging.FileHandler(path.join(PROMTIMER_LOGS_DIR,
                                                          'promtimer.log')),
                            stream_handler])


def make_stats_sources(
        prometheus_base_port: int,
        secure: bool | None,
        cluster: str | None,
        nodes: list[str],
        user: str | None,
        password: str | None,
        backup_archive_path: str | None,
        cbmstatparser_path: str):
    live_cluster = cluster or nodes
    if live_cluster:
        if nodes:
            secure = secure or any([util.has_secure_scheme(n) for n in nodes])
            stats_sources = cbstats.ServerNode.get_stats_sources_from_nodes(nodes,
                                                                            user,
                                                                            password,
                                                                            secure)
        else:
            secure = secure or util.has_secure_scheme(cluster)
            stats_sources = cbstats.ServerNode.get_stats_sources(cluster,
                                                                 user,
                                                                 password,
                                                                 secure)
        if not stats_sources:
            sys.exit(1)
        min_time = 'now-30m'
        max_time = 'now'
    elif backup_archive_path:
        stats_sources, min_time, max_time = backupstats.handle_backup_archive_mode(  # Here
            backup_archive_path,
            cbmstatparser_path,
            prometheus_base_port
        )
    else:
        stats_sources = cbstats.CBCollect.get_stats_sources(prometheus_base_port)
        if not stats_sources:
            sys.exit(1)
        times = cbstats.CBCollect.compute_min_and_max_times(stats_sources)
        min_time = datetime.datetime.fromtimestamp(times[0]).isoformat()
        max_time = datetime.datetime.fromtimestamp(times[1]).isoformat()

    return stats_sources, min_time, max_time


def start_processes_and_monitor(
        stats_sources: list[cbstats.Source],
        grafana_bin: str,
        grafana_home_path: str,
        grafana_port: int,
        create_annotations: bool,
        consult_events_log: bool,
        dont_open_browser: bool,
        initial_url: str):
    processes = cbstats.Source.maybe_start_stats_servers(stats_sources,
                                                         PROMTIMER_LOGS_DIR)
    processes.append(start_grafana(grafana_bin,
                                   grafana_home_path,
                                   grafana_port))

    try:
        connect_to_grafana(grafana_port)
        process = util.Process.poll_processes(processes, 1)
        if process is None:
            maybe_open_browser(grafana_port, dont_open_browser, initial_url)
            if create_annotations:
                annotations.get_and_create_annotations(grafana_port,
                                                       stats_sources,
                                                       consult_events_log)
            process = util.Process.poll_processes(processes)

        logging.info('process {} exited with status {}'.format(process.name(),
                                                               process.poll()))
        log_filename = process.log_filename()
        if log_filename:
            line_count = 3
            lines = util.read_last_n_lines(log_filename, line_count)
            logging.info('last {} lines of {}'.format(line_count, log_filename))
            for line in lines:
                logging.info(line.strip())
    except KeyboardInterrupt:
        # do nothing and let the program quietly expire
        pass


def run_promtimer(
        grafana_bin: str,
        grafana_home_path: str,
        grafana_port: int,
        secure: bool | None,
        cluster: str | None,
        nodes: list[str],
        user: str | None,
        password: str | None,
        buckets: list[str],
        backup_archive_path: str | None,
        cbmstatparser_path: str,
        refresh: str,
        dont_open_browser: bool):

    # make the stats sources
    stats_sources, min_time, max_time = \
        make_stats_sources(
            prometheus_base_port=grafana_port + 1,
            secure=secure,
            cluster=cluster,
            nodes=nodes,
            user=user,
            password=password,
            backup_archive_path=backup_archive_path,
            cbmstatparser_path=cbmstatparser_path)

    # determine timezone, list of buckets, refresh interval, etc
    timezone_override = os.environ.get('GRAFANA_TZ', '')
    if timezone_override != '':
        default_timezone = timezone_override
    else:
        default_timezone = cbstats.Source.get_one_timezone(stats_sources)
    if default_timezone is None:
        default_timezone = 'browser'
    logging.info('setting default timezone to {}'.format(default_timezone))

    if not buckets and not backup_archive_path:
        buckets = stats_sources[0].get_buckets()
    elif buckets:
        buckets = sorted(buckets)

    live_cluster = cluster or nodes
    if live_cluster:
        refresh = refresh or '5s'
    else:
        refresh = ''
    logging.info('using grafana home path:{} '.format(grafana_home_path))

    dashboard_name_predicate = lambda x: not x.startswith(BACKUPMGR_STATS)  # noqa E731
    if backup_archive_path:
        dashboard_name_predicate = lambda x: x.startswith(BACKUPMGR_STATS)  # noqa E731

    # create datasources, dashboards and Grafana initialization files
    prepare_grafana(
        grafana_port=grafana_port,
        grafana_timezone=default_timezone,
        stats_sources=stats_sources,
        buckets=buckets,
        min_time_string=min_time,
        max_time_string=max_time,
        refresh=refresh,
        dashboard_name_predicate=dashboard_name_predicate)

    url_path = 'dashboards'
    if backup_archive_path:
        url_path = f'd/{BACKUPMGR_STATS}/{BACKUPMGR_STATS}-dashboard'

    # start Grafana and any stats servers, monitor them, and open the browser
    start_processes_and_monitor(
        stats_sources=stats_sources,
        grafana_bin=grafana_bin,
        grafana_home_path=grafana_home_path,
        grafana_port=grafana_port,
        create_annotations=not backup_archive_path,
        consult_events_log=not cluster,
        dont_open_browser=dont_open_browser,
        initial_url=url_path)


def parse_args_validate_and_run():
    parser = argparse.ArgumentParser()
    grafana_home_default = None
    if sys.platform == 'darwin':
        grafana_home_default = '/usr/local/share/grafana'
    elif sys.platform == 'linux':
        grafana_home_default = '/usr/share/grafana'

    parser.add_argument('-g', '--grafana-home', dest='grafana_home_path',
                        help='''
                        Grafana configuration "homepath"; should be set to the
                        out-of-the-box Grafana config path. On brew-installed Grafana on
                        Macs this is something like:
                            /usr/local/share/grafana
                        On linux systems the homepath should usually be:
                            /usr/share/grafana
                        On Mac and Linux 
                        ''')
    parser.add_argument('--grafana-install-path', dest='grafana_install_path',
                        help='''
                        Grafana installation path. If specified, this path is used to
                        find the Grafana binary (in ${install}/bin/grafana-server) and to 
                        find the Grafana homepath (in ${install}/share/grafana).
                        If not specified, then the Grafana binary is assumed to be
                        available on $PATH and the Grafana home directory is assumed to be
                        the value of --grafana-home.
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
    parser.add_argument('--refresh', dest='refresh',
                        help='grafana refresh interval; '
                             'only valid when connecting to live cluster')
    parser.add_argument('-n', '--node', dest='nodes', nargs="*",
                        help='Explicit list of nodes to connect to. Supply multiple values for multiple nodes. '
                             'Useful if the nodes are not accessed using their cluster hostnames '
                             '(e.g. support using port-forwarding in Capella)')
    parser.add_argument('-s', '--secure', dest='secure', action="store_true",
                        help='Default to connect to nodes using HTTPS and secure ports if these are not'
                             'explicitly specified in the -c or -n options. '
                             'Only applicable if connecting to a live cluster')
    parser.add_argument("--backup-archive-path", dest='backup_archive_path',
                        help="Path to backup archive")
    parser.add_argument('--cbmstatparser-path', dest='cbmstatparser_bin',
                        help='path to cbmstatparser binary if it\'s not available on $PATH')
    parser.add_argument("--verbose", dest='verbose', action='store_true',
                        default=False, help="verbose output")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.grafana_install_path:
        grafana_bin = os.path.join(args.grafana_install_path, 'bin', 'grafana-server')
        if not os.path.isfile(grafana_bin):
            logging.error('No Grafana binary found in specified installation path: {}'.
                          format(grafana_bin))
            sys.exit(1)
        if not os.access(grafana_bin, os.X_OK):
            logging.error('Grafana binary is not executable: {}'.format(grafana_bin))
            sys.exit(1)
        logging.info('using Grafana binary: {}'.format(grafana_bin))
        if args.grafana_home_path is None:
            args.grafana_home_path = os.path.join(args.grafana_install_path, 'share', 'grafana')
    else:
        grafana_bin = 'grafana-server'

    if args.grafana_home_path is None:
        args.grafana_home_path = grafana_home_default

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

    nodes = []
    for node in (args.nodes if args.nodes else []):
        nodes.extend(node.split(","))

    live_cluster = args.cluster or nodes
    if live_cluster and args.backup_archive_path:
        logging.error("--cluster/--nodes and --backup-archive-path are mutually exclusive options")
        sys.exit(1)

    # Prometheus binary validation
    prometheus_bin = PROMETHEUS_BIN
    if args.prom_bin:
        prometheus_bin = args.prom_bin
    if not live_cluster and not is_executable_file(prometheus_bin):
        logging.error('Invalid prometheus executable path: {}'.format(prometheus_bin))
        sys.exit(1)
    cbstats.Source.PROMETHEUS_BIN = prometheus_bin

    run_promtimer(
        grafana_bin=grafana_bin,
        grafana_home_path=args.grafana_home_path,
        grafana_port=args.grafana_port,
        secure=args.secure,
        cluster=args.cluster,
        nodes=nodes,
        user=args.user,
        password=args.password,
        buckets=args.buckets.split(',') if args.buckets else [],
        backup_archive_path=args.backup_archive_path,
        cbmstatparser_path=args.cbmstatparser_bin if args.cbmstatparser_bin else CBMSTATPARSER_BIN,
        refresh=args.refresh if args.refresh else '',
        dont_open_browser=args.dont_open_browser)


if __name__ == '__main__':
    parse_args_validate_and_run()
