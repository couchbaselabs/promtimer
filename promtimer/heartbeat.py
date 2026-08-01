# Copyright (c) 2026 Couchbase, Inc All rights reserved.
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
"""Backfill the ns_doctor heartbeat (ns_server.stats.log) into each
cbcollect's stats_snapshot as Prometheus TSDB blocks, so heartbeat-only
metrics (Erlang memory breakdown, the /proc/meminfo anon/file split,
per-process RSS/CPU, and PSI pressure for captures from before 7.2.4, which
is where sys_pressure_* starts being scraped) appear in the same datasource
as the snapshot stats. For a cbcollect that has no stats_snapshot at all (pre-7.0),
this creates one, which makes the collect openable in Promtimer.

The logs are read out of the cbcollect zip whenever there is one, the way
CBCollect.operate_on_log_file already reads couchbase.log and diag.log, so
working from a directory of downloaded zips needs no unzipping and a
cbcollect that has been unzipped with its zip left in place is no different.
Both logs are consumed as a stream (ns_server.stats.log is tens of MB,
diag.log can be hundreds), so nothing large is held in memory or on disk.

Cost model: the backfill runs ONCE per cbcollect. A heartbeat_blocks.txt
manifest in the snapshot records the blocks written; when it exists the
backfill is skipped entirely (a stat call), so re-opening a cbcollect stays
as fast as it is today. --heartbeat=refresh replaces the blocks; the
manifest also makes removal safe (native snapshot blocks are never listed).

Metric names carry a heartbeat_ prefix, so they can never collide with real
exposition names. Collection gaps of >= 2 minutes become explicit NaN
samples so Grafana renders a break instead of repeating the last value
through the query lookback window. Requires promtool (looked up next to the
prometheus binary, then on PATH); without it the backfill is skipped with a
log line and Promtimer behaves exactly as before.
"""
import concurrent.futures
import contextlib
import enum
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections import defaultdict
from datetime import datetime

# Local Imports
import cbstats


class HeartbeatMode(enum.Enum):
    """What the heartbeat backfill should do for a cbcollect that already has
    backfilled blocks: leave them alone (the default: the parse then happens
    once per cbcollect), regenerate them, or don't backfill at all."""
    AUTO = 'auto'
    SKIP = 'skip'
    REFRESH = 'refresh'

    def __str__(self):
        return self.value


MANIFEST = 'heartbeat_blocks.txt'

# What a cbcollect holds and where: cbstats owns the layout, these are just
# short local names for it.
STATS_LOG = cbstats.NS_SERVER_STATS_LOG
DIAG_LOG = cbstats.DIAG_LOG
SNAPSHOT_DIR = cbstats.STATS_SNAPSHOT_DIR_NAME

# Heartbeat cadence and the gap rule: >= 2min between a series' samples is a
# collection gap; the NaN break is stamped one nominal interval after the
# last real sample.
INTERVAL_S = 60
GAP_S = 120


# ---------------------------------------------------------------------------
# cbcollect file access: on disk, or streamed out of the zip when the
# cbcollect hasn't been unzipped
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def open_binary(cbcollect_dir, zip_path, name):
    """Binary handle on a file of a cbcollect: read out of the cbcollect
    zip whenever there is one, as CBCollect.operate_on_log_file already
    does for couchbase.log and diag.log, and off disk only for a cbcollect
    with no zip beside it. Reading the zip regardless of what happens to
    be extracted means a partly unzipped cbcollect needs no special case.
    Raises the usual FileNotFoundError/KeyError when the file isn't
    there."""
    if zip_path:
        with zipfile.ZipFile(zip_path) as z:
            with z.open(cbstats.CBCollect.zip_member_path(cbcollect_dir,
                                                          name)) as f:
                yield f
    else:
        with open(os.path.join(cbcollect_dir, name), 'rb') as f:
            yield f


@contextlib.contextmanager
def open_text(cbcollect_dir, zip_path, name):
    """As open_binary, decoded as utf-8."""
    with open_binary(cbcollect_dir, zip_path, name) as f:
        yield io.TextIOWrapper(f, 'utf-8', errors='replace')


# ---------------------------------------------------------------------------
# stats.log (ns_doctor heartbeat) parser
# ---------------------------------------------------------------------------

_TS_RE = re.compile(
    r'ns_doctor:\w+,('
    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?'
    r'(?:[+-]\d{2}:\d{2}|Z)?)')


def _parse_doctor_ts(ts_str):
    """UTC epoch (float) from the dump's ISO timestamp, or None when the
    line carries no UTC offset (very old logs)."""
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


def _with_lookahead(lines):
    """Yield (index, line, next_line) over lines, next_line None at the end.
    A few of the dump's values sit on the line after their key, and the
    lookahead keeps the parser streaming rather than holding the whole
    stats.log in memory."""
    prev = None
    for i, line in enumerate(lines):
        if prev is not None:
            yield prev[0], prev[1], line
        prev = (i, line)
    if prev is not None:
        yield prev[0], prev[1], None


def parse_entries(lines):
    """Parse a stats.log (ns_doctor dump), given an iterable of its lines,
    into a list of per-(dump, node) dicts: node, ts_epoch, plus every stat
    key (system_*, memory_*, <proc>_*, disk_*, meminfo_*). Stale node
    statuses (same last_heard as the previous dump) are dropped."""
    entries = []
    heard = defaultdict(str)

    current_entry = None
    mode = None
    current_process = None
    current_ts_epoch = None
    seen_ts = False

    for i, line, next_line in _with_lookahead(lines):
        if 'ns_doctor:debug,' in line:
            m = _TS_RE.search(line)
            if not m:
                raise ValueError('invalid timestamp at line {}'.format(i))
            current_ts_epoch = _parse_doctor_ts(m.group(1))
            seen_ts = True

        elif re.match(r"[\[ ]{'(?:ns_1@|n_\d+@)", line):
            if not seen_ts:
                raise ValueError(
                    'node entry without timestamp at line {}'.format(i))
            node_match = re.search(r"{'([^']+)'", line)
            if not node_match:
                raise ValueError('invalid node format at line {}'.format(i))
            if current_entry:
                entries.append(current_entry)
            current_entry = {
                'node': node_match.group(1),
                'ts_epoch': current_ts_epoch,
            }

        elif 'last_heard' in line and current_entry:
            m = re.search(r'{last_heard,([-]*[0-9]+)', line)
            if m:
                last_heard = m.group(1)
                if heard[current_entry['node']] == last_heard:
                    current_entry = None        # stale status: drop
                else:
                    heard[current_entry['node']] = last_heard

        elif current_entry and '{system_stats,' in line:
            mode = 'system_stats'
        elif mode == 'system_stats':
            m = re.search(r'\{([^,]+),([0-9.]+)\}', line)
            if m:
                name = m.group(1)
                if (name == 'allocstall' or 'cpu' in name.lower()
                        or 'cores' in name.lower()):
                    current_entry['system_' + name] = float(m.group(2))
            if ']}' in line:
                mode = None

        elif current_entry and '{memory_data,' in line:
            m = re.search(
                r'\{memory_data,\{(\d+),(\d+),\{([^,]+),(\d+)\}\}\}', line)
            if m:
                current_entry['memory_worst_pid'] = m.group(3)
                current_entry['memory_worst_used'] = int(m.group(4))

        elif current_entry and '{meminfo,' in line:
            blob = line
            if next_line is not None:
                blob += next_line
            for key, field in [
                ('active_anon', r'Active\(anon\)'),
                ('inactive_anon', r'Inactive\(anon\)'),
                ('active_file', r'Active\(file\)'),
                ('inactive_file', r'Inactive\(file\)'),
                ('dirty', 'Dirty'),
                ('writeback', 'Writeback'),
                ('mem_available', 'MemAvailable'),
                ('slab', 'Slab'),
                ('sunreclaim', 'SUnreclaim'),
                ('percpu', 'Percpu'),
            ]:
                m = re.search(field + r':\s*(\d+)\s*kB', blob)
                if m:
                    current_entry['meminfo_' + key] = int(m.group(1)) * 1024

        elif current_entry and '{disk_data,' in line:
            mode = 'disk_data'
        elif mode == 'disk_data':
            # Every mount disksup reports, whatever it is called: a data path
            # is as likely to be /data2 or /mnt/data as /data.
            m = re.search(r'\{("[^"]+"),(\d+),(\d+)\}', line)
            if m:
                disk = m.group(1)
                current_entry['disk_{}_usage'.format(disk)] = int(m.group(3))
                current_entry['disk_{}_capacity'.format(disk)] = \
                    int(m.group(2))
            if '}]}]}' in line:
                mode = None

        elif current_entry and '{system_memory_data,' in line:
            mode = 'system_memory_data'
        elif mode == 'system_memory_data':
            m = re.search(r'\{([^,]+),(\d+)\}', line)
            if m:
                current_entry['system_' + m.group(1)] = int(m.group(2))
            if ']}' in line:
                mode = None

        elif current_entry and '{memory,' in line:
            mode = 'memory'
        elif mode == 'memory':
            m = re.search(r'\{([^,]+),(\d+)\}', line)
            if m:
                current_entry['memory_' + m.group(1)] = int(m.group(2))
            if ']}' in line:
                mode = None

        elif (current_entry and '{processes_stats,' in line
                and '{processes_stats,[]},' not in line
                and next_line is not None):
            if '<<' in next_line.strip():
                mode = 'processes_stats_pre_7_2_4'
            else:
                mode = 'processes_stats_7_2_4'
        elif mode == 'processes_stats_pre_7_2_4':
            m = re.search(r'{<<"([\S]+)/([\S]+)">>,(\d*\.*\d+)}', line)
            if m:
                process, stat, value = m.groups()
                try:
                    value = int(value)
                except ValueError:
                    value = float(value)
                current_entry['{}_{}'.format(process, stat)] = value
            if '}]},' in line:
                mode = None
        elif mode == 'processes_stats_7_2_4':
            m = re.search(r'\{([^,]+),$', line)
            if m:
                current_process = m.group(1).strip("'")
            m = re.search(r'\{([^,]+),([0-9.]+)\}', line)
            if m and current_process:
                stat = m.group(1).strip("'")
                current_entry['{}_{}'.format(current_process, stat)] = \
                    float(m.group(2))
            if '}]}]}' in line:
                mode = None

        elif current_entry and '_pressure' in line:
            m = re.search(r'\{([\w]+)_pressure', line)
            if m and next_line is not None:
                ptype = m.group(1)
                for kind in ('some', 'full'):
                    km = re.search(
                        kind + r' avg10=([0-9]+.[0-9]+) '
                        'avg60=([0-9]+.[0-9]+) '
                        'avg300=([0-9]+.[0-9]+) '
                        'total=([0-9]+)',
                        next_line)
                    if km:
                        pfx = 'system_{}_pressure_{}'.format(ptype, kind)
                        current_entry[pfx + '_avg60'] = float(km.group(2))
                        current_entry[pfx + '_total'] = int(km.group(4))

    if current_entry:
        entries.append(current_entry)
    return entries


# ---------------------------------------------------------------------------
# diag.log pid -> process name map (for the worst-memory-consumer series).
# diag.log embeds the collected logs and can run to hundreds of MB while
# the process sections are a few MB, so the scan is a single forward pass
# over chunks and only the bytes of a section get split into lines. That
# also keeps the scan working against a zip member, which can be read
# forwards but not seeked.
# ---------------------------------------------------------------------------

_SECTION_BYTES_RE = re.compile(rb'per_node_\w*processes\(')
_SCAN_CHUNK = 8 << 20
_OVERLAP = 64                   # >= the longest section marker
_PROC_START_RE = re.compile(r'^\s*\{(<\d+\.\d+\.\d+>),')
_NAME_RE = re.compile(r'\{registered_name,\s*([^}\]]+)\}')
_INITCALL_RE = re.compile(r'\{initial_call,\s*\{([^}]+)\}\}')


def _process_section_lines(stream):
    """Yield the lines of diag.log's process-dump sections (the section
    header and the blank line that ends a section are not yielded)."""
    tail = b''
    in_section = False
    while True:
        chunk = stream.read(_SCAN_CHUNK)
        if not chunk:
            break
        buf = tail + chunk
        if not in_section and not _SECTION_BYTES_RE.search(buf):
            # Nothing of interest here: carry over only enough bytes for a
            # marker straddling the chunk boundary.
            tail = buf[-_OVERLAP:]
            continue
        lines = buf.split(b'\n')
        tail = lines.pop()          # possibly-partial last line
        for line in lines:
            if in_section:
                if not line.strip():    # sections end with a blank line
                    in_section = False
                else:
                    yield line.decode('utf-8', 'replace')
            elif _SECTION_BYTES_RE.search(line):
                in_section = True
    if in_section and tail.strip():
        yield tail.decode('utf-8', 'replace')


def pid_names(cbcollect_dir, zip_path=None):
    """Best-effort {erlang_pid: name} from diag.log's process dump. Only
    local pids (<0.x.y>) appear in the dump, and remote pids in the
    heartbeat print with a nonzero node index, so a remote pid can never
    match. Anonymous processes and pids that died before collection simply
    stay unlabeled."""
    names = {}

    def collect(buf, pid):
        if not buf or not pid:
            return
        text = '\n'.join(buf)
        m = _NAME_RE.search(text)
        name = m.group(1).strip() if m else None
        if name in ('[]', ''):
            name = None
        if not name:
            m = _INITCALL_RE.search(text)
            name = m.group(1).strip() if m else None
        if name and name not in (pid, '?'):
            names[pid] = name

    try:
        with open_binary(cbcollect_dir, zip_path, DIAG_LOG) as f:
            buf, buf_pid = [], None
            for line in _process_section_lines(f):
                m = _PROC_START_RE.match(line)
                if m:
                    collect(buf, buf_pid)
                    buf, buf_pid = [line], m.group(1)
                elif buf:
                    buf.append(line)
            collect(buf, buf_pid)
    except (OSError, KeyError):     # no diag.log: the pids stay unlabeled
        return {}
    return names


# ---------------------------------------------------------------------------
# heartbeat entries -> OpenMetrics -> TSDB blocks
# ---------------------------------------------------------------------------

_OS_MEMORY_KINDS = (
    'total_memory', 'free_memory', 'available_memory', 'system_total_memory',
    'buffered_memory', 'cached_memory', 'shared_memory', 'largest_free',
    'total_swap', 'free_swap')

_PROC_SUFFIXES = {
    '_mem_resident': ('heartbeat_process_resident_memory_bytes', 'gauge'),
    '_mem_size': ('heartbeat_process_virtual_memory_bytes', 'gauge'),
    '_cpu_utilization': ('heartbeat_process_cpu_percent', 'gauge'),
    '_major_faults_raw': ('heartbeat_process_major_faults', 'counter'),
    '_minor_faults_raw': ('heartbeat_process_minor_faults', 'counter'),
    '_page_faults_raw': ('heartbeat_process_page_faults', 'counter'),
}

_PRESSURE_RE = re.compile(
    r'^system_(cpu|memory|io)_pressure_(some|full)_(avg60|total)$')
_DISK_RE = re.compile(r'^disk_"(.*)"_(usage|capacity)$')


def _esc(v):
    return str(v).replace('\\', '\\\\').replace('"', '\\"').replace(
        '\n', '\\n')


def _classify(key, value, entry):
    """Map one parsed entry key/value to (family, type, labels, value), or
    None for keys that don't translate to a metric."""
    if not isinstance(value, (int, float)):
        return None

    m = _PRESSURE_RE.match(key)
    if m:
        resource, kind, which = m.groups()
        if which == 'avg60':
            return ('heartbeat_pressure_avg60_percent', 'gauge',
                    {'resource': resource, 'kind': kind}, value)
        return ('heartbeat_pressure_stall_microseconds', 'counter',
                {'resource': resource, 'kind': kind}, value)

    m = _DISK_RE.match(key)
    if m:
        mount, which = m.groups()
        if which == 'usage':
            return ('heartbeat_disk_usage_percent', 'gauge',
                    {'mount': mount}, value)
        return ('heartbeat_disk_capacity_bytes', 'gauge',
                {'mount': mount}, value * 1024)    # disksup reports KB

    if key == 'system_allocstall':
        return ('heartbeat_allocstall', 'counter', {}, value)
    if key == 'system_cpu_utilization_rate':
        return ('heartbeat_cpu_utilization_percent', 'gauge', {}, value)
    if key == 'system_cpu_stolen_rate':
        return ('heartbeat_cpu_stolen_percent', 'gauge', {}, value)
    if key == 'system_cpu_cores_available':
        return ('heartbeat_cpu_cores_available', 'gauge', {}, value)

    if key == 'memory_worst_used':
        pid = entry.get('memory_worst_pid')
        labels = {'pid': pid} if pid else {}
        return ('heartbeat_erlang_worst_process_memory_bytes', 'gauge',
                labels, value)

    if key.startswith('meminfo_'):
        return ('heartbeat_meminfo_bytes', 'gauge',
                {'kind': key[len('meminfo_'):]}, value)

    if key.startswith('system_'):
        kind = key[len('system_'):]
        if kind in _OS_MEMORY_KINDS:
            return ('heartbeat_os_memory_bytes', 'gauge',
                    {'kind': kind}, value)
        return None

    if key.startswith('memory_') and key != 'memory_worst_pid':
        return ('heartbeat_erlang_memory_bytes', 'gauge',
                {'type': key[len('memory_'):]}, value)

    for suffix, (family, mtype) in _PROC_SUFFIXES.items():
        if key.endswith(suffix):
            return (family, mtype, {'proc': key[: -len(suffix)]}, value)

    return None


def to_openmetrics(entries, nodes=None, names=None):
    """Render heartbeat entries as OpenMetrics text. Where consecutive
    samples of a series are >= GAP_S apart (a collection gap), an explicit
    NaN is written one interval after the last real sample, so Prometheus's
    query lookback carries forward NaN and Grafana breaks the line instead
    of repeating stale values. Each series is terminated the same way, so
    its final sample doesn't carry forward for the whole lookback window
    either. Returns (text, n_samples)."""
    types = {}
    series = defaultdict(lambda: defaultdict(list))

    for e in entries:
        ts = e.get('ts_epoch')
        if ts is None:
            continue
        if nodes is not None and e['node'] not in nodes:
            continue
        for key, value in e.items():
            got = _classify(key, value, e)
            if not got:
                continue
            family, mtype, labels, val = got
            labels = dict(labels, node=e['node'])
            if (names
                    and family == 'heartbeat_erlang_worst_process_memory_bytes'
                    and labels.get('pid') in names):
                labels['name'] = names[labels['pid']]
            labelstr = ','.join(
                '{}="{}"'.format(k, _esc(v))
                for k, v in sorted(labels.items()))
            types[family] = mtype
            series[family][labelstr].append((ts, val))

    lines = []
    n = 0
    for family in sorted(series):
        mtype = types[family]
        lines.append('# TYPE {} {}'.format(family, mtype))
        name = family + '_total' if mtype == 'counter' else family
        for labelstr in sorted(series[family]):
            prev_ts = None
            for ts, val in sorted(series[family][labelstr]):
                if prev_ts is not None and ts - prev_ts >= GAP_S:
                    lines.append('{}{{{}}} NaN {}'.format(
                        name, labelstr, prev_ts + INTERVAL_S))
                lines.append('{}{{{}}} {} {}'.format(name, labelstr, val, ts))
                prev_ts = ts
                n += 1
            if prev_ts is not None:
                lines.append('{}{{{}}} NaN {}'.format(
                    name, labelstr, prev_ts + INTERVAL_S))
    lines.append('# EOF')
    return '\n'.join(lines) + '\n', n


def _backfill_one(task):
    """Worker: backfill one cbcollect, reading its logs out of the zip when
    it hasn't been unzipped. Returns a status string."""
    cbcollect_dir, zip_path, promtool = task
    snapshot = os.path.join(cbcollect_dir, SNAPSHOT_DIR)
    try:
        if zip_path:
            # Extract the cbcollect's own snapshot first: the backfill writes
            # blocks into stats_snapshot, and the normal extraction skips a
            # snapshot directory that already exists. This is the same call
            # the cbcollect discovery makes later, and is a no-op then.
            with zipfile.ZipFile(zip_path) as z:
                cbstats.CBCollect.maybe_extract_from_zipfile(z)
        with open_text(cbcollect_dir, zip_path, STATS_LOG) as f:
            entries = parse_entries(f)
        all_nodes = {e['node'] for e in entries}
        # Every node's heartbeat describes the whole cluster, so restrict this
        # cbcollect's to the node that captured it (named by the dir name):
        # each Prometheus instance then serves its own node, as the snapshot
        # beside it does. Backfill nothing at all when that node can't be
        # identified - the panels don't put the node in the legend, so keeping
        # every node's series would silently pass another node's memory off as
        # this one's.
        # Absolute, so a cbcollect given as '.' (Promtimer run inside an
        # unzipped cbcollect) is named by its directory rather than by '.'.
        parsed = cbstats.CBCollect.parse_dir_name(
            os.path.abspath(cbcollect_dir))
        # cbcollect_info builds the directory name from the node name but
        # replaces ':' with '-', so an IPv6 node's name doesn't survive into
        # it intact: match the log's node names the same way rather than
        # expecting the directory to spell the node exactly.
        matched = [n for n in sorted(all_nodes)
                   if parsed and n.replace(':', '-') == parsed.node]
        if len(matched) != 1:
            return ('{}: not backfilled, cannot tell which node captured it:'
                    ' the directory is not named for exactly one of the nodes'
                    ' the heartbeat describes ({})'
                    .format(cbcollect_dir,
                            ', '.join(sorted(all_nodes)) or 'none'))
        nodes = {matched[0]}
        # names only adds a label, never changes the sample count, so get
        # the count first and only pay for pid_names (a diag.log byte-scan)
        # when there is data to enrich.
        text, n = to_openmetrics(entries, nodes=nodes)
        if n == 0:
            return '{}: no exportable heartbeat samples'.format(cbcollect_dir)
        names = pid_names(cbcollect_dir, zip_path)
        text, n = to_openmetrics(entries, nodes=nodes, names=names)

        os.makedirs(snapshot, exist_ok=True)
        before = {d for d in os.listdir(snapshot)
                  if os.path.isdir(os.path.join(snapshot, d))}
        with tempfile.NamedTemporaryFile('w', suffix='.om.txt',
                                         delete=False) as f:
            om_path = f.name
            f.write(text)
        try:
            subprocess.run(
                [promtool, 'tsdb', 'create-blocks-from', 'openmetrics',
                 om_path, snapshot],
                check=True, capture_output=True, text=True)
        finally:
            os.unlink(om_path)
        created = sorted(
            {d for d in os.listdir(snapshot)
             if os.path.isdir(os.path.join(snapshot, d))} - before)
        with open(os.path.join(snapshot, MANIFEST), 'a') as f:
            for ulid in created:
                f.write(ulid + '\n')
        return '{}: backfilled {} heartbeat samples'.format(cbcollect_dir, n)
    except subprocess.CalledProcessError as e:
        return '{}: promtool failed: {}'.format(
            cbcollect_dir, (e.stderr or e.stdout or '').strip())
    except Exception as e:
        return '{}: heartbeat backfill failed: {}'.format(cbcollect_dir, e)


def _undo(snapshot):
    """Remove the blocks a previous backfill wrote (native snapshot blocks
    are never in the manifest). Removes the snapshot dir itself if that
    leaves it empty (it was created by the backfill)."""
    manifest = os.path.join(snapshot, MANIFEST)
    if not os.path.isfile(manifest):
        return
    with open(manifest) as f:
        for ulid in f.read().split():
            block = os.path.join(snapshot, ulid)
            if os.path.isdir(block):
                shutil.rmtree(block)
    os.remove(manifest)
    try:
        os.rmdir(snapshot)
    except OSError:
        pass


def find_promtool(prom_bin):
    """promtool next to the prometheus binary, else on PATH, else None."""
    if prom_bin:
        cand = os.path.join(os.path.dirname(os.path.abspath(prom_bin)),
                            'promtool')
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return shutil.which('promtool')


def find_cbcollects():
    """Every cbcollect in the working directory that carries an
    ns_server.stats.log, as a sorted list of (cbcollect_dir, zip_path)
    pairs. zip_path is the zip holding the cbcollect, or None for a
    cbcollect with no zip beside it; a cbcollect that has been unzipped
    with its zip left in place is still read from the zip, so how much of
    it has been extracted doesn't matter. When two zips hold the same
    cbcollect directory the first by name wins.

    The zips and the directories are the ones cbcollect discovery considers,
    so a cbcollect Promtimer would never open is never backfilled. What
    makes one usable differs though: discovery wants a stats_snapshot,
    which a pre-7.0 cbcollect has nowhere, while the backfill only wants an
    ns_server.stats.log - and creates the snapshot."""
    found = {}
    for z in cbstats.CBCollect.find_candidate_zips():
        try:
            with zipfile.ZipFile(z) as zip_file:
                cbcollect_dir = cbstats.CBCollect.find_dir_in_zip(zip_file)
                if cbcollect_dir and cbstats.CBCollect.zip_member_path(
                        cbcollect_dir, STATS_LOG) in zip_file.namelist():
                    found.setdefault(cbcollect_dir, z)
        except (OSError, zipfile.BadZipFile) as e:
            logging.debug('not reading heartbeat from {}: {}'.format(z, e))
    for d in cbstats.CBCollect.find_candidate_dirs():
        if os.path.isfile(os.path.join(d, STATS_LOG)):
            found.setdefault(d, None)
    if not found and os.path.isfile(STATS_LOG):
        # Nothing beside us and a heartbeat log right here: Promtimer is being
        # run inside an unzipped cbcollect. CBCollect.get_stats_sources takes
        # the same cbcollect as '.' on the same reasoning, testing for the
        # stats_snapshot it needs where this tests for the log it needs.
        found['.'] = None
    return sorted(found.items())


def maybe_backfill(prom_bin, mode=None):
    """Backfill the heartbeat for every cbcollect in the working directory
    that has an ns_server.stats.log, unzipped or still zipped. Runs BEFORE
    cbcollect discovery so a snapshot created here makes an old
    (pre-snapshot) collect discoverable. Skips cbcollects whose snapshot
    already carries the manifest, so this costs a stat call per cbcollect
    on every open after the first; HeartbeatMode.REFRESH replaces
    previously backfilled blocks and HeartbeatMode.SKIP does nothing at
    all. mode defaults to HeartbeatMode.AUTO."""
    mode = mode or HeartbeatMode.AUTO
    if mode is HeartbeatMode.SKIP:
        return
    cbcollects = find_cbcollects()
    if mode is HeartbeatMode.REFRESH:
        for cbcollect_dir, _ in cbcollects:
            _undo(os.path.join(cbcollect_dir, SNAPSHOT_DIR))
    todo = [(cbcollect_dir, zip_path)
            for cbcollect_dir, zip_path in cbcollects
            if not os.path.isfile(
                os.path.join(cbcollect_dir, SNAPSHOT_DIR, MANIFEST))]
    if not todo:
        return
    promtool = find_promtool(prom_bin)
    if not promtool:
        logging.info('heartbeat backfill skipped: promtool not found next '
                     'to prometheus or on PATH (brew install prometheus)')
        return
    logging.info(
        'backfilling ns_server.stats.log heartbeat for {} cbcollect(s). '
        'This runs once per cbcollect (parsed in parallel) and is skipped '
        'on later opens. '
        'To skip it entirely, pass --heartbeat=skip. '
        'To regenerate after changing the heartbeat parser, pass '
        '--heartbeat=refresh.'.format(len(todo)))
    start = time.perf_counter()
    tasks = [(cbcollect_dir, zip_path, promtool)
             for cbcollect_dir, zip_path in todo]
    workers = min(len(tasks), os.cpu_count() or 1)
    if workers > 1:
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=workers) as ex:
            results = list(ex.map(_backfill_one, tasks))
    else:
        results = [_backfill_one(t) for t in tasks]
    for r in results:
        logging.info(r)
    logging.info('heartbeat backfill done: {} cbcollect(s) in {:.0f}s'.format(
        len(todo), time.perf_counter() - start))
