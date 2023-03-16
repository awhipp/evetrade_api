const AWS = require('aws-sdk');
const redis = require('redis');
const lambda = new AWS.Lambda();
const { promisify } = require('util');

// Create a Redis client
const client = redis.createClient({
    socket: {
        host: process.env.REDIS_HOST,
        port: process.env.REDIS_PORT,
    },
    password: process.env.REDIS_PASSWORD
});

// Promisify Redis commands for easier use
const redisIncrAsync = promisify(client.incr).bind(client);
const redisExpireAsync = promisify(client.expire).bind(client);
const redisGetAsync = promisify(client.get).bind(client);

const IP_WHITE_LIST = process.env.IP_WHITE_LIST.split(',');
const IP_BAN_LIST = process.env.IP_BAN_LIST.split(',');

async function check_rate_limit(headers) {
    await client.connect().catch(error => {
        console.log('Redis already connected');
    });
    
    const ip = headers['x-forwarded-for'];
    const rateLimitKey = `rate_limit:${ip}`;
    
    // Get the current rate limit count for the IP address
    const currentCount = await client.incr(rateLimitKey);
    
    // If the count is 1, set the expiration time for the key
    if (currentCount === 1) {
        await client.expire(rateLimitKey, process.env.RATE_LIMIT_INTERVAL);
    }
    
    // Check if the current count exceeds the rate limit
    console.log(`${rateLimitKey} - Current Count: ${currentCount} of ${ process.env.RATE_LIMIT_COUNT}.`);
    return currentCount > process.env.RATE_LIMIT_COUNT;
}

async function check_authorization(headers) {
    let authorized = true;
    
    if (headers) {
        if ('x-forwarded-for' in headers) {
            const ip_address = headers['x-forwarded-for'];
            if (IP_WHITE_LIST.indexOf(ip_address) >= 0) {
                console.log('White Listed IP: ' + ip_address);
                return true;
            } else if (IP_BAN_LIST.indexOf(ip_address) >= 0) {
                console.log('Banned IP: ' + ip_address);
                authorized = false;
            }
        }
        
        Object.keys(headers).forEach((key, index) => {
            if (key.toLowerCase().indexOf('postman') >= 0) {
                console.log('Invalid header contains Postman: ' + key);
                authorized = false;
            }
        });
        
        if (!('origin' in headers)) {
            console.log('Origin not in headers.');
            authorized = false;
        } else        if (headers.origin.indexOf('evetrade.space') == -1) {
            console.log('Not originating from evetrade.space domain.');
            authorized = false;
        }
    } else {
        authorized = false;
    }
    
    return authorized;
}

function payload(statusCode, body) {
    return JSON.stringify({
            statusCode: statusCode,
            body: body,
        });
}

exports.handler = async function(event, context) {
    console.log(event);
    
    const rate_limit_exceeded = await check_rate_limit(event.headers);
    
    if (rate_limit_exceeded) {
        return payload(429, 'Too Many Requests.');
    }
    
    const authorized = await check_authorization(event.headers);
    
    if (!authorized) {
        return payload(401, 'Unauthorized.');
    }
    
    
    // Map the path to the corresponding Lambda function name
    let functionName;
    let alias;

    switch (event.rawPath.replace('/dev', '')) {
        case '/hauling':
          functionName = 'evetrade-get-hauling-orders';
          alias = 'EVETradeGetHaulProd';
          break;
        case '/station':
          functionName = 'evetrade-get-station-trades';
          alias = 'EVETradeStatTradPROD';
          break;
        case '/orders':
          functionName = 'evetrade-get-orders';
          alias = 'EVETradeGETOrders';
          break;
        default:
          return payload(404, 'Not found.');
    }
    
    // Invoke the corresponding Lambda function
    let config;
    if (event.rawPath.indexOf('/dev') >= 0) {
        config = {
            FunctionName: functionName,
        };
    } else {
        config = {
            FunctionName: functionName,
            Qualifier: alias,
        };
    }
    
    console.log('Routing to:');
    console.log(config);
    
    config['Payload'] = JSON.stringify(event);
    
    const response = await lambda.invoke(
        config
    ).promise();
    
    // Return the response from the invoked Lambda function
    return JSON.parse(response.Payload);
};