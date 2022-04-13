// Synchronizes the EVE Universe Resource in S3

const https = require('https');
const AWS = require('aws-sdk');
AWS.config.update({region: 'us-east-1'});

const s3 = new AWS.S3();

const RES_ENDPOINT = 'https://api.github.com/repos/awhipp/evetrade_resources/contents/resources';

const options = {
    headers: {
        'User-Agent': 'evetrade-api-lambda'
    }
};

function get_request(url, options) {
    
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
            const systemId = metadata["system"];
            const security = metadata["security"];
            const securityCode = get_security_code(security);

            systemIdToSecurity[systemId] = {
                "rating": security,
                "security_code": securityCode
            };
        }

        await upload_to_s3('evetrade', 'resources/systemIdToSecurity.json', JSON.stringify(systemIdToSecurity), 'application/json');
    }
}

exports.handler = async function(event, context) {    
    console.log(`Sending Request to ${RES_ENDPOINT}`);
    
    const data = await get_request(RES_ENDPOINT, options);
    
    for (var i = 0; i < data.length; i++) {
        const body = await get_request(data[i].download_url, options);

        await upload_to_s3('evetrade', `resources/${data[i].name}`, JSON.stringify(body), 'application/json');
    }
};