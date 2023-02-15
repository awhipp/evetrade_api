'''
Pulls citadel data from ESI and stores it in the database.
'''
import os
import json
import time
import requests
import urllib3
urllib3.disable_warnings()

from esipy import EsiSecurity


CLIENT_ID = os.getenv('ESI_CLIENT_ID', 'TO BE ADDED')
SECRET_KEY = os.getenv('ESI_SECRET_KEY', 'TO BE ADDED')
CALL_BACK = 'https://evetrade.space'
USER_AGENT = 'EVETrade.space - https://evetrade.space - Structure Market Data Application'
REFRESH_TOKEN = os.getenv('ESI_REFRESH_TOKEN', 'TO BE ADDED'),


security = EsiSecurity(
    redirect_uri=CALL_BACK,
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    headers={'User-Agent': USER_AGENT},
)


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

    while page_idx < total_pages:
        page_idx += 1
        url = f"https://esi.evetech.net/latest/markets/structures/{citadel_id}/?datasource=tranquility&page={page_idx}&token={access_token}"
        response = requests.get(url, timeout=30, verify=False)
        if response.status_code == 200:
            data = response.json()
            total_pages = int(response.headers['X-Pages'])
            citadel_orders += data
        else:
            print(f"Error: {response.status_code} - {response.text}")
            break

    return citadel_orders


def get_all_orders(access_token, citadels):
    '''
    Get all citadel orders
    '''
    print(f"Processing Total Citadels: {len(citadels)}")

    citadel_orders = []
    for idx, citadel in enumerate(citadels):
        citadel_orders += get_citadel_data(access_token, citadel)
        print(f"-- Citadel Order Percentage: {round((idx + 1) / len(citadels) * 100, 2)}%")

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
    
    return best_orders


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
    return orders
