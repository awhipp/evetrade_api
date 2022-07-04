'''
market_data module is a helper module for other EVETrade functions
'''

import sys
import time
import json
import asyncio
import aiohttp
import requests

from retrying import retry

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
            'region': self.region,
            'order_type': self.order_type,
            'station_ids': self.station_ids
        })

    def construct_next_esi_endpoint(self, idx):
        '''
        Constructs the ESI endpoint for a given region, order_type, and page
        '''
        return  f'{ESI_ENDPOINT}/latest/markets/{self.region}' \
                f'/orders/?datasource=tranquility&order_type=all' \
                f'&page={idx}'

    @retry(wait_random_min=3000, wait_random_max=8000, stop_max_attempt_number=5)
    def get_initial_market_data(self, url):
        '''
        Gets an initial page of market data (synchronously) in order to get the number of pages
        '''
        response = requests.get(url)
        self.orders = self.orders + response.json()
        self.page_count = int(response.headers['x-pages'])

        limit_remain = int(response.headers['X-Esi-Error-Limit-Remain'])

        if limit_remain < 10:
            print(f'WARNING: ESI limit remaining is {limit_remain}')
            time.sleep(5)

    @staticmethod
    @retry(wait_random_min=3000, wait_random_max=8000, stop_max_attempt_number=5)
    async def get_market_data(session, url):
        '''
        Asynchronously requests the market data for a given ESI page
        '''
        async with session.get(url) as resp:
            return await resp.json()

    @retry(wait_random_min=3000, wait_random_max=8000, stop_max_attempt_number=5)
    async def execute_requests(self):
        '''
        Executes all requests for a given market data class
        '''
        start_time = time.time()

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

        # TODO for buy orders only keep the most expensive
        # TODO for sell orders only keep the least expensive
        # Cut down 1.1million records

        for order in self.orders:
            if 'location_id' in order and order['location_id'] < 99999999:
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

        for station_id in best_orders:
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
        
        end_time = round(time.time() - start_time, 4)

        if len(self.orders) > 0:
            percentage_of_orders = round((1 - (len(valid_orders) / len(self.orders))) * 100, 2)
            print(
                f'--- {end_time}s ({self.region} = {len(valid_orders)} orders of {len(self.orders)} original orders ({percentage_of_orders}% less)) ---'
            )

        return [json.dumps(record) for record in valid_orders]
