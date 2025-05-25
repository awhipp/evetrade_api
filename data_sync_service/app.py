'''
Data Sync Service which pulls data from the EVE API and loads it into the Elasticsearch instance
'''

import os
import time
from datetime import datetime
import asyncio
import threading
import traceback

import citadel_data

from flask import Flask
from waitress import serve
import requests
from market_data import MarketData
from elasticsearch import Elasticsearch, helpers

AWS_BUCKET = os.environ['AWS_BUCKET']

ES_ALIAS = os.environ['ES_ALIAS']
ES_HOST = os.environ['ES_HOST']

app = Flask(__name__)
es_client = Elasticsearch(ES_HOST)

# Function which pulls universeList.json file from S3
# and returns the regionID values as an array
def get_region_ids():
    '''
    Gets the region IDs from the universeList.json file
    '''
    s3_file_json: dict = requests.get(
        'https://evetrade.s3.amazonaws.com/resources/universeList.json', timeout=30
    ).json()

    region_ids = []
    for item in s3_file_json:
        station = s3_file_json[item]

        if 'region' in station:
            region_ids.append(station['region'])

    region_ids = list(set(region_ids))

    print(f'Getting orders for {len(region_ids)} regions.')

    return region_ids

def get_data(index_name, region_ids):
    '''
    Gets market data for a given region and saves it to the local file system
    '''

    threads = []
    order_count = 0
    
    try:
        orders = citadel_data.get_citadel_orders()
        load_orders_to_es(index_name, orders, 'Citadels')
        order_count = len(orders)
    except Exception as e:
        time.sleep(30)
        print(e)

    for region_id in region_ids:

        market_data = MarketData(region_id)

        orders = asyncio.run(market_data.execute_requests())

        if len(orders) > 0:
            order_thread = threading.Thread(
                target=load_orders_to_es,
                name=f'Ingesting Orders for {region_id}',
                args=(index_name, orders, region_id)
            )
            order_thread.start()
            threads.append(order_thread)
            order_count += len(orders)

    for order_thread in threads:
        order_thread.join()

    return order_count

def create_index(index_name):
    '''
    Creates the index for the data sync service
    '''    

    print(f'Creating new index {index_name}')

    es_index_settings = {
	    "settings" : {}
    }

    es_client.indices.create(index = index_name, body = es_index_settings)
    return index_name

def load_orders_to_es(index_name, all_orders, region_id):
    '''
    Loads a list of orders to the Elasticsearch instance
    '''
    print(f'Ingesting {len(all_orders)} orders from {region_id} into {index_name}')
    helpers.bulk(es_client, all_orders, index=index_name, request_timeout=30)

def get_index_with_alias(alias):
    '''
    Returns the index name that the alias points to
    '''
    print(f'Getting index with alias {alias}')
    if es_client.indices.exists_alias(name=alias):
        return (list(es_client.indices.get_alias(index=alias).keys())[0])
    return None

def update_alias(new_index, alias):
    '''
    Updates the alias to point to the new index
    '''
    print(f'Removing adding {alias} to {new_index}')
    if new_index and alias:
        es_client.indices.update_aliases(body={
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

def refresh_index(index_name):
    '''
    Refreshes an index
    '''
    print(f'Refreshing index {index_name}')
    if index_name and es_client.indices.exists(index_name):
        es_client.indices.refresh(index=index_name)

def delete_index(index_name):
    '''
    Deletes an index from the Elasticsearch instance
    '''
    print(f'Deleting index {index_name}')
    if index_name and es_client.indices.exists(index_name):
        es_client.indices.delete(index_name)

def delete_stale_indices(protected_indices):
    '''
    Loop through all indices and delete any that are not currently in use
    '''
    indices = es_client.indices.get_alias(index='*')
    for index in indices:
        if index not in protected_indices:
            print(f'Deleting stale index {index}')
            delete_index(index)

def execute_sync():
    '''
    Executes the data sync process
    '''
    start = time.time()
    now = datetime.now()


    try:
        index_name = f'market-data-{now.strftime("%Y%m%d-%H%M%S")}'
        print(f'--Executing sync on index {index_name}')

        previous_index = get_index_with_alias(ES_ALIAS)
        delete_stale_indices([
            previous_index, index_name, 'evetrade_jump_data'
        ])
        region_ids = get_region_ids()
        create_index(index_name)
        get_data(index_name, region_ids)
        region_ids = get_region_ids()
        update_alias(index_name, ES_ALIAS)
        refresh_index(ES_ALIAS)
        end = time.time()
        minutes = round((end - start) / 60, 2)
        print(f'Completed in {minutes} minutes.')

        if minutes > 4:
            print(f'WARNING: Execution took {minutes} minutes. Stopping for 3 minutes.')
            time.sleep(60*3)

    except Exception as general_exception:
        print(
            f'Error ingesting data into {index_name}.' + \
            f'Removing new index. Exception: {str(general_exception)}'
        )

        delete_index(index_name)
        raise general_exception


def background_task():
    '''
    Executes the data sync process in the background
    '''
    while True:
        try:
            execute_sync()
        except Exception as general_exception:
            print(f'Error executing sync. Exception: {str(general_exception)}')
            traceback.print_exc()
        finally:
            time.sleep(60)

@app.route("/")
def run():
    '''
    Runs the data sync process
    '''
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
