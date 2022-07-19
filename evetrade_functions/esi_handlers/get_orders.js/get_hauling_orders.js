// Gets orders for a specific item ID from two stations
const https = require('https');

async function get_orders(itemId, regionId, stationId, orderType) {
    const url = `https://esi.evetech.net/latest/markets/${regionId}/orders/?datasource=tranquility&order_type=${orderType}&page=1&type_id=${itemId}`;

    return new Promise((resolve, reject) => {
        const req = https.get(url, {}, res => {
            let rawData = '';
            
            res.on('data', chunk => {
                rawData += chunk;
            });
            
            res.on('end', () => {
                try {
                    resolve(
                        JSON.parse(rawData).filter(function(item){
                            return item.location_id == stationId;         
                        })  
                    );
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

/**
 * Lambda function handler
 * @param {*} event 
 * @param {*} context 
 * @returns Payload of orders between two stations
 */
exports.handler = async function(event, context) {
    console.log(event);
    const queries = event['queryStringParameters'];
    const ITEM_ID = queries['itemId'];
    const FROM = queries['from'].split(':');
    const TO = queries['to'].split(':');

    const orders = {
        'from': await get_orders(ITEM_ID, FROM[0], FROM[1], 'sell'),
        'to': await get_orders(ITEM_ID, TO[0], TO[1], 'buy'),
    };

    return {
        headers: {
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify(orders)
    };
};