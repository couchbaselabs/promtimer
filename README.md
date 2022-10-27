# Promtimer

In 7.0, Couchbase Server has moved to use Prometheus as the storage backend
for stats and when logs are collected, a Prometheus snapshot is generated
and included in the zip archive. Promtimer is a tool that uses Prometheus
itself and Grafana to allow easy, powerful browsing of Prometheus metrics
(stats) available in cbcollects.

In addition to offline browsing of stats, Promtimer supports setting up
Grafana to run against a live Couchbase Server cluster.

If you've already installed, here are a some quick links you might be
interested in:
* [Dashboards README](dashboards/README.md)
* [Todos](TODO.md)

## Idea
Promtimer:

1. When running against cbcollects, starts a Prometheus server for each
   cbcollect you are interested in exploring. (When run against a live
   cluster this step is not necessary.)
1. Generates a convenient Grafana configuration with anonymous login, a
   custom home dashboard, data sources and dashboards.
1. Starts Grafana allowing you to login and browse dashboards that collect
   metrics from across each node in the cluster.
1. Creates dashboard annotations based on important events that happened in
   the cbcollect, taking information from the `diag.log` (or from an
   `events.log` file generated by the Event Logger) or from the `/logs` REST
   API.

## Dependencies

You will need:

* Python 3.8 or later
* Grafana (version 7.1 or later)
* Promtimer

To browse stats online, all you need is a live cluster to run against.

For offline browsing of stats, you will additionally need:
* A Prometheus binary (version 2.20 or later)
* Some cbcollects
* (Optional) Event Logger from [cbmultimanager](https://github.com/couchbaselabs/cbmultimanager)
  if you wish to generate an `events.log` file

If you happen to be building Couchbase Server 7.0 or later, you will already
have a Prometheus binary: it's in the `install/bin` directory of one of your
local builds. If you don't, the [Getting Started](https://prometheus.io/docs/introduction/first_steps/)
instructions on the Prometheus website are comprehensive. You don't actually
need to install Prometheus, you just need the binary. [Downloading](https://prometheus.io/download/)
and unzipping the pre-compiled binaries for your platform is sufficient.

If you're on Mac,`brew` is convenient:

    brew install prometheus

It's also possible to build Prometheus from source yourself. This is
straightforward:

```
git clone git@github.com:prometheus/prometheus.git
cd prometheus
make prometheus
```

You'll need a full Grafana install. The `grafana-server` binary alone isn't
sufficient as Grafana ships with many configuration files.
[Installation instructions](https://grafana.com/docs/grafana/latest/installation/)
on the Grafana website look comprehensive. Follow the instructions for your
platform to get a recent version of Grafana. On Mac, it's easy:

    brew install grafana

To get Promtimer, clone this repo locally:

    git clone https://github.com/couchbaselabs/promtimer.git

As to cbcollects, you probably wouldn't be reading this if you didn't already
have them.

## How to Use Promtimer for Offline Analysis
### Visualising CBCollects
Assemble the cbcollects in a directory. It's fine if you unzip them, but it's not
necessary.

Start Promtimer:

```
bin/promtimer [--prometheus <path-to-prometheus-binary>]
     [--grafana-home <path-to-grafana-shared-config-home>]
```

The `path-to-prometheus-binary` specifies the path to the prometheus binary and
must be specified if the binary you wish to use isn't on your PATH.

The `path-to-grafana-shared-config-home` is what is known in Grafana terminology as the
"homepath". This is the out-of-the-box Grafana shared config path. On brew-installed
Grafana on Macs this is something like:

    /usr/local/share/grafana

On linux systems the homepath should usually be:

    /usr/share/grafana

Promtimer defaults the Grafana homepath to these locations on these platforms. However,
if you're on a different platform or want to use a different homepath you'll need to
explicitly specify it.

The Grafana dashboards page should open for you automatically. If not, navigate
to `localhost:13300/dashboards` in your browser and begin exploring the
available dashboards.

### Visualising cbbackupmgr stats files
Ensure that you have access to either a backup archive or a cbbackupmgr collect zip
file.

Start Promtimer:

```bash
promtimer --stats-archive-path <path-to-backup-archive-or-zip>
```

The `path-to-backup-archive-or-zip` specifies the path to either a backup archive or to
a cbbackupmgr collect zip file.

The Grafana dashboards page should open for you automatically. If not, navigate
to `localhost:13300/dashboards` in your browser and begin exploring the
available dashboards.

## How to Use Promtimer for Online Monitoring

Start Promtimer and provide the URL to the cluster and the name of the user that
Promtimer should authenticate with:
```
bin/promtimer --cluster <host:port> --user username [--password password]
```

You'll be securely prompted for the password at the command line, if not specified.

## Annotations from System Events

Promtimer will grab user log information (from the `diag.log` in the offline case and
the `/logs` REST API in the online case) and create dashboard annotations in Grafana
for important system events.

As an option, Promtimer also supports the creating annotations based on an `events.log`
file for system events generated by the Event Logger in the
[cbmultimanager](https://github.com/couchbaselabs/cbmultimanager) repository. Read
[here](EVENTS.md) for more information on the Event Logger.

## Clean Up

Promtimer creates a `.promtimer` sub-directory in the directory where it's
started and places the Grafana configuration. To clean up, remove this
directory:

```
rm -rf .promtimer
```

## Want to Help?

Awesome! See the [list of todos](TODO.md).
