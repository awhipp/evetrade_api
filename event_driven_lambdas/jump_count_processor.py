import os
import json
import asyncio
from datetime import datetime
import requests
from elasticsearch import Elasticsearch

# Create an Elasticsearch client

es = Elasticsearch(os.environ['ES_HOST'])

def get_route_data_from_esi(start, end, route_type):
    esi_api_route = f'https://esi.evetech.net/latest/route/{start}/{end}/?datasource=tranquility&flag={route_type}'
    print(f'Sending: {esi_api_route}')

    response = requests.get(esi_api_route)
    if response.status_code == 200:
        data = response.json()
        if isinstance(data, list):
            return len(data)
    return -1

def get_doc_ids_from_elasticsearch(start, end):
    route_ids = {}
    search_body = {
        "index": "evetrade_jump_data",
        "size": 10000,
        "body": {
            "query": {
                "bool": {
                    "should": [
                        {"match_phrase": {"route": f"{start}-{end}"}},
                        {"match_phrase": {"route": f"{end}-{start}"}}
                    ]
                }
            }
        }
    }

    response = es.search(index=search_body["index"], body=search_body["body"])
    all_hits = response["hits"]["hits"]

    print(f'Retrieved {len(all_hits)} route IDs.')

    for hit in all_hits:
        doc = hit["_source"]
        id_ = hit["_id"]
        route = doc["route"]
        route_ids[route] = id_

    for route_str in [f"{start}-{end}", f"{end}-{start}"]:
        if route_ids.get(route_str) is None:
            print(f'Route ID not found for {route_str}. Creating new route in Elasticsearch')
            response = es.index(
                index="evetrade_jump_data",
                body={
                    "route": route_str,
                    "insecure": -1,
                    "secure": -1,
                    "shortest": -1,
                    "last_modified": int(datetime.now().timestamp() * 1000),
                },
            )
            route_ids[route_str] = response["_id"]

    return route_ids

async def update_elasticsearch_record(doc_id, start, end, insecure, secure, shortest):
    params = {
        "index": "evetrade_jump_data",
        "id": doc_id,
        "body": {
            "doc": {
                "route": f"{start}-{end}",
                "insecure": insecure,
                "secure": secure,
                "shortest": shortest,
                "last_modified": int(datetime.now().timestamp() * 1000),
            }
        }
    }
    # Update the document
    es.update(index=params["index"], id=params["id"], body=params["body"])

def lambda_handler(event, context):
    print(event)

    # Loop through each record in the event["Records"]
    for record in event["Records"]:
        payload = json.loads(record["body"])
        start = payload["start"]
        end = payload["end"]

        new_insecure = get_route_data_from_esi(start, end, 'insecure')
        new_secure = get_route_data_from_esi(start, end, 'secure')
        new_shortest = get_route_data_from_esi(start, end, 'shortest')

        route_ids = get_doc_ids_from_elasticsearch(start, end)
        for route, doc_id in route_ids.items():
            new_start, new_end = route.split('-')
            asyncio.run(
                update_elasticsearch_record(doc_id, new_start, new_end, new_insecure, new_secure, new_shortest)
            )

            print({
                "start": new_start,
                "end": new_end,
                "insecure": new_insecure,
                "secure": new_secure,
                "shortest": new_shortest,
                "doc_id": doc_id,
            })
