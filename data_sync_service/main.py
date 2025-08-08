'''
Main entry point for the data sync service GitHub action
'''
import os
import sys
import time
from datetime import datetime
import asyncio
import threading
import traceback

# Add the current directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(__file__))

import citadel_data
from market_data import MarketData
from elasticsearch import Elasticsearch, helpers
import requests

def get_required_env_vars():
    '''
    Gets required environment variables and validates they exist
    '''
    required_vars = {
        'AWS_BUCKET': os.environ.get('AWS_BUCKET'),
        'ES_ALIAS': os.environ.get('ES_ALIAS'),
        'ES_HOST': os.environ.get('ES_HOST'),
        'ESI_CLIENT_ID': os.environ.get('ESI_CLIENT_ID'),
        'ESI_SECRET_KEY': os.environ.get('ESI_SECRET_KEY'),
        'ESI_REFRESH_TOKEN': os.environ.get('ESI_REFRESH_TOKEN')
    }
    
    missing_vars = [var for var, value in required_vars.items() if not value]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    return required_vars

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

def get_data(es_client, index_name, region_ids):
    '''
    Gets market data for a given region and saves it to Elasticsearch
    '''
    threads = []
    order_count = 0
    
    try:
        orders = citadel_data.get_citadel_orders()
        load_orders_to_es(es_client, index_name, orders, 'Citadels')
        order_count = len(orders)
    except Exception as e:
        time.sleep(30)
        print(f"Error getting citadel orders: {e}")

    for region_id in region_ids:
        market_data = MarketData(region_id)
        orders = asyncio.run(market_data.execute_requests())

        if len(orders) > 0:
            order_thread = threading.Thread(
                target=load_orders_to_es,
                name=f'Ingesting Orders for {region_id}',
                args=(es_client, index_name, orders, region_id)
            )
            order_thread.start()
            threads.append(order_thread)
            order_count += len(orders)

    for order_thread in threads:
        order_thread.join()

    return order_count

def create_index(es_client, index_name):
    '''
    Creates the index for the data sync service
    '''    
    print(f'Creating new index {index_name}')

    es_index_settings = {
        "settings" : {}
    }

    es_client.indices.create(index = index_name, body = es_index_settings)
    return index_name

def load_orders_to_es(es_client, index_name, all_orders, region_id):
    '''
    Loads a list of orders to the Elasticsearch instance
    '''
    print(f'Ingesting {len(all_orders)} orders from {region_id} into {index_name}')
    helpers.bulk(es_client, all_orders, index=index_name, request_timeout=30)

def get_index_with_alias(es_client, alias):
    '''
    Returns the index name that the alias points to
    '''
    print(f'Getting index with alias {alias}')
    if es_client.indices.exists_alias(name=alias):
        return (list(es_client.indices.get_alias(index=alias).keys())[0])
    return None

def update_alias(es_client, new_index, alias):
    '''
    Updates the alias to point to the new index
    '''
    print(f'Updating alias {alias} to point to {new_index}')
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

def refresh_index(es_client, index_name):
    '''
    Refreshes an index
    '''
    print(f'Refreshing index {index_name}')
    if index_name and es_client.indices.exists(index_name):
        es_client.indices.refresh(index=index_name)

def delete_index(es_client, index_name):
    '''
    Deletes an index from the Elasticsearch instance
    '''
    print(f'Deleting index {index_name}')
    if index_name and es_client.indices.exists(index_name):
        es_client.indices.delete(index_name)

def delete_stale_indices(es_client, protected_indices):
    '''
    Loop through all indices and delete any that are not currently in use
    '''
    indices = es_client.indices.get_alias(index='*')
    for index in indices:
        if index not in protected_indices:
            print(f'Deleting stale index {index}')
            delete_index(es_client, index)

def execute_sync():
    '''
    Executes the data sync process once
    '''
    start = time.time()
    now = datetime.now()

    # Get and validate environment variables
    env_vars = get_required_env_vars()
    
    # Initialize Elasticsearch client
    es_client = Elasticsearch(env_vars['ES_HOST'])

    try:
        index_name = f'market-data-{now.strftime("%Y%m%d-%H%M%S")}'
        print(f'--Executing sync on index {index_name}')

        previous_index = get_index_with_alias(es_client, env_vars['ES_ALIAS'])
        delete_stale_indices(es_client, [
            previous_index, index_name, 'evetrade_jump_data'
        ])
        
        region_ids = get_region_ids()
        create_index(es_client, index_name)
        order_count = get_data(es_client, index_name, region_ids)
        update_alias(es_client, index_name, env_vars['ES_ALIAS'])
        refresh_index(es_client, env_vars['ES_ALIAS'])
        
        end = time.time()
        minutes = round((end - start) / 60, 2)
        print(f'Completed sync in {minutes} minutes. Processed {order_count} orders.')
        
        return True

    except Exception as general_exception:
        print(
            f'Error ingesting data into {index_name}. ' + \
            f'Removing new index. Exception: {str(general_exception)}'
        )
        delete_index(es_client, index_name)
        raise general_exception

def main():
    '''
    Main entry point for the data sync service
    '''
    try:
        print("Starting EVETrade data sync service...")
        success = execute_sync()
        if success:
            print("Data sync completed successfully!")
            sys.exit(0)
        else:
            print("Data sync failed!")
            sys.exit(1)
    except Exception as e:
        print(f'Fatal error in data sync: {str(e)}')
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()