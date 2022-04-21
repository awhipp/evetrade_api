import sys
import time
import json
import aiohttp
import asyncio
import requests

ESI_ENDPOINT = 'https://esi.evetech.net';

if sys.version_info[0] == 3 and sys.version_info[1] >= 8 and sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
class MarketData:

    def __init__(self, region, order_type, station_ids):
        self.region = region;
        self.order_type = order_type
        self.station_ids = station_ids
        self.orders = []
        self.page_count = -1

    
    def __repr__(self):
        return json.dumps({
            'region': self.region,
            'order_type': self.order_type,
            'station_ids': self.station_ids
        })

    def construct_next_ESI_endpoint(self, idx):
        endpoint =  '%s/latest/markets/%s/orders/?datasource=tranquility&order_type=%s&page=%s' % (ESI_ENDPOINT, self.region, self.order_type, idx)
        return endpoint

    def get_initial_market_data(self, url):
        response = requests.get(url)
        self.orders = self.orders + response.json()
        self.page_count = int(response.headers['x-pages'])

    async def get_market_data(self, session, url):
        async with session.get(url) as resp:
            return await resp.json()                

    async def execute_requests(self):
        start_time = time.time()

        self.get_initial_market_data(self.construct_next_ESI_endpoint(1))

        async with aiohttp.ClientSession() as session:
            
            tasks = []

            for idx in range(2, self.page_count + 1):
                url = self.construct_next_ESI_endpoint(idx)
                tasks.append(asyncio.ensure_future(self.get_market_data(session, url)))

            all_orders = await asyncio.gather(*tasks)

            for order_page in all_orders:
                self.orders = self.orders + order_page

            if len(self.station_ids) > 0:
                self.orders = [item for item in self.orders if item['location_id'] in self.station_ids]
        
        print("--- %s seconds (%s = %s %s orders) ---" % (time.time() - start_time, self.region,  str(len(self.orders)), self.order_type))

        return self.orders
