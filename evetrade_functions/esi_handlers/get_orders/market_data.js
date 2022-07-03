// Gets all Market Orders for a particular Region (can be refined by station ID)
const https = require('https');
const ESI_ENDPOINT = 'https://esi.evetech.net';

class MarketData {

    /**
     * Builds the specific MarketData Class
     * @param {*} region Region of Interest
     * @param {*} order_type Order Type of Interest
     * @param {*} station_ids List of Stations of Interest (can be undefined)
     */
    constructor (region, order_type, station_ids) {
        this.region = region;
        this.order_type = order_type;
        this.station_ids = station_ids;
        this.orders = [];
        this.completed_requests = [];
        this.page_count = -1;
        this.page = 1;
        this.completeExecution = false;
    }
    
    /**
     * Processes the data from ESI APIs
     * @param {*} url Generated ESI API Endpoint
     * @returns The JSON Payload for the current page
     */
    getMarketData(url) {
        const thiz = this;
        const current_page = url.split('page=')[1];
    
        return new Promise((resolve, reject) => {
            const req = https.get(url, res => {
                let rawData = '';
                
                res.on('data', chunk => {
                    rawData += chunk;
                });
                
                res.on('end', () => {
                    const new_orders = JSON.parse(rawData);

                    if (thiz.page_count == -1) {
                        thiz.page_count = parseInt(res.headers['x-pages'], 10);
                    }

                    if (thiz.station_ids.length > 0) {
                        const filtered_orders = [];

                        for(let idx = 0; idx < new_orders.length; idx ++) {
                            if(thiz.station_ids.indexOf(new_orders[idx].location_id) != -1) filtered_orders.push(new_orders[idx]);
                        }

                        resolve([filtered_orders, current_page]);
                    }
            
                    resolve([new_orders, current_page]);
                });
            });
            
            req.on('error', err => {
                reject(new Error(err));
            });
        });
    }

    /**
     * Constructs the ESI constructed ESI ENDPOINT based on class properties
     * @param {*} page The specific page in question
     * @returns ESI ENDPOINT
     */
    constructESIEndpoint(page) {
        const endpoint =  `${ESI_ENDPOINT}/latest/markets/${this.region}/orders/?datasource=tranquility&order_type=${this.order_type}&page=${page}`;
        return endpoint;
    }

    /**
     * Waits for all the orders to be retrieved
     * @returns When all the orders have been retrieved
     */
    waitForOrders() {
        const thiz = this;
        return new Promise(function (resolve) {
            const interval = setInterval(async function() {
                if(thiz.completed_requests.length == thiz.page_count) {
                    clearInterval(interval);
                    resolve();
                }
            }, 100);
        });
    }

    /**
     * Begins processing all the endpoint data
     * @returns A compilation of all the orders
     */
    executeRequest() {
        const thiz = this;
        return new Promise(async function(resolve) {
            const startTime = new Date();
                
            // Get First Page of Data
            await thiz.getMarketData(thiz.constructESIEndpoint(thiz.page), thiz.station_ids)
            .then(function(data) { 
                thiz.orders = thiz.orders.concat(data[0]); 
                thiz.completed_requests.push(data[1]);
            })
            .catch(function(err) { console.log(`Error getting data: ${err}`); });
    
            thiz.page += 1;
        
            // Get the remaining pages asynchronously
            for (; thiz.page <= thiz.page_count; thiz.page++) {
                thiz.getMarketData(thiz.constructESIEndpoint(thiz.page), thiz.station_ids)
                .then(function(data) { 
                    thiz.orders = thiz.orders.concat(data[0]); 
                    thiz.completed_requests.push(data[1]);
                })
                .catch(function(err) { console.log(`Error getting data: ${err}`); });
            }
            console.log(`All Page Requests Sent: ${thiz.page_count} Pages.`);
        
            // Wait for all pages to be returned
            await thiz.waitForOrders().then(async function(){
                const endTime = new Date();
    
                console.log(`${thiz.orders.length} orders returned to request.`);
                console.log(`Total request took: ${(endTime - startTime) / 1000} seconds to process.`);
                
                thiz.completeExecution = true;
                
                resolve(thiz.orders);
            });
        });
    }
}

exports.MarketData = MarketData;