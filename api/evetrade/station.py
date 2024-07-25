'''
Station trading module and logic.
'''
import os
from datetime import datetime
from elasticsearch import Elasticsearch
import redis
import requests
from api.utils.helpers import round_value, remove_mismatch_type_ids\



redis_client = redis.Redis(
    host=os.environ['REDIS_HOST'],
    port=int(os.environ['REDIS_PORT']),
    password=os.environ['REDIS_PASSWORD'],
)

es_client = Elasticsearch([os.getenv('ES_HOST')])

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

    response = es_client.search( # pylint: disable=E1123
        index='market_data',
        scroll='10s',
        size=10000,
        _source=['volume_remain', 'price', 'region_id', 'type_id'],
        body={
            'query': {
                'bool': must_clause
            }
        }
    )

    all_hits = response['hits']['hits']

    scroll_id = response['_scroll_id']
    print(f"Retrieved {len(all_hits)} of {response['hits']['total']['value']} total hits.")

    while response['hits']['total']['value'] != len(all_hits):
        scroll_response = es_client.scroll(scroll_id=scroll_id, scroll='10s') # pylint: disable=E1123
        all_hits = all_hits + scroll_response['hits']['hits']
        print(f"Retrieved {len(all_hits)} of {scroll_response['hits']['total']['value']} total hits.")

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

    for item_id in orders['from']:
        buy_order = orders['from'][item_id][0]
        sell_order = orders['to'][item_id][0]

        sale_price = float(sell_order['price'])
        buy_price = float(buy_order['price'])

        item_sell_tax = sale_price * sales_tax
        item_buy_fee = buy_price * broker_fee
        item_sell_fee = sale_price * broker_fee
        gross_margin = sale_price - buy_price
        item_profit = gross_margin - item_sell_tax - item_buy_fee - item_sell_fee
        item_margin = item_profit / buy_price
        ROI = (sale_price - buy_price) / buy_price

        if margin_limit[0] <= item_margin <= margin_limit[1] and item_profit > profit_limit:
            item_name = type_id_to_name.get(str(item_id))
            if item_name:
                item_volume = redis_client.get(f"{buy_order['region_id']}-{item_id}")
                avg_volume = 0
                if item_volume is not None:
                    avg_volume = item_volume.decode()

                row = {
                    'Item ID': item_id,
                    'Item': item_name['name'],
                    'Buy Price': round_value(buy_price, 2),
                    'Sell Price': round_value(sale_price, 2),
                    'Net Profit': round_value(item_profit, 2),
                    'ROI': f"{round_value(100 * ROI, 2)}%",
                    'Volume': int(avg_volume),
                    'Margin': f"{round_value(100 * item_margin, 2)}%",
                    'Sales Tax': f"{round_value(item_sell_tax, 2)}",
                    'Gross Margin': f"{round_value(gross_margin, 2)}",
                    'Buying Fees': f"{round_value(item_buy_fee, 2)}",
                    'Selling Fees': f"{round_value(item_sell_fee, 2)}",
                    'Region ID': buy_order['region_id']
                }

                station_trades.append(row)

    return station_trades

def get_type_id_mappings() -> dict:
    '''
    Pulls from URL and converts json to dict
    '''
    url = 'https://evetrade.s3.amazonaws.com/resources/typeIDToName.json'
    response = requests.get(url, timeout=30)
    return response.json()


async def get(event: dict) -> list:
    '''
    Get all station trades for a given event request
    '''
    start_time = datetime.now()
    queries = event['queryStringParameters']

    STATION = queries['station']
    SALES_TAX = float(queries.get('tax', 0.045))
    BROKER_FEE = float(queries.get('fee', 0.03))
    MARGINS = list(map(float, queries.get('margins', '0.20,0.40').split(',')))
    MIN_VOLUME = int(queries.get('min_volume', 1000))
    PROFIT_LIMIT = int(queries.get('profit', 1000))

    buy_orders = await get_orders(STATION, True)
    sell_orders = await get_orders(STATION, False)
    orders = remove_mismatch_type_ids(buy_orders, sell_orders)

    orders = await find_station_trades(orders, SALES_TAX, BROKER_FEE, MARGINS, PROFIT_LIMIT)

    orders = list(filter(lambda item: item['Volume'] > MIN_VOLUME, orders))

    print(f"Full analysis took: {(datetime.now() - start_time).total_seconds()} seconds to process.")
    print(f"Found {len(orders)} profitable trades.")

    return orders
