import json
from datetime import datetime, timedelta
import requests
import boto3
from statistics import mean

# Initialize AWS S3 and CloudWatch clients
s3 = boto3.client('s3')
cloudwatch = boto3.client('cloudwatch', region_name='us-east-1')

def get_request(url):
    headers = {'User-Agent': 'evetrade-api-lambda'}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error fetching data from {url}: {e}")

def get_security_code(security):
    if security >= 0.5:
        return "high_sec"
    elif 0 < security < 0.5:
        return "low_sec"
    elif security <= 0:
        return "null_sec"
    else:
        return -1

def upload_to_s3(bucket, key, body, content_type):
    upload_params = {
        'Bucket': bucket,
        'Key': key,
        'Body': json.dumps(body),
        'ContentType': content_type
    }

    print(f'Uploading to {upload_params["Bucket"]} {upload_params["Key"]}', end='... ')

    try:
        s3.put_object(**upload_params)
        print('Success!')
    except Exception as e:
        print(f'Failed: {e}')

def calculate_p95(arr):
    mean_value = mean(arr)
    squared_diff = [(k - mean_value) ** 2 for k in arr]
    sum_squared_diff = sum(squared_diff)
    
    return mean_value + (2 * (sum_squared_diff / len(arr)) ** 0.5)

def get_average_lambda_execution_time(lambda_function_name):
    start_time = datetime.now() - timedelta(days=14)
    end_time = datetime.now()

    print(f'Getting average lambda execution time for {lambda_function_name} from {start_time} to {end_time}')

    params = {
        'MetricName': 'Duration',
        'Namespace': 'AWS/Lambda',
        'Statistics': ['Average'],
        'Period': 1440,
        'StartTime': start_time,
        'EndTime': end_time,
        'Dimensions': [
            {'Name': 'FunctionName', 'Value': lambda_function_name}
        ]
    }

    try:
        metric = cloudwatch.get_metric_statistics(**params)['Datapoints']
        durations = [datapoint['Average'] for datapoint in metric]
        return calculate_p95(durations)
    except Exception as e:
        raise RuntimeError(f"Error fetching metric statistics for {lambda_function_name}: {e}")

def lambda_handler(event, context):
    # Get the 95th percentile of lambda execution time for the last 14 days
    api_functions = [
        'evetrade-jump-count-processor',
        'evetrade-synchronize-universe-resources',
        'evetrade_api'
    ]

    function_durations = {}

    for function_name in api_functions:
        duration = get_average_lambda_execution_time(function_name)
        function_durations[function_name] = round(duration, 2)
        print(f'{function_name} average is {round(duration, 2)} seconds')

    upload_to_s3('evetrade', 'resources/functionDurations.json', function_durations, 'application/json')

    # Get data from GitHub resources
    res_endpoint = 'https://api.github.com/repos/awhipp/evetrade_resources/contents/resources'

    print(f'Sending Request to {res_endpoint}')

    try:
        data = get_request(res_endpoint)

        for resource in data:
            body = get_request(resource['download_url'])
            upload_to_s3('evetrade', f"resources/{resource['name']}", body, 'application/json')
    except RuntimeError as e:
        print(f"Error: {e}")