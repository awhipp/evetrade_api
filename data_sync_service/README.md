# Data Sync Service

This service runs as a GitHub Action to synchronize Elasticsearch with the EVE ESI API in terms of Market Data. It has been converted from a continuously running Heroku service to a scheduled GitHub Action.

## Features

- Fetches market data from EVE ESI API for all regions
- Retrieves citadel market data using authenticated ESI endpoints
- Processes and stores data in Elasticsearch
- Manages index aliasing for zero-downtime updates
- Handles rate limiting and error recovery

## Requirements

- Python 3.9+ (to support esipy)
- Poetry for dependency management
- Environment variables for configuration

## Environment Variables

Required environment variables:

- `AWS_BUCKET`: S3 bucket containing universe data
- `ES_ALIAS`: Elasticsearch alias for market data
- `ES_HOST`: Elasticsearch host URL
- `ESI_CLIENT_ID`: EVE ESI client ID
- `ESI_SECRET_KEY`: EVE ESI secret key
- `ESI_REFRESH_TOKEN`: EVE ESI refresh token

## Local Development

1. Install Poetry:
   ```bash
   pip install poetry
   ```

2. Install dependencies:
   ```bash
   poetry install
   ```

3. Run tests:
   ```bash
   poetry run pytest tests/ -v
   ```

4. Run the sync (with proper environment variables):
   ```bash
   poetry run python main.py
   ```

## GitHub Action

The service runs automatically as a GitHub Action on:
- Push to main branch (when data_sync_service files change)
- Hourly schedule (cron: '0 * * * *')
- Manual trigger (workflow_dispatch)

The action is defined in `.github/workflows/data_sync_service.yml`.

## Testing

The service includes comprehensive tests covering:
- Environment variable validation
- Market data retrieval and processing
- Citadel data handling
- Elasticsearch operations
- Error handling and edge cases

Run tests with coverage:
```bash
poetry run pytest tests/ -v --cov=. --cov-report=xml
```
