# EVE TRADE API

The serverless backend API which assists in computation for EVETrade.space

[![Data Ingestion Process](https://github.com/awhipp/evetrade_api/actions/workflows/check_data_sync.yml/badge.svg)](https://github.com/awhipp/evetrade_api/actions/workflows/check_data_sync.yml)

[![API Service Check](https://github.com/awhipp/evetrade_api/actions/workflows/check_endpoints.yml/badge.svg)](https://github.com/awhipp/evetrade_api/actions/workflows/check_endpoints.yml)

[![EVETrade API Tests](https://github.com/awhipp/evetrade_api/actions/workflows/evetrade_api_tests.yml/badge.svg)](https://github.com/awhipp/evetrade_api/actions/workflows/evetrade_api_tests.yml)

# Testing

```
pytest
```

```
pytest --cov=src --cov-report term-missing --cov-report=xml
```