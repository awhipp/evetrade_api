'''
Service validation GitHub Action
'''
import os
import time
import urllib.request

from elasticsearch import Elasticsearch, RequestsHttpConnection
from urllib3 import Timeout, PoolManager

ES_HOST = os.environ['ES_HOST']
ES_TIMEOUT = int(os.environ.get('ES_TIMEOUT', 30))  # Default timeout is 30 seconds
ES_RETRY_ON_TIMEOUT = os.environ.get('ES_RETRY_ON_TIMEOUT', 'true').lower() == 'true'
ES_RETRIES = int(os.environ.get('ES_RETRIES', 10))

# Create a custom Timeout object
custom_timeout = Timeout(connect=ES_TIMEOUT, read=ES_TIMEOUT)

# Create a custom PoolManager with the custom timeout
custom_pool = PoolManager(timeout=custom_timeout)

# Create the Elasticsearch client with custom timeout settings
es_client = Elasticsearch(
    [ES_HOST],
    connection_class=RequestsHttpConnection,
    timeout=ES_TIMEOUT,
    max_retries=ES_RETRIES,
    retry_on_timeout=ES_RETRY_ON_TIMEOUT,
    http_auth=('user', 'password'),  # Add your authentication if needed
    use_ssl=True,
    verify_certs=True,
    ssl_show_warn=False,
    connection_pool_class=custom_pool
)

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

one_hour_ago = time.time() - (60 * 60)

print(f'Getting most recent document. 10 minutes ago was: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(one_hour_ago))}')

results = get_recent_values('market_data')
last_order_time = int(results[0]['sort'][0])/1000

print(f'Most recent document was from from: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(last_order_time))}')

if time.time() - 60*60 > last_order_time:
    raise Exception('No new data ingested into Elasticsearch index for the last 60 minutes.')

status_code = urllib.request.urlopen('https://evetrade-api.herokuapp.com/').getcode()

if status_code == 200:
    print('EVETrade Data Sync Service is up.')
else:
    raise Exception('EVETrade Data Sync Service is not running.')
