'''
Serverless Lambda Function which provides profitable
hauling orders for given a given API Request
'''

import sys
import time
import json
import asyncio
import math
import aiohttp
import boto3
from market_data import MarketData

jump_count = {}

def round_up(number):
    '''
    Rounds a value up to the nearest 2 decimal places
    '''
    return math.ceil(number*100)/100

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


def remap_orders(orders, cheaper):
    '''
    Maps to cheaper / expensive by station to ensure one item per station
    '''

    new_orders = {}
    for order in orders:
        type_id = order['type_id']
        station_id = order['location_id']

        # TODO find how to get Citadel Name mapping
        if station_id > 99999999:
            continue

        if type_id not in new_orders:
            new_orders[type_id] = {}

        if station_id not in new_orders[type_id]:
            new_orders[type_id][station_id] = order
        else:
            if order['volume_remain'] > 0: # Bug where API returns orders with 0 volume
                if cheaper and order['price'] < new_orders[type_id][station_id]['price']:
                    new_orders[type_id][station_id] = order
                elif not cheaper and order['price'] > new_orders[type_id][station_id]['price']:
                    new_orders[type_id][station_id] = order

    return new_orders


def remove_mismatch_type_ids(orders):
    '''
    Removes the type IDs that do not align between FROM and TO orders
    '''

    from_keys = list(orders['from'].keys())

    for type_id in from_keys:
        if type_id not in orders['to']:
            del orders['from'][type_id]

    to_keys = list(orders['to'].keys())

    for type_id in to_keys:
        if type_id not in orders['from']:
            del orders['to'][type_id]

    return orders


def get_valid_trades(data, tax, min_profit, min_roi, max_budget, max_weight):
    '''
    Based on given parameters it returns a set of valid trades which meet initial parameters
    '''

    mappings = data['mappings']
    type_id_to_name = mappings['typeIDToName']
    station_id_to_name = mappings['stationIdToName']
    system_id_to_security = mappings['systemIdToSecurity']

    from_orders = data['from']
    to_orders = data['to']

    valid_trades = []
    type_ids = list(from_orders.keys())

    for type_id in type_ids:
        from_stations = from_orders[type_id]
        to_stations = to_orders[type_id]

        from_keys = list(from_stations.keys())
        for from_station in from_keys:
            initial_order = from_orders[type_id][from_station]

            to_keys = list(to_stations.keys())
            for to_station in to_keys:
                closing_order = to_orders[type_id][to_station]
                volume = closing_order['volume_remain'] \
                    if closing_order['volume_remain'] < initial_order['volume_remain'] \
                    else initial_order['volume_remain']

                initial_price = initial_order['price'] * volume
                sale_price = closing_order['price'] * volume * (1-tax)
                profit = sale_price - initial_price

                return_on_investment = (sale_price - initial_price) / initial_price
                weight = type_id_to_name[
                        str(initial_order['type_id'])
                    ]['volume'] * volume
                if (
                    profit > min_profit
                        and return_on_investment >= min_roi
                        and initial_price <= max_budget
                        and weight < max_weight
                    ):
                    new_record = {
                        'Item': type_id_to_name[
                                str(initial_order['type_id'])
                            ]['name'],
                        'From': {
                            'name': station_id_to_name[
                                    str(initial_order['location_id'])
                                ],
                            'system_id': initial_order['system_id'],
                            'rating': system_id_to_security[
                                    str(initial_order['system_id'])
                                ]['rating'],
                            'security_code': system_id_to_security[
                                    str(initial_order['system_id'])
                                ]['security_code']
                        },
                        'Quantity': volume,
                        'Buy Price': initial_order['price'],
                        'Net Costs': volume * initial_order['price'],
                        'Take To': {
                            'name': station_id_to_name[
                                    str(closing_order['location_id'])
                                ],
                            'system_id': closing_order['system_id'],
                            'rating': system_id_to_security[
                                    str(closing_order['system_id'])
                                ]['rating'],
                            'security_code': system_id_to_security[
                                    str(closing_order['system_id'])
                                ]['security_code']
                        },
                        'Sell Price': round_up(closing_order['price']),
                        'Net Sales': round_up(volume * closing_order['price']),
                        'Gross Margin': round_up(
                                volume * (closing_order['price'] - initial_order['price'])
                            ),
                        'Sales Taxes': round_up(volume * (closing_order['price'] * tax / 100)),
                        'Net Profit': round_up(profit),
                        'R.O.I.': f'{round_up(100 * return_on_investment)}%',
                        'Total Volume (m3)': round_up(weight),
                    }

                    valid_trades.append(new_record)

                    jump_count[f'{initial_order["system_id"]}-{closing_order["system_id"]}'] = ''

    return valid_trades

async def get_jump_count(session, from_system, to_system, route_safety):
    '''
    Gets jump count for a particular system to system route
    '''
    base_url = 'https://esi.evetech.net/latest/route/'
    url = f'{base_url}{from_system}/{to_system}/?datasource=tranquility&flag={route_safety}'

    async with session.get(url) as resp:
        data = await resp.json()
        jump_count[f'{from_system}-{to_system}'] =  len(data) - 1

async def get_all_jump_counts(trades, route_safety):
    '''
    Gets all jump counts needed for viable trades
    '''
    async with aiohttp.ClientSession() as session:
        tasks = []
        for routes in jump_count:
            route = routes.split('-')
            tasks.append(
                asyncio.ensure_future(get_jump_count(session, route[0], route[1], route_safety))
            )

        await asyncio.gather(*tasks)

    for trade in trades:
        from_system = trade['From']['system_id']
        to_system = trade['Take To']['system_id']
        trade['Jumps'] = jump_count[f'{from_system}-{to_system}']
        trade['Profit per Jump'] = round_up(float(trade['Net Profit']) / int(trade['Jumps']))

    return trades

def lambda_handler(event, context):
    '''
    Serverless Lambda Handler which is invoked at initialization
    and event body is passed which contains request information from API Gateway
    '''
    print(event, context)

    start_time = time.time()

    queries = event['queryStringParameters']

    sales_tax = 0.08 if 'tax' not in queries else queries['tax']
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
    size = len(data['from']) + len(data['to'])

    print(f'-- {time.time() - start_time} seconds to retrieve {size} orders --')

    data['from'] = remap_orders(data['from'], False if from_type == 'buy' else True)
    data['to'] = remap_orders(data['to'], False if to_type == 'buy' else True)
    data = remove_mismatch_type_ids(data)
    size = len(data['from']) + len(data['to'])

    print(f'-- {time.time() - start_time} seconds to process {size} orders --')

    trades = get_valid_trades(data, sales_tax, min_profit, min_roi, max_budget, max_weight)

    print(f'-- {time.time() - start_time} seconds to get valid {len(trades)} trades --')

    trades = asyncio.run(get_all_jump_counts(trades, route_safety))

    print(f'-- {time.time() - start_time} seconds to apply jump counts to {len(trades)} trades --')

    return {
        'statusCode': 200,
        'body': trades
    }
