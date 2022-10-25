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

import subprocess
import atexit
import time
import os
import urllib.request
import ssl
import re
import logging
import copy

HTTP = 'http'
HTTPS = 'https'
ROOT_DIR = os.path.join(os.path.dirname(__file__), '..')


def get_root_dir():
    return ROOT_DIR


def index(alist, predicate):
    for i, element in enumerate(alist):
        if predicate(element):
            return i
    return -1


def kill_node(process):
    """
    Kills the supplied process
    :param process: the process to kill
    """
    try:
        process.kill()
    except OSError:
        pass


def start_process(args, log_filename, cwd=None):
    """
    Starts a process using args logging both stdout and stderr to a file by the name
    of log file_name, which is opened in append mode.
    :param args: the process arguments
    :param log_filename: the name of the log file to append to
    :param cwd: the current working directory
    :return: the process handle
    """
    if log_filename is not None:
        log_file = open(log_filename, 'a')
    else:
        log_file = subprocess.DEVNULL
    process = subprocess.Popen(args,
                               stdin=None,
                               cwd=cwd,
                               stdout=log_file,
                               stderr=log_file)
    atexit.register(lambda: kill_node(process))
    return process


class Process:
    """
    Class that captures the process handle, name and log filename
    of an executing process. The name of the process has no
    significance beyond distinguishing it from other Process
    instances.
    """

    def __init__(self, process, name='', log_filename=None):
        self._process = process
        self._name = name
        self._log_filename = log_filename

    def name(self):
        """
        :return: the name of this Process
        """
        return self._name

    def process(self):
        """
        :return: the process handle
        """
        return self._process

    def log_filename(self):
        """
        :return: the name of the file to which this process logs; None if this process
                 logs to dev null
        """
        return self._log_filename

    def set_log_filename(self, log_filename):
        """
        Sets the name of the log file that the underlying process writes to.

        :param log_filename: the name of the log file
        """
        self._log_filename = log_filename

    def poll(self):
        """
        :return: the result of polling the underlying process handle
        """
        return self._process.poll()

    @staticmethod
    def start(name, args, log_filename, cwd=None):
        """
        Starts a process using util.start_process and returns an instance of
        util.Process.

        :param name: the name associated with the process handle
        :param args: the arguments with which to start the process
        :param log_filename: the file to log to or None if the process should log to
                             dev null
        :param cwd: the current working directory or None if default
        :return: a new instance of util.Process that wraps the process handle
        """
        process = start_process(args, log_filename, cwd)
        return Process(process, name, log_filename)

    @staticmethod
    def poll_processes(processes, count=-1):
        """
        Periodically polls each of the supplied processes and exits when one of the
        polls returns a non-zero value or when the requested number of poll attempts
        is reached.

        The process that gave a non-zero poll value is returned - or None if no process
        returned a non-zero poll.

        :param processes:  the processes to poll
        :param count: the number of times to poll; if less than zero, polling continues
                      indefinitely
        :return: the process for which poll returned non-zero or None if the number of
                 requested polls is reached
        """
        check = 0
        while count < 0 or check < count:
            for p in processes:
                result = p.poll()
                if result is not None:
                    return p
            time.sleep(0.1)
            check += 1


def get_scheme(url):
    """
    :param url: the URL to check for a scheme
    :return: the scheme associated with the URL if any. Else None.
    """
    m = re.match('(https?)://', url, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


def is_https(scheme):
    """
    :param scheme: the URL scheme to check
    :return: whether or not the scheme is HTTPS
    """
    return scheme and scheme.casefold() == HTTPS


def has_secure_scheme(url):
    """
    :param url: the URL to check
    :return: whether or not url has a secure scheme (i.e. HTTPS)
    """
    return is_https(get_scheme(url))


def default_scheme(url, default):
    """
    :param url: the URL to prepend a default scheme to, if none is present
    :param default: the scheme to default to if none is present
    :return: the url with default_scheme prepended if no scheme is present.
             Else url is returned unmodified.
    """
    scheme = get_scheme(url)
    if scheme is None:
        url = '{}://{}'.format(default, url)
    return url


def execute_request(url, path, method='GET', data=None,
                    username=None, password=None, headers=None,
                    retries=0, secure=False):
    url = default_scheme(url, HTTPS if secure else HTTP)

    handlers = []
    if username is not None:
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, url, username, password)
        handlers.append(urllib.request.HTTPBasicAuthHandler(password_mgr))

    if has_secure_scheme(url):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))

    opener = urllib.request.build_opener(*handlers)
    if not path.startswith('/'):
        path = '/' + path
    url = '{}{}'.format(url, path)
    attempts = 0
    while True:
        try:
            if headers is None:
                headers = {}
            request = urllib.request.Request(url=url,
                                             method=method,
                                             data=data,
                                             headers=headers)
            response = opener.open(request)
            return response
        except urllib.request.URLError as ue:
            logging.debug('Attempting connection to {}, '
                          'retrying... {} retries left'.format(url, retries - attempts))
            attempts += 1
            if retries < 0:
                logging.warn('Failed to connect to {} after {} '
                             'attempts: {}'.format(url, attempts, ue))
                raise
            time.sleep(0.1)
    return None


_CommandOutputResults = {}


def search_command_output(command, pattern, cache=True):
    """
    Searches the command output for the supplied pattern and returns the first
    match from applying the pattern to the output line-by-line. Caching the
    result if requested. Cached matches are deep-copied.
    :param command: the command to run
    :param pattern: the pattern to search for
    :param cache: whether to cache the result of the search; defaults to True
    :return: the result of applying the pattern to each of the lines of the
             stdout obtained by running the command
    """
    if isinstance(pattern, str):
        pattern = re.compile(pattern)
    key = None
    m = None
    if cache:
        key = (''.join(command), pattern)
        if key in _CommandOutputResults:
            m = _CommandOutputResults[key]
            logging.debug('got cache hit for command {} and pattern {}; '
                          'match: {}'
                          .format(command, pattern, m))
            return copy.deepcopy(m)
    result = subprocess.run(command, capture_output=True, encoding='UTF-8')
    for line in result.stdout.splitlines():
        m = re.search(pattern, line)
        if m:
            break
    if cache:
        _CommandOutputResults[key] = copy.deepcopy(m)
    logging.debug('ran command: {} and applied pattern {} with result: {}'
                  .format(command, pattern, m))
    return m


def read_last_n_lines(filename, line_count=1):
    """
    :param filename: the name of the file to open and read
    :param line_count: the number of trailing lines to read
    :return: an array of the last line_count lines in file
    """
    if line_count < 1:
        line_count = 1
    count = 0
    with open(filename, 'rb') as f:
        try:
            # don't count newline at eof
            f.seek(-2, os.SEEK_END)
            while True:
                b = f.read(1)
                if b == b'\n':
                    count += 1
                    if count >= line_count:
                        break
                f.seek(-2, os.SEEK_CUR)
        except OSError:
            f.seek(0)
        return f.read().decode('UTF-8').splitlines()


def read_last_line(filepath):
    with open(filepath, 'rb') as f:
        # Only read last line of file:
        try:
            f.seek(-2, os.SEEK_END)  # Skip last byte in case it is a newline char
            while f.read(1) != b'\n':  # Read 1 byte
                f.seek(-2, os.SEEK_CUR)
        except OSError:
            f.seek(0)

        last_line = f.readline().decode()
        if not last_line:
            raise ValueError(f'CPU stats file at \'{filepath}\' is empty!')

        return last_line
