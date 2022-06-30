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

    def get_initial_market_data(self, url):
        '''
        Gets an initial page of market data (synchronously) in order to get the number of pages
        '''
        response = requests.get(url)
        self.orders = self.orders + response.json()
        self.page_count = int(response.headers['x-pages'])

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

        end_time = time.time() - start_time
        print(
            f'--- {end_time}s ({self.region} = {len(self.orders)} orders) ---'
        )

        return self.orders