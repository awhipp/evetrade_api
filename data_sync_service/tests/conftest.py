"""
Test configuration for data sync service
"""
import pytest
import os
from unittest.mock import Mock, patch

@pytest.fixture
def mock_env_vars():
    """Mock environment variables for testing"""
    return {
        'AWS_BUCKET': 'test-bucket',
        'ES_ALIAS': 'test-alias',
        'ES_HOST': 'http://localhost:9200',
        'ESI_CLIENT_ID': 'test-client-id',
        'ESI_SECRET_KEY': 'test-secret-key',
        'ESI_REFRESH_TOKEN': 'test-refresh-token'
    }

@pytest.fixture
def mock_elasticsearch():
    """Mock Elasticsearch client"""
    mock_es = Mock()
    mock_es.indices.create.return_value = True
    mock_es.indices.exists.return_value = False
    mock_es.indices.exists_alias.return_value = False
    mock_es.indices.get_alias.return_value = {}
    mock_es.indices.update_aliases.return_value = True
    mock_es.indices.refresh.return_value = True
    mock_es.indices.delete.return_value = True
    return mock_es

@pytest.fixture
def mock_requests():
    """Mock requests for API calls"""
    mock_response = Mock()
    mock_response.json.return_value = {
        "1": {"region": 10000001},
        "2": {"region": 10000002}
    }
    mock_response.status_code = 200
    return mock_response