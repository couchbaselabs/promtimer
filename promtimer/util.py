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

import subprocess
import atexit
import time
from os import path

ROOT_DIR = path.join(path.dirname(__file__), '..')

def get_root_dir():
    return ROOT_DIR

def index(alist, predicate):
    for i, element in enumerate(alist):
        if predicate(element):
            return i
    return -1

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

def kill_node(process):
    try:
        process.kill()
    except OSError:
        pass

def start_process(args, log_filename, cwd=None):
    log_file = open(log_filename, 'a')
    process = subprocess.Popen(args,
                               stdin=None,
                               cwd=cwd,
                               stdout=log_file,
                               stderr=log_file)
    atexit.register(lambda: kill_node(process))
    return process

def poll_processes(processes, count=-1):
    check = 0
    while count < 0 or check < count:
        for p in processes:
            result = p.poll()
            if result is not None:
                return result
        time.sleep(0.1)
        check += 1




