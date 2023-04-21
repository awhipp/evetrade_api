'''
This file is used to test the API locally.
'''
from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)

from api.gateway import gateway

def test_get_orders() -> None:
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
    result = gateway(params)

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


def test_get_hauling(mock_boto_sqs) -> None:
    '''
    Test the get hauling API.
    '''
    # ASSIGN
    params = {
        "rawPath": "/hauling",
        "headers": {
            "x-forwarded-for": "127.0.0.1",
            "origin": "https://evetrade.space"
        },
        "queryStringParameters": {
            "from": "10000002",
            "to": "10000043",
            "tax": 0.08,
            "minProfit": 500000,
            "minROI": 0.05,
            "routeSafety": "secure",
            "maxWeight": 30000,
        }
    }

    # ACT
    result = gateway(params)
    
    # ASSERT
    assert len(result) > 0

    valid_keys = [
        'Item ID',
        'Item',
        'From',
        'Quantity',
        'Buy Price',
        'Net Costs',
        'Take To',
        'Sell Price',
        'Net Sales',
        'Gross Margin',
        'Sales Taxes',
        'Net Profit',
        'Jumps',
        'Profit per Jump',
        'Profit Per Item',
        'ROI',
        'Total Volume (m3)'
    ]

    # All orders should have all keys in above list
    for order in result:
        for key in order:
            assert key in valid_keys


def test_get_stations() -> None:
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
    result = gateway(params)

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


def test_get_invalid() -> None:
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
    result = gateway(params)
    assert result == {
        "statusCode": 404,
        "body": "Not found."
    }