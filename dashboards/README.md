# Dashboards and Promtimer

One of the goals of Promtimer is to make it quick and easy to add useful Grafana dashboards and
graphs. The dashboard "meta model" is Promtimer's attempt to do this. To explain how Promtimer
dashboarding works it's necessary to understand a little about how Grafana dashboarding works.

[Grafana Background](GrafanaBackground.md)

However, if you're already comfortable with that, or you just want to proceed to creating your
first Promtimer dashboard by example, feel free to keep reading.

# How the Promtimer Dashboarding Model Works

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

If you run `promtimer` against some cbcollect_info and browse to http://localhost:13300/dashboards,
you'll now find a new dashboard titled "New Dashboard". You can visit this dashboard directly by
navigating to: http://localhost:13300/d/new-dashboard/new-dashboard.

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

## Add a Target Parameterized by Data Source Name

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
              "datasource": "{data-source:name}",
              "expr": "sys_cpu_utilization_rate",
              "legendFormat": "{data-source:name} sys_cpu_utilization_rate",
              "_base": "target"
            }
          ]
        }
      ]
    }

You will notice that the panel now contains one or more time series traces, or targets. Each target
is the `sys_cpu_utilization_rate` for one of the cbcollects against which Promtimer is run. This
happens because the target contains at least one instance of the Promtimer template parameter
`{data-source:name}` which is automatically expanded by Promtimer to add one trace per data source,
or cbcollect.

## Make the Panel Data-Source-Name Parameterized

Add a data-source:name parameter to the panel, as follows:

    {
      "title": "New Dashboard",
      "_base": "dashboard",
      "_panels": [
        {
          "title": "sys_cpu_utilization_rate",
          "datasource": "{data-source:name}",
          "_base": "panel",
          "_targets": [
            {
              "datasource": "{data-source:name}",
              "expr": "sys_cpu_utilization_rate",
              "legendFormat": "{data-source:name} sys_cpu_utilization_rate",
              "_base": "target"
            }
          ]
        }
      ]
    }

You'll notice that adding the data-source:name parameter to the panel caused the template expansion
to occur at the panel level and you now have two panels, one for each data source.



