# ess_billing project

# INTRODUCTION
This project uses Elastic Cloud Billing APIs to get the usage costs of your clusters in a given organization 

**WARNINGs & Remarks:**
* This project is not supported by Elastic
* This project was tested on Elastic 8.6.2 
* This project needs an APM/integration server 
* Elastic Cloud Billing APIs are still in Beta and subject to changes (https://www.elastic.co/guide/en/cloud/current/Billing_Costs_Analysis.html)
* Credits for origin and initial project goes to Jeff Vestal https://github.com/jeffvestal/ess-billing-ingest


# STEP 1 - Elastic Cluster - Set up index templates, ingest pipelines, transform
In your Elastic Cluster, go to the **Dev Tools** and run everything inside the file _ess.billing.elasticsearch.ilm_pipelines_mapping.json_  

# STEP 2 - Elastic Cloud - generate an API key and get your cloud id
## API key
In Elastic Cloud console, generate an API Key (**Features > API keys > Create API key**) and save it next to you.
We will need it later.
This API key is used to fetch the cost metrics of your clusters inside the organisation under which you are logged in Elastic Cloud. 
The cost metrics will be fetched from the service api.elastic-cloud.com 

Let's call it __billing_api_key__
=> We will need it to populate config.ini

## Cloud id
Get the cloud id of the cluster in which the scrapped cost metrics will be ingested 
=> We will need it to populate config.ini , field __billing_es_id__

# STEP 3 - Elastic Cluster - generate an API key , get your APM url and token 
## API key
Inside your Elastic Cluster, go to **Stack Management > API keys > Create API key** and generate a key 
This key will be used by our python script to ingest cost metrics scrapped from api.elastic-cloud.com into the elastic cluster
 
Let's call it __billing_es_api__
=> We will need it to populate config.ini

## APM URL & Token
fetch these information from **Elastic APM integration** in the integration policy under which your APM server is running  
 => We will need them to populate config.ini in the dedicated section of apm 
 
# STEP 4 - VM - setup the python cost metrics scrapping script 
On a linux VM running python 3.x at least, 
* install python packages using pip3 : elasticsearch, requests, elasticapm 
* install _ess-billing-ingest.py_ in the folder of your choice
* install _config.ini_ in the same folder and populate it according previous chapters

And then run it as 
```
nohup /<path to>/ess-billing-ingest.py /<path to>/config.ini >  /dev/null 2>&1
```

# STEP 5 - Elastic Cluster - Import Dashboards
Go to **Stack Management>Kibana>Saved Objects** and import the dashboards in the file _ess.billing.kibana.export.ndjson_

#Known Limitations
* in case of api.elastic-cloud.com timeout, the script will catch the exception and may stop. You will have to launch it again 
* Dashboards can be imported into 8.6.2 only, for versions below, you might get an error from the Elastic Cluster 
* APM is enabled by default for now. ENABLED setting in config.ini is ignored for now 


  
