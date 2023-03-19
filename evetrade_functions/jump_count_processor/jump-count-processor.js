/**
 * Lambda Function which gets a message from an SQS queue, 
 * checks the routes API, 
 * and updates the route in Elasticsearch if there was a change
 */

// Load HTTPS for Node.js
var https = require('https');

// Load the Elasticsearch SDK for Node.js
const { Client } = require('@elastic/elasticsearch');

// Create an Elasticsearch client
const client = new Client({
    node: process.env.ES_HOST
});

function getRouteDataFromESI(start, end, type) {
    const esi_api_route = `https://esi.evetech.net/latest/route/${start}/${end}/?datasource=tranquility&flag=${type}`;
    console.log(`Sending: ${esi_api_route}`);

    return new Promise(function(resolve, reject) {
        https.get(esi_api_route, function(res) {
            var body = '';
            res.on('data', function(chunk) {
                body += chunk;
            });
            res.on('end', function() {
                var response = JSON.parse(body);
                if (response.error) {
                    resolve(-1);
                } else {
                    resolve(response.length);
                }
            });
        }).on('error', function(e) {
            console.log("Got an error: ", e);
            reject(e);
        });
    });
}

async function get_doc_ids_from_elasticsearch(start, end) {
    const routeIds = {};
    
    const search_body = {
        index: 'evetrade_jump_data',
        size: 10000,
        body: {
            query: {
                'bool': {
                    'should': [
                        {"match_phrase": {"route":  `${start}-${end}`}},
                        {"match_phrase": {"route":  `${end}-${start}`}}
                     ]
                }
            }
        }
    };

    
    // first we do a search, and specify a scroll timeout
    const response = await client.search(search_body);
    
    const all_hits = response.body.hits.hits;

    console.log(`Retrieved ${all_hits.length} route IDs.`);
    
    all_hits.forEach(function (hit) {
        const doc = hit['_source'];
        const id = hit['_id'];
        const route = doc['route'];
        routeIds[route] = id;
    });

    return routeIds;
}

async function update_elasticsearch_record(doc_id, start, end, insecure, secure, shortest) {
    const params = {
        index: 'evetrade_jump_data',
        id: doc_id,
        body: {
            doc: {
                route: `${start}-${end}`,
                insecure: insecure,
                secure: secure,
                shortest: shortest,
                last_modified: new Date().getTime(),
            }
        }
    };
    // Update the document
    await client.update(params);
}

exports.handler = async (event) => {
    console.log(event);

    // loop through each record in the event.Records
    for (var i = 0; i < event.Records.length; i++) {
        const record = event.Records[i];
        const payload = JSON.parse(record.body);
        const start = payload.start;
        const end = payload.end;
        
        const new_insecure = await getRouteDataFromESI(start, end, 'insecure');
        const new_secure = await getRouteDataFromESI(start, end, 'secure');
        const new_shortest = await getRouteDataFromESI(start, end, 'shortest');

        const routeIds = await get_doc_ids_from_elasticsearch(start, end);
        for (const route in routeIds) {
            const doc_id = routeIds[route];
            const new_start = route.split('-')[0];
            const new_end = route.split('-')[1];
            await update_elasticsearch_record(doc_id, new_start, new_end, new_insecure, new_secure, new_shortest);

            console.log({
                "start": new_start,
                "end": new_end,
                "insecure": new_insecure,
                "secure": new_secure,
                "shortest": new_shortest,
                "doc_id": doc_id,
            });
        }
    }
};