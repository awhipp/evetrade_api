'''
Serverless Lambda Function which provides profitable
hauling orders for given a given API Request
'''

import sys
import time
import json
import asyncio
import boto3
from market_data import MarketData


def convert_locations(locations, order_type):
    '''
    Converts plaintext string locations and orders into market_data classes
    '''
    individual_locations = locations.split(',')
    converted = {}

    for location in individual_locations:
        if ':' in location:
            split = location.split(':')
            region = int(split[0])
            station = int(split[1])

            if region not in converted:
                converted[region] = []

            converted[region].append(station)
        else:
            converted[location] = []

    market_requests = []

    for region, station_ids in converted.items():
        market_requests.append(MarketData(region, order_type, station_ids))

    return market_requests


async def get_order_data(market_requests, chunk_size):
    '''
    Asynchronously retrives order data for all market data requests
    by chunking the requests accordingly to avoid overworking any
    network bandwidth for the larger queries
    '''
    chunk_requests = [
        market_requests[i:i + chunk_size] for i in range(0, len(market_requests), chunk_size)
    ]

    chunk_count = len(chunk_requests)
    print(f'Processing in {chunk_count} chunks')

    orders = []

    for chunk_idx, chunk in enumerate(chunk_requests):
        tasks = []
        print(f'-- Chunk: #{chunk_idx+1}')
        for market_data in chunk:
            tasks.append(
                asyncio.ensure_future(market_data.execute_requests())
            )

        all_orders = await asyncio.gather(*tasks)

        for order_page in all_orders:
            orders = orders + order_page

    return orders

async def async_order_request(from_locations, from_size, to_locations, to_size):
    '''
    Asynchronously gets all the orders related to the from and to locations
    '''
    tasks = [
        asyncio.ensure_future(initialize_mapping()),
        asyncio.ensure_future(get_order_data(from_locations, from_size)),
        asyncio.ensure_future(get_order_data(to_locations, to_size))
    ]

    data = await asyncio.gather(*tasks)

    return {
        'mappings': data[0],
        'from': data[1],
        'to': data[2]
    }

async def initialize_mapping():
    '''
    Grabs static mapping files that are retrieved from EVE SDE
    and stored on S3 for rapid calculations
    '''
    s3_client = boto3.client(
        's3'
    )

    mapping_data = {
        'typeIDToName': {},
        'stationIdToName': {},
        'systemIdToSecurity': {}
    }

    for s3_file in mapping_data.copy():
        obj = s3_client.get_object(Bucket = 'evetrade', Key = f'resources/{s3_file}.json')
        data = obj['Body'].read().decode('utf-8')
        mapping_data[s3_file] = json.loads(data)

        print(f'- Successfully loaded {s3_file}.json -')

    return mapping_data


def lambda_handler(event, context):
    '''
    Serverless Lambda Handler which is invoked at initialization
    and event body is passed which contains request information from API Gateway
    '''
    print(event, context)

    start_time = time.time()

    queries = event['queryStringParameters']

    sales_tax = 0.08 if 'tax' not in queries else queries
    min_profit = 500000 if 'minProfit' not in queries else queries['minProfit']
    min_roi = 0.04 if 'minROI' not in queries else queries['minROI']
    max_budget = sys.maxsize if 'maxBudget' not in queries else queries['maxBudget']
    max_weight = sys.maxsize if 'maxWeight' not in queries else queries['maxWeight']
    route_safety = 'shortest' if 'routeSafety' not in queries else queries['routeSafety']
    from_type = 'sell' if 'fromType' not in queries else queries['fromType']
    to_type = 'buy' if 'toType' not in queries else queries['toType']

    chunk_size = 10
    from_locations = convert_locations(queries['from'], from_type)
    from_size = chunk_size if len(from_locations) > chunk_size else len(from_locations)
    to_locations = convert_locations(queries['to'], to_type)
    to_size = chunk_size if len(to_locations) > chunk_size else len(to_locations)

    data = asyncio.run(async_order_request(from_locations, from_size, to_locations, to_size))

    print(f'-- {time.time() - start_time} seconds to retrieve orders --')

    return {
        'statusCode': 200,
        'body': len(data['from']) + len(data['to'])
    }

evt = {
    "queryStringParameters": {
      "from": "10000002",
      "to": "10000043",
      "tax": 0.08,
      "minProfit": 500000,
      "minROI": 0.05,
      "routeSafety": "shortest",
      "fromType": "sell",
      "toType": "buy"
    }
  }

lambda_handler(evt, {})
