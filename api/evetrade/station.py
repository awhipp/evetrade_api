'''
Station trading module and logic.
'''
import os
from datetime import datetime
from elasticsearch import Elasticsearch
import redis
from api.utils.helpers import round_value, remove_mismatch_type_ids, get_resource_from_s3

redis_client = redis.Redis(
    host=os.environ['REDIS_HOST'],
    port=int(os.environ['REDIS_PORT']),
    password=os.environ['REDIS_PASSWORD'],
)

es_client = Elasticsearch([os.getenv('ES_HOST')])

# Use cached type mappings instead of loading them every time
_type_id_mapping_cache = None

async def get_orders(location, is_buy_order) -> list:
    '''
    Get all orders for a given location and order type from ES.
    '''
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
            {
                'term':{
                    'station_id': location
                }
            }
        ]
    }

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
    
    response = es_client.search( # pylint: disable=E1123
        index='market_data',
        _source=['volume_remain', 'price', 'region_id', 'type_id'],
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
        
        response = es_client.search( # pylint: disable=E1123
            index='market_data',
            _source=['volume_remain', 'price', 'region_id', 'type_id'],
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

async def find_station_trades(orders, sales_tax, broker_fee, margin_limit, profit_limit):
    '''
    Find all trades that meet the given criteria.
    '''
    station_trades = []
    type_id_to_name = get_type_id_mappings()
    
    # Use a batch processing approach to reduce memory pressure
    batch_size = 100
    
    # Get all item IDs
    item_ids = list(orders['from'].keys())
    
    # Process in batches
    for i in range(0, len(item_ids), batch_size):
        batch_ids = item_ids[i:i+batch_size]
        
        # Process items in the current batch
        for item_id in batch_ids:
            # Quick filtering for valid items
            if str(item_id) not in type_id_to_name:
                continue
                
            buy_order = orders['from'][item_id][0]
            sell_order = orders['to'][item_id][0]

            # Early filtering to avoid unnecessary calculations
            if float(sell_order['price']) <= float(buy_order['price']):
                continue

            sale_price = float(sell_order['price'])
            buy_price = float(buy_order['price'])

            # Calculate all financial aspects
            item_sell_tax = sale_price * sales_tax
            item_buy_fee = buy_price * broker_fee
            item_sell_fee = sale_price * broker_fee
            gross_margin = sale_price - buy_price
            item_profit = gross_margin - item_sell_tax - item_buy_fee - item_sell_fee
            
            # Early profit check
            if item_profit <= profit_limit:
                continue
                
            item_margin = item_profit / buy_price
            ROI = gross_margin / buy_price
            
            # Check margin thresholds
            if margin_limit[0] <= item_margin <= margin_limit[1]:
                item_name = type_id_to_name.get(str(item_id))
                if item_name:
                    # Use Redis pipeline for efficient batch retrieval
                    region_id = buy_order['region_id']
                    avg_volume = 0
                    item_volume_key = f"{region_id}-{item_id}"
                    
                    item_volume = redis_client.get(item_volume_key)
                    if item_volume is not None:
                        avg_volume = int(item_volume.decode())
                    
                    # Create the trade record with all calculated values
                    row = {
                        'Item ID': item_id,
                        'Item': item_name['name'],
                        'Buy Price': round_value(buy_price, 2),
                        'Sell Price': round_value(sale_price, 2),
                        'Net Profit': round_value(item_profit, 2),
                        'ROI': f"{round_value(100 * ROI, 2)}%",
                        'Volume': avg_volume,
                        'Margin': f"{round_value(100 * item_margin, 2)}%",
                        'Sales Tax': round_value(item_sell_tax, 2),
                        'Gross Margin': round_value(gross_margin, 2),
                        'Buying Fees': round_value(item_buy_fee, 2),
                        'Selling Fees': round_value(item_sell_fee, 2),
                        'Region ID': region_id
                    }
                    station_trades.append(row)

    return station_trades

def get_type_id_mappings() -> dict:
    '''
    Pulls from URL and converts json to dict with caching
    '''
    global _type_id_mapping_cache
    
    if _type_id_mapping_cache is None:
        _type_id_mapping_cache = get_resource_from_s3('https://evetrade.s3.amazonaws.com/resources/typeIDToName.json')
        
    return _type_id_mapping_cache


async def get(event: dict) -> list:
    '''
    Get all station trades for a given event request
    '''
    start_time = datetime.now()
    queries = event['queryStringParameters']

    STATION = queries['station']
    SALES_TAX = float(queries.get('tax', 0.075))
    BROKER_FEE = float(queries.get('fee', 0.03))
    MARGINS = list(map(float, queries.get('margins', '0.20,0.40').split(',')))
    MIN_VOLUME = int(queries.get('min_volume', 1000))
    PROFIT_LIMIT = int(queries.get('profit', 1000))

    # Fetch orders in parallel
    import asyncio
    buy_orders_task = asyncio.create_task(get_orders(STATION, True))
    sell_orders_task = asyncio.create_task(get_orders(STATION, False))
    
    buy_orders = await buy_orders_task
    sell_orders = await sell_orders_task
    
    orders = remove_mismatch_type_ids(buy_orders, sell_orders)

    orders = await find_station_trades(orders, SALES_TAX, BROKER_FEE, MARGINS, PROFIT_LIMIT)

    # Filter by volume more efficiently
    if MIN_VOLUME > 0:
        orders = [order for order in orders if order['Volume'] > MIN_VOLUME]

    print(f"Full analysis took: {(datetime.now() - start_time).total_seconds()} seconds to process.")
    print(f"Found {len(orders)} profitable trades.")

    return orders
