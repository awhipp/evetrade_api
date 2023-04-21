'''
Gateway Lambda function for the evetrade.space API which validates requests
and routes them to the appropriate modules.
'''
import os
import json
import asyncio
from typing import Any, Dict, List, Union, Literal

import logging
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)

import redis


redis_client = redis.Redis(
    host=os.environ['REDIS_HOST'],
    port=int(os.environ['REDIS_PORT']),
    password=os.environ['REDIS_PASSWORD'],
)

def decode_env_redis(env_var: str) -> List[str]:
    '''
    Decode a Redis environment variable.
    '''
    return redis_client.get(env_var).decode(encoding='utf-8').replace('\n', '').split(',')

IP_WHITE_LIST: List[str] = decode_env_redis('IP_WHITE_LIST')
IP_BAN_LIST: List[str] = decode_env_redis('IP_BAN_LIST')

RATE_LIMIT_COUNT = int(os.environ['RATE_LIMIT_COUNT'] or 5)
RATE_LIMIT_INTERVAL = int(os.environ['RATE_LIMIT_INTERVAL'] or 60)

# Def ENUM for HTTP status codes
class HTTPStatus:
    '''
    HTTP status codes.
    '''
    WHITELISTED = 100
    OK = 200
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    TOO_MANY_REQUESTS = 429

def check_authorization(headers: dict) -> int:
    '''
    Check if the request is authorized to access the Lambda function.
    '''
    if headers:
        if 'x-forwarded-for' in headers:
            ip_address = headers['x-forwarded-for']
            if ip_address in IP_WHITE_LIST:
                logging.info(f"White Listed IP: {ip_address}")
                return HTTPStatus.WHITELISTED
            elif ip_address in IP_BAN_LIST:
                logging.info(f"Banned IP: {ip_address}")
                return HTTPStatus.UNAUTHORIZED

        for key in headers:
            if key.lower().find('postman') >= 0:
                logging.info(f"Invalid header contains Postman: {key}")
                return HTTPStatus.UNAUTHORIZED

    if 'origin' not in headers:
        logging.info("Origin not in headers.")
        return HTTPStatus.UNAUTHORIZED
    elif 'evetrade.space' not in headers['origin'] and 'evetrade.netlify.app' not in headers['origin']:
        logging.info("Not originating from evetrade.space domain.")
        return HTTPStatus.UNAUTHORIZED
    else:
        return HTTPStatus.OK

def check_rate_limit(headers) -> Union[
        Literal[100], Literal[200], 
        Literal[400], Literal[401], Literal[403], Literal[404], Literal[429]
    ]:
    '''
    Check if the request exceeds the rate limit.
    '''
    receiving_ip = headers['x-forwarded-for']
    rate_limit_key = f'rate_limit:{receiving_ip}'

    # Get the current rate limit count for the IP address
    current_count = redis_client.incr(rate_limit_key)
   
    # If the count is 1, set the expiration time for the key
    if current_count == 1:
        redis_client.expire(rate_limit_key, RATE_LIMIT_INTERVAL)

    # Check if the current count exceeds the rate limit
    logging.info(f"{rate_limit_key} - Current Count: {current_count} of {RATE_LIMIT_COUNT}.")

    concurrent_limit_key = f'concurrent_count_limit:{receiving_ip}'
    concurrent_count = int( redis_client.get(concurrent_limit_key) or 0 )

    # Concurrent Rate Limit (if numerous rate limit hit in short time)
    if current_count > RATE_LIMIT_COUNT:
        concurrent_count = redis_client.incr(concurrent_limit_key)
        logging.info(f"{concurrent_limit_key} - Current Count: {concurrent_count} of {RATE_LIMIT_COUNT * 2} today.")

        if concurrent_count == 1:
            redis_client.expire(concurrent_limit_key, RATE_LIMIT_INTERVAL * 60 * 24)

        if concurrent_count == 10:
            redis_client.expire(concurrent_limit_key, RATE_LIMIT_INTERVAL * 60 * 24 * 7)
            return HTTPStatus.FORBIDDEN
    
    daily_count_key = f'daily_rate_limit:{receiving_ip}'
    daily_count = redis_client.incr(daily_count_key)
    logging.info(f"{daily_count_key} - Current Count: {current_count} of {RATE_LIMIT_COUNT}.")

    # Daily Rate Limit
    if daily_count > RATE_LIMIT_COUNT * RATE_LIMIT_INTERVAL:
        redis_client.expire(concurrent_limit_key, RATE_LIMIT_INTERVAL * 60 * 24 * 1)
        return HTTPStatus.TOO_MANY_REQUESTS

    if concurrent_count >= 10:
        logging.info(f"{concurrent_limit_key} - Concurrent Rate Limit: {concurrent_count} of {RATE_LIMIT_COUNT*2} today.")
        return HTTPStatus.FORBIDDEN
    # Standard Rate Limit in short time
    elif current_count > RATE_LIMIT_INTERVAL:
        return HTTPStatus.TOO_MANY_REQUESTS
    else:
        return HTTPStatus.OK

def gateway (
        request: Dict[str, Any]
) -> Union[Dict[str, Any], List]:
    '''
    Gateway function that routes requests to the appropriate downstream method after validating request
    '''
    authorization = check_authorization(request['headers'])

    if authorization == HTTPStatus.UNAUTHORIZED:
        return {
            'statusCode': HTTPStatus.UNAUTHORIZED,
            'body': 'Unauthorized.'
        }

    rate_limit_exceeded = HTTPStatus.OK if authorization == HTTPStatus.WHITELISTED else check_rate_limit(request['headers'])

    if rate_limit_exceeded == 429:
        logging.info('Rate Limit Exceeded: ' + request['headers']['x-forwarded-for'])
        return {
            'statusCode': 429,
            'body': 'Too Many Requests.'
        }

    if rate_limit_exceeded == 403:
        logging.info('Rate Limit Exceeded 10 times: ' + request['headers']['x-forwarded-for'])
        return {
            'statusCode': 403,
            'body': 'Forbidden.'
        }

    path = request['rawPath']

    if path == '/hauling':
        import api.evetrade.hauling as hauling # pylint: disable=import-outside-toplevel
        return asyncio.run(hauling.get(request))
    elif path == '/station':
        import api.evetrade.station as station # pylint: disable=import-outside-toplevel
        return asyncio.run(station.get(request))
    elif path == '/orders':
        import api.evetrade.orders as orders # pylint: disable=import-outside-toplevel
        return asyncio.run(orders.get(request))
    else:
        return {
            'statusCode': HTTPStatus.NOT_FOUND,
            'body': 'Not found.'
        }

def lambda_handler(
    event: Dict[str, Any],
    context: Any # pylint: disable=unused-argument
) -> str:
    """
    AWS Lambda function that routes incoming requests to the appropriate
    downstream Lambda function based on the rawPath field of the event.
    """
    logging.info(event)

    # TODO implement streaming responses when released for python
    response = gateway(event)
    return json.dumps(response)