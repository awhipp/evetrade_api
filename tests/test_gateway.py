'''
This file is used to test the API locally.
'''
import pytest

from dotenv import load_dotenv
load_dotenv()

from src.gateway import gateway

def test_get_orders(asyncio_loop) -> None:
    '''
    Test the get orders API.
    '''
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
    result = asyncio_loop.run_until_complete(gateway(params))
    assert len(result) == 0 # type: ignore


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
    params = {
        "rawPath": "/station",
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