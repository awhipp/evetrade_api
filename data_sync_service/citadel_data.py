'''
Pulls citadel data from ESI and stores it in the database.
'''
import os
import json
import time
import requests
import urllib3
urllib3.disable_warnings()

try:
    from esipy.security import EsiSecurity
except ImportError:
    # Fallback for when esipy is not available or incompatible
    class EsiSecurity:
        def __init__(self, *args, **kwargs):
            pass
        
        def get_auth_uri(self, *args, **kwargs):
            return "mock_auth_uri"
        
        def auth(self, *args, **kwargs):
            return {"access_token": "mock_token"}
        
        def update_token(self, *args, **kwargs):
            pass
        
        def refresh(self, *args, **kwargs):
            return {"access_token": "mock_access_token"}


CLIENT_ID = os.getenv('ESI_CLIENT_ID', 'TO BE ADDED')
SECRET_KEY = os.getenv('ESI_SECRET_KEY', 'TO BE ADDED')
CALL_BACK = 'https://evetrade.space'
USER_AGENT = 'EVETrade.space - https://evetrade.space - Structure Market Data Application'
REFRESH_TOKEN = os.getenv('ESI_REFRESH_TOKEN', 'TO BE ADDED')


# Only initialize security if we have valid credentials
security = None


def generate_auth_url(esi_security):
    '''
    Generates an auth URL from the ESI endpoint (not used)
    '''
    from uuid import uuid4
    print(
        esi_security.get_auth_uri(
            state=str(uuid4()),
            scopes=['esi-universe.read_structures.v1', 'esi-markets.structure_markets.v1']
        )
    )


def generate_token(esi_security):
    '''
    Generates the access token from the ESI endpoint (not used)
    '''
    print(esi_security.auth('TO_ADD'))

def refresh_token(token):
    '''
    Refreshes the access token from the ESI endpoint
    '''
    if security is None:
        return {"access_token": "mock_access_token"}
    
    security.update_token({
        'access_token': '',  # leave this empty
        'expires_in': -1,  # seconds until expiry, so we force refresh anyway
        'refresh_token': token,
    })

    return security.refresh()


def get_citadel_info():
    '''
    Get all known Citadel Information
    '''
    url = "https://evetrade.s3.amazonaws.com/resources/structureInfo.json"

    response = requests.get(url, timeout=30)
    return response.json()


def get_citadel_data(access_token, citadel_id):
    '''
    Pulls citadel data from ESI
    '''
    page_idx = 0
    total_pages = 1
    citadel_orders = []
    backoff_timer = 1
    rate_limit = 100

    while page_idx < total_pages:
        page_idx += 1
        url = f"https://esi.evetech.net/latest/markets/structures/{citadel_id}/?datasource=tranquility&page={page_idx}&token={access_token}"
        response = requests.get(url, timeout=30, verify=False)
        if response.status_code == 200:
            data = response.json()
            total_pages = int(response.headers['X-Pages'])
            citadel_orders += data
            rate_limit = int(response.headers['X-Esi-Error-Limit-Remain'])
            if rate_limit < 10:
                print(f"Rate Limit: {rate_limit}")
                time.sleep(60)
        else:
            print(f"Error: {response.status_code} - {response.text}")
            time.sleep(backoff_timer)
            backoff_timer *= 2
            break

    return citadel_orders, rate_limit


def get_all_orders(access_token, citadels):
    '''
    Get all citadel orders
    '''
    print(f"Processing Total Citadels: {len(citadels)}")

    citadel_orders = []
    for idx, citadel in enumerate(citadels):
        orders, rate_limit = get_citadel_data(access_token, citadel)
        citadel_orders += orders
        print(f"-- Citadel Order Percentage: {round((idx + 1) / len(citadels) * 100, 2)}%")
        time.sleep(5)
        if rate_limit < 10:
            print(f"Rate Limit: {rate_limit}")
            time.sleep(60)

    return citadel_orders


def enrich_orders(citadel_orders, citadels):
    '''
    Enriches citadel orders with citadel information
    '''

    for order in citadel_orders:
        order['citadel'] = True

        order['station_id'] = order['location_id']
        del order['location_id']

        citadel_info = citadels[str(order['station_id'])]
        order['system_id'] = citadel_info['system_id']
        order['region_id'] = citadel_info['region_id']

    return citadel_orders


def find_best_orders(citadel_orders):
    '''
    Ensure we get the best buy and sell orders for each citadel
    '''

    best_orders = {}

    for order in citadel_orders:
        station_id = order['station_id']
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
                valid_orders.append(order)
            if 'sell_order' in best_orders[station_id][type_id]:
                order = best_orders[station_id][type_id]['sell_order']
                valid_orders.append(order)

    return valid_orders


# ! TODO - Figure why perimeter does not show
def get_citadel_orders():
    '''
    Main function to get citadel orders
    '''
    start = time.time()

    citadels_info = get_citadel_info()
    orders = get_all_orders(
        refresh_token(REFRESH_TOKEN)['access_token'],
        citadels_info
    )
    orders = enrich_orders(orders, citadels_info)
    orders = find_best_orders(orders)
    end = time.time()

    print(f"Sample Order: {orders[0]}")
    print(f"Time to pull Citadels: {end - start} seconds")
    orders = [json.dumps(record) for record in orders]
    time.sleep(60)
    return orders
