'''
Hauling trade module and logic.
'''
import json
import os
import time
from datetime import datetime
import boto3
import requests
from elasticsearch import Elasticsearch
from api.utils.helpers import round_value, remove_mismatch_type_ids


type_id_to_name: dict = requests.get(
    'https://evetrade.s3.amazonaws.com/resources/typeIDToName.json', timeout=30
    ).json()
station_id_to_name: dict = requests.get(
    'https://evetrade.s3.amazonaws.com/resources/stationIdToName.json', timeout=30
    ).json()
system_id_to_security = requests.get(
    'https://evetrade.s3.amazonaws.com/resources/systemIdToSecurity.json', timeout=30
    ).json()
structure_info: dict = requests.get(
    'https://evetrade.s3.amazonaws.com/resources/structureInfo.json', timeout=30
    ).json()

jump_count = {}

es_client = Elasticsearch([os.getenv('ES_HOST')])

# Load the SQS SDK for Python
sqs = boto3.client('sqs')

async def send_message(payload: dict) -> None:
    '''
    Sends message to SQS queue to reprocess jump count data if stale.
    '''
    params = {
        'MessageBody': json.dumps(payload),
        'QueueUrl': os.getenv('SQS_QUEUE_URL')
    }

    await sqs.send_message(**params)


async def get_orders(location_string: str, order_type: str, structure_type: str) -> list:
    '''
    Get all orders for a given location and order type from ES.
    '''
    locations = location_string.split(',')

    is_buy_order = order_type == 'buy'

    station_list = []
    region_list = []

    terms_clause = {}
    for location in locations:
        if ':' in location:
            split_location = location.split(':')
            station_list.append(split_location[1])
        else:
            region_list.append(location)

    if station_list:
        terms_clause = {'terms':{
            'station_id': station_list
        }}

    if region_list:
        terms_clause = {'terms':{
            'region_id': region_list
        }}

    must_clause = {
        'must': [
            {
                'term': {
                    'is_buy_order': is_buy_order
                }
            },
            {
                'term': {
                    'min_volume': 1
                }
            },
            terms_clause
        ]
    }

    if structure_type == 'citadel':
        must_clause['must'].append(
            {
                'term': {
                    'citadel': True
                }
            }
        )
    elif structure_type == 'npc':
        must_clause['must'].append(
            {
                'term': {
                    'citadel': False
                }
            }
        )

    all_hits = []
    response = es_client.search(  # pylint: disable=E1123
        index='market_data', 
        scroll='10s', 
        size=10000, 
        _source= ['volume_remain', 'price', 'station_id', 'system_id', 'type_id'], 
        body={
            'query': {
                'bool': must_clause
            }
        }
    )

    all_hits = all_hits + response['hits']['hits']

    scroll_id = response['_scroll_id']
    print(f"Retrieved {len(all_hits)} of {response['hits']['total']['value']} total hits.")

    while response['hits']['total']['value'] != len(all_hits):
        scroll_response = es_client.scroll(  # pylint: disable=E1123
            scroll_id=scroll_id, scroll='10s'
        )
        all_hits = all_hits + scroll_response['hits']['hits']
        print(f"Retrieved {len(all_hits)} of {scroll_response['hits']['total']['value']} total hits.")

    all_orders = []
    for hit in all_hits:
        all_orders.append(hit['_source'])

    return all_orders


async def get_routes(route_safety):
    '''
    Get all routes from ES.
    '''
    should_clause = []

    for route in jump_count:
        should_clause.append({
            'match_phrase': {
                'route': route
            }
        })

    sqs_messages_to_send = []
    chunk_size = 128

    for i in range(0, len(should_clause), chunk_size):
        should_chunk = should_clause[i:i + chunk_size]

        # first we do a search, and specify a scroll timeout
        response = es_client.search( # pylint: disable=E1123
            index='evetrade_jump_data', 
            size=10000, 
            _source=[route_safety, 'route', 'last_modified'], 
            body={
                'query': {
                    'bool': {
                        'should': should_chunk
                    }
                }
            }
        )

        all_hits = response['hits']['hits']
        print(f"Retrieved {len(all_hits)} routes for route chunk.")

        for hit in all_hits:
            doc = hit['_source']
            route = doc['route']
            jumps = doc[route_safety]
            jump_count[route] = jumps

            # If last modified data is 30 days or older then send a message to SQS to check for update
            last_modified = datetime.fromtimestamp(doc['last_modified']/1000)
            now = datetime.now()
            diff_days = (now - last_modified).days

            if diff_days > 30:
                if route not in sqs_messages_to_send:
                    sqs_messages_to_send.append(route)

        print(f"Sending {len(sqs_messages_to_send)} messages to SQS to update routes.")

        for message in sqs_messages_to_send:
            start, end = message.split('-')
            await send_message({
                'start': start,
                'end': end
            })

    return jump_count


def get_station_name(station_id: int) -> str:
    '''
    Returns the name of a station given its ID.
    '''
    if station_id > 99999999:
        return structure_info[str(station_id)]['name']
    return station_id_to_name[str(station_id)]



async def get_valid_trades(from_orders: dict, to_orders: dict, tax: float,
                           min_profit: float, min_roi: float, max_budget: float, max_weight: float,
                           system_security: list) -> list:
    '''
    Returns a list of valid trades given a set of orders.
    '''
    ids = list(from_orders.keys())
    valid_trades = []

    for item_id in ids:
        if str(item_id) in type_id_to_name:
            for initial_order in from_orders[item_id]:
                for closing_order in to_orders[item_id]:
                    try:
                        initial_order_type_id = str(initial_order['type_id'])
                        initial_order_system_id = str(initial_order['system_id'])
                        closing_order_system_id = str(closing_order['system_id'])

                        volume = min(closing_order['volume_remain'], initial_order['volume_remain'])
                        weight = type_id_to_name[initial_order_type_id]['volume'] * volume

                        # If weight is greater than max weight rearrange volume to be less than max weight
                        # Then run conditional checks
                        if weight > max_weight:
                            volume = int((max_weight/ weight) * volume)
                            weight = type_id_to_name[initial_order_type_id]['volume'] * volume

                        initial_price = initial_order['price'] * volume
                        sale_price = closing_order['price'] * volume * (1 - tax)
                        profit = sale_price - initial_price
                        roi = (sale_price - initial_price) / initial_price
                        source_security = system_id_to_security[initial_order_system_id]['security_code']
                        destination_security = system_id_to_security[closing_order_system_id]['security_code']

                        valid_trade = profit >= min_profit and \
                                      roi >= min_roi and \
                                      initial_price <= max_budget and \
                                      weight <= max_weight and \
                                      source_security in system_security and \
                                      destination_security in system_security

                        if valid_trade:
                            new_record = {
                                'Item ID': initial_order_type_id,
                                'Item': type_id_to_name[initial_order_type_id]['name'],
                                'From': {
                                    'name': get_station_name(initial_order['station_id']),
                                    'station_id': initial_order['station_id'],
                                    'system_id': initial_order_system_id,
                                    'rating': system_id_to_security[initial_order_system_id]['rating'],
                                    'citadel': initial_order['station_id'] > 99999999
                                },
                                'Quantity': round_value(volume, 0),
                                'Buy Price': round_value(initial_order['price'], 2),
                                'Net Costs': round_value(volume * initial_order['price'], 2),
                                'Take To': {
                                    'name': get_station_name(closing_order['station_id']),
                                    'station_id': closing_order['station_id'],
                                    'system_id': closing_order_system_id,
                                    'rating': system_id_to_security[closing_order_system_id]['rating'],
                                    'citadel': closing_order['station_id'] > 99999999
                                },
                                'Sell Price': round_value(closing_order['price'], 2),
                                'Net Sales': round_value(volume * closing_order['price'], 2),
                                'Gross Margin': round_value(volume * (closing_order['price'] - initial_order['price']), 2),
                                'Sales Taxes': round_value(volume * (closing_order['price'] * tax / 100), 2),
                                'Net Profit': profit,
                                'Jumps': 0,
                                'Profit per Jump': 0,
                                'Profit Per Item': round_value(profit / volume, 2),
                                'ROI': f"{round_value(100 * roi, 2)}%",
                                'Total Volume (m3)': round_value(weight, 2),
                            }

                            valid_trades.append(new_record)

                            jump_count[f'{initial_order["system_id"]}-{closing_order["system_id"]}'] = ''
                    except Exception as e:
                        print(e)
                        print(f"Error processing trade {initial_order['type_id']} from {initial_order['station_id']} to {closing_order['station_id']}")
                        continue

    return valid_trades

def compare(a, b):
    '''
    Compare two trades by net profit
    '''
    if a['Net Profit'] < b['Net Profit']:
        return -1
    elif a['Net Profit'] > b['Net Profit']:
        return 1
    else:
        return 0

async def get(request) -> list:
    '''
    Get all hauling trades for a given event request
    '''
    startTime = time.time()
    queries = request['queryStringParameters']
    SALES_TAX = float(queries.get('tax', 0.08))
    MIN_PROFIT = float(queries.get('minProfit', 500000))
    MIN_ROI = float(queries.get('minROI', 0.04))
    MAX_BUDGET = float(queries.get('maxBudget', float('inf')))
    MAX_WEIGHT = float(queries.get('maxWeight', float('inf')))
    ROUTE_SAFETY = queries.get('routeSafety', 'secure') # secure, shortest, insecure
    SYSTEM_SECURITY = queries.get('systemSecurity', 'high_sec').split(',')
    STRUCTURE_TYPE = queries.get('structureType', 'both') # citadel, npm, both

    FROM = queries['from']
    TO = queries['to']

    FROM_TYPE = 'buy' if FROM.startswith('buy-') else 'sell'
    TO_TYPE = 'sell' if TO.startswith('sell-') else 'buy'

    FROM = FROM.replace('buy-', '').replace('sell-', '')
    TO = TO.replace('buy-', '').replace('sell-', '')

    orders = {
        'from': await get_orders(FROM, FROM_TYPE, STRUCTURE_TYPE),
        'to': await get_orders(TO, TO_TYPE, STRUCTURE_TYPE)
    }

    # Grab one item per station in each each (cheaper for sell orders, expensive for buy orders)
    # Remove type Ids that do not exist in each side of the trade
    orders = remove_mismatch_type_ids(orders['from'], orders['to'])
    print(f"Retrieval took: {time.time() - startTime} seconds to process.")

    valid_trades = await get_valid_trades(orders['from'], orders['to'], SALES_TAX, MIN_PROFIT, MIN_ROI, MAX_BUDGET, MAX_WEIGHT, SYSTEM_SECURITY)
    print(f"Valid Trades = {len(valid_trades)}")

    print(f"Routes = {len(jump_count.keys())}")

    route_data = await get_routes(ROUTE_SAFETY)

    for _, valid_trade in enumerate(valid_trades):
        system_from = valid_trade['From']['system_id']
        system_to = valid_trade['Take To']['system_id']

        valid_trade['Jumps'] = round_value(route_data[f"{system_from}-{system_to}"], 0)

        if valid_trade['Jumps'] == '':
            print(f"Sending message for empty jumps:{system_from}-{system_to}")
            await send_message({
                'start': system_from,
                'end': system_to,
            })

        if route_data[f"{system_from}-{system_to}"] > 0:
            valid_trade['Profit per Jump'] = round_value(valid_trade['Net Profit'] / int(valid_trade['Jumps']), 2)
        else:
            valid_trade['Profit per Jump'] = round_value(valid_trade['Net Profit'], 2)

        valid_trade['Net Profit'] = round_value(valid_trade['Net Profit'], 2)

    valid_trades = sorted(valid_trades, key=lambda x: x['Net Profit'])

    json_size = len(json.dumps(valid_trades).encode('utf-8'))

    print(f"Truncated Valid Trades = {len(valid_trades)}")
    print(f"Full analysis took {time.time() - startTime} seconds to process.")
    print(f"Final payload size = {json_size/1024/1024} MB")

    return valid_trades
