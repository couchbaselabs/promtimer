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

from os import path
import time
import json
from dateutil import parser as dateparser
import urllib.request

ANNOTS_URL = 'http://localhost:13300/api/annotations'
ANNOTS_HEADERS = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
}
ANNOTS_EVENTS_START = {
    'rebalance_start': 'rebalance',
}
ANNOTS_EVENTS_END = {
    'rebalance_finish': 'rebalance',
}
ANNOTS_EVENT_TAGS = {
    'dataset_created': 'success',
    'dataset_dropped': 'warning',
    'analytics_index_created': 'success',
    'analytics_index_dropped': 'warning',

    'task_finished': 'success',
    'task_started': 'info',
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

    'eventing_function_deployed': 'success',
    'eventing_function_undeployed': 'warning',

    'fts_index_created': 'success',
    'fts_index_dropped': 'warning',

    'index_created': 'success',
    'index_deleted': 'warning',
    'indexer_active': 'info',
    'index_built': 'info',

    'bucket_created': 'success',
    'bucket_deleted': 'warning',
    'bucket_updated': 'info',
    'bucket_flushed': 'warning',

    'dropped_ticks': 'info',
    'data_lost': 'failure',
    'server_error': 'failure',
    'sigkill_error': 'failure',
    'lost_connection_to_server': 'failure',

    'LDAP_settings_modified': 'info',
    'password_policy_changed': 'info',
    'group_added': 'success',
    'group_deleted': 'warning',
    'user_added': 'success',
    'user_deleted': 'warning',

    'XDCR_replication_create_started': 'info',
    'XDCR_replication_remove_started': 'info',
    'XDCR_replication_create_failed': 'failure',
    'XDCR_replication_create_successful': 'success',
    'XDCR_replication_created': 'success',
    'XDCR_replication_remove_failed': 'failure',
    'XDCR_replication_remove_successful': 'success',
}

def retry_get(url, retries):
    req = urllib.request.Request(url=url, data=None)
    success = False
    get = None
    while (not success) and (retries > 0):
        try:
            get = urllib.request.urlopen(req).read()
            success = True
        except:
            print('Failed to connect to Grafana, retrying...',retries,'retries left')
            retries -= 1
            time.sleep(0.5)
    return get

def create_annotations():
    annotations_json = retry_get(ANNOTS_URL, 5)
    if annotations_json is not None:
        print('Successfully connected to Grafana')
        annotations_json = json.loads(annotations_json)
        if len(annotations_json) > 0:
            print('Found existing annotations, skipping annotation adding')
        else:
            if not path.isfile('events.log'):
                print('No events.log, skipping annotation adding')
            else:
                print('Adding annotations from events.log')
                ongoing_events = {}
                file = open('events.log', 'r')
                for line in file:
                    event = json.loads(line)
                    event_timestamp = event['timestamp']
                    event_type = event['event_type']
                    unix_time_ms = int(dateparser.parse(event_timestamp).timestamp()*1000)
                    try:
                        tag = ANNOTS_EVENT_TAGS[event_type]
                    except KeyError:
                        tag = 'info'
                    if event_type in ANNOTS_EVENTS_START:
                        ongoing_events[ANNOTS_EVENTS_START[event_type]] = unix_time_ms
                        continue
                    elif event_type in ANNOTS_EVENTS_END and ANNOTS_EVENTS_END[event_type] in ongoing_events:
                        data = {
                            'time': ongoing_events[ANNOTS_EVENTS_END[event_type]],
                            'timeEnd': unix_time_ms,
                            'text': ANNOTS_EVENTS_END[event_type],
                            'tags': [
                                'kv',
                                tag,
                            ],
                        }
                    else:
                        data = {
                            'time': unix_time_ms,
                            'text': event_type,
                            'tags': [
                                'kv',
                                tag,
                            ],
                        }
                    payload = json.dumps(data).encode('utf-8')
                    req = urllib.request.Request(url=ANNOTS_URL, data=payload, headers=ANNOTS_HEADERS)
                    post = urllib.request.urlopen(req).read()
                    print(json.loads(post), '-', event_timestamp, '-', data['text'], '-', data['tags'])
    else:
        print('Unable to connect to Grafana, skipping annotation adding')