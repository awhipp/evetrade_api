import os
import json
import time
import boto3
import asyncio
import threading

from flask import Flask
from waitress import serve
from datetime import datetime
from market_data import MarketData
from elasticsearch import Elasticsearch, helpers

AWS_ACCESS_KEY = os.environ['AWS_ACCESS_KEY']
AWS_SECRET_KEY = os.environ['AWS_SECRET_KEY']
AWS_BUCKET = os.environ['AWS_BUCKET']

ES_ALIAS = os.environ['ES_ALIAS']
ES_HOST = os.environ['ES_HOST']

app = Flask(__name__)

s3 = boto3.client(
    's3', 
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY
)

es = Elasticsearch(ES_HOST)

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
def get_data(es, index_name, region_ids):
    idx = 0

    threads = []
    order_count = 0

    for region_id in region_ids:

        percent_complete = float_to_percent(idx / len(region_ids))
        idx+=1

        print(f'Getting data for {region_id} ({percent_complete})')

        market_data = MarketData(region_id)

        orders = asyncio.run(market_data.execute_requests())

        if len(orders) > 0:
            thread = threading.Thread(
                target=load_orders_to_es,
                name=f'Ingesting Orders for {region_id}',
                args=(es, index_name, orders, region_id)
            )
            thread.start()
            threads.append(thread)
            order_count += len(orders)

    for thread in threads:
        thread.join()
    
    print(f'Finished ingesting {order_count} orders')
    return order_count

def create_index(es):
    now = datetime.now()
    dt_string = now.strftime("%Y%m%d-%H%M%S")  

    index_name = f'market-data-{dt_string}'
    print(f'Creating new index {index_name}')

    es_index_settings = {
	    "settings" : {
            "index.max_result_window": 2000000
	    }
    }

    es.indices.create(index = index_name, body = es_index_settings)
    return index_name

def load_orders_to_es(es, index_name, all_orders, region_id):
    print(f'Ingesting {len(all_orders)} orders from {region_id} into {index_name}')
    helpers.bulk(es, all_orders, index=index_name, request_timeout=30)

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

def log(es, record):
    if not es.indices.exists(index='data_log'):
        es.indices.create(index = 'data_log')
    es.index(index='data_log', body=record)

def execute_sync():
    start = time.time()
    start_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    index_name = create_index(es)
    print(f'--Executing sync on index {index_name}')

    try:
        region_ids = get_region_ids()
        order_count = get_data(es, index_name, region_ids)
        previous_index = get_index_with_alias(es, ES_ALIAS)
        update_alias(es, index_name, ES_ALIAS)
        refresh_index(es, ES_ALIAS)
        delete_index(es, previous_index)
        end = time.time()
        minutes = round((end - start) / 60, 2)
        print(f'Completed in {minutes} minutes.')

        log(es, {
            'index_name': index_name,
            'epoch_start': start,
            'epoch_end': end,
            'start_datetime': start_datetime,
            'end_datetime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'time_to_complete': f'{minutes} minutes',
            'number_of_records': order_count,
            'message': 'Success'
        })

        if minutes > 4:
            print(f'WARNING: Execution took {minutes} minutes. Stopping for 1 minute.')
            time.sleep(60)

    except Exception as e:
        print(f'Error ingesting data into {index_name}. Removing new index. Exception: {str(e)}')

        delete_index(es, index_name)
        log(es, {
            'index_name': index_name,
            'epoch_start': start,
            'epoch_end': -1,
            'start_datetime': start_datetime,
            'end_datetime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'time_to_complete': 'N/A',
            'number_of_records': 0,
            'message': f'Failed to ingest data: {str(e)}'
        })
        raise e


def background_task():
    while True:
        try:
            execute_sync()
        except Exception as e:
            print(f'Error executing sync. Exception: {str(e)}')
        finally:
            time.sleep(10)

@app.route("/")
def run():
    return '''
<!doctype html>

<html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">

        <title>EVE Trade Data Sync Service</title>
        <script type="text/javascript">
            !function(a,b,c,d,e,f,g,h){a.RaygunObject=e,a[e]=a[e]||function(){
            (a[e].o=a[e].o||[]).push(arguments)},f=b.createElement(c),g=b.getElementsByTagName(c)[0],
            f.async=1,f.src=d,g.parentNode.insertBefore(f,g),h=a.onerror,a.onerror=function(b,c,d,f,g){
            h&&h(b,c,d,f,g),g||(g=new Error(b)),a[e].q=a[e].q||[],a[e].q.push({
            e:g})}}(window,document,"script","//cdn.raygun.io/raygun4js/raygun.min.js","rg4js");
        </script>
        <script type="text/javascript">
            rg4js('apiKey', 'EfZUQt6fprohatzNdusB2g');
            rg4js('enablePulse', true);
        </script>
    </head>

    <body>
        <h1>EVE Trade Data Sync Service is Running.</h1>
    </body>
</html>
'''

PORT = 8080
if 'PORT' in os.environ:
    PORT = os.environ['PORT']

if __name__ == '__main__':
    thread = threading.Thread(target=background_task)
    thread.daemon = True
    thread.start()
    serve(app, host="0.0.0.0", port=PORT)
