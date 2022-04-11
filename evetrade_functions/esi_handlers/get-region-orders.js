// Gets all Market Orders for a particular Region (can be refined by station ID or system)
const https = require('https');

const ESI_ENDPOINT = 'https://esi.evetech.net';

let page_count = -1;
let completed_requests = 0;
let orders = [];

function getMarketData(url, system_ids) {
    return new Promise((resolve, reject) => {
        const req = https.get(url, res => {
            let rawData = '';
            
            res.on('data', chunk => {
                rawData += chunk;
            });
            
            res.on('end', () => {
                try {
                    completed_requests += 1;
                    
                    if (page_count == -1) {
                        page_count = parseInt(res.headers['x-pages']);
                    }
                    const new_orders = JSON.parse(rawData);
                    const filtered_orders = [];

                    if (system_ids.length > 0) {
                        for(let idx = 0; idx < new_orders.length; idx ++) {
                            if (system_ids.indexOf(new_orders[idx].system_id) != -1) {
                                filtered_orders.push(new_orders[idx]);
                            }
                        }
                        orders = orders.concat(filtered_orders);
                    } else {
                        orders = orders.concat(new_orders);
                    }

                    resolve();
                } catch (err) {
                    reject(new Error(err));
                }
            });
        });
        
        req.on('error', err => {
            reject(new Error(err));
        });
    });
}

function constructESIEndpoint(region, order_type, page) {
    const endpoint =  `${ESI_ENDPOINT}/latest/markets/${region}/orders/?datasource=tranquility&order_type=${order_type}&page=${page}`;
    return endpoint;
}

exports.handler = async function(event, context) {
    const REGION = '10000002';
    const ORDER_TYPE = 'buy';
    const SYSTEM_IDS = [30000142, 30000144];
    let page = 1;

    // Get First Page of Data
    await getMarketData(constructESIEndpoint(REGION, ORDER_TYPE, page), SYSTEM_IDS);
    page += 1;

    for (; page <= page_count; page++) {
        data = getMarketData(constructESIEndpoint(REGION, ORDER_TYPE, page), SYSTEM_IDS);
    }

    const waitForOrders = setInterval(function() {
        if (completed_requests == page_count) {
            clearInterval(waitForOrders);
            console.log(orders.length);
        }
    }, 100);

};

exports.handler();