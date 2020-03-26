#### 1. couchbase_exporter.py
collects couchbase metrics using the rest api. This is inspired by brunopsoares/prometheus_couchbase_exporter and  brunopsoares/statsmetrics. 
__Usage:__  couchbase_exporter.py -c _couchbase_host:port_ -p _port_to_listen_



#### 2. azure_health_exporter.py
Collects Azure Resource Health metrics using the Azure Rest API. This exporter requires managed identity on the VM it is running. It takes the subscription id as the target parameter. Publish port can be overridden using an environment variable. 
