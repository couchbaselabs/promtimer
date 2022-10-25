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

import atexit
import os
import subprocess
import sys
import tempfile
import zipfile
import logging

# Local Imports
import cbstats


def handle_backup_archive_mode(
    backup_archive_path: str, cbmstatparser_bin: str, prometheus_base_port: int
) -> tuple[list[cbstats.BackupStatsFiles], str, str, str]:
    archive_path = backup_archive_path
    if zipfile.is_zipfile(backup_archive_path):
        archive_path_tmpdir = tempfile.TemporaryDirectory()
        atexit.register(archive_path_tmpdir.cleanup)
        archive_path = archive_path_tmpdir.name

        with zipfile.ZipFile(backup_archive_path, "r") as zipped_archive:
            zipped_archive.extractall(archive_path)

        archive_path = os.path.join(
            archive_path, os.path.splitext(os.path.basename(backup_archive_path))[0]
        )
    # Check that backup_archive_path exists and is not an empty dir
    elif (
        not os.path.isdir(backup_archive_path)
        or len(os.listdir(backup_archive_path)) == 0
    ):
        logging.error(
            "directory supplied as backup_archive_path either does not exist or is empty"
        )
        sys.exit(1)

    stats_tsdb_path_tmpdir = tempfile.TemporaryDirectory()
    atexit.register(stats_tsdb_path_tmpdir.cleanup)
    stats_tsdb_path = stats_tsdb_path_tmpdir.name

    subprocess.run(
        [cbmstatparser_bin, "parse", "-a", archive_path, "-t", stats_tsdb_path],
        check=True,  # Raises exception if exit code is not 0
    )

    stats_sources = [
        cbstats.BackupStatsFiles(
            stats_tsdb_path, "cbmstatparser-prometheus-tsdb", prometheus_base_port
        )
    ]

    min_time, max_time = cbstats.BackupStatsFiles.compute_min_and_max_times(
        archive_path
    )
    min_time, max_time = min_time.isoformat(), max_time.isoformat()

    return stats_sources, min_time, max_time, ""
