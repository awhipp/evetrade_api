'''
Hauling trade module and logic.
'''
import json
import os
import time
from datetime import datetime
import traceback
import boto3
import requests
from elasticsearch import Elasticsearch
from api.utils.helpers import round_value, remove_mismatch_type_ids, get_resource_from_s3

# Use the new caching mechanism
type_id_to_name = get_resource_from_s3('https://evetrade.s3.amazonaws.com/resources/typeIDToName.json')
station_id_to_name = get_resource_from_s3('https://evetrade.s3.amazonaws.com/resources/stationIdToName.json')
system_id_to_security = get_resource_from_s3('https://evetrade.s3.amazonaws.com/resources/systemIdToSecurity.json')
structure_info = get_resource_from_s3('https://evetrade.s3.amazonaws.com/resources/structureInfo.json')

jump_count = {}

es_client = Elasticsearch([os.getenv('ES_HOST')])

# Load the SQS SDK for Python
sqs = boto3.client('sqs')

def send_message(payload: dict) -> None:
    '''
    Sends message to SQS queue to reprocess jump count data if stale.
    '''
    params = {
        'MessageBody': json.dumps(payload),
        'QueueUrl': os.getenv('SQS_QUEUE_URL')
    }

    sqs.send_message(**params)


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

    # Set a larger size to potentially reduce scroll operations
    page_size = 10000
    all_hits = []
    
    # Use the search_after parameter instead of scroll for better performance
    search_body = {
        'query': {
            'bool': must_clause
        },
        'sort': [
            {'type_id': 'asc'},  # Sort by type_id for consistency
            {'_id': 'asc'}       # Secondary sort by _id for pagination
        ],
        'size': page_size
    }
    
    response = es_client.search(  # pylint: disable=E1123
        index='market_data',
        _source= ['volume_remain', 'price', 'station_id', 'system_id', 'type_id'], 
        body=search_body
    )
    
    total_hits = response['hits']['total']['value']
    current_hits = response['hits']['hits']
    all_hits.extend(current_hits)
    
    print(f"Retrieved {len(all_hits)} of {total_hits} total hits.")
    
    # Continue fetching if necessary using search_after
    while len(all_hits) < total_hits and current_hits:
        # Get the sort values from the last hit for search_after
        last_hit = current_hits[-1]
        search_after = last_hit['sort']
        
        search_body['search_after'] = search_after
        
        response = es_client.search(  # pylint: disable=E1123
            index='market_data',
            _source= ['volume_remain', 'price', 'station_id', 'system_id', 'type_id'], 
            body=search_body
        )
        
        current_hits = response['hits']['hits']
        all_hits.extend(current_hits)
        print(f"Retrieved {len(all_hits)} of {total_hits} total hits.")
        
        # Break if no more hits or we've reached the total
        if not current_hits:
            break

    all_orders = []
    for hit in all_hits:
        all_orders.append(hit['_source'])

    return all_orders


def get_routes(route_safety):
    '''
    Get all routes from ES.
    '''
    # Early return if no routes to query
    if not jump_count:
        return jump_count
        
    should_clause = []

    for route in jump_count:
        should_clause.append({
            'match_phrase': {
                'route': route
            }
        })

    sqs_messages_to_send = []
    chunk_size = 128
    
    # Batch processing to reduce ES round trips
    for i in range(0, len(should_clause), chunk_size):
        should_chunk = should_clause[i:i + chunk_size]
        
        # Use termination-aware search with efficient filter
        search_body = {
            'query': {
                'bool': {
                    'should': should_chunk,
                    'minimum_should_match': 1
                }
            },
            'size': 10000,
            '_source': [route_safety, 'route', 'last_modified']
        }

        response = es_client.search(  # pylint: disable=E1123
            index='evetrade_jump_data', 
            body=search_body
        )

        all_hits = response['hits']['hits']
        print(f"Retrieved {len(all_hits)} routes for route chunk.")
        
        now_timestamp = datetime.now().timestamp() * 1000
        thirty_days_ago = now_timestamp - (30 * 24 * 60 * 60 * 1000)  # 30 days in milliseconds

        # Process all hits in a batch
        for hit in all_hits:
            doc = hit['_source']
            route = doc['route']
            jumps = doc[route_safety]
            jump_count[route] = jumps

            # Check if data is stale using timestamp comparison
            if doc['last_modified'] < thirty_days_ago:
                if route not in sqs_messages_to_send:
                    sqs_messages_to_send.append(route)

        if sqs_messages_to_send:
            print(f"Sending {len(sqs_messages_to_send)} messages to SQS to update routes.")
            
            # Batch send messages to SQS
            for message in sqs_messages_to_send:
                start, end = message.split('-')
                send_message({
                    'start': start,
                    'end': end
                })
                
            # Clear the list after sending
            sqs_messages_to_send = []

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
    
    # Pre-filter type_ids to avoid unnecessary lookups
    valid_ids = [item_id for item_id in ids if str(item_id) in type_id_to_name]
    
    # Pre-compute security checks for systems to avoid repeated lookups
    security_cache = {}
    
    # Batch processing to reduce memory pressure
    batch_size = 100
    
    for i in range(0, len(valid_ids), batch_size):
        batch_ids = valid_ids[i:i+batch_size]
        
        for item_id in batch_ids:
            item_id_str = str(item_id)
            if item_id_str not in type_id_to_name:
                continue
                
            item_volume = type_id_to_name[item_id_str].get('volume', 0)
            if item_volume <= 0:  # Skip items with no volume data
                continue
                
            for initial_order in from_orders[item_id]:
                initial_order_system_id = str(initial_order['system_id'])
                
                # Check source security once per system
                if initial_order_system_id not in security_cache:
                    try:
                        security_cache[initial_order_system_id] = system_id_to_security[initial_order_system_id]['security_code']
                    except KeyError:
                        print(f"Missing security data for system {initial_order_system_id}")
                        continue
                
                source_security = security_cache[initial_order_system_id]
                if source_security not in system_security:
                    continue
                    
                for closing_order in to_orders[item_id]:
                    try:
                        closing_order_system_id = str(closing_order['system_id'])
                        
                        # Check destination security once per system
                        if closing_order_system_id not in security_cache:
                            try:
                                security_cache[closing_order_system_id] = system_id_to_security[closing_order_system_id]['security_code']
                            except KeyError:
                                print(f"Missing security data for system {closing_order_system_id}")
                                continue
                                
                        destination_security = security_cache[closing_order_system_id]
                        if destination_security not in system_security:
                            continue
                            
                        # Early filter to reduce computation
                        if closing_order['price'] <= initial_order['price']:
                            continue

                        # Calculate volume and weight
                        volume = min(closing_order['volume_remain'], initial_order['volume_remain'])
                        weight = item_volume * volume

                        # If weight is greater than max weight adjust volume
                        if weight > max_weight:
                            volume = max_weight / item_volume
                            weight = item_volume * volume
                        
                        quantity = round(volume, 0)
                        if volume <= 0 or weight <= 0 or quantity <= 0:
                            continue

                        # Calculate financials
                        initial_price = initial_order['price'] * volume
                        
                        # Budget check early to avoid unnecessary calculations
                        if initial_price > max_budget:
                            continue
                            
                        sale_price = closing_order['price'] * volume * (1 - tax)
                        profit = sale_price - initial_price
                        
                        # Profit check early
                        if profit < min_profit:
                            continue
                            
                        roi = profit / initial_price
                        
                        # ROI check
                        if roi < min_roi:
                            continue

                        # All checks passed, this is a valid trade
                        initial_order_type_id = str(initial_order['type_id'])
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
                            'Quantity': round_value(quantity, 0),
                            'Buy Price': round_value(initial_order['price'], 2),
                            'Net Costs': round_value(initial_price, 2),
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
                            'Sales Taxes': round_value(volume * closing_order['price'] * tax, 2),
                            'Net Profit': round_value(profit, 2),
                            'Jumps': 0,
                            'Profit per Jump': 0,
                            'Profit Per Item': round_value(profit / volume, 2),
                            'ROI': f"{round_value(100 * roi, 2)}%",
                            'Total Volume (m3)': round_value(weight, 2),
                        }

                        valid_trades.append(new_record)
                        jump_count[f'{initial_order["system_id"]}-{closing_order["system_id"]}'] = ''
                    except Exception as unhandled_exception: # pylint: disable=broad-except
                        traceback.print_exc()
                        print(f"Error processing trade {initial_order['type_id']} from {initial_order['station_id']} to {closing_order['station_id']}")
                        continue

    return valid_trades

def get_nearby_regions(universe_list:dict, region_id: int) -> list:
    '''
    Returns a list of nearby regions given a region id.
    '''
    for key in universe_list:
        if "around" in universe_list[key]:
            if int(region_id) == universe_list[key]["id"]:
                return universe_list[key]["around"]

    return []

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
    SALES_TAX = float(queries.get('tax', 0.075))
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

    if TO == 'nearby':
        universe_list = requests.get(
            'https://evetrade.s3.amazonaws.com/resources/universeList.json', timeout=30
        ).json()
        TO = ','.join(map(str, get_nearby_regions(universe_list, FROM))) + "," + str(FROM)

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

    route_data = get_routes(ROUTE_SAFETY)

    for _, valid_trade in enumerate(valid_trades):
        system_from = valid_trade['From']['system_id']
        system_to = valid_trade['Take To']['system_id']

        valid_trade['Jumps'] = route_data[f"{system_from}-{system_to}"]

        if valid_trade['Jumps'] == '':
            print(f"Sending message for empty jumps:{system_from}-{system_to}")
            send_message({
                'start': system_from,
                'end': system_to,
            })
        elif valid_trade['Jumps'] == -1:
            print(f"Sending message for invalid jumps (-1):{system_from}-{system_to}")
            send_message({
                'start': system_from,
                'end': system_to,
            })
        else:
            round_value(valid_trade['Jumps'], 0)

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
