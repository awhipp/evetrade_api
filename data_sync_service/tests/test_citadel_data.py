"""
Tests for citadel data functionality
"""
import pytest
from unittest.mock import Mock, patch
import sys
import os

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import citadel_data

class TestCitadelData:
    """Test citadel data functionality"""
    
    @patch('citadel_data.requests.get')
    def test_get_citadel_info(self, mock_get):
        """Test getting citadel information"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "123456": {
                "name": "Test Citadel",
                "system_id": 30000142,
                "region_id": 10000001
            }
        }
        mock_get.return_value = mock_response
        
        result = citadel_data.get_citadel_info()
        
        assert "123456" in result
        assert result["123456"]["name"] == "Test Citadel"
        mock_get.assert_called_once_with(
            "https://evetrade.s3.amazonaws.com/resources/structureInfo.json",
            timeout=30
        )

    @patch('citadel_data.security')
    def test_refresh_token(self, mock_security):
        """Test token refresh functionality"""
        token = "test-refresh-token"
        mock_security.refresh.return_value = {"access_token": "new-access-token"}
        
        result = citadel_data.refresh_token(token)
        
        assert result["access_token"] == "new-access-token"
        mock_security.refresh.assert_called_once()

    @patch('citadel_data.requests.get')
    def test_get_citadel_data_success(self, mock_get):
        """Test successful citadel data retrieval"""
        access_token = "test-token"
        citadel_id = "123456"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "order_id": 5234562,
                "location_id": 123456,
                "type_id": 34,
                "is_buy_order": True,
                "price": 100.0,
                "volume_remain": 1000
            }
        ]
        mock_response.headers = {
            'X-Pages': '1',
            'X-Esi-Error-Limit-Remain': '100'
        }
        mock_get.return_value = mock_response
        
        orders, rate_limit = citadel_data.get_citadel_data(access_token, citadel_id)
        
        assert len(orders) == 1
        assert orders[0]["order_id"] == 5234562
        assert rate_limit == 100

    @patch('citadel_data.time.sleep')
    @patch('citadel_data.requests.get')
    def test_get_citadel_data_error(self, mock_get, mock_sleep):
        """Test citadel data retrieval with error"""
        access_token = "test-token"
        citadel_id = "123456"
        
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response
        
        orders, rate_limit = citadel_data.get_citadel_data(access_token, citadel_id)
        
        assert len(orders) == 0
        mock_sleep.assert_called_once_with(1)  # Should sleep on error

    def test_enrich_orders(self):
        """Test order enrichment with citadel information"""
        citadel_orders = [
            {
                "order_id": 5234562,
                "location_id": 123456,
                "type_id": 34,
                "is_buy_order": True,
                "price": 100.0
            }
        ]
        
        citadels = {
            "123456": {
                "system_id": 30000142,
                "region_id": 10000001
            }
        }
        
        result = citadel_data.enrich_orders(citadel_orders, citadels)
        
        assert len(result) == 1
        order = result[0]
        assert order["citadel"] is True
        assert order["station_id"] == 123456
        assert order["system_id"] == 30000142
        assert order["region_id"] == 10000001
        assert "location_id" not in order

    def test_find_best_orders(self):
        """Test finding best buy and sell orders"""
        citadel_orders = [
            {
                "station_id": 123456,
                "type_id": 34,
                "is_buy_order": True,
                "price": 100.0
            },
            {
                "station_id": 123456,
                "type_id": 34,
                "is_buy_order": True,
                "price": 150.0  # Higher buy order - should be selected
            },
            {
                "station_id": 123456,
                "type_id": 34,
                "is_buy_order": False,
                "price": 200.0  # Lower sell order - should be selected
            },
            {
                "station_id": 123456,
                "type_id": 34,
                "is_buy_order": False,
                "price": 250.0
            }
        ]
        
        result = citadel_data.find_best_orders(citadel_orders)
        
        # Should have 2 orders: 1 best buy and 1 best sell
        assert len(result) == 2
        
        # Find the buy and sell orders
        buy_order = next(order for order in result if order['is_buy_order'])
        sell_order = next(order for order in result if not order['is_buy_order'])
        
        # Best buy order should have higher price (150.0)
        assert buy_order['price'] == 150.0
        # Best sell order should have lower price (200.0)
        assert sell_order['price'] == 200.0

    @patch('citadel_data.get_citadel_info')
    @patch('citadel_data.get_all_orders')
    @patch('citadel_data.refresh_token')
    @patch('citadel_data.REFRESH_TOKEN', 'test-token')
    def test_get_citadel_orders_integration(self, mock_refresh, mock_get_all, mock_get_info):
        """Test the main get_citadel_orders function"""
        # Mock the token refresh
        mock_refresh.return_value = {"access_token": "test-token"}
        
        # Mock citadel info
        mock_get_info.return_value = {
            "123456": {
                "system_id": 30000142,
                "region_id": 10000001
            }
        }
        
        # Mock orders
        mock_get_all.return_value = [
            {
                "location_id": 123456,
                "type_id": 34,
                "is_buy_order": True,
                "price": 100.0
            }
        ]
        
        result = citadel_data.get_citadel_orders()
        
        assert len(result) == 1
        # Result should be JSON strings
        assert isinstance(result[0], str)
        
        mock_refresh.assert_called_once_with('test-token')
        mock_get_info.assert_called_once()
        mock_get_all.assert_called_once_with("test-token", mock_get_info.return_value)