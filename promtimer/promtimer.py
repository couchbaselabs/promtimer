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
import re
import webbrowser
import logging
import sys
import zipfile
import pathlib

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
STATS_SNAPSHOT_DIR_NAME = 'stats_snapshot'
COUCHBASE_LOG = 'couchbase.log'

def make_snapshot_dir_path(candidate_cbcollect_dir):
    """
    Returns a path representing the 'stats_snapshot' directory in
    candidate_cbcollect_dir.
    :type candidate_cbcollect_dir: pathlib.Path
    :rtype: pathlib.Path
    """
    return candidate_cbcollect_dir / '{}'.format(STATS_SNAPSHOT_DIR_NAME)

def snapshot_dir_exists(candidate_cbcollect_dir):
    """
    Returns whether or not the 'stats_snapshot' directory inside
    candidate_cbcollect_dir exists.
    :type candidate_cbcollect_dir: ,lib.Path
    """
    return make_snapshot_dir_path(candidate_cbcollect_dir).exists()

def is_cbcollect_dir(candidate_path):
    """
    Returns a guess as to whether candidate_path represents a
    cbcollect directory by checking whether the 'stats_snapshot' directory exists
    inside it.
    :type candidate_path: pathlib.Path
    """
    return candidate_path.is_dir() and snapshot_dir_exists(candidate_path)

def is_executable_file(candidate_file):
    return os.path.isfile(candidate_file) and os.access(candidate_file, os.X_OK)

def find_cbcollect_dirs():
    cbcollects = sorted(glob.glob('cbcollect_info*'))
    return [f for f in cbcollects if is_cbcollect_dir(pathlib.Path(f))]

def is_stats_snapshot_file(filename):
    """
    Returns whether filename contains 'stats_snapshot' (and thus is a file we
    probably want to extract from a cbcollect zip).
    :type filename: string
    :rtype: bool
    """
    return filename.find('/{}/'.format(STATS_SNAPSHOT_DIR_NAME)) >= 0

def maybe_extract_from_zipfile(zip_file):
    """
    Extract files needed for Promtimer to run if necessary. Files needed by Promtimer are:
    * everything under the stats_snapshot directory; nothing is extracted if the
      stats_snapshot directory is already present
    * couchbase.log: extracted if not present
    """
    root = zipfile.Path(zip_file)
    for p in root.iterdir():
        if is_cbcollect_dir(p):
            stats_snapshot_exists = snapshot_dir_exists(pathlib.Path(p.name))
            logging.debug("{}/stats_snapshot exists: {}".format(p.name, stats_snapshot_exists))
            extracting = False
            for item in zip_file.infolist():
                item_path = path.join(*item.filename.split('/'))
                should_extract = False
                if is_stats_snapshot_file(item.filename):
                    should_extract = not stats_snapshot_exists
                elif item.filename.endswith(COUCHBASE_LOG):
                    should_extract = not path.exists(item_path)
                if should_extract:
                    logging.debug("zipfile item:{}, exists:{}".format(item_path, path.exists(item_path)))
                    if not extracting:
                        extracting = True
                        logging.info('extracting stats, couchbase.log from cbcollect zip:{}'
                                     .format(zip_file.filename))
                    zip_file.extract(item)

def get_cbcollect_dirs():
    zips = sorted(glob.glob('*.zip'))
    for z in zips:
        with zipfile.ZipFile(z) as zip_file:
            maybe_extract_from_zipfile(zip_file)
    return find_cbcollect_dirs()

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

def make_dashboards(stats_sources, buckets, times):
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    min_time = datetime.datetime.fromtimestamp(times[0] / 1000.0)
    max_time = datetime.datetime.fromtimestamp(times[1] / 1000.0)
    data_sources = [s.short_name() for s in stats_sources]
    template_params = \
        [{'type': 'data-source-name', 'values': data_sources},
         {'type': 'bucket', 'values': buckets}]
    meta_file_names = glob.glob(path.join(util.get_root_dir(), 'dashboards', '*.json'))
    for meta_file_name in meta_file_names:
        with open(meta_file_name, 'r') as meta_file:
            meta = json.loads(meta_file.read())
            base_file_name = path.basename(meta_file_name)
            dash = dashboard.make_dashboard(meta, template_params, min_time, max_time)
            dash['uid'] = base_file_name[:-len('.json')]
            with open(path.join(get_dashboards_dir(), base_file_name), 'w') as file:
                file.write(json.dumps(dash, indent=2))

def make_data_sources(stats_sources):
    datasources_dir = path.join(get_provisioning_dir(), 'datasources')
    os.makedirs(datasources_dir, exist_ok=True)
    template = get_data_source_template()
    for i, stats_source in enumerate(stats_sources):
        data_source_name = stats_source.short_name()
        replacement_map = {'data-source-name': data_source_name,
                           'data-source-port' : str(stats_source.port())}
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
    """
    Returns a list of names of data sources for the given list of cbcollect directories.
    This function attempts to make short names uniquely identifying each cbcollect
    directory in the given list. Frequently the node name embedded in the name of
    the cbcollect directory will be sufficient to uniquely identify the directory,
    however it may be necessary to use the full name of the directory.
    :type cbcollect_dirs: list of names of directories, there should be no duplicate
                          entries
    :rtype: list of names of data sources; if cbcollect_dirs contains no duplicates the
            returned list is guaranteed to also contain no duplicates
    """
    regex = re.compile('cbcollect_info_ns_(\d+)\@(.*)_(\d+)-(\d+)')
    formats = ['{1}', 'ns_{0}@{1}', '{1}-{2}-{3}', 'ns_{0}-{1}-{2}-{3}']
    for fmt in formats:
        result = try_get_data_source_names(cbcollect_dirs, regex, fmt)
        if result:
            return result
    return cbcollect_dirs

def prepare_grafana(grafana_port, stats_sources, buckets, times):
    os.makedirs(PROMTIMER_DIR, exist_ok=True)
    os.makedirs(PROMTIMER_LOGS_DIR, exist_ok=True)
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    os.makedirs(get_plugins_dir(), exist_ok=True)
    os.makedirs(get_notifiers_dir(), exist_ok=True)
    make_custom_ini(grafana_port)
    make_home_dashboard()
    make_data_sources(stats_sources)
    make_dashboards_yaml()
    make_dashboards(stats_sources, buckets, times)

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

def open_browser(grafana_http_port):
    url = 'http://localhost:{}/dashboards'.format(grafana_http_port)
    # Helpful for those who accidently close the browser
    logging.info('starting browser using {}'.format(url))
    try:
        # For some reason this sometimes throws an OSError with no
        # apparent side-effects. Probably related to forking processes
        webbrowser.open_new_tab(url)
    except OSError:
        logging.error("Hit `OSError` opening web browser")
        pass

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
    parser.add_argument('--buckets', dest='buckets',
                        help='comma-separated list of buckets to build bucket dashboards '
                             'for; if this option is provided, auto-detection of the '
                             'buckets by parsing couchbase.log will be skipped')
    parser.add_argument("--verbose", dest='verbose', action='store_true',
                        default=False, help="verbose output")
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
    if args.grafana_home_path is None:
        logging.error('Please specify the Grafana home directory as it '
                      'cant\'t be defaulted on this platform')
        sys.exit(1)
    if not os.path.isdir(args.grafana_home_path):
        logging.error('Invalid grafana path: {}'.format(args.grafana_home_path))
        sys.exit(1)
    logging.info('using grafana home path:{} '.format(args.grafana_home_path))

    grafana_port = args.grafana_port
    prometheus_base_port = grafana_port + 1

    cbcollects = get_cbcollect_dirs()
    if len(cbcollects) == 0:
        if os.path.isdir(STATS_SNAPSHOT_DIR_NAME):
            # Found stats directory, assume we're inside an unzip'd cbcollect
            # directory
            cbcollects.append(".")
        else:
            logging.error('No "collectinfo*.zip" files or "cbcollect_info*" '
                          'directories or "{}" directory found'.format(
                              STATS_SNAPSHOT_DIR_NAME))
            sys.exit(1)
    data_source_names = get_data_source_names(cbcollects)
    stats_sources = []
    for idx in range(len(cbcollects)):
        cbcollect_dir = cbcollects[idx]
        name = data_source_names[idx]
        source = cbstats.Source(cbcollect_dir,
                                name,
                                prometheus_base_port + idx)
        stats_sources.append(source)

    if not args.buckets:
        buckets = stats_sources[0].get_buckets()
    else:
        buckets = sorted(args.buckets.split(','))

    times = cbstats.Source.get_prometheus_min_and_max_times(stats_sources)

    prepare_grafana(grafana_port,
                    stats_sources,
                    buckets,
                    times)

    if args.prom_bin:
        global PROMETHEUS_BIN
        PROMETHEUS_BIN = args.prom_bin

    if not is_executable_file(PROMETHEUS_BIN):
        logging.error('Invalid prometheus executable path: {}'.format(
            PROMETHEUS_BIN))
        sys.exit(1)

    cbstats.Source.PROMETHEUS_BIN = PROMETHEUS_BIN
    processes = cbstats.Source.start_stats_servers(stats_sources,
                                                   PROMTIMER_LOGS_DIR)
    processes.append(start_grafana(args.grafana_home_path, grafana_port))

    time.sleep(0.1)
    result = util.poll_processes(processes, 1)
    if result is None:
        open_browser(grafana_port)
        annotations.create_annotations(grafana_port)
        util.poll_processes(processes)

if __name__ == '__main__':
    main()
