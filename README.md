# EVE TRADE API

The serverless backend API which assists in computation for EVETrade.space.

It has 2 components:

* The core API which is a bundled and deployed AWS Lambda function
* The event driven lambdas which are deployed on AWS Lambda and are triggered by events (time or SQS)

## Status

[![EVETrade API Tests](https://github.com/awhipp/evetrade_api/actions/workflows/evetrade_api_tests.yml/badge.svg)](https://github.com/awhipp/evetrade_api/actions/workflows/evetrade_api_tests.yml)

[![EVETrade API Deploy - Dev](https://github.com/awhipp/evetrade_api/actions/workflows/evetrade_deploy_dev.yml/badge.svg)](https://github.com/awhipp/evetrade_api/actions/workflows/evetrade_deploy_dev.yml)

[![EVETrade API Deploy - Prod](https://github.com/awhipp/evetrade_api/actions/workflows/evetrade_deploy_prod.yml/badge.svg)](https://github.com/awhipp/evetrade_api/actions/workflows/evetrade_deploy_prod.yml)

## Setup

* Python 3.12
* Poetry
* Environment Variables (see .env.example)
* NodeJS 16.x (for event driven lambdas only)
** Soon to be refactored
* In the future will dockerize the entire API stack to allow for easier local development

## Setup and Testing

Install dependencies:

```sh
poetry install --sync
```

Activate the virtual environment:

```sh
poetry shell
```

Running tests:

```sh
pytest
```

Running tests to include coverage report:

```sh
pytest --cov=api --cov-report term-missing --cov-report=xml
```
