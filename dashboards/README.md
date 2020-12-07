# Dashboard Meta Model

One of the goals of Promtimer is to make it quick and easy to add useful Grafana dashboards and
graphs. The dashboard "meta model" is Promtimer's attempt to do this.

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

# How the Meta Model Works

It's probably best explained by example.

## Create Your First Dashboard

Create an empty dashboard by adding a new meta file `new-dashboard.json` in the
`promtimer/dashboards` directory containing the following JSON:

    {
      "title": "New Dashboard",
      "_base": "dashboard",
      "_panels": [
      ]
    }

If you run `promtimer` against some cbcollect_info and browse to http://localhost:13000/dashboards,
you'll now find a new dashboard titled "New Dashboard". You can visit this dashboard directly by
navigating to: http://localhost:13000/d/new-dashboard/new-dashboard.

The `_base` attribute specifies the name of the dashboard template that this dashboard is based on.
In this case the base dashboard is the file of the name `dashboard` in the `templates` directory
-- this [file](../templates/dashboard.json). The base dashboard captures a lot of boilerplate
that's tedious to repeat when you create a dashboard.

Note that the title of the dashboard you created shows as "New Dashboard". This happens because
the `title` attribute is copied from the dashboard meta object to the dasbboard on which it is
based. This is true for all attributes that don't have a leading underscore.

## Create a Panel

Add a panel to the `_panels` attribute to your dashboard and restart Promtimer.

    {
      "title": "New Dashboard",
      "_base": "dashboard",
      "_panels": [
        {
          "title": "My Panel",
          "_base": "panel",
          "_targets": [
          ]
        }
      ]
    }

You'll see that you're new dashboard has a single empty panel.

## Add a Target Parameterized by Data-Source-Name

To add some time series to the panel, change the dashboard to look as follows and again restart.
Let's also give the panel a better title:

    {
      "title": "New Dashboard",
      "_base": "dashboard",
      "_panels": [
        {
          "title": "sys_cpu_utilization_rate",
          "_base": "panel",
          "_targets": [
            {
              "datasource": "{data-source-name}",
              "expr": "sys_cpu_utilization_rate",
              "legendFormat": "{data-source-name} sys_cpu_utilization_rate",
              "_base": "target"
            }
          ]
        }
      ]
    }

You will notice that the panel now contains one or more time series traces, or targets. Each target
is the `sys_cpu_utilization_rate` for one of the cbcollects against which Promtimer is run. This
happens because the target contains at least one instance of the Promtimer template parameter
`{data-source-name}` which is automatically expanded by Promtimer to add one trace per data source,
or cbcollect.

## Make the Panel Data-Source-Name Parameterized

Add a data-source-name parameter to the panel, as follows:

    {
      "title": "New Dashboard",
      "_base": "dashboard",
      "_panels": [
        {
          "title": "sys_cpu_utilization_rate",
          "datasource": "{data-source-name}",
          "_base": "panel",
          "_targets": [
            {
              "datasource": "{data-source-name}",
              "expr": "sys_cpu_utilization_rate",
              "legendFormat": "{data-source-name} sys_cpu_utilization_rate",
              "_base": "target"
            }
          ]
        }
      ]
    }

You'll notice that adding the data-source-name parameter to the panel caused the template expansion
to occur at the panel level and you now have two panels, one for each data source.
