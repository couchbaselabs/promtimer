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
from typing import Any

# Local Imports
import util
import templating
from templating import Parameter


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


def make_dashboard_part(
        part_meta: dict[str, Any],
        template_params: list[Parameter.ValueList],
        sub_part_function=None):
    base_part = part_meta['_base']
    part_template = get_template(base_part)
    part_template = metaify_template_string(part_template, part_meta)
    template_params_to_expand = Parameter.find_params_in_string(part_template,
                                                                template_params)
    logging.debug('template_params_to_expand:{}'.format(template_params_to_expand))
    combinations: list[list[Parameter.Value]] = \
        templating.make_cartesian_product(template_params_to_expand)
    result = []
    logging.debug('part_template:{}'.format(part_template))
    logging.debug('template_params:{}'.format(template_params))
    logging.debug('combinations:{}'.format(combinations))
    if combinations:
        for combination in combinations:
            sub_template_params = template_params[:]
            for param in combination:
                idx = util.index(sub_template_params, lambda p: p[0] == param[0])
                sub_template_params[idx] = (param[0], [param[1]])
            logging.debug('sub_template_params:{}'.format(sub_template_params))
            part_string = Parameter.replace_all(combination, part_template)
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


def make_and_add_targets(panel, panel_meta, template_params):
    if '_targets' in panel_meta:
        targets = make_targets(panel_meta['_targets'], template_params)
        add_targets_to_panel(panel, targets)


def make_panels(panel_metas: list[dict[str, Any]],
                template_params: list[Parameter.ValueList]):
    result = []
    for panel_meta in panel_metas:
        result += make_dashboard_part(panel_meta,
                                      template_params,
                                      make_and_add_targets)
    return result


def maybe_substitute_templating_variables(
        dashboard,
        template_params: list[Parameter.ValueList]):
    """
    Returns a new list of template parameters, substituting the templating variable
    name for the parameter value for datasource parameters, if the dashboard uses
    datasource templating.
    :param dashboard: the dashboard to check
    :param template_params: the set of template parameters to use
    :return: a list of template parameters, with substitutions made if needed
    """
    template_params = template_params[:]
    dashboard_template = dashboard.get('templating')
    if dashboard_template:
        templating_list = dashboard_template.get('list')
        for item in templating_list:
            variable = item['name']
            for idx, param_values in enumerate(template_params):
                param = param_values[0]
                pname = param.name()
                should_substitute = \
                    (item['type'] == 'datasource' and pname == 'data-source') or \
                    (item['type'] == 'custom' and pname == 'bucket' and item['name'] == 'bucket')
                if should_substitute:
                    value = param.make_single_valued_value(f'${variable}')
                    template_params[idx] = (param, [value])
    return template_params


def maybe_expand_templating(
        dashboard: dict[str, Any],
        template_params: list[Parameter.ValueList]):
    """
    Adds options to custom template parameters of type 'bucket', if present.
    :param dashboard: the dashboard to update
    :param template_params: the template parameters to use
    """
    dashboard_template = dashboard.get('templating')
    logging.debug('dashboard_template:{}'.format(dashboard_template))
    bucket_param = Parameter.find_parameter_by_name('bucket', template_params)
    if not bucket_param:
        return
    if dashboard_template:
        templating_list = dashboard_template.get('list')
        logging.debug('templating_list:{}'.format(templating_list))
        for element in templating_list:
            if element['type'] == 'custom' and element['name'] == 'bucket':
                options = element['options']
                option_template = options.pop()
                option_string = json.dumps(option_template)
                logging.debug('options:{}'.format(options))
                logging.debug('option_template:{}'.format(option_template))
                logging.debug('option_string:{}'.format(option_string))
                logging.debug('template_params:{}'.format(template_params))
                # Grafana versions < 12 require the different values of the templating
                # variable to be specified as options in the option list
                for idx, value in enumerate(bucket_param[1]):
                    option = templating.replace(option_string, {'bucket': value})
                    option_json = json.loads(option)
                    if idx == 0:
                        option_json['selected'] = True
                        element['current'] = option_json
                    options.append(option_json)
                escaped = [b.replace(',', '\\,') for b in bucket_param[1]]
                # Grafana 12 requires the query to be set as a comma-separated list
                # of the different templating variable options
                element['query'] = ','.join(escaped)


def make_dashboard(dashboard_meta,
                   template_params: list[Parameter.ValueList],
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
