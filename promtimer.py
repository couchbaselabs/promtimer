#!/usr/bin/env python3
#
# Copyright (c) 2015 Couchbase, Inc All rights reserved.
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
import atexit
import glob
import os
from os import path
import subprocess
import time
import json
import datetime
import re
import webbrowser
import logging

ROOT_DIR = path.dirname(__file__)
PROMETHEUS_BIN = 'prometheus'
GRAFANA_DIR = '.grafana'
GRAFANA_BIN = 'grafana-server'

def start_process(args, log_filename, cwd=None):
    log_file = open(log_filename, 'a')
    process = subprocess.Popen(args,
                               stdin=None,
                               cwd=cwd,
                               stdout=log_file,
                               stderr=log_file)
    atexit.register(lambda: kill_node(process))
    return process

def kill_node(process):
    try:
        process.kill()
    except OSError:
        pass

class CBCollect:

    def __init__(self, directory_name):
        self.dir_name = directory_name

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

def start_prometheuses(cbcollects, base_port):
    nodes = []
    for i in range(len(cbcollects)):
        cbcollect= cbcollects[i]
        log_path = path.join(cbcollect, 'prom.log')
        args = [PROMETHEUS_BIN,
                '--config.file', path.join(ROOT_DIR, 'noscrape.yml'),
                '--storage.tsdb.path', path.join(cbcollect, 'stats_snapshot'),
                '--storage.tsdb.retention.time', '10y',
                '--web.listen-address', '0.0.0.0:{}'.format(base_port + i)]
        print('starting node', i)
        node = start_process(args, log_path)
        nodes.append(node)

    return nodes

def poll_processes(processes):
    while True:
        for p in processes:
            if p.poll() is not None:
                return

        time.sleep(0.1)

def get_data_source_template():
    with open(path.join(ROOT_DIR, 'data-source.yaml'), 'r') as file:
        return file.read()

def replace(string, replacement_map):
    for k, v in replacement_map.items():
        string = string.replace('{' + k + '}', v)
    return string

def get_provisioning_dir():
    return path.join(GRAFANA_DIR, 'provisioning')

def get_dashboards_dir():
    return path.join(get_provisioning_dir(), 'dashboards')

def get_plugins_dir():
    return path.join(get_provisioning_dir(), 'plugins')

def get_notifiers_dir():
    return path.join(get_provisioning_dir(), 'notifiers')

def get_custom_ini_template():
    with open(path.join(ROOT_DIR, 'custom.ini'), 'r') as file:
        return file.read()

def get_home_dashboard():
    with open(path.join(ROOT_DIR, 'home.json'), 'r') as file:
        return file.read()

def make_custom_ini(grafana_http_port):
    os.makedirs(GRAFANA_DIR, exist_ok=True)
    replacements = {'absolute-path-to-cwd': os.path.abspath('.'),
                    'grafana-http-port': str(grafana_http_port)}
    template = get_custom_ini_template()
    contents = replace(template, replacements)
    with open(path.join(GRAFANA_DIR, 'custom.ini'), 'w') as file:
        file.write(contents)

def make_home_dashboard():
    dashboard = get_home_dashboard()
    with open(path.join(GRAFANA_DIR, 'home.json'), 'w') as file:
        file.write(dashboard)

def make_dashboards_yaml():
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    with open(path.join(ROOT_DIR, 'dashboards.yaml'), 'r') as file:
        replacements = {'absolute-path-to-cwd': os.path.abspath('.')}
        contents = replace(file.read(), replacements)
        with open(path.join(get_dashboards_dir(), 'dashboards.yaml'), 'w') as file:
            file.write(contents)

def get_template(name):
    with open(path.join(ROOT_DIR, 'templates', name + '.json'), 'r') as file:
        return file.read()

def get_dashboard_metas():
    files = glob.glob(path.join(ROOT_DIR, 'dashboards', '*.json'))
    result = []
    for f in files:
        with open(f, 'r') as file:
            result.append(file.read())
    return result

def find_template_parameters(template_string):
    candidates = ['{data-source-name}']
    return [c for c in candidates    if template_string.find(c) >= 0]

def merge_meta_into_template(template, meta):
    for k in meta:
        if not k.startswith('_'):
            val = meta[k]
            if type(val) is dict:
                sub_template = template.get(k)
                if sub_template is None:
                    sub_template = {}
                    template[k] = sub_template
                merge_meta_into_template(sub_template, val)
            else:
                template[k] = val

def make_targets(target_metas, template_params):
    result = []
    for target_meta in target_metas:
        base_target = target_meta['_base']
        target_template = get_template(base_target)
        target = json.loads(target_template)
        merge_meta_into_template(target, target_meta)
        target_template = json.dumps(target)
        logging.debug('target template:{}'.format(target_template))
        for param_meta in template_params:
            param_type = param_meta['type']
            param_values = param_meta['values']
            if target_template.find('{' + param_type + '}') >= 0:
                for i in range(len(param_values)):
                    param_value = param_values[i]
                    expr = target_meta['expr']
                    replacements = {param_type: param_value,
                                        'legend': param_value + ' ' + expr}
                    logging.debug('replacements:{}'.format(replacements))
                    target_string = replace(target_template, replacements)
                    target = json.loads(target_string)
                    result.append(target)
            else:
                replacements = {'legend': ''}
                target_string = replace(target_template, replacements)
                target = json.loads(target_string)
                result.append(target)
    return result

def make_panels(panel_metas, template_params):
    result = []
    for panel_meta in panel_metas:
        base_panel = panel_meta['_base']
        panel_template = get_template(base_panel)
        for param_meta in template_params:
            param_type = param_meta['type']
            if panel_template.find('{' + param_type + '}') >= 0:
                param_values = param_meta['values']
                for param_value in param_values:
                    replacements = {param_type: param_value,
                                    'panel-title': param_value}
                    logging.debug('replacements:{}'.format(replacements))
                    panel_string = replace(panel_template, replacements)
                    panel = json.loads(panel_string)
                    targets = make_targets(panel_meta['_targets'],
                                           [{'type': 'data-source-name',
                                             'values': [param_value]}])
                    for i in range(len(targets)):
                        target = targets[i]
                        target['refId'] = chr(65 + i)
                        panel['targets'].append(target)
                    result.append(panel)
            else:
                panel_string = replace(panel_template, {})
                panel = json.loads(panel_string)
                panel['title'] = panel_meta['title']
                targets = make_targets(panel_meta['_targets'], template_params)
                for i in range(len(targets)):
                    target = targets[i]
                    target['refId'] = chr(65 + i)
                    panel['targets'].append(target)
                result.append(panel)
    return result

def make_dashboard(dashboard_meta, template_params, min_time, max_time):
    replacements = {'dashboard-from-time': min_time.isoformat(),
                    'dashboard-to-time': max_time.isoformat(),
                    'dashboard-title': dashboard_meta['title']}
    base_dashboard = dashboard_meta['_base']
    dashboard_string = replace(get_template(base_dashboard), replacements)
    dashboard = json.loads(dashboard_string)
    panel_id = 0
    panels = make_panels(dashboard_meta['_panels'], template_params)
    for i in range(len(panels)):
        panel = panels[i]
        panel['gridPos']['w'] = 12
        panel['gridPos']['h'] = 12
        panel['gridPos']['x'] = (i % 2) * 12
        panel['gridPos']['y'] = int(i / 2) * 12
        panel['id'] = panel_id
        panel_id += 1
        dashboard['panels'].append(panel)
    return dashboard

def make_dashboards(data_sources, times):
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    min_time = datetime.datetime.fromtimestamp(times[0] / 1000.0)
    max_time = datetime.datetime.fromtimestamp(times[1] / 1000.0)
    dashboard_meta_strings = get_dashboard_metas()
    for meta_string in dashboard_meta_strings:
        meta = json.loads(meta_string)
        dashboard_template = meta.get('_dashboardTemplate')
        template_params = [{'type': 'data-source-name',
                            'values': data_sources}]
        logging.debug('dashboard template:{}'.format(dashboard_template))
        if dashboard_template:
            variable = dashboard_template['variable']
            for template_param in template_params:
                if dashboard_template['type'] == template_param['type']:
                    template_param['values'] = ['$' + variable]
        dashboard = make_dashboard(meta, template_params, min_time, max_time)
        file_name = meta['title'].replace(' ', '-').lower() + '.json'
        with open(path.join(get_dashboards_dir(), file_name), 'w') as file:
            file.write(json.dumps(dashboard))

def make_data_sources(data_sources_names, base_port):
    datasources_dir = path.join(get_provisioning_dir(), 'datasources')
    os.makedirs(datasources_dir, exist_ok=True)
    template = get_data_source_template()
    for i in range(len(data_sources_names)):
        data_source_name = data_sources_names[i]
        replacement_map = {'data-source-name': data_source_name,
                           'data-source-port' : str(base_port + i)}
        filename = path.join(datasources_dir, 'ds-{}.yaml'.format(data_source_name))
        with open(filename, 'w') as file:
            file.write(replace(template, replacement_map))

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
    for format in formats:
        result = try_get_data_source_names(cbcollect_dirs, regex, format)
        if result:
            return result
    return cbcollect_dirs

def prepare_grafana(grafana_port, prometheus_base_port, cbcollect_dirs, times):
    os.makedirs(GRAFANA_DIR, exist_ok=True)
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    os.makedirs(get_plugins_dir(), exist_ok=True)
    os.makedirs(get_notifiers_dir(), exist_ok=True)
    data_sources = get_data_source_names(cbcollect_dirs)
    make_custom_ini(grafana_port)
    make_home_dashboard()
    make_data_sources(data_sources, prometheus_base_port)
    make_dashboards_yaml()
    make_dashboards(data_sources, times)

def start_grafana(grafana_home_path):
    log_path = path.join(GRAFANA_DIR, 'grafana.log')
    args = [GRAFANA_BIN,
            '--homepath', grafana_home_path,
            '--config','custom.ini']
    print('starting grafana server')
    return start_process(args, log_path, GRAFANA_DIR)

def open_browser(grafana_http_port):
    url = 'http://localhost:{}/dashboards'.format(grafana_http_port)
    try:
        # For some reason this sometimes throws an OSError with no
        # apparent side-effects. Probably related to forking processes
        webbrowser.open_new(url)
    except OSError:
        print("Hit `OSError` opening web browser")
        pass

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
    args = parser.parse_args()

    cbcollects = get_cbcollect_dirs()
    times = get_prometheus_min_and_max_times(cbcollects)

    grafana_port = args.grafana_port
    prometheus_base_port = grafana_port + 1
    prepare_grafana(grafana_port, prometheus_base_port, cbcollects, times)

    if args.prom_bin:
        global PROMETHEUS_BIN
        PROMETHEUS_BIN = args.prom_bin

    logging.basicConfig(filename=path.join('.grafana','promtimer.log'),
                        level=logging.DEBUG)

    processes = start_prometheuses(cbcollects, prometheus_base_port)
    processes.append(start_grafana(args.grafana_home_path))

    open_browser(grafana_port)
    poll_processes(processes)

if __name__ == '__main__':
    main()
