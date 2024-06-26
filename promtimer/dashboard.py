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

from os import path
import json
import logging

# Local Imports
import util
import templating


def get_template(name):
    with open(path.join(util.get_root_dir(), 'templates', name + '.json'), 'r') as file:
        return file.read()


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


def make_dashboard_part(part_meta, template_params, sub_part_function=None):
    base_part = part_meta['_base']
    part_template = get_template(base_part)
    part_template = metaify_template_string(part_template, part_meta)

    template_params_to_expand = [
        p for p in template_params if
        templating.find_parameter(part_template, p['type']) >= 0]

    combinations = get_all_param_value_combinations(template_params_to_expand)
    result = []
    logging.debug('part_template:{}'.format(part_template))
    logging.debug('template_params:{}'.format(template_params))
    logging.debug('combinations:{}'.format(combinations))
    if combinations:
        for combination in combinations:
            replacements = {}
            sub_template_params = template_params[:]
            for param in combination:
                param_type = param['type']
                param_value = param['value']
                replacements[param_type] = param_value
                idx = util.index(sub_template_params, lambda x: x['type'] == param_type)
                sub_template_params[idx] = {'type': param_type, 'values': [param_value]}
            logging.debug('replacements:{}'.format(replacements))
            logging.debug('sub_template_params:{}'.format(sub_template_params))
            part_string = templating.replace(part_template, replacements)
            part = json.loads(part_string)
            if sub_part_function:
                sub_part_function(part, part_meta, sub_template_params)
            if part not in result:
                result.append(part)
    else:
        part_string = templating.replace(part_template, {})
        part = json.loads(part_string)
        if sub_part_function:
            sub_part_function(part, part_meta, template_params)
        if part not in result:
            result.append(part)
    return result


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


def make_and_add_targets(panel, panel_meta, template_params):
    if '_targets' in panel_meta:
        targets = make_targets(panel_meta['_targets'], template_params)
        add_targets_to_panel(panel, targets)


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
    logging.debug('dashboard_template:{}'.format(dashboard_template))
    if dashboard_template:
        templating_list = dashboard_template.get('list')
        logging.debug('templating_list:{}'.format(templating_list))
        for element in templating_list:
            for template_param in template_params:
                if template_param['type'] == 'bucket' and \
                                element['type'] == 'custom':
                    options = element['options']
                    option_template = options.pop()
                    option_string = json.dumps(option_template)
                    logging.debug('options:{}'.format(options))
                    logging.debug('option_template:{}'.format(option_template))
                    logging.debug('option_string:{}'.format(option_string))
                    logging.debug('template_params:{}'.format(template_params))
                    for idx, value in enumerate(template_param['values']):
                        option = templating.replace(option_string, {'bucket': value})
                        option_json = json.loads(option)
                        if idx == 0:
                            option_json['selected'] = True
                            element['current'] = option_json
                        options.append(option_json)


def make_dashboard(dashboard_meta,
                   template_params,
                   min_time_string,
                   max_time_string,
                   refresh,
                   timezone):
    replacements = {'dashboard-from-time': min_time_string,
                    'dashboard-to-time': max_time_string,
                    'dashboard-refresh': refresh,
                    'dashboard-timezone': timezone}
    template_string = get_template(dashboard_meta['_base'])
    template_string = metaify_template_string(template_string, dashboard_meta)
    dashboard_string = templating.replace(template_string, replacements)
    logging.debug('make_dashboard: dashboard_string:{}'.format(dashboard_string))
    dashboard = json.loads(dashboard_string)
    maybe_expand_templating(dashboard, template_params)
    template_params = maybe_substitute_templating_variables(dashboard, template_params)
    logging.debug('make_dashboard: title:{}, template_params {}'.format(
        dashboard_meta['title'], template_params))
    panel_id = 0
    current_y = 0
    panel_row_width = 0
    panel_row_height = 0
    panels = make_panels(dashboard_meta['_panels'], template_params)
    for i, panel in enumerate(panels):
        panel = panels[i]
        if panel['gridPos']['w'] > (24 - panel_row_width):
            # If the next panel won't fit, move it to the next row of panels
            current_y = current_y + panel_row_height
            panel_row_height = 0
            panel_row_width = 0
        if panel['gridPos']['h'] > panel_row_height:
            # If the current panel is the tallest, update row height
            panel_row_height = panel['gridPos']['h']
        panel['gridPos']['x'] = panel_row_width
        panel['gridPos']['y'] = current_y
        panel_row_width += panel['gridPos']['w']
        panel['id'] = panel_id
        panel_id += 1
        dashboard['panels'].append(panel)
    return dashboard
