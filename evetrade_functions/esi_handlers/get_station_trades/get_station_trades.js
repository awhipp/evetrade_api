// Find profitable stations trades at a given station
const https = require('https');
const AWS = require('aws-sdk');
const { Client } = require('@elastic/elasticsearch');

AWS.config.update({region: 'us-east-1'});
const s3 = new AWS.S3();

let typeIDToName, stationIdToName;

/**
 * Generates and executes market data requests based on the requested queries
 * @param {*} location
 * @returns Market Data Mapping which has all the requests executed
 */
async function get_orders(location, is_buy_order) {

    const client = new Client({
        node: process.env.ES_HOST
    });

    const must_clause = {
        'must': [
            {
                'term': {
                    'is_buy_order': is_buy_order
                }
            },
            {
                'term': {
                    'min_volume': 1
                }
            },
            {
                'term':{
                    'station_id': location
                }
            }
        ]
    };

    const search_body = {
        index: 'market_data',
        scroll: '10s',
        size: 10000,
        _source: ['volume_remain', 'price', 'station_id', 'system_id', 'type_id'],
        body: {
            query: {
                'bool': must_clause
            }
        }
    };

    console.log(JSON.stringify(search_body));

    var all_hits = [];
    // first we do a search, and specify a scroll timeout
    const response = await client.search(search_body);

    all_hits = all_hits.concat( response.body.hits.hits);
    

    let scroll_id = response.body._scroll_id;
    console.log(`Retrieved ${all_hits.length} of ${response.body.hits.total.value} total hits.`);

    while (response.body.hits.total.value !== all_hits.length) {
        const scroll_response = await client.scroll({
            scroll_id: scroll_id,
            scroll: '10s'
        });
        all_hits = all_hits.concat(scroll_response.body.hits.hits);
        console.log(`Retrieved ${all_hits.length} of ${scroll_response.body.hits.total.value} total hits.`);
    }

    var all_orders = [];
    all_hits.forEach(function (hit) {
        all_orders.push(hit['_source']);
    });

    return all_orders;
}

/**
 * Round value to 2 decimal and add commas
 */
function round_value(value, amount) {
    return value.toLocaleString("en-US", {
        minimumFractionDigits: amount, 
        maximumFractionDigits: amount
    });
}

/**
 * Removes the type IDs that do not align between FROM and TO orders
 * @param {*} buyArray Buy Orders at given station
 * @param {*} sellArray Sell Orders at given station
 * @returns Subset of all the Ids (should be equal in size)
 */
 function remove_mismatch_type_ids(buyArray, sellArray) {
    const fromOrders = {};
    const toOrders = {};

    for (const order of buyArray) {
        if (!fromOrders[order.type_id]) {
            fromOrders[order.type_id] = [];
        }
        fromOrders[order.type_id].push(order);

    }
    for (const order of sellArray) {
        if (!toOrders[order.type_id]) {
            toOrders[order.type_id] = [];
        }
        toOrders[order.type_id].push(order);
    }

    const fromIds = Object.keys(fromOrders);
    const toIds = Object.keys(toOrders);
    
    for (const id of fromIds) {
        if(toOrders[id] === undefined) {
            delete fromOrders[id];
        }
    }
    
    for (const id of toIds) {
        if(fromOrders[id] === undefined) {
            delete toOrders[id];
        }
    }
    
    console.log(`After: Buy ID Count = ${Object.keys(fromOrders).length} and Sell ID Count = ${Object.keys(toOrders).length}`);

    return {
        'buy': fromOrders,
        'sell': toOrders
    };
}

/**
 * For a given list of orders, find profitable trades within a station
 * @param {*} buy_orders List of currrent buy orders in the station
 * @param {*} sell_orders List of currrent sell orders in the station
 * @returns profitable trades
 */
async function find_station_trades(orders, salesTax, brokerFee, marginLimit, volumeLimit, profitLimit) {
    const station_trades = [];

    for (const itemId in orders.buy) {
        const buyOrder = orders.buy[itemId][0];
        const sellOrder = orders.sell[itemId][0];

        const salePrice = parseFloat(sellOrder.price);
        const buyPrice = parseFloat(buyOrder.price);
        
        const itemSellTax = salePrice * salesTax;
        const itemBuyFee = buyPrice * brokerFee;
        const itemSellFee = salePrice * brokerFee;
        const grossMargin = salePrice - buyPrice;
        const itemProfit = grossMargin - itemSellTax - itemBuyFee - itemSellFee;
        const itemMargin = itemProfit / buyPrice;
        const ROI = (salePrice-buyPrice)/buyPrice;

        if(itemMargin >= marginLimit[0] && itemMargin <= marginLimit[1] && itemProfit > profitLimit){
            const row = {
                'Buy Price': round_value(buyPrice, 2),
                'Sell Price': round_value(salePrice, 2),
                'Item ID': itemId,
                'Region ID': buyOrder.region_id,
                'Name': typeIDToName[itemId].name,
                '1-Day Volume': 0,
                '14-Day Volume': 0,
                '30-Day Volume': 0,
                'Sell Tax': round_value(itemSellTax, 2),
                'Gross Margin':round_value(grossMargin, 2),
                'ROI': round_value(100 * ROI, 2) + '%',
                'Buy Fee': round_value(itemBuyFee, 2),
                'Sell Fee': round_value(itemSellFee, 2)
            }

            station_trades.push(row);
        }
    }

    return station_trades;
}

function get_mappings() {
    const DOWNLOAD_PARAMS = {
        Bucket: 'evetrade',
        Key: `resources/typeIDToName.json`
    };

    s3.getObject(DOWNLOAD_PARAMS).promise()
    .then( data => { 
        console.log(`Successfully retrieved typeIDToName`);
        typeIDToName = JSON.parse(data.Body.toString('utf-8'));
    })
    .catch( err => { console.log(`Failed`, err); });

    DOWNLOAD_PARAMS.Key = `resources/stationIdToName.json`;
    s3.getObject(DOWNLOAD_PARAMS)
    .promise()
    .then( data => { 
        console.log(`Successfully retrieved stationIdToName`);
        stationIdToName = JSON.parse(data.Body.toString('utf-8'));
    })
    .catch( err => { console.log(`Failed`, err); });
    
    // TODO check volume by adding a S3 object during the nightly job that contains the volume data
}

/**
 * Lambda function handler
 * @param {*} event 
 * @param {*} context 
 * @returns Payload of profitable trades
 */
exports.handler = async function(event, context) {
    console.log(event);
    const startTime = new Date();
    const queries = event['queryStringParameters'];

    const STATION = queries['station'];
    const SALES_TAX = queries['tax'] === undefined ? 0.08 : parseFloat(queries['tax']);
    const BROKER_FEE = queries['fee'] === undefined ? 0.03 : parseFloat(queries['fee']);
    const MARGINS = queries['margins'] === undefined ? [0.20, 0.40] : [
        parseFloat(queries['margins'].split(',')[0]), 
        parseFloat(queries['margins'].split(',')[1])
    ];
    const VOLUME = queries['volume'] === undefined ? 1000 : parseInt(queries['volume'], 10);
    const PROFIT_LIMIT = queries['profit'] === undefined ? 1000 : parseInt(queries['profit'], 10);
    
    // Get cached mappings files for easier processing later.
    get_mappings();

    console.log(`Mapping retrieval took: ${(new Date() - startTime) / 1000} seconds to process.`);

    const buy_orders = await get_orders(STATION, true);
    const sell_orders = await get_orders(STATION, false);
    let orders = remove_mismatch_type_ids(buy_orders, sell_orders);

    orders = await find_station_trades(orders, SALES_TAX, BROKER_FEE, MARGINS, VOLUME, PROFIT_LIMIT);

    // orders = await get_volume_data(orders);

    // orders = orders.filter(function(item){
    //     return item['14-Day Volume'] > VOLUME;         
    // });

    console.log(`Full analysis took: ${(new Date() - startTime) / 1000} seconds to process.`);

    return {
        headers: {
          'Access-Control-Allow-Origin': '*'
        },
        body: orders.length
    };
};