// Compares profitable hailing orders between stations and/or regions (or within the same region)
const AWS = require('aws-sdk');
const https = require('https');
const MarketData = require('./helper_modules/MarketData.js').MarketData;

AWS.config.update({region: 'us-east-1'});
const s3 = new AWS.S3();

let typeIDToName, stationIdToName, systemIdToSecurity;

const jumpCount = {};

/**
 * Generates and executes market data requests based on the requested queries
 * @param {*} inputList 
 * @param {*} orderType 
 * @returns Market Data Mapping which has all the requests executed
 */
function aggregate_mapping(locations, orderType) {
    const marketDataMapping = {};
    
    for (const region in locations){
        const stations = locations[region];
        
        marketDataMapping[region] = new MarketData(region, orderType, stations);
        marketDataMapping[region].executeRequest();
    }
    
    return marketDataMapping;
}

/**
 * Once all orders are received generate aggregate maps
 * @param {*} fromMapping The current mapping of MarketData classes for initial orders
 * @param {*} toMapping  The current mapping of MarketData classes for closing orders
 * @returns Mapping which aggregates all region orders
 */
function get_aggregate_orders(fromMapping, toMapping) {
    return new Promise(function (resolve) {
        const interval = setInterval(async function() {
            let completeExecution = true;
            
            for (const region in fromMapping){
                if (!fromMapping[region].completeExecution) {
                    completeExecution = false;
                }
            }
            
            for (const region in toMapping){
                if (!toMapping[region].completeExecution) {
                    completeExecution = false;
                }
            }
            
            if (completeExecution) {
                clearInterval(interval);
                
                const orders = {
                    'from': [],
                    'to': []
                };
                
                for (const region in fromMapping){
                    orders['from'] = orders['from'].concat(fromMapping[region].orders);
                }

                for (const region in toMapping){
                    orders['to'] = orders['to'].concat(toMapping[region].orders);
                }

                resolve(orders);
            }
            

        });
    });
}

/**
 * Maps to cheaper/expensive by station to ensure one item per station
 * @param {*} orders The full list of orders
 * @param {*} cheaper Whether we want cheaper (sell orders) or more expensive (buy orders) 
 * @returns Mapping of inidividual items in given stations that are most adventageous
 */
function remap_orders(orders, cheaper) {
    const newOrders = {};
    for (const obj of orders) {
        const typeId = obj.type_id;
        const stationId = obj.location_id;
        if (newOrders[typeId] === undefined) {
            newOrders[typeId] = {};
        } 

        if(newOrders[typeId][stationId] === undefined) {
            newOrders[typeId][stationId] = obj;
        } else {
            if (cheaper && obj.price < newOrders[typeId][stationId].price) {
                newOrders[typeId][stationId] = obj;
            } else if (!cheaper && obj.price > newOrders[typeId][stationId].price) {
                newOrders[typeId][stationId] = obj;
            }
        }
    }
    return newOrders;
}

/**
 * Removes the type IDs that do not align between FROM and TO orders
 * @param {*} fromOrders Orders at the initiating end
 * @param {*} toOrders Orders at the closing end
 * @returns Subset of all the Ids (should be equal in size)
 */
function remove_mismatch_type_ids(fromOrders, toOrders) {
    const fromIds = Object.keys(fromOrders);
    const toIds = Object.keys(toOrders);

    console.log(`Before: From Order Count = ${fromIds.length} and To Order Count = ${toIds.length}`);
    
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
    
    console.log(`After: From Order Count = ${Object.keys(fromOrders).length} and To Order Count = ${Object.keys(toOrders).length}`);

    return {
        'from': fromOrders,
        'to': toOrders
    };
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
 * @returns Map of valid trades
 */
function get_valid_trades(fromOrders, toOrders, tax, minProfit, minROI, maxBudget, maxWeight) {
    const ids = Object.keys(fromOrders);
    const validTrades = [];

    for (const id of ids) {
        const fromStations = fromOrders[id];
        const toStations = toOrders[id];

        const fromKeys = Object.keys(fromStations);
        for (const fromStation of fromKeys) {
            const initialOrder = fromOrders[id][fromStation];

            const toKeys = Object.keys(toStations);
            for (const toStation of toKeys) {
                const closingOrder = toOrders[id][toStation];
                const volume = closingOrder.volume_remain < initialOrder.volume_remain ? closingOrder.volume_remain : initialOrder.volume_remain;

                const initialPrice = initialOrder.price * volume;
                const salePrice = closingOrder.price * volume * (1-tax);
                const profit = salePrice - initialPrice;
                const ROI = (salePrice-initialPrice)/initialPrice;
                const weight = typeIDToName[initialOrder.type_id].volume * volume;
                if (profit > minProfit && ROI >= minROI && initialPrice <= maxBudget && weight < maxWeight) {
                    const newRecord = {
                        'Item': typeIDToName[initialOrder.type_id].name,
                        'From': {
                            'name': stationIdToName[initialOrder.location_id],
                            'system_id': initialOrder.system_id,
                            'rating': systemIdToSecurity[initialOrder.system_id]["rating"],
                            'security_code': systemIdToSecurity[initialOrder.system_id]["security_code"]
                        },
                        'Quantity': volume,
                        'Buy Price': initialOrder.price,
                        'Net Costs': volume * initialOrder.price,
                        'Take To': {
                            'name': stationIdToName[closingOrder.location_id],
                            'system_id': closingOrder.system_id,
                            'rating': systemIdToSecurity[closingOrder.system_id]["rating"],
                            'security_code': systemIdToSecurity[closingOrder.system_id]["security_code"]
                        },
                        'Sell Price': closingOrder.price,
                        'Net Sales': volume * closingOrder.price,
                        'Gross Margin': volume * (closingOrder.price - initialOrder.price),
                        'Sales Taxes': volume * (closingOrder.price * tax / 100),
                        'Net Profit': profit,
                        'R.O.I.': (100 * ROI).toFixed(2) + "%",
                        'Total Volume (m3)': weight,
                    };

                    validTrades.push(newRecord);

                    jumpCount[`${initialOrder.system_id}-${closingOrder.system_id}`] = '';
                }
            }
        }
    }
    return validTrades;
}

let request_complete, request_count;

async function get_number_of_jumps(safety, validTrades) {
    const routes = Object.keys(jumpCount);
    request_count = 0;
    request_complete = 0;

    for (const route of routes) {
        const fromSystem = route.split('-')[0];
        const toSystem = route.split('-')[1];
        const url = `https://esi.evetech.net/latest/route/${fromSystem}/${toSystem}/?datasource=tranquility&flag=${safety}`;
        request_count += 1;

        new Promise((resolve, reject) => {
            const req = https.get(url, {}, res => {
                let rawData = '';
                
                res.on('data', chunk => {
                    rawData += chunk;
                });
                
                res.on('end', () => {
                    try {
                        request_complete += 1;
                        resolve(JSON.parse(rawData));
                    } catch (err) {
                        reject(new Error(err));
                    }
                });
            });
            
            req.on('error', err => {
                reject(new Error(err));
            });
        }).then(function(data){
            jumpCount[`${data[0]}-${data[data.length-1]}`] = data.length - 1;
            
        });
    }
    
    return new Promise(function (resolve) {
        const interval = setInterval(async function() {
            if (request_count == request_complete) {
                clearInterval(interval);
                
                for (const trades of validTrades) {
                    const fromSystem = trades['From']['system_id'];
                    const toSystem = trades['Take To']['system_id'];
                    trades['Jumps'] = jumpCount[`${fromSystem}-${toSystem}`];
                    trades['Profit per Jump'] = (parseFloat(trades['Net Profit']) / parseInt(trades['Jumps'], 10)).toFixed(2);
                }
                
                resolve(validTrades);
            }
        });
    });
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

function convert_locations(locations) {
    const splitValues = {};
    
    const individualLocations = locations.split(',');
    
    for (const location of individualLocations) {
        if (location.indexOf(':') > 0) {
            const region = parseInt(location.split(':')[0], 10);
            const station = parseInt(location.split(':')[1], 10);
            
            if(splitValues[region] === undefined) {
                splitValues[region] = [];
            }
            
            splitValues[region].push(station);
        } else {
            splitValues[location] = [];
        }
    }
    
    return splitValues;
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
    const queries = event["queryStringParameters"];
    const AGG_FROM = aggregate_mapping(convert_locations(queries['from']), 'sell');
    const AGG_TO = aggregate_mapping(convert_locations(queries['to']), 'buy');
    const SALES_TAX = queries['tax'] === undefined ? 0.08 : queries['tax'];
    const MIN_PROFIT = queries['minProfit'] === undefined ? 500000 : queries['minProfit'];
    const MIN_ROI = queries['minROI'] === undefined ? 0.04 : queries['minROI'];
    const MAX_BUDGET = queries['maxBudget'] === undefined ? Number.MAX_SAFE_INTEGER : queries['maxBudget'];
    const MAX_WEIGHT = queries['maxWeight'] === undefined ? Number.MAX_SAFE_INTEGER : queries['maxWeight'];
    const ROUTE_SAFETY = queries['routeSafety'] === undefined ? 'shortest' : queries['routeSafety'];
    const FROM_TYPE = queries['fromType'] === undefined ? 'sell' : queries['fromType'];
    const TO_TYPE = queries['toType'] === undefined ? 'buy' : queries['toType'];
    
    // Get cached mappings files for easier processing later.
    get_mappings();

    console.log(`Mapping retrieval took: ${(new Date() - startTime) / 1000} seconds to process.`);

    let orders = await get_aggregate_orders(AGG_FROM, AGG_TO);
    
    // Grab one item per station in each each (cheaper for sell orders, expensive for buy orders)
    // Remove type Ids that do not exist in each side of the trade
    orders = remove_mismatch_type_ids(
        remap_orders(orders['from'], FROM_TYPE == 'buy' ? false : true), 
        remap_orders(orders['to'], TO_TYPE == 'buy' ? false : true)
    );

    let validTrades = get_valid_trades(orders['from'], orders['to'], SALES_TAX, MIN_PROFIT, MIN_ROI, MAX_BUDGET, MAX_WEIGHT);
    console.log(`Valid Trades = ${validTrades.length}`);

    validTrades = await get_number_of_jumps(ROUTE_SAFETY, validTrades);

    console.log(`Full analysis took: ${(new Date() - startTime) / 1000} seconds to process.`);

    return {
        'body': JSON.stringify(validTrades)
    };
};