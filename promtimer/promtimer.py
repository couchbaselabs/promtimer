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

ROOT_DIR = path.join(path.dirname(__file__), '..')
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

def start_prometheuses(cbcollects, base_port, log_dir):
    nodes = []
    for i, cbcollect in enumerate(cbcollects):
        log_path = path.join(log_dir, 'prom-{}.log'.format(i))
        args = [PROMETHEUS_BIN,
                '--config.file', path.join(ROOT_DIR, 'noscrape.yml'),
                '--storage.tsdb.path', path.join(cbcollect, 'stats_snapshot'),
                '--storage.tsdb.retention.time', '10y',
                '--web.listen-address', '0.0.0.0:{}'.format(base_port + i)]
        print('starting node', i)
        node = start_process(args, log_path)
        nodes.append(node)

    return nodes

def poll_processes(processes, count=-1):
    check = 0
    while count < 0 or check < count:
        for p in processes:
            result = p.poll()
            if result is not None:
                return result
        time.sleep(0.1)
        check += 1

def get_data_source_template():
    with open(path.join(ROOT_DIR, 'data-source.yaml'), 'r') as file:
        return file.read()

def find_template_parameter(string, parameter, start_idx=0):
    to_find = '{' + parameter + '}'
    idx = string.find(to_find, start_idx)
    if idx <= 0:
        return idx
    if string[idx - 1] == '{' and string[idx + len(to_find)] == '}':
        return -1
    return idx

def replace_template_parameter(string, to_find, to_replace):
    idx = find_template_parameter(string, to_find)
    if idx < 0:
        return string
    find_len = len(to_find)
    result = []
    prev_idx = 0
    while idx >= 0:
        result.append(string[prev_idx:idx])
        result.append(to_replace)
        prev_idx = idx + find_len + 2
        idx = find_template_parameter(string, to_find, prev_idx)
    result.append(string[prev_idx:])
    return ''.join(result)

def replace(string, replacement_map):
    for k, v in replacement_map.items():
        string = replace_template_parameter(string, k, v)
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
        with open(path.join(get_dashboards_dir(), 'dashboards.yaml'), 'w') as file_to_write:
            file_to_write.write(contents)

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

def metaify_template_string(template_string, meta):
    template = json.loads(template_string)
    merge_meta_into_template(template, meta)
    return json.dumps(template)

def make_targets(target_metas, template_params):
    result = []
    for target_meta in target_metas:
        result += make_dashboard_part(target_meta, template_params)
    return result

def add_targets_to_panel(panel, targets):
    for i, target in enumerate(targets):
        target['refId'] = chr(65 + i)
        panel['targets'].append(target)


def get_all_param_value_combinations(template_params):
    if not template_params:
        return []
    head = template_params[0]
    rest = template_params[1:]
    rest_permutations = get_all_param_value_combinations(rest)
    result = []
    for value in head['values']:
        head_value = ({'type': head['type'], 'value': value},)
        if not rest_permutations:
            result.append(head_value)
        else:
            for rest_permutation in rest_permutations:
                result.append(head_value + rest_permutation)
    return result

def index(alist, predicate):
    for i, element in enumerate(alist):
        if predicate(element):
            return i
    return -1

def make_and_add_targets(panel, panel_meta, template_params):
    targets = make_targets(panel_meta['_targets'], template_params)
    add_targets_to_panel(panel, targets)

def make_dashboard_part(part_meta, template_params, sub_part_function=None):
    base_part = part_meta['_base']
    part_template = get_template(base_part)
    part_template = metaify_template_string(part_template, part_meta)

    template_params_to_expand = [
        p for p in template_params if
        find_template_parameter(part_template, p['type']) >= 0]

    combinations = get_all_param_value_combinations(template_params_to_expand)
    result = []
    if combinations:
        for combination in combinations:
            replacements = {}
            sub_template_params = template_params[:]
            for param in combination:
                param_type = param['type']
                param_value = param['value']
                replacements[param_type] = param_value
                idx = index(sub_template_params, lambda x: x['type'] == param_type)
                sub_template_params[idx] = {'type': param_type, 'values': param_value}
            logging.debug('replacements:{}'.format(replacements))
            logging.debug('sub_template_params:{}'.format(sub_template_params))
            part_string = replace(part_template, replacements)
            part = json.loads(part_string)
            if sub_part_function:
                sub_part_function(part, part_meta, template_params)
            if part not in result:
                result.append(part)
    else:
        part_string = replace(part_template, {})
        part = json.loads(part_string)
        if sub_part_function:
            sub_part_function(part, part_meta, template_params)
        if part not in result:
            result.append(part)
    return result

def make_panels(panel_metas, template_params):
    result = []
    for panel_meta in panel_metas:
        result += make_dashboard_part(panel_meta, template_params,
                                      make_and_add_targets)
    return result

def maybe_substitute_templating_variables(dashboard, template_params):
    template_params = [p.copy() for p in template_params]
    dashboard_template = dashboard.get('templating')
    if dashboard_template:
        templating_list = dashboard_template.get('list')
        for templating in templating_list:
            variable = templating['name']
            for template_param in template_params:
                if template_param['type'] == 'data-source-name' and \
                    templating['type'] == 'datasource':
                    template_param['values'] = ['$' + variable]
                if template_param['type'] == 'bucket' and \
                    templating['type'] == 'custom':
                    template_param['values'] = ['$' + variable]
    return template_params

def maybe_expand_templating(dashboard, template_params):
    dashboard_template = dashboard.get('templating')
    logging.debug('dashboard_tempate:{}'.format(dashboard_template))
    if dashboard_template:
        templating_list = dashboard_template.get('list')
        logging.debug('templating_list:{}'.format(templating_list))
        for templating in templating_list:
            for template_param in template_params:
                if template_param['type'] == 'bucket' and \
                                templating['type'] == 'custom':
                    options = templating['options']
                    option_template = options.pop()
                    option_string = json.dumps(option_template)

                    logging.debug('options:{}'.format(options))
                    logging.debug('option_template:{}'.format(option_template))
                    logging.debug('option_string:{}'.format(option_string))
                    logging.debug('template_params:{}'.format(template_params))
                    for idx, value in enumerate(template_param['values']):
                        option = replace(option_string, {'bucket': value})
                        option_json = json.loads(option)
                        if idx == 0:
                            option_json['selected'] = True
                            templating['current'] = option_json
                        options.append(option_json)


def make_dashboard(dashboard_meta, template_params, min_time, max_time):
    replacements = {'dashboard-from-time': min_time.isoformat(),
                    'dashboard-to-time': max_time.isoformat()}
    template_string = get_template(dashboard_meta['_base'])
    template_string = metaify_template_string(template_string, dashboard_meta)
    dashboard_string = replace(template_string, replacements)
    logging.debug('dashboard_string:{}'.format(dashboard_string))
    dashboard = json.loads(dashboard_string)
    maybe_expand_templating(dashboard, template_params)
    template_params = maybe_substitute_templating_variables(dashboard, template_params)
    logging.debug('make_dashboard: title:{}, template_params {}'.format(
        dashboard_meta['title'], template_params))
    panel_id = 0
    panels = make_panels(dashboard_meta['_panels'], template_params)
    for i, panel in enumerate(panels):
        panel = panels[i]
        panel['gridPos']['w'] = 12
        panel['gridPos']['h'] = 12
        panel['gridPos']['x'] = (i % 2) * 12
        panel['gridPos']['y'] = int(i / 2) * 12
        panel['id'] = panel_id
        panel_id += 1
        dashboard['panels'].append(panel)
    return dashboard

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
        dashboard = make_dashboard(meta, template_params, min_time, max_time)
        file_name = meta['title'].replace(' ', '-').lower() + '.json'
        with open(path.join(get_dashboards_dir(), file_name), 'w') as file:
            file.write(json.dumps(dashboard, indent=2))

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
    for fmt in formats:
        result = try_get_data_source_names(cbcollect_dirs, regex, fmt)
        if result:
            return result
    return cbcollect_dirs

def prepare_grafana(grafana_port, prometheus_base_port, cbcollect_dirs, buckets, times):
    os.makedirs(GRAFANA_DIR, exist_ok=True)
    os.makedirs(get_dashboards_dir(), exist_ok=True)
    os.makedirs(get_plugins_dir(), exist_ok=True)
    os.makedirs(get_notifiers_dir(), exist_ok=True)
    data_sources = get_data_source_names(cbcollect_dirs)
    make_custom_ini(grafana_port)
    make_home_dashboard()
    make_data_sources(data_sources, prometheus_base_port)
    make_dashboards_yaml()
    make_dashboards(data_sources, buckets, times)

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
    args = parser.parse_args()

    os.makedirs(GRAFANA_DIR, exist_ok=True)
    logging.basicConfig(filename=path.join('.grafana','promtimer.log'),
                        level=logging.DEBUG)

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

    processes = start_prometheuses(cbcollects, prometheus_base_port, GRAFANA_DIR)
    processes.append(start_grafana(args.grafana_home_path))

    time.sleep(0.1)
    result = poll_processes(processes, 1)
    if result is None:
        open_browser(grafana_port)
        poll_processes(processes)

if __name__ == '__main__':
    main()
