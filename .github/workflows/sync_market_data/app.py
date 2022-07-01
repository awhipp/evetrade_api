import json
import time
import boto3
import os
from psycopg2 import connect
import asyncio
from market_data import MarketData

AWS_ACCESS_KEY = os.environ['AWS_ACCESS_KEY']
AWS_SECRET_KEY = os.environ['AWS_SECRET_KEY']
AWS_BUCKET = os.environ['AWS_BUCKET']

PG_HOST = os.environ['PG_HOST']
PG_USER = os.environ['PG_USER']
PG_DB = os.environ['PG_DB']
PG_PASSWORD = os.environ['PG_PASSWORD']

s3 = boto3.client(
    's3', 
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY
)

conn = connect (
    dbname = PG_DB,
    user = PG_USER,
    host = PG_HOST,
    password = PG_PASSWORD
)

# Function which pulls mapRegions.json file from S3
# and returns the regionID values as an array
def get_region_ids():

    s3_file = s3.get_object(Bucket=AWS_BUCKET, Key='resources/mapRegions.json')
    s3_file_json = json.loads(s3_file['Body'].read())

    region_ids = []
    for item in s3_file_json:
        region_ids.append(item['regionID'])

    return region_ids

def float_to_percent(float_value):
    return str(round(float_value * 100, 2)) + '%'

# Executes RESTful request against the Eve API to get market data for a given region
# and saves it to the local file system
def get_data(region_ids):
    idx = 0

    print('Flagging orders for later removal...')
    execute_sql(
        generate_update_flag_sql()
    )

    for region_id in region_ids:

        percent_complete = float_to_percent(idx / len(region_ids))
        idx+=1 

        print(f'Getting data for {region_id} ({percent_complete})')

        market_data = MarketData(region_id)

        orders = asyncio.run(market_data.execute_requests())

        orders_to_upsert = []
        total_orders = 0

        for order in orders:
            if 'location_id' in order and order['location_id'] < 99999999:
                new_order = f'( {region_id}, {order["system_id"]}, {order["location_id"]}, {order["is_buy_order"]}, {order["min_volume"]}, {order["volume_remain"]}, {order["volume_total"]}, {order["order_id"]}, {order["price"]}, \'{order["range"]}\', {order["type_id"]}, false )'

                orders_to_upsert.append(new_order)
                total_orders += 1
            
        if total_orders > 0:

            updated_records = execute_sql(
                generate_upsert_sql_from_array(orders_to_upsert)
            )
            print(f'--- {updated_records} records added/updated')

    print('Removing any outdated orders...')
    removed_records = execute_sql(
        generate_removal_sql()
    )
    print(f'--- {removed_records} old records removed')
            

def generate_update_flag_sql():
    sql = f'UPDATE market_data.orders SET flagged = true'
    return sql

def generate_upsert_sql_from_array(array):
    sql = 'INSERT INTO market_data.orders(region_id, system_id, station_id, is_buy_order, min_volume, volume_remain, volume_total, order_id, price, range, type_id, flagged) VALUES '
    sql += ', '.join(array)
    sql += ' ON CONFLICT (order_id) DO UPDATE'
    sql += ' SET region_id = EXCLUDED.region_id, system_id = EXCLUDED.system_id, is_buy_order = EXCLUDED.is_buy_order, min_volume = EXCLUDED.min_volume, ' \
        'volume_remain = EXCLUDED.volume_remain, volume_total = EXCLUDED.volume_total, price = EXCLUDED.price, range = EXCLUDED.range, type_id = EXCLUDED.type_id, ' \
        'flagged = EXCLUDED.flagged;'

    return sql

def generate_removal_sql():
    sql = f'DELETE FROM market_data.orders WHERE flagged = true'
    return sql

# Upserts array into postgres table
def execute_sql(sql):
    cursor = conn.cursor()
    cursor.execute(sql)
    row_count = cursor.rowcount
    conn.commit()
    cursor.close()
    return row_count


start = time.time()

region_ids = get_region_ids()
get_data(region_ids)

end = time.time()
minutes = (end - start) / 60
print(f'Completed in {minutes} minutes')
conn.close()