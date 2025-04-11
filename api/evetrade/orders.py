'''
Orders module and logic
'''
import json
from typing import Any, Dict, List
import http.client
import asyncio
import aiohttp
from urllib.parse import urlencode
from datetime import datetime

from api.utils.helpers import round_value

# Connection pool for HTTP requests
_connection_pool = {}
# Cache for order results
_order_cache = {}
_cache_ttl = 300  # 5 minutes TTL

async def retrieve_orders_async(
        item_id: int, region_id: int, station_id: int, order_type: str
    ) -> List[Dict[str, Any]]:
    '''
    Asynchronously retrieve orders from ESI Endpoint for a given item, region and station.
    '''
    # Generate cache key
    cache_key = f"{item_id}:{region_id}:{station_id}:{order_type}"
    
    # Check cache first
    now = datetime.now().timestamp()
    if cache_key in _order_cache and now - _order_cache[cache_key]['timestamp'] < _cache_ttl:
        return _order_cache[cache_key]['data']
    
    params = {
        'datasource': 'tranquility',
        'order_type': order_type,
        'page': 1,
        'type_id': item_id,
    }
    
    url = f"https://esi.evetech.net/latest/markets/{region_id}/orders/?{urlencode(params)}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                orders_data = await response.json()
                filtered_orders = [item for item in orders_data if item['location_id'] == station_id]
                
                trimmed_orders = []
                for order in filtered_orders:
                    trimmed_orders.append({
                        'price': round_value(order['price'], 2),
                        'quantity': round_value(order['volume_remain'], 0)
                    })
                
                # Store in cache
                _order_cache[cache_key] = {
                    'data': trimmed_orders,
                    'timestamp': now
                }
                
                return trimmed_orders
            else:
                # Fallback to sync method if async fails
                return await retrieve_orders(item_id, region_id, station_id, order_type)

async def retrieve_orders(
        item_id: int, region_id: int, station_id: int, order_type: str
    ) -> List[Dict[str, Any]]:
    '''
    Retrieve orders from ESI Endpoint for a given item, region and station.
    '''
    # Generate cache key
    cache_key = f"{item_id}:{region_id}:{station_id}:{order_type}"
    
    # Check cache first
    now = datetime.now().timestamp()
    if cache_key in _order_cache and now - _order_cache[cache_key]['timestamp'] < _cache_ttl:
        return _order_cache[cache_key]['data']
    
    params = {
        'datasource': 'tranquility',
        'order_type': order_type,
        'page': 1,
        'type_id': item_id,
    }
    url = f"https://esi.evetech.net/latest/markets/{region_id}/orders/?{urlencode(params)}"

    # Use connection pool for better performance
    conn_key = 'esi.evetech.net'
    if conn_key not in _connection_pool:
        _connection_pool[conn_key] = http.client.HTTPSConnection('esi.evetech.net', timeout=10)
    
    conn = _connection_pool[conn_key]
    
    try:
        conn.request("GET", url)
        res = conn.getresponse()
        raw_data = res.read().decode('utf-8')
        
        orders = json.loads(raw_data)
        filtered_orders = [item for item in orders if item['location_id'] == station_id]

        trimmed_orders = []
        for order in filtered_orders:
            trimmed_orders.append({
                'price': round_value(order['price'], 2),
                'quantity': round_value(order['volume_remain'], 0)
            })

        # Store in cache
        _order_cache[cache_key] = {
            'data': trimmed_orders,
            'timestamp': now
        }
        
        return trimmed_orders
    except Exception as e:
        print(f"Error retrieving orders: {e}")
        # Create a new connection if the old one failed
        _connection_pool[conn_key] = http.client.HTTPSConnection('esi.evetech.net', timeout=10)
        return []

async def get(event: Dict[str, Any]) -> Dict[str, Any]:
    '''
    Get all orders for a given event request
    '''
    start_time = datetime.now()
    queries = event['queryStringParameters']
    item_id = int(queries['itemId'])
    from_station = queries['from']
    to_station = queries['to']

    from_type = 'buy' if from_station.startswith('buy-') else 'sell'
    to_type = 'sell' if to_station.startswith('sell-') else 'buy'

    from_region_id, from_station_id = map(int, from_station.replace('buy-', '').replace('sell-', '').split(':'))
    to_region_id, to_station_id = map(int, to_station.replace('buy-', '').replace('sell-', '').split(':'))

    # Try the async method first for better performance
    try:
        from_orders_task = asyncio.create_task(retrieve_orders_async(item_id, from_region_id, from_station_id, from_type))
        to_orders_task = asyncio.create_task(retrieve_orders_async(item_id, to_region_id, to_station_id, to_type))
        
        from_orders = await from_orders_task
        to_orders = await to_orders_task
        
        orders = {
            'from': from_orders,
            'to': to_orders,
        }
    except Exception as e:
        print(f"Async retrieval failed, falling back to synchronous: {e}")
        # Fall back to synchronous method if async fails
        orders = {
            'from': await retrieve_orders(item_id, from_region_id, from_station_id, from_type),
            'to': await retrieve_orders(item_id, to_region_id, to_station_id, to_type),
        }

    print(f"Full analysis took: {(datetime.now() - start_time).total_seconds()} seconds to process.")
    print(f"Found {len(orders['from'] + orders['to'])} orders at stations.")

    return orders
