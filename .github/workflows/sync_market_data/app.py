import os
import json
import time
import boto3
import asyncio

from retrying import retry
from datetime import datetime
from market_data import MarketData
from requests_aws4auth import AWS4Auth
from elasticsearch import Elasticsearch, RequestsHttpConnection, helpers

AWS_ACCESS_KEY = os.environ['AWS_ACCESS_KEY']
AWS_SECRET_KEY = os.environ['AWS_SECRET_KEY']
AWS_BUCKET = os.environ['AWS_BUCKET']

ES_ALIAS = os.environ['ES_ALIAS']
ES_HOST = os.environ['ES_HOST']

s3 = boto3.client(
    's3', 
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY
)

awsauth = AWS4Auth(AWS_ACCESS_KEY, AWS_SECRET_KEY, 'us-east-1', 'es')

# Function which pulls mapRegions.json file from S3
# and returns the regionID values as an array
def get_region_ids():

    s3_file = s3.get_object(Bucket=AWS_BUCKET, Key='resources/mapRegions.json')
    s3_file_json = json.loads(s3_file['Body'].read())

    region_ids = []
    for item in s3_file_json:
        region_ids.append(item['regionID'])

    return region_ids

def float_to_percent(float_value):
    return str(round(float_value * 100, 2)) + '%'

# Executes RESTful request against the Eve API to get market data for a given region
# and saves it to the local file system
@retry(stop_max_attempt_number=5, wait_random_min=1000, wait_random_max=5000)
def get_data(region_ids):
    idx = 0

    all_orders = []
    for region_id in region_ids:

        percent_complete = float_to_percent(idx / len(region_ids))
        idx+=1 

        print(f'Getting data for {region_id} ({percent_complete})')

        market_data = MarketData(region_id)

        orders = asyncio.run(market_data.execute_requests())
        all_orders = all_orders + orders

    return all_orders

def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def create_index(es):
    now = datetime.now()
    dt_string = now.strftime("%Y%m%d-%H%M")  

    index_name = f'market-data-{dt_string}'
    print(f'Creating new index {index_name}')

    es_index_settings = {
	    "settings" : {
	        "number_of_shards": 1,
	        "number_of_replicas": 0,
            "index.max_result_window": 2000000
	    }
    }

    es.indices.create(index = index_name, body = es_index_settings)
    return index_name

def load_orders_to_es(es, index_name, all_orders):
    print(f'Ingesting {len(all_orders)} orders into {index_name}')
    helpers.bulk(es, all_orders, index=index_name, chunk_size=10000, request_timeout=30)
    print(f'Ingestion into {index_name} complete')

def get_index_with_alias(es, alias):
    print(f'Getting index with alias {alias}')
    if es.indices.exists_alias(name=alias):
        return (list(es.indices.get_alias(index=alias).keys())[0])
    return None

def update_alias(es, new_index, alias):
    print(f'Removing adding {alias} to {new_index}')
    if new_index and alias:
        es.indices.update_aliases(body={
            "actions": [
                {
                    "remove": {
                        "index": "*",
                        "alias": alias
                    }
                },
                {
                    "add": {
                        "index": new_index,
                        "alias": alias
                    }
                }
            ]
        })

def refresh_index(es, index_name):
    print(f'Refreshing index {index_name}')
    if index_name and es.indices.exists(index_name):
        es.indices.refresh(index=index_name)

def delete_index(es, index_name):
    print(f'Deleting index {index_name}')
    if index_name and es.indices.exists(index_name):
        es.indices.delete(index_name)

start = time.time()

es = Elasticsearch(
    hosts = [{'host': ES_HOST, 'port': 443}],
    http_auth = awsauth,
    use_ssl = True,
    verify_certs = True,
    connection_class = RequestsHttpConnection
)

region_ids = get_region_ids()
all_orders = get_data(region_ids)

index_name = create_index(es)

try:
    load_orders_to_es(es, index_name, all_orders)
    previous_index = get_index_with_alias(es, ES_ALIAS)
    update_alias(es, index_name, ES_ALIAS)
    refresh_index(es, ES_ALIAS)
    delete_index(es, previous_index)

except Exception as e:
    print(e)
    print(f'Error ingesting data into {index_name}. Removing new index.')
    delete_index(es, index_name)
    raise e

end = time.time()
minutes = (end - start) / 60
print(f'Completed in {minutes} minutes.')