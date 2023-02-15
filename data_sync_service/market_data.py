'''
market_data module is a helper module for other EVETrade functions
'''
import sys
import time
import json
import asyncio
import aiohttp
import requests


ESI_ENDPOINT = 'https://esi.evetech.net'

if sys.version_info[0] == 3 and sys.version_info[1] >= 8 and sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class MarketData:
    '''
    Market Data class for a given region, order_type, and set of station_ids (optional)
    '''

    def __init__(self, region):
        self.region = region
        self.orders = []
        self.page_count = -1

    def __repr__(self):
        '''
        String representation of a MarketData class
        '''
        return json.dumps({
            'region': self.region
        })

    def construct_next_esi_endpoint(self, idx):
        '''
        Constructs the ESI endpoint for a given region, order_type, and page
        '''
        return  f'{ESI_ENDPOINT}/latest/markets/{self.region}' \
                f'/orders/?datasource=tranquility&order_type=all' \
                f'&page={idx}'

    def get_initial_market_data(self, url):
        '''
        Gets an initial page of market data (synchronously) in order to get the number of pages
        '''
        response = requests.get(url, timeout=30)
        self.orders = self.orders + response.json()
        self.page_count = int(response.headers['x-pages'])

        limit_remain = int(response.headers['X-Esi-Error-Limit-Remain'])

        if limit_remain < 10:
            print(f'WARNING: ESI limit remaining is {limit_remain}')
            time.sleep(5)

    @staticmethod
    async def get_market_data(session, url):
        '''
        Asynchronously requests the market data for a given ESI page
        '''
        async with session.get(url) as resp:
            return await resp.json()

    async def execute_requests(self):
        '''
        Executes all requests for a given market data class
        '''
        self.get_initial_market_data(self.construct_next_esi_endpoint(1))

        async with aiohttp.ClientSession() as session:
            tasks = []

            for idx in range(2, self.page_count + 1):
                url = self.construct_next_esi_endpoint(idx)
                tasks.append(asyncio.ensure_future(self.get_market_data(session, url)))

            all_orders = await asyncio.gather(*tasks)

            for order_page in all_orders:
                self.orders = self.orders + order_page

        best_orders = {}

        for order in self.orders:
            if order['location_id'] > 99999999:
                continue
                
            order['citadel'] = False
            if 'location_id' in order:
                station_id = order['location_id']
                type_id = order['type_id']

                if station_id not in best_orders:
                    best_orders[station_id] = {}
                    best_orders[station_id][type_id] = {}
                elif type_id not in best_orders[station_id]:
                    best_orders[station_id][type_id] = {}

                if order['is_buy_order']:
                    if 'buy_order' not in best_orders[station_id][type_id]:
                        best_orders[station_id][type_id]['buy_order'] = order
                    elif order['price'] > best_orders[station_id][type_id]['buy_order']['price']:
                        best_orders[station_id][type_id]['buy_order'] = order
                else:
                    if 'sell_order' not in best_orders[station_id][type_id]:
                        best_orders[station_id][type_id]['sell_order'] = order
                    elif order['price'] < best_orders[station_id][type_id]['sell_order']['price']:
                        best_orders[station_id][type_id]['sell_order'] = order

        valid_orders = []

        for station_id in best_orders: # pylint: disable=consider-using-dict-items
            for type_id in best_orders[station_id]:
                if 'buy_order' in best_orders[station_id][type_id]:
                    order = best_orders[station_id][type_id]['buy_order']
                    order['station_id'] = order['location_id']
                    order['region_id'] = self.region
                    del order['location_id']
                    valid_orders.append(order)
                if 'sell_order' in best_orders[station_id][type_id]:
                    order = best_orders[station_id][type_id]['sell_order']
                    order['station_id'] = order['location_id']
                    order['region_id'] = self.region
                    del order['location_id']
                    valid_orders.append(order)

        return [json.dumps(record) for record in valid_orders]
