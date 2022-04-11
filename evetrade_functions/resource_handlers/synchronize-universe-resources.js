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

function getRequest(url, options) {
    
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

async function uploadToS3(bucket, key, body, contentType) {
    const UPLOAD_PARAMS = {
        Bucket: bucket,
        Key: key,
        Body: body, 
        ContentType: contentType
    }
    
    console.log(`Uploading to ${UPLOAD_PARAMS.Bucket} ${UPLOAD_PARAMS.Key}`);
    
    await s3.upload(UPLOAD_PARAMS)
    .promise()
    .then( data => { console.log(`Success`, data); })
    .catch( err => { console.log(`Failed`, err); })
}

exports.handler = async function(event, context) {    
    console.log(`Sending Request to ${RES_ENDPOINT}`);
    
    const data = await getRequest(RES_ENDPOINT, options);
    
    for (var i = 0; i < data.length; i++) {
        body = await getRequest(data[i].download_url, options);

        await uploadToS3('evetrade', `resources/${data[i].name}`, JSON.stringify(body), 'application/json');
    }
}