// Synchronizes the EVE Universe Resource in S3

const https = require('https');
const AWS = require('aws-sdk');
AWS.config.update({region: 'us-east-1'});

const s3 = new AWS.S3();

// Get data from REST API and return as JSON
function get_request(url) {
    const options = {
        headers: {
            'User-Agent': 'evetrade-api-lambda'
        }
    };
    
    return new Promise((resolve, reject) => {
        const req = https.get(url, options, res => {
            let rawData = '';
            
            res.on('data', chunk => {
                rawData += chunk;
            });
            
            res.on('end', () => {
                try {
                    resolve(JSON.parse(rawData));
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

// Maps Security Rating to Security Code
function get_security_code(security) {
    if (security >= 0.5) {
        return "high_sec";
    } else if (security > 0) {
        return "low_sec";
    } else if (security <= 0) {
        return "null_sec";
    } else {
        return -1;
    }
}

// Asynchronous Function to upload JSON to S3
async function upload_to_s3(bucket, key, body, contentType) {
    const UPLOAD_PARAMS = {
        Bucket: bucket,
        Key: key,
        Body: body, 
        ContentType: contentType
    };
    
    console.log(`Uploading to ${UPLOAD_PARAMS.Bucket} ${UPLOAD_PARAMS.Key}`);
    
    await s3.upload(UPLOAD_PARAMS)
    .promise()
    .then( data => { console.log(`Success`, data); })
    .catch( err => { console.log(`Failed`, err); });
    
    if (key.indexOf('invTypes') > 0) {
        const json = JSON.parse(body.toString('utf-8'));
        const typeIDToName = {};
        for (const obj in json) {
            const metadata = json[obj];
            const typeId = metadata["typeID"];
            const name = metadata["typeName"];
            const volume = metadata["volume"];
            typeIDToName[typeId] = {
                "name": name,
                "volume": volume
            };
        }
        
        await upload_to_s3('evetrade', 'resources/typeIDToName.json', JSON.stringify(typeIDToName), 'application/json');
    }
    
    if (key.indexOf('universeList') > 0) {
        const json = JSON.parse(body.toString('utf-8'));
        const systemIdToSecurity = {};
        for (const obj in json) {
            const metadata = json[obj];
            if (metadata["security"] != undefined) {
                const systemId = metadata["system"];
                const security = metadata["security"];
                const securityCode = get_security_code(security);
                
                systemIdToSecurity[systemId] = {
                    "rating": security,
                    "security_code": securityCode
                };
            }
        }
        await upload_to_s3('evetrade', 'resources/systemIdToSecurity.json', JSON.stringify(systemIdToSecurity), 'application/json');
    }
}

function p95(arr){
    // Creating the mean with Array.reduce
    let mean = arr.reduce((acc, curr)=>{
        return acc + curr;
    }, 0) / arr.length;
    
    // Assigning (value - mean) ^ 2 to every array item
    arr = arr.map((k)=>{
        return (k - mean) ** 2;
    });
    
    // Calculating the sum of updated array
    let sum = arr.reduce((acc, curr)=> acc + curr, 0);
    
    // Return 95th percentile
    return mean + (2 * Math.sqrt(sum / arr.length));
}

async function get_average_lambda_execution_time(lambdaFunctionName) {
    const AWS = require('aws-sdk');
    AWS.config.update({region: 'us-east-1'});
    const startTime = new Date(new Date().setDate(new Date().getDate() - 14));
    const endTime = new Date();
    console.log(`Getting average lambda execution time for ${lambdaFunctionName} from ${startTime} to ${endTime}`);
    
    const cloudwatch = new AWS.CloudWatch();
    const params = {
        MetricName: 'Duration',
        Namespace: 'AWS/Lambda',
        Statistics: ['Average'],
        Period: 1440,
        StartTime: startTime,
        EndTime: endTime,
        Dimensions: [
            {
                Name: 'FunctionName',
                Value: lambdaFunctionName
            }
        ]
    };
    const metric = await cloudwatch.getMetricStatistics(params).promise();
    const datapoints = metric.Datapoints;
    const durations = [];
    for (const datapoint of datapoints) {
        durations.push(datapoint.Average);
    }
    return p95(durations);
}

// Lambda function which pulls data from GitHub resource and uploads to S3
exports.handler = async function(event, context) {    

    // Gets the 95th percentile of lambda execution time for the last 14 days
    const apiFunctions = [
        'evetrade-get-orders',
        'evetrade-get-hauling-orders',
        'evetrade-get-station-trades',
        'evetrade-synchronize-universe-resources'
    ];

    const functionDurations = {};
    
    for (const functionName of apiFunctions) {
        const duration = await get_average_lambda_execution_time(functionName);
        functionDurations[functionName] = parseFloat(duration.toFixed(2));
    }

    await upload_to_s3('evetrade', 'resources/functionDurations.json', JSON.stringify(functionDurations), 'application/json');

    // Get data from GitHub resources
    const RES_ENDPOINT = 'https://api.github.com/repos/awhipp/evetrade_resources/contents/resources';
    
    console.log(`Sending Request to ${RES_ENDPOINT}`);
    
    const data = await get_request(RES_ENDPOINT);
    
    for (var i = 0; i < data.length; i++) {
        const body = await get_request(data[i].download_url);
        await upload_to_s3('evetrade', `resources/${data[i].name}`, JSON.stringify(body), 'application/json');
    }
};