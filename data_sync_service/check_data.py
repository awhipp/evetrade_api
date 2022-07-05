'''
Service validation GitHub Action
'''

import os
import time
import urllib.request

from elasticsearch import Elasticsearch

ES_HOST = os.environ['ES_HOST']

es_client = Elasticsearch(ES_HOST)

def get_recent_values(index_name, limit):
    '''
    Gets the most recent values from the given index
    '''
    query = {
        "query": {
            "bool": {
                "filter": {
                    "range": {
                        "epoch_end": {
                            "gt": limit
                        }
                    }
                }
            }
        }
    }

    hits = es_client.search(index=index_name, body=query)
    return hits['hits']['hits']


print(f'Getting recent values from {time.time() - 60*10}')

results = get_recent_values('data_log', time.time() - 60*10)

if len(results) > 0:
    print(f'Found {len(results)} results')
else:
    raise Exception('No new data ingested into Elasticsearch index for the last 10 minutes.')

status_code = urllib.request.urlopen('https://evetrade-api.herokuapp.com/').getcode()

if status_code == 200:
    print('EVETrade Data Sync Service is up.')
else:
    raise Exception('EVETrade Data Sync Service is not running.')
