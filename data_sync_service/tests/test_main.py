"""
Tests for the main data sync functionality
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import os
import sys

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import (
    get_required_env_vars,
    get_region_ids,
    create_index,
    get_index_with_alias,
    update_alias,
    refresh_index,
    delete_index,
    delete_stale_indices,
    load_orders_to_es
)

class TestEnvironmentVariables:
    """Test environment variable handling"""
    
    def test_get_required_env_vars_success(self, mock_env_vars):
        """Test successful environment variable retrieval"""
        with patch.dict(os.environ, mock_env_vars):
            result = get_required_env_vars()
            assert result['AWS_BUCKET'] == 'test-bucket'
            assert result['ES_ALIAS'] == 'test-alias'
            assert result['ES_HOST'] == 'http://localhost:9200'

    def test_get_required_env_vars_missing(self):
        """Test error when environment variables are missing"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                get_required_env_vars()
            assert "Missing required environment variables" in str(exc_info.value)

class TestRegionIds:
    """Test region ID retrieval"""
    
    @patch('main.requests.get')
    def test_get_region_ids_success(self, mock_get, mock_requests):
        """Test successful region ID retrieval"""
        mock_get.return_value = mock_requests
        
        result = get_region_ids()
        
        assert len(result) == 2
        assert 10000001 in result
        assert 10000002 in result
        mock_get.assert_called_once_with(
            'https://evetrade.s3.amazonaws.com/resources/universeList.json',
            timeout=30
        )

class TestElasticsearchOperations:
    """Test Elasticsearch operations"""
    
    def test_create_index(self, mock_elasticsearch):
        """Test index creation"""
        index_name = "test-index"
        
        result = create_index(mock_elasticsearch, index_name)
        
        assert result == index_name
        mock_elasticsearch.indices.create.assert_called_once_with(
            index=index_name,
            body={"settings": {}}
        )

    def test_get_index_with_alias_exists(self, mock_elasticsearch):
        """Test getting index with existing alias"""
        alias = "test-alias"
        mock_elasticsearch.indices.exists_alias.return_value = True
        mock_elasticsearch.indices.get_alias.return_value = {"test-index": {}}
        
        result = get_index_with_alias(mock_elasticsearch, alias)
        
        assert result == "test-index"
        mock_elasticsearch.indices.exists_alias.assert_called_once_with(name=alias)

    def test_get_index_with_alias_not_exists(self, mock_elasticsearch):
        """Test getting index with non-existing alias"""
        alias = "test-alias"
        mock_elasticsearch.indices.exists_alias.return_value = False
        
        result = get_index_with_alias(mock_elasticsearch, alias)
        
        assert result is None

    def test_update_alias(self, mock_elasticsearch):
        """Test alias update"""
        new_index = "new-index"
        alias = "test-alias"
        
        update_alias(mock_elasticsearch, new_index, alias)
        
        mock_elasticsearch.indices.update_aliases.assert_called_once()
        call_args = mock_elasticsearch.indices.update_aliases.call_args[1]['body']
        assert len(call_args['actions']) == 2
        assert call_args['actions'][0]['remove']['alias'] == alias
        assert call_args['actions'][1]['add']['index'] == new_index

    def test_refresh_index(self, mock_elasticsearch):
        """Test index refresh"""
        index_name = "test-index"
        mock_elasticsearch.indices.exists.return_value = True
        
        refresh_index(mock_elasticsearch, index_name)
        
        mock_elasticsearch.indices.refresh.assert_called_once_with(index=index_name)

    def test_delete_index(self, mock_elasticsearch):
        """Test index deletion"""
        index_name = "test-index"
        mock_elasticsearch.indices.exists.return_value = True
        
        delete_index(mock_elasticsearch, index_name)
        
        mock_elasticsearch.indices.delete.assert_called_once_with(index_name)

    def test_delete_stale_indices(self, mock_elasticsearch):
        """Test deletion of stale indices"""
        protected_indices = ["protected-index"]
        mock_elasticsearch.indices.get_alias.return_value = {
            "protected-index": {},
            "stale-index": {}
        }
        mock_elasticsearch.indices.exists.return_value = True
        
        delete_stale_indices(mock_elasticsearch, protected_indices)
        
        # Should only delete the stale index
        mock_elasticsearch.indices.delete.assert_called_once_with("stale-index")

    @patch('main.helpers.bulk')
    def test_load_orders_to_es(self, mock_bulk, mock_elasticsearch):
        """Test loading orders to Elasticsearch"""
        index_name = "test-index"
        orders = ['{"order": "data"}', '{"order": "data2"}']
        region_id = "10000001"
        
        load_orders_to_es(mock_elasticsearch, index_name, orders, region_id)
        
        mock_bulk.assert_called_once_with(
            mock_elasticsearch,
            orders,
            index=index_name,
            request_timeout=30
        )