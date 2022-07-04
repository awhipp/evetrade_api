import os
import time

from elasticsearch import Elasticsearch

ES_HOST = os.environ['ES_HOST']

def get_recent_values(es, index_name, time):
    query = {
        "query": {
            "bool": {
                "filter": {
                    "range": {
                        "epoch_end": {
                            "gt": time
                        }
                    }
                }
            }
        }
    }

    results = es.search(index=index_name, body=query)
    return results['hits']['hits']

es = Elasticsearch(ES_HOST)

print(f'Getting recent values from {time.time() - 60*10}')

results = get_recent_values(es, 'data_log', time.time() - 60*10)

if len(results) > 0:
    print(f'Found {len(results)} results')
else:
    raise Exception('No new data ingested into Elasticsearch index for the last 10 minutes.')