import sys
import time
import json
import boto3
import asyncio
from MarketData import MarketData

mapping_data = {}

def convert_locations(locations, order_type):
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

    for region in converted:
        market_requests.append(MarketData(region, order_type, converted[region]))

    return market_requests


async def get_order_data(market_requests, n):
    chunk_requests = [market_requests[i:i + n] for i in range(0, len(market_requests), n)]
    chunk_count = len(chunk_requests)
    print('Processing in %s chunks' % chunk_count)

    orders = []

    for idx, chunk in enumerate(chunk_requests):
        tasks = []
        print('-- Chunk: # %s' % (str(idx+1)))
        for idx in range(0, len(chunk)):
            tasks.append(
                asyncio.ensure_future(chunk[idx].execute_requests())
            )

        all_orders = await asyncio.gather(*tasks)

        for order_page in all_orders:
            orders = orders + order_page

    return orders

async def async_order_request(from_locations, from_size, to_locations, to_size):
    tasks = [
            asyncio.ensure_future(get_order_data(from_locations, from_size)),
            asyncio.ensure_future(get_order_data(to_locations, to_size))
    ]

    all_orders = await asyncio.gather(*tasks)

    return {
        'from': all_orders[0],
        'to': all_orders[1]
    }

async def initialize_mapping():
    s3 = boto3.client()

    mapping_data = {
        'typeIDToName': {},
        'stationIdToName': {},
        'systemIdToSecurity': {}
    }

    for s3_file in mapping_data:
        obj = s3.get_object(Bucket = 'evetrade', Key = 'resources/%s.json' % s3_file)
        data = obj['Body'].read().decode('utf-8')
        mapping_data[s3_file] = json.loads(data)

        print('- Successfully loaded %s.json -' % s3_file)


def lambda_handler(event, context):    
    print(event)

    start_time = time.time()
    queries = event["queryStringParameters"];
    asyncio.run(initialize_mapping())

    print("-- %s seconds to retrieve mapping data --" % (time.time() - start_time))

    SALES_TAX = 0.08 if 'tax' not in queries else queries;
    MIN_PROFIT = 500000 if 'minProfit' not in queries else queries['minProfit'];
    MIN_ROI = 0.04 if 'minROI' not in queries else queries['minROI'];
    MAX_BUDGET = sys.maxsize if 'maxBudget' not in queries else queries['maxBudget'];
    MAX_WEIGHT = sys.maxsize if 'maxWeight' not in queries else queries['maxWeight'];
    ROUTE_SAFETY = 'shortest' if 'routeSafety' not in queries else queries['routeSafety'];
    FROM_TYPE = 'sell' if 'fromType' not in queries else queries['fromType'];
    TO_TYPE = 'buy' if 'toType' not in queries else queries['toType'];
        
    chunk_size = 10
    from_locations = convert_locations(queries['from'], FROM_TYPE)
    from_size = chunk_size if len(from_locations) > chunk_size else len(from_locations)
    to_locations = convert_locations(queries['to'], TO_TYPE)
    to_size = chunk_size if len(to_locations) > chunk_size else len(to_locations)

    orders = asyncio.run(async_order_request(from_locations, from_size, to_locations, to_size))
    
    print("-- %s seconds to retrieve orders --" % (time.time() - start_time))

    return {
        'statusCode': 200,
        'body': len(orders['from']) + len(orders['to'])
    }

event = {
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

lambda_handler(event, {})