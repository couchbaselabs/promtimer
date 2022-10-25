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

import os
import json
import logging
import datetime
import re

# local imports
import util

FILENAME = 'events.log'
HEADERS = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
}
EVENTS_START = {
    'rebalance_start': 'rebalance',
    'failover_start': 'failover',
    'graceful_failover_start': 'graceful_failover',
}
EVENTS_END = {
    'rebalance_finish': 'rebalance',
    'failover_finish': 'failover',
    'graceful_failover_finish': 'graceful_failover',
}
EVENT_TAGS = {
    'analytics_index_created': 'success',
    'analytics_index_dropped': 'warning',

    'backup_removed': 'warning',
    'backup_paused': 'warning',
    'backup_resumed': 'info',
    'backup_plan_created': 'success',
    'backup_plan_deleted': 'warning',
    'backup_repo_created': 'success',
    'backup_repo_deleted': 'warning',
    'backup_repo_imported': 'success',
    'backup_repo_archived': 'success',

    'rebalance_start': 'info',
    'rebalance_finish': 'info',

    'failover_start': 'warning',
    'failover_finish': 'warning',

    'graceful_failover_start': 'info',
    'graceful_failover_finish': 'info',

    'node_joined': 'success',
    'node_went_down': 'warning',

    'fts_index_created': 'success',
    'fts_index_dropped': 'warning',

    'index_created': 'success',
    'index_deleted': 'warning',

    'bucket_created': 'success',
    'bucket_deleted': 'warning',
    'bucket_updated': 'info',
    'bucket_flushed': 'warning',

    'data_lost': 'failure',
    'server_error': 'failure',
    'sigkill_error': 'failure',
    'lost_connection_to_server': 'failure',

    'XDCR_replication_create_started': 'info',
    'XDCR_replication_remove_started': 'info',
    'XDCR_replication_create_failed': 'failure',
    'XDCR_replication_create_successful': 'success',
    'XDCR_replication_created': 'success',
    'XDCR_replication_remove_failed': 'failure',
    'XDCR_replication_remove_successful': 'success',
}
ANNOTATIONS_API_PATH = 'api/annotations'


def get_existing_annotations(host_url):
    response = util.execute_request(host_url, ANNOTATIONS_API_PATH, retries=5)
    payload = response.read()
    if payload is not None:
        logging.info('Successfully connected to Grafana')
        try:
            return json.loads(payload)
        except json.decoder.JSONDecodeError as err:
            logging.error('Error decoding JSON response: {} for payload {}'.format(err, payload))
    else:
        logging.error('Unable to connect to Grafana, skipping annotation adding')
    return None


def post_annotation(top_level_url, data):
    payload = json.dumps(data).encode('utf-8')
    response = util.execute_request(top_level_url,
                                    ANNOTATIONS_API_PATH,
                                    method='POST',
                                    data=payload,
                                    headers=HEADERS)
    return response


def parse_event_date(date_repr):
    if type(date_repr) == int:
        return datetime.datetime.fromtimestamp(date_repr / 1000)
    # event log dates are in the following form: 2021-05-08T05:43:57.894-07:00
    return datetime.datetime.strptime(date_repr, '%Y-%m-%dT%H:%M:%S.%f%z')


def create_annotation(timestamp, text, end_timestamp=None, extra_text=None, tags=None):
    if extra_text:
        text = '{}: {}'.format(text, extra_text)
    result = {'time': timestamp,
              'text': text}
    if tags:
        result['tags'] = tags
    if end_timestamp:
        result['timeEnd'] = end_timestamp
    return result


def concat(*args):
    result = ''
    for arg in args:
        if arg:
            result = '{}\n{}'.format(result, arg)
    return result


def parse_events(events):
    result = []
    ongoing_events = {}
    for event in events:
        event_type = event.get('event_type')
        tags = event.get('tags')
        event_timestamp = event['timestamp']
        unix_time_ms = int(parse_event_date(event_timestamp).timestamp() * 1000)
        event['timestamp_ms'] = unix_time_ms
        if not tags:
            tags = EVENT_TAGS.get(event_type)
            if isinstance(tags, list):
                tags = tags[:]
            elif tags:
                tags = [tags]
        if event_type is None or tags is None:
            logging.debug('Skipping event: {}'.format(event['text']))
            continue
        elif event_type in EVENTS_START:
            ongoing_events[EVENTS_START[event_type]] = event
            continue
        else:
            if event_type in EVENTS_END and EVENTS_END[event_type] in ongoing_events:
                start_event = ongoing_events.pop(EVENTS_END[event_type])
                extra_text = concat(start_event.get('extra_text'),
                                    event.get('extra_text'))
                data = create_annotation(timestamp=start_event['timestamp_ms'],
                                         text=EVENTS_END[event_type],
                                         end_timestamp=unix_time_ms,
                                         extra_text=extra_text,
                                         tags=tags)
            else:
                data = create_annotation(timestamp=unix_time_ms,
                                         text=event_type,
                                         extra_text=event.get('extra_text'),
                                         tags=tags)
        logging.debug('append data: {}'.format(data))
        result.append(data)
    for event_type in ongoing_events:
        event = ongoing_events[event_type]
        tags = event.get('tags')
        if tags:
            tags = tags + ['unfinished']
        else:
            tags = ['unfinished']
        data = create_annotation(timestamp=event['timestamp_ms'],
                                 text=event_type + ' (no end time)',
                                 extra_text=event.get('extra_text'),
                                 tags=tags)
        result.append(data)
        logging.error('Could not find {} event end time! '
                      'Adding start time...'.format(event['event_type']))
    return result


def post_events(top_level_url, events):
    for event in events:
        post = post_annotation(top_level_url, event)
        logging.debug('{} - {} - {} - {}'.format(json.loads(post.read()),
                                                 event['time'],
                                                 event['text'],
                                                 event['tags']))


def events_log_reader(filename):
    with open(filename, 'r') as file:
        for line in file:
            event = json.loads(line)
            yield event


USER_LOGS_REGEX_MAP = {
    r'Starting rebalance.*KeepNodes(.*)EjectNodes': {
        'type': 'rebalance_start',
        'extra_text': 'Starting rebalance\nKeep nodes: {0}',
        'tags': ['topology']
    },
    r'Rebalance completed successfully': {
        'type': 'rebalance_finish',
        'extra_text': '\nCompleted successfully',
        'tags': ['info', 'topology']
    },
    r'Rebalance stopped by user': {
        'type': 'rebalance_finish',
        'extra_text': '\nStopped by user',
        'tags': ['topology']
    },
    r'Rebalance exited with reason (.*)\n': {
        'type': 'rebalance_finish',
        'extra_text': '\nRebalance exited with reason:\n{0}',
        'tags': ['topology']
    },
    r'Starting failover of nodes (.*). Operation Id': {
        'type': 'failover_start',
        'extra_text': '\nStarted failing over:\n{0}',
        'tags': ['warning', 'topology']
    },
    r'Failover completed successfully': {
        'type': 'failover_finish',
        'extra_text': '\nFailover completed successfully\n',
        'tags': ['warning', 'topology']
    },
    r'Starting graceful failover of nodes (.*). Operation Id': {
        'type': 'graceful_failover_start',
        'extra_text': '\nStarted gracefully failing over:\n{0}',
        'tags': ['info', 'topology']
    },
    r'Graceful failover completed successfully': {
        'type': 'graceful_failover_finish',
        'extra_text': '\nGraceful failover completed successfully',
        'tags': ['info', 'topology']
    },
    r'Created bucket \"(\S+)\" of type: (\S+)': {
        'type': 'bucket_created',
        'extra_text': '\nname: {0}, type:{1}',
        'tags': ['info', 'buckets']
    },
    r'Deleted bucket \"(\S+)\"': {
        'type': 'bucket_deleted',
        'extra_text': '\nname: {0}',
        'tags': ['info', 'buckets']
    }
}


def decorate_user_logs(event_logs):
    re_map = {}
    for pattern, tag in USER_LOGS_REGEX_MAP.items():
        re_map[re.compile(pattern, re.M | re.S)] = tag
    for event in event_logs:
        event['timestamp'] = event['tstamp']
        text = event['text']
        for regex in re_map:
            result = regex.search(text)
            if result:
                map_obj = re_map[regex]
                event['event_type'] = map_obj['type']
                extra_text = map_obj.get('extra_text')
                if extra_text:
                    event['extra_text'] = extra_text.format(*result.groups())
                tags = map_obj.get('tags')
                if tags:
                    event['tags'] = tags
                break
        yield event


def filter_existing(existing, proposed_new):
    result = []
    existing_map = {}
    for annotation in existing:
        existing_map[annotation['time']] = annotation
    for annotation in proposed_new:
        exists = existing_map.get(annotation['time'])
        if not exists or exists['text'] != annotation['text']:
            result.append(annotation)
    return result


def create_annotations(grafana_port, events):
    top_level_url = 'http://localhost:{}'.format(grafana_port)
    parsed = parse_events(events)
    if parsed:
        logging.info('Potential annotations: {}'.format(len(parsed)))
        existing = get_existing_annotations(top_level_url)
        if existing:
            parsed = filter_existing(existing, parsed)
        post_events(top_level_url, parsed)
        logging.info('Annotations added: {}'.format(len(parsed)))
    else:
        logging.info('No annotations to add')


def get_and_create_annotations(grafana_port, stats_sources, consult_events_log):
    events = []
    if consult_events_log:
        if os.path.isfile(FILENAME):
            events = events_log_reader(FILENAME)
    if not events:
        first = stats_sources[0]
        log_entries = first.get_my_user_log()
        events = decorate_user_logs(log_entries)
    create_annotations(grafana_port, events)
