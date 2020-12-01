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




