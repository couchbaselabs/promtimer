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

import os
import json
import logging
import datetime
import urllib.request

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
}
EVENTS_END = {
    'rebalance_finish': 'rebalance',
    'failover_finish': 'failover',
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
    'failover_end': 'warning',

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

def check_no_existing_annotations(host_url, path):
    response = util.get_url(host_url, path, retries=5)
    payload = response.read()
    if payload is not None:
        logging.info('Successfully connected to Grafana')
        annotations_json = json.loads(payload)
        if len(annotations_json) > 0:
            logging.info('Found existing annotations, skipping annotation adding')
            return False
        else:
            return True
    else:
        logging.error('Unable to connect to Grafana, skipping annotation adding')
        return False

def post_annotation(url, data):
    payload = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url=url, data=payload, headers=HEADERS)
    post = urllib.request.urlopen(req).read()
    return post

def parse_event_date(date_string):
    # event log dates are in the following form: 2021-05-08T05:43:57.894-07:00
    return datetime.datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S.%f%z')

def parse_events(url):
    ongoing_events = {}
    with open(FILENAME, 'r') as file:
        for line in file:
            event = json.loads(line)
            event_timestamp = event['timestamp']
            event_type = event['event_type']
            unix_time_ms = int(parse_date(event_timestamp).timestamp()*1000)
            try:
                tag = EVENT_TAGS[event_type]
                if event_type in EVENTS_START:
                    ongoing_events[EVENTS_START[event_type]] = unix_time_ms
                    continue
                elif event_type in EVENTS_END and EVENTS_END[event_type] in ongoing_events:
                    data = {
                        'time': ongoing_events[EVENTS_END[event_type]],
                        'timeEnd': unix_time_ms,
                        'text': EVENTS_END[event_type],
                        'tags': [
                            tag,
                        ],
                    }
                    ongoing_events.pop(EVENTS_END[event_type])
                else:
                    data = {
                        'time': unix_time_ms,
                        'text': event_type,
                        'tags': [
                            tag,
                        ],
                    }
                post = post_annotation(url, data)
                logging.debug('{} - {} - {} - {}'.format(json.loads(post), event_timestamp, data['text'], data['tags']))
            except KeyError:
                logging.debug('{} event type not accepted, skipping'.format(event_type))
        for event in ongoing_events:
            data = {
                'time': ongoing_events[event],
                'text': event + ' (no end time)',
                'tags': [
                    'failure',
                    'unfinished',
                ]
            }
            post = post_annotation(url, data)
            logging.error('Could not find {} event end time! Adding start time...'.format(event))
            logging.error('{} - {} - {} - {}'.format(json.loads(post), event_timestamp, data['text'], data['tags']))

def create_annotations(grafana_port):
    top_level_url = 'http://localhost:{}'.format(grafana_port)
    path = 'api/annotations'
    if check_no_existing_annotations(top_level_url, path):
        if not os.path.isfile(FILENAME):
            logging.info('No events.log, skipping annotation adding')
        else:
            logging.info('Adding annotations from events.log')

            parse_events('{}/{}'.format(top_level_url, path))
            logging.info('Annotations added')
