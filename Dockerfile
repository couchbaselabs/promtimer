#
# Copyright (c) 2023 Couchbase, Inc All rights reserved.
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
# Build arguments:
# GRAFANA_VERSION - version of Grafana to install
# PROMETHEUS_VERSION - version of Prometheus to install
# 
# Usage:
# docker run --rm -p 13300:13300 -v PATH_TO_CBCOLLECTS:/promtimer/data promtimer
# docker run --rm -p 13300:13300 promtimer -c CLUSTER -u USER -p PASSWORD

FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install adduser libfontconfig1 python3 python3-pip wget -y && \
    apt-get clean

ARG GRAFANA_VERSION=8.5.22

RUN ARCH=$(dpkg --print-architecture) && \
    wget https://dl.grafana.com/oss/release/grafana_${GRAFANA_VERSION}_$ARCH.deb && \
    dpkg -i grafana_${GRAFANA_VERSION}_$ARCH.deb && \
    rm grafana_${GRAFANA_VERSION}_$ARCH.deb

ARG PROMETHEUS_VERSION=2.37.6

RUN ARCH=$(dpkg --print-architecture) && \
    wget -O- https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-$ARCH.tar.gz | \
    tar -zxvf - prometheus-$PROMETHEUS_VERSION.linux-$ARCH/prometheus && \
    mv prometheus-${PROMETHEUS_VERSION}.linux-$ARCH/prometheus /bin/prometheus && \
    rmdir prometheus-${PROMETHEUS_VERSION}.linux-$ARCH && \
    chmod +x /usr/bin/prometheus

RUN mkdir -p /promtimer/data

COPY . /promtimer

ENV PROM_BIN=/usr/bin/prometheus

RUN python3 -m pip install -r /promtimer/requirements.txt

WORKDIR /promtimer/data
EXPOSE 13300/tcp
ENTRYPOINT ["/promtimer/promtimer/promtimer.py"]
