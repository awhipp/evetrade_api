'''
This file is used to test the API locally.
'''
import pytest

from dotenv import load_dotenv
load_dotenv()

from api.gateway import gateway

def test_get_orders(asyncio_loop) -> None:
    '''
    Test the get orders API.
    '''

    # ASSIGN
    params = {
        "rawPath": "/orders",
        "headers": {
        "x-forwarded-for": "127.0.0.1",
        "origin": "https://evetrade.space"
        },
        "queryStringParameters": {
        "from": "10000002:60003760",
        "to": "10000043:60008494",
        "itemId": "33697"
        }
    }

    # ACT
    result = asyncio_loop.run_until_complete(gateway(params))

    # ASSERT
    
    valid_keys = [
        'price',
        'quantity'
    ]
    assert len(result['from']) > 0
    for order in result['from']:
        for key in order:
            assert key in valid_keys

    assert len(result['to']) > 0
    for order in result['to']:
        for key in order:
            assert key in valid_keys


def test_get_hauling(asyncio_loop) -> None:
    '''
    Test the get hauling API.
    '''
    params = {
        "rawPath": "/hauling",
        "headers": {
            "x-forwarded-for": "127.0.0.1",
            "origin": "https://evetrade.space"
        },
        "queryStringParameters": {
            "from": "10000002:60003760",
            "to": "10000043:60008494",
            "itemId": "33697"
        }
    }
    result = asyncio_loop.run_until_complete(gateway(params))
    assert len(result) == 0 # type: ignore


def test_get_stations(asyncio_loop) -> None:
    '''
    Test the get stations API.
    '''
    # ASSIGN
    params = {
        "rawPath": "/station",
        "headers": {
            "x-forwarded-for": "127.0.0.1",
            "origin": "https://evetrade.space"
        },
        "queryStringParameters": {
            "station": "60008494",
            "tax": "0.08",
            "fee": "0.03",
            "margins": "0.10,0.20",
            "min_volume": 1000,
            "profit": 1000
        }
    }

    # ACT
    result = asyncio_loop.run_until_complete(gateway(params))

    # ASSERT
    assert len(result) > 0

    valid_keys = [
        'Item ID',
        'Item',
        'Buy Price',
        'Sell Price',
        'Net Profit',
        'ROI',
        'Volume',
        'Margin',
        'Sales Tax',
        'Gross Margin',
        'Buying Fees',
        'Selling Fees',
        'Region ID'
    ]

    
    # All orders should have all keys in above list
    for order in result:
        for key in order:
            assert key in valid_keys


def test_get_invalid(asyncio_loop) -> None:
    '''
    Test the get invalid API.
    '''
    params = {
        "rawPath": "/invalid",
        "headers": {
        "x-forwarded-for": "127.0.0.1",
        "origin": "https://evetrade.space"
        },
        "queryStringParameters": {
        "from": "10000002:60003760",
        "to": "10000043:60008494",
        "itemId": "33697"
        }
    }
    result = asyncio_loop.run_until_complete(gateway(params))
    assert result == {
        "statusCode": 404,
        "body": "Not found."
    }