'''
Orders module and logic
'''
import json
from typing import Any, Dict, List
import http.client
from urllib.parse import urlencode
from datetime import datetime

import logging
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)

from api.utils.helpers import round_value

async def retrieve_orders(
        item_id: int, region_id: int, station_id: int, order_type: str
    ) -> List[Dict[str, Any]]:
    '''
    Retrieve orders from ESI Endpoint for a given item, region and station.
    '''
    params = {
        'datasource': 'tranquility',
        'order_type': order_type,
        'page': 1,
        'type_id': item_id,
    }
    url = f"https://esi.evetech.net/latest/markets/{region_id}/orders/?{urlencode(params)}"

    conn = http.client.HTTPSConnection('esi.evetech.net')
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

    return trimmed_orders

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

    orders = {
        'from': await retrieve_orders(item_id, from_region_id, from_station_id, from_type),
        'to': await retrieve_orders(item_id, to_region_id, to_station_id, to_type),
    }
    logging.info(f"Full analysis took: {(datetime.now() - start_time).total_seconds()} seconds to process.")
    logging.info(f"Found {len(orders['from'] + orders['to'])} orders at stations.")

    return orders
