#!/usr/bin/env python3
import os
import sys
import logging
import ecs_logging
import requests
from elasticsearch import Elasticsearch, helpers
from time import time, sleep
from datetime import datetime
from elasticapm import Client
import elasticapm
import configparser
import json

config = configparser.ConfigParser()
if sys.argv[1:] : 
   file = sys.argv[1:]
else:
   file = 'config.ini'

config.read(file)

client = Client( 
	{
         'SERVICE_NAME':config['APM']['SERVICE_NAME'],
	 'SERVER_URL': config['APM']['SERVER_URL'],
	 'SECRET_TOKEN':config['APM']['SECRET_TOKEN'],
	 'ENVIRONMENT': config['APM']['ENVIRONMENT']
        }
)

__version__ = 0.1

'''
connect to Elastic Cloud Billing API to pull down detailed cluster billing metrics
send them to an elasticsearch cluster for magic
https://www.elastic.co/guide/en/cloud/current/Billing_Costs_Analysis.html
'''

#elasticapm.instrument()
elasticapm.instrumentation.control.instrument()

@elasticapm.capture_span()
def ess_connect(cluster_id, cluster_api_key):
    '''
    Create a connection to Elastic Cloud
    '''

    logger.info('Attempting to create connection to elastic cluster')

    es = Elasticsearch(
        cloud_id = cluster_id,
        api_key = cluster_api_key
    )

    return es

@elasticapm.capture_span()
def get_billing_api(org_id,endpoint, billing_api_key):
    '''
    make a GET request to the billing api
    '''

    logger.info(f'{org_id}-calling billing api with {endpoint}')
    ess_api = 'api.elastic-cloud.com'

    response = requests.get(
        url = f'https://{ess_api}{endpoint}',
        headers = {'Authorization': f'ApiKey  {billing_api_key}'}
    )
    
    elasticapm.set_transaction_outcome(http_status_code=response.status_code) 

    return response

@elasticapm.capture_span()
def pull_org_id(billing_api_key):
    '''
    Get account /api/v1/account info to org_id
    return org_id
    '''

    logger.info(f'Starting pull_org_id')

    # get org_id if it doesn't exist
    account_endp = '/api/v1/account'
    response = get_billing_api(0,account_endp, billing_api_key)

    if response.status_code != 200:
        logger.error(f'pull_org_id returned error {response} {response.reason}')
        # TODO Need to decide what to do in this situation
    else:
        rj = response.json()
        logger.info(rj)
        return rj['id']

@elasticapm.capture_span()
def pull_org_summary(org_id, org_summary_index, now):
    '''
    Get org billing summary including balance
    '''

    logger.info(f'{org_id}-starting pull_org_summary')

    org_summary_endp = f'/api/v1/billing/costs/{org_id}'
    response = get_billing_api(org_id,org_summary_endp, billing_api_key)

    if response.status_code != 200:
        logger.error(f'{org_id}-pull_org_summary returned error {response} {response.reason}')
        return None
    else:
        rj = response.json()
       
        index_date=datetime.today().strftime('%Y-%m-00')

        rj['org_id'] = org_id
        rj['_index'] = org_summary_index+'-'+index_date
        rj['api'] = org_summary_endp
        rj['@timestamp'] = now

        logger.debug(rj)
        return rj

@elasticapm.capture_span()
def pull_deployments( org_id, billing_api_key, deployment_index, now):
    '''
    Pull list of deployments from /api/v1/billing/costs/<org_id>/deployments
    return list of deployments payload
    '''

    logger.info(f'{org_id}-starting pull_deployments')

    # get deployments
    deployments_endp = f'/api/v1/billing/costs/{org_id}/deployments'
    response = get_billing_api(org_id,deployments_endp, billing_api_key)

    if response.status_code != 200:
        payload = []
        logger.error(f'{org_id}-pull_deployments returned error {response} {response.reason}')
        return payload
	#raise
        #TODO something else
    else:
        rj = response.json()

        index_date=datetime.today().strftime('%Y-%m-00') 

        #build deployments payload
        payload = []
        for d in rj['deployments']:
            d['_index'] = deployment_index+'-'+index_date
            d['api'] = deployments_endp
            d['@timestamp'] = now
            d['org_id'] = org_id
            payload.append(d)


        logger.debug(payload)
        return (payload)

@elasticapm.capture_span()
def pull_deployment_itemized(org_id, billing_api_key, deployment_itemized_index, deployment, now):
    '''
    Get the itemized billing for a deployment
    '''

    logger.info(f'{org_id}-starting pull_deployment_itemized')
    # get itemized
    deployment_id = deployment['deployment_id']
    itemized_endp = f'/api/v1/billing/costs/{org_id}/deployments/{deployment_id}/items'
    response = get_billing_api(org_id,itemized_endp, billing_api_key)

    payload = []

    if response.status_code != 200:
        logger.error(f'{org_id}-pull_deployment_itemized returned error {response} {response.reason}')
        #raise
        #TODO something else
    else:
        rj = response.json()

        index_date=datetime.today().strftime('%Y-%m-00')

        #Break apart the itemized items to make aggregating easier
        common = {
                'deployment_id' : deployment['deployment_id'],
                'deployment_name' : deployment['deployment_name'],
                'api' : itemized_endp,
                'org_id' : org_id, 
                '_index' : deployment_itemized_index+'-'+index_date,
                '@timestamp' : now
                }

        # high level costs
        rj['costs'].update(common)
        rj['costs']['bill.type'] = 'costs-summary'
        payload.append(rj['costs'])

        # split out dts and resources line items and add cloud_provider field
        for bt in ('data_transfer_and_storage', 'resources'):
            for item in rj[bt]:
                item['cloud.provider'] = item['sku'].split('.')[0]
                item['bill.type'] = bt
                item.update(common)
                payload.append(item)


    logger.debug(payload)
    return payload

#def gendata():
#    mywords = ['foo', 'bar', 'baz']
#    for word in mywords:
#        yield {
#            "_index": "mywords",
#            "word": word,
#        }

def main(billing_api_key, es, inventory_delay, org_summary_index, deployment_index, deployment_itemized_index):
    '''
    Connect to API to pull organization id from account,needed for billing APIs
    get list of all deployments currently in the account
    pull the billing info for:
    - account summary level
    - deployment summary level
    - deployment itemized level

    index into elastic cluster
    '''

    logger.info(f'Starting main ')

    # Run the billing pulls on the startup
    inventory_last_run = 0


    # get the account org_id
    logger.info(f'calling pull_org_id')
    org_id = pull_org_id(billing_api_key)

    #r=gendata()
    #print(r)
    #helpers.bulk(es,r)

    logger.info(f'Starting main loop')
    while True:
        # This is kinf of a lazy way to do a timer but exactly running on intervals is not super important so here we are

        loop_start_time = time()

        billing_payload = []
        now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
	
        StartTransaction = 0

        inventory_elapsed = time() - inventory_last_run
        if  inventory_elapsed >= inventory_delay:
            client.begin_transaction('script')
            
            # get deployment summary billing
            logger.info(f'{org_id}-calling pull_deployments after {inventory_elapsed} seconds')
            deployments = pull_deployments(org_id, billing_api_key, deployment_index, now)
            if deployments is not None:
               billing_payload.extend(deployments)

            # get organization billing summary
            logger.info(f'{org_id}-calling pull_org_summary')
            org_summary = pull_org_summary(org_id, org_summary_index, now)
            if org_summary is not None:
                billing_payload.append(org_summary)

            # get deployment itimieze billing
            for d in deployments:
                logger.info(f'{org_id}-calling pull_deployment_itemized')
                itemized = pull_deployment_itemized(org_id, billing_api_key, deployment_itemized_index, d, now)
                if itemized is not None:
                   billing_payload.extend(itemized)


            if billing_payload is None or (not billing_payload): 
               loop_duration = time() - loop_start_time
               logger.info(f'{org_id}-loop performed in {loop_duration} seconds')
               inventory_last_run = time()
               client.end_transaction('ess.billing','failure')
               continue	
            else:
              logger.info(f'{org_id}-sending payload to bulk')
              #print(billing_payload)
              response=helpers.bulk(es, billing_payload)
              #print ("\nRESPONSE:", response)
              logger.info(f'{org_id}-Bulk indexing complete')

            loop_duration = time() - loop_start_time
            logger.info(f'{org_id}-loop performed in {loop_duration} seconds')
            inventory_last_run = time()
            client.end_transaction('ess.billing') 
        sleep(1)




if __name__ == '__main__':

    #create var log repository
    path = '/var/log/ess_billing/'
    isExist = os.path.exists(path)

    if not isExist:
    	os.makedirs(path)	

    
    #config = configparser.ConfigParser()
    #config.read('config.ini')

    # ESS Billing
    billing_api_key = config['BILLING_INGEST']['billing_api_key']
    # Destination Elastic info
    es_id  = config['BILLING_INGEST']['billing_es_id']
    es_api = config['BILLING_INGEST']['billing_es_api']

	
    
    logger = logging.getLogger("EssBilling") 
    logger.setLevel(logging.INFO)
    file_handler = logging.handlers.RotatingFileHandler('/var/log/ess_billing/ess_billing'+str(hash(billing_api_key))+'.log',maxBytes=5000000,backupCount=5)
    stream_handler = logging.StreamHandler()
    file_handler.setFormatter(ecs_logging.StdlibFormatter())
    stream_handler.setFormatter(ecs_logging.StdlibFormatter())
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    logger.info('Starting up')

    # ESS Billing
    #billing_api_key = os.getenv('billing_api_key')

    inventory_delay = 600
    
    org_summary_index = 'ess.billing'
    deployment_index = 'ess.billing.deployment'
    deployment_itemized_index = 'ess.billing.deployment.itemized'

    # Destination Elastic info
    #es_id = os.getenv('billing_es_id')
    #es_api = os.getenv('billing_es_api')
    indexName = 'ess_billing'
    es = ess_connect(es_id, es_api)

    # Start main loop
    try:
      main(billing_api_key, es, inventory_delay, org_summary_index, deployment_index, deployment_itemized_index)
    except Exception as e:
      client.capture_exception()
      logger.exception('main crashed %s',e)
      client.end_transaction('ess.billing','failure')


#vim: expandtab tabstop=4
