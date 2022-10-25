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

def find_parameter(string, parameter, start_idx=0):
    to_find = '{' + parameter + '}'
    idx = string.find(to_find, start_idx)
    if idx <= 0:
        return idx
    if string[idx - 1] == '{' and string[idx + len(to_find)] == '}':
        return -1
    return idx


def replace_parameter(string, to_find, to_replace):
    idx = find_parameter(string, to_find)
    if idx < 0:
        return string
    find_len = len(to_find)
    result = []
    prev_idx = 0
    while idx >= 0:
        result.append(string[prev_idx:idx])
        result.append(to_replace)
        prev_idx = idx + find_len + 2
        idx = find_parameter(string, to_find, prev_idx)
    result.append(string[prev_idx:])
    return ''.join(result)


def replace(string, replacement_map):
    for k, v in replacement_map.items():
        string = replace_parameter(string, k, v)
    return string
