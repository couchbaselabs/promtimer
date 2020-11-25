# Promtimer

[Mortimer](https://github.com/couchbaselabs/mortimer) is a convenient 
tool that can be used to display statistics grabbed from Couchbase collected 
log bundles (cbcollects). With the move to use Prometheus for stats
storage and management, Mortimer will no longer work. It would be possible
to extract stats from cbcollects and adapt them to work with Mortimer, but
this project attempts somthing different: use Prometheus itself and Grafana
to allow easy, powerful browsing of Prometheus metrics (stats) available in 
cbcollects. 

## Idea
Promtimer:

1. starts a Prometheus server for each of the cbcollects you are interesteed 
   in exploring
1. generates a convenient Grafana configuration including supporting
   anonymous login, a custom home dashboard, data sources and dashboards
1. starts Grafana allowing you to login and browse dashboards that collect
   metrics from across each node in the cluster

## Dependencies

You will need:

* A Prometheus binary
* Grafana
* Promtimer
* Some cbcollects

If you happen to be building Couchbase Server 7.0 or later, you will already 
have a Prometheus binary: it's in the `install/bin` directory of one of your 
local builds. If you don't, the [Getting Started](https://prometheus.io/docs/introduction/first_steps/) 
instructions on the Prometheus website are comprehensive. If you're on Mac,
`brew` works great:

```
brew install prometheus
```

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
on the Grafana website look comprehensive. On Mac, it's easy:

```
brew install grafana
```

To get Promtimer, clone this repo locally:

```
git clone git@github.com:couchbaselabs/promtimer.git
```

As to cbcollects, you probably wouldn't be reading this if you didn't already
have them. 

## How to Use Promtimer

Assemble the cbcollects in a directory and unzip them. 

```
ls cbcollect*.zip | xargs -n 1 unzip
```

Start Promtimer:

```
promtimer.py
```

The Grafana dashboards page should open for you automatically. If not, navigate
to (`localhost:3000/dashboards`) in your browser and begin exploring the 
available dashboards.

## Clean Up

Promtimer creates a `.grafana` sub-directory in the directory where it's 
started and places the Grafana configuration. To clean up, remove this
directory:

```
rm -rf .grafana
```

## Want to Help?

Awesome! See the [list of todos](TODO.md).