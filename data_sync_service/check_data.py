'''
Service validation GitHub Action
'''

import os
import time
import urllib.request

from elasticsearch import Elasticsearch

ES_HOST = os.environ['ES_HOST']

es_client = Elasticsearch(ES_HOST)

def get_recent_values(index_name):
    '''
    Gets the most recent values from the given index
    '''
    query = {
        "size": 1,
        "sort": { "issued": "desc" },
        "query": {
            "match_all": {}   
        }
    }

    hits = es_client.search(index=index_name, body=query)
    return hits['hits']['hits']

ten_minutes_ago = time.time() - (10 * 60)

print(f'Getting most recent document. 10 minutes ago was: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ten_minutes_ago))}')

results = get_recent_values('market_data')
last_order_time = int(results[0]['sort'][0])/1000

print(f'Most recent document was from from: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(last_order_time))}')

if time.time() - 60*10 > last_order_time:
    raise Exception('No new data ingested into Elasticsearch index for the last 10 minutes.')

status_code = urllib.request.urlopen('https://evetrade-api.herokuapp.com/').getcode()

if status_code == 200:
    print('EVETrade Data Sync Service is up.')
else:
    raise Exception('EVETrade Data Sync Service is not running.')
