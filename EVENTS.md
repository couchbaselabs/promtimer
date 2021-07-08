## Generating Annotations using Event Logger

Promtimer is able to automatically generate Grafana annotations representing important
events in the cbcollect. Currently this is done using the output of the Event Logger,
which is part of [cbmultimanager](https://github.com/couchbaselabs/cbmultimanager).

To generate the necessary file for Promtimer to use:

* Clone the [cbmultimanager](https://github.com/couchbaselabs/cbmultimanager) repository
* Create a `build` directory in the repo if one doesn't exist and build the Event Logger
  using the following command:

```
go build -o ./build ./cmd/cbeventlog
```

* Once Event Logger is built, generate the relevant `events.log` file using the following
  command, pointing to your cbcollect:

```
./build/cbeventlog cbcollect --path "YOUR/PATH/TO/CBCOLLECT.zip" --node-name cbcollect
```

* A file with the cluster's events should now be generated in the repo directory. Place
  this file in the same directory as the cbcollect you're analyzing and **importantly**
  make sure it is named **`events.log`** as this is currently the filename that Promtimer
  looks for in order to generate annotations
* Enjoy auto-generated annotations! If they need to be rebuilt, delete the `.promtimer`
  directory next to the cbcollect to start Promtimer cleanly
