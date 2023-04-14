'''
Configuration of Tests
'''

import asyncio
import pytest

@pytest.fixture(scope='session')
def asyncio_loop():
    '''
    Define the asyncio loop.
    '''
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def mock_boto_sqs(mocker):
    '''
    Mock boto SQS client and functions using mocker
    '''
    sqs = mocker.patch('boto3.client')
    sqs.return_value = mocker.MagicMock()
    sqs.return_value.send_message.return_value = {}
