// Compares profitable hailing orders between stations and/or regions (or within the same region)
const AWS = require('aws-sdk');
const { Client } = require('@elastic/elasticsearch');

AWS.config.update({region: 'us-east-1'});
const s3 = new AWS.S3();

let typeIDToName, stationIdToName, systemIdToSecurity;

const jumpCount = {};

const MAX_PAYLOAD_SIZE_BYTES = 5 * 1024 * 1024;
    
const client = new Client({
    node: process.env.ES_HOST
});

/**
* Generates and executes market data requests based on the requested queries
* @param {*} inputList 
* @param {*} orderType 
* @returns Market Data Mapping which has all the requests executed
*/
async function get_orders(locations, orderType) {
    locations = locations.split(',');
    
    const is_buy_order = orderType === 'buy';
    
    const station_list = [];
    const region_list = [];
    
    let terms_clause = '';
    for (const location of locations) {
        if (location.indexOf(':') > -1) {
            let split_location = location.split(':');
            station_list.push(split_location[1]);
        } else {
            region_list.push(location);
        }
    }
    
    if (station_list.length > 0) {
        terms_clause = {'terms':{
            'station_id': station_list
        }};
    }
    
    
    if (region_list.length > 0) {
        terms_clause = {'terms':{
            'region_id': region_list
        }};
    }
    
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
            terms_clause
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
    
    all_hits = all_hits.concat(response.body.hits.hits);
    
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
* Generates and executes route data requests
* @param {*} routeSafety 
* @returns Route Data
*/
async function get_routes(routeSafety) {
    
    const should_clause = [];

    for (const route in jumpCount) {
        should_clause.push({
            'match_phrase': {
                'route': route
            }
        });
    }
    
    const chunkSize = 128;
    for (let i = 0; i < should_clause.length; i += chunkSize) {
        const should_chunk = should_clause.slice(i, i + chunkSize);

        const search_body = {
            index: 'evetrade_jump_data',
            size: 10000,
            _source: [routeSafety, 'route'],
            body: {
                query: {
                    'bool': {
                        'should': should_chunk
                    }
                }
            }
        };
        
        // first we do a search, and specify a scroll timeout
        const response = await client.search(search_body);
        
        const all_hits = response.body.hits.hits;

        console.log(`Retrieved ${all_hits.length} routes of for route chunk.`);
        
        all_hits.forEach(function (hit) {
            const doc = hit['_source'];
            const route = doc['route'];
            const jumps = doc[routeSafety];
            jumpCount[route] = jumps;
        });
    }

    return jumpCount;
}


/**
* Removes the type IDs that do not align between FROM and TO orders
* @param {*} fromArray Orders at the initiating end
* @param {*} toArray Orders at the closing end
* @returns Subset of all the Ids (should be equal in size)
*/
function remove_mismatch_type_ids(fromArray, toArray) {
    const fromOrders = {};
    const toOrders = {};
    
    for (const order of fromArray) {
        if (!fromOrders[order.type_id]) {
            fromOrders[order.type_id] = [];
        }
        fromOrders[order.type_id].push(order);
        
    }
    for (const order of toArray) {
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
    
    console.log(`After: From ID Count = ${Object.keys(fromOrders).length} and To ID Count = ${Object.keys(toOrders).length}`);
    
    return {
        'from': fromOrders,
        'to': toOrders
    };
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
* Based on given parameters it returns a set of valid trades which meet initial parameters
* @param {*} fromOrders Originating orders
* @param {*} toOrders Closing orders
* @param {*} tax Tax rate
* @param {*} minProfit Minimum Profit
* @param {*} minROI Minimum ROI 
* @param {*} maxBudget Maximum Budget
* @param {*} maxWeight Maximum Weight
* @param {*} systemSecurity Security of the system
* @param {*} routeSafety Route Preference
* @returns Map of valid trades
*/
async function get_valid_trades(fromOrders, toOrders, tax, minProfit, minROI, maxBudget, maxWeight, systemSecurity) {
    const ids = Object.keys(fromOrders);
    const validTrades = [];
    
    for (const id of ids) {
        if (typeIDToName[id]) {
            for (const initialOrder of fromOrders[id]) {
                for (const closingOrder of toOrders[id]) {
                        
                    let volume = closingOrder.volume_remain < initialOrder.volume_remain ? closingOrder.volume_remain : initialOrder.volume_remain;
                    let weight = typeIDToName[initialOrder.type_id].volume * volume;
                    
                    // If weight is greater than max weight rearrange volume to be less than max weight
                    // Then run conditional checks
                    if (weight > maxWeight) {
                        volume = Math.floor((maxWeight/ weight) * volume);
                        weight = typeIDToName[initialOrder.type_id].volume * volume;
                    }
                    
                    const initialPrice = initialOrder.price * volume;
                    const salePrice = closingOrder.price * volume * (1-tax);
                    const profit = salePrice - initialPrice;
                    const ROI = (salePrice-initialPrice)/initialPrice;
                    const sourceSecurity = systemIdToSecurity[initialOrder.system_id]['security_code'];
                    const destinationSecuity = systemIdToSecurity[closingOrder.system_id]['security_code'];
                    
                    const validTrade = profit >= minProfit &&
                    ROI >= minROI && 
                    initialPrice <= maxBudget && 
                    weight <= maxWeight &&
                    systemSecurity.indexOf(sourceSecurity) >= 0 &&
                    systemSecurity.indexOf(destinationSecuity) >= 0;

                    if (validTrade) {
                        const newRecord = {
                            'Item ID': initialOrder.type_id,
                            'Item': typeIDToName[initialOrder.type_id].name,
                            'From': {
                                'name': stationIdToName[initialOrder.station_id],
                                'station_id': initialOrder.station_id,
                                'system_id': initialOrder.system_id,
                                'rating': systemIdToSecurity[initialOrder.system_id]['rating']
                            },
                            'Quantity': round_value(volume, 0),
                            'Buy Price': round_value(initialOrder.price, 2),
                            'Net Costs': round_value(volume * initialOrder.price, 2),
                            'Take To': {
                                'name': stationIdToName[closingOrder.station_id],
                                'station_id': closingOrder.station_id,
                                'system_id': closingOrder.system_id,
                                'rating': systemIdToSecurity[closingOrder.system_id]['rating']
                            },
                            'Sell Price': round_value(closingOrder.price, 2),
                            'Net Sales': round_value(volume * closingOrder.price, 2),
                            'Gross Margin': round_value(volume * (closingOrder.price - initialOrder.price), 2),
                            'Sales Taxes': round_value(volume * (closingOrder.price * tax / 100), 2),
                            'Net Profit': profit,
                            'Jumps': 0,
                            'Profit per Jump': 0,
                            'Profit Per Item': round_value(profit / volume, 2),
                            'ROI': round_value(100 * ROI, 2) + '%',
                            'Total Volume (m3)': round_value(weight, 2),
                        };
                        
                        validTrades.push(newRecord);
                        
                        jumpCount[`${initialOrder.system_id}-${closingOrder.system_id}`] = '';
                    }
                }
            }
        }
    }
    return validTrades;
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
        .catch( err => { console.log(`Failed`, err); 
    });

    DOWNLOAD_PARAMS.Key = `resources/stationIdToName.json`;
    s3.getObject(DOWNLOAD_PARAMS)
    .promise()
    .then( data => { 
        console.log(`Successfully retrieved stationIdToName`);
        stationIdToName = JSON.parse(data.Body.toString('utf-8'));
    })
    .catch( err => { 
        console.log(`Failed`, err); 
    });

    DOWNLOAD_PARAMS.Key = `resources/systemIdToSecurity.json`;
    s3.getObject(DOWNLOAD_PARAMS)
    .promise()
    .then( data => { 
        console.log(`Successfully retrieved systemIdToSecurity`);
        systemIdToSecurity = JSON.parse(data.Body.toString('utf-8'));
    })
    .catch( err => { 
        console.log(`Failed`, err); 
    });
}

function compare( a, b ) {
  if ( a['Net Profit'] < b['Net Profit'] ){
    return -1;
  }
  if ( a['Net Profit'] > b['Net Profit'] ){
    return 1;
  }
  return 0;
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
    const SALES_TAX = queries['tax'] === undefined ? 0.08 : parseFloat(queries['tax']);
    const MIN_PROFIT = queries['minProfit'] === undefined ? 500000 : parseFloat(queries['minProfit']);
    const MIN_ROI = queries['minROI'] === undefined ? 0.04 : parseFloat(queries['minROI']);
    const MAX_BUDGET = queries['maxBudget'] === undefined ? Number.MAX_SAFE_INTEGER : parseFloat(queries['maxBudget']);
    const MAX_WEIGHT = queries['maxWeight'] === undefined ? Number.MAX_SAFE_INTEGER : parseFloat(queries['maxWeight']);
    const ROUTE_SAFETY = queries['routeSafety'] === undefined ? 'secure' : queries['routeSafety']; // secure, shortest, insecure
    const SYSTEM_SECURITY = queries['systemSecurity'] === undefined ? ['high_sec'] : queries['systemSecurity'].split(',');
    
    let FROM = queries['from'];
    let TO = queries['to'];
    
    const FROM_TYPE = FROM.startsWith('buy-') ? 'buy' : 'sell';
    const TO_TYPE = TO.startsWith('sell-') ? 'sell' : 'buy';
    
    FROM = FROM.replace('buy-', '').replace('sell-', '');
    TO = TO.replace('buy-', '').replace('sell-', '');
    
    
    // Get cached mappings files for easier processing later.
    get_mappings();
    
    console.log(`Mapping retrieval took: ${(new Date() - startTime) / 1000} seconds to process.`);
    
    let orders = {
        'from': await get_orders(FROM, FROM_TYPE),
        'to': await get_orders(TO, TO_TYPE)
    };
    
    // Grab one item per station in each each (cheaper for sell orders, expensive for buy orders)
    // Remove type Ids that do not exist in each side of the trade
    orders = remove_mismatch_type_ids(orders['from'], orders['to']);
    console.log(`Retrieval took: ${(new Date() - startTime) / 1000} seconds to process.`);
    
    let validTrades = await get_valid_trades(orders['from'], orders['to'], SALES_TAX, MIN_PROFIT, MIN_ROI, MAX_BUDGET, MAX_WEIGHT, SYSTEM_SECURITY);
    validTrades = validTrades.sort(compare);
    validTrades = validTrades.slice(0, 1000);
    
    console.log(`Valid Trades = ${validTrades.length}`);    
    
    console.log(`Routes = ${Object.keys(jumpCount).length}`);

    let routeData = await get_routes(ROUTE_SAFETY);

    for (let i = 0; i < validTrades.length; i++) {
        const systemFrom = validTrades[i]['From']['system_id'];
        const systemTo = validTrades[i]['Take To']['system_id'];

        validTrades[i]['Jumps'] = round_value(routeData[`${systemFrom}-${systemTo}`], 0);

        if (routeData[`${systemFrom}-${systemTo}`] > 0) {
            validTrades[i]['Profit per Jump'] = round_value(validTrades[i]['Net Profit'] / validTrades[i]['Jumps'], 2);
        } else {
            validTrades[i]['Profit per Jump'] = round_value(validTrades[i]['Net Profit'], 2);
        }

        validTrades[i]['Net Profit'] = round_value(validTrades[i]['Net Profit'], 2);
    }

    validTrades = validTrades.sort(compare);

    let bytes = Buffer.byteLength(JSON.stringify(validTrades));
    
    while (bytes > MAX_PAYLOAD_SIZE_BYTES) {
        validTrades.splice(-100);
        bytes = Buffer.byteLength(JSON.stringify(validTrades));
    }
    
    console.log(`Truncated Valid Trades = ${validTrades.length}`);    
    console.log(`Full analysis took: ${(new Date() - startTime) / 1000} seconds to process.`);
    console.log(`Size of payload is ${bytes/1024/1024} megabytes`);
    
    return JSON.stringify(validTrades);
};