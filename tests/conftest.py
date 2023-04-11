import pytest
import asyncio

@pytest.fixture(scope='session')
def asyncio_loop():
    '''
    Define the asyncio loop.
    '''
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()