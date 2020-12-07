# Grafana Background

## Data Sources

Grafana gets the metrics that it displays in dashboard panels from "data sources". Grafana
supports obtaining metrics from a variety of data source types, but in the case of Promtimer
all of the data sources are of type `prometheus`. Promtimer creates a data source for every
cbcollect against which it is run. The name of the data source is the name of the node that
is embedded in the name of the cbcollect directory.

## Dasboards

Grafana dashboards are constructed from three key building blocks:
1. The dashboard itself
1. The graphs on the dashboard ('panels' in Grafana parlance)
1. The time-series lines on each graph ('targets' in Grafana parlance)

Let's look at these in reverse order.

### Targets

As mentioned targets are time-series lines on a graph and are generally represented by the
following JSON:

    {
      "expr": "...",
      "datasource": "..."
      "legendFormat": "...",
      "refId": "..."
    }

The key attribute is `expr`. This defines the promql query that will be run against
the identified data source. The `datasource` attribute is optional; if not specified, the data
source of the panel that contains the target will be used. The `legendFormat` attribute defines
how the target will be described in the legend that's presented below the panel.

The `refId` attributed is an ID for the target that needs to be unique in the panel. (Promtimer
takes care of generating unique IDs for targets.)

Targets have other non-critical attributes that don't need to be discussed at this point.

### Panels

Panels contain many attributes related to rendering of graphs but the key conceptual / structural
attributes are: `targets`, `datasource` and `gridPos`.


    {
      "title": "..."
      "targets": [
        {...},
        {...}
      ],
      "datasource": "..."
      "gridPos": {
        "x": ...,
        "y": ...,
        "w": ...,
        "h": ...
      },
      ...
    }

The `targets` attribute contains a list of targets as described above. The `datasource`
attribute is optional, but when specified, any targets that don't specify a data source will
automatically pick it up.

The `gridPos` attribute describes where the panel should be placed on the dashboard. More on this
later.

### Dashboards

Similar to panels, dashboards have a quite a number of attributes however, the key ones are:
`panels`, `title`, `templating` and `time`.

      "title": "Bucket Overview",
      "templating": {
        ...
      },
      "panels": [
        {...}
        {...}
      ],
      "time": {
        "from": ...
        "to": ...
      }

The `title` attribute is straightforward - it's how the dashboard shows up in the dasbhoard list
in Grafana. The `panels` attribute contains the list of panels as previously described. The `time`
attributed describes the default time range for each panel in the dashboard. (Promtimer figures
out the min and max time points from each cbcollect against which it's run and automatically 
sets this time range.)

The `templating` attribute allows the dashboard to have list of template parameters that users can
select from at runtime. Data sources are a natural template parameter and Grafana has OOTB support
for this. Custom data sources for thing such as buckets can also be defined and Promtimer has
support for this.
