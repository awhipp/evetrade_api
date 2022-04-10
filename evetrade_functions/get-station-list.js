// Returns the EVE Online List of Stations

const AWS = require('aws-sdk');
AWS.config.update({region: 'us-east-1'});

const s3 = new AWS.S3();

exports.handler = async function(event, context) {
    const DOWNLOAD_PARAMS = {
        Bucket: 'evetrade',
        Key: 'resources/stationList.json'
    };

    return await s3.getObject(DOWNLOAD_PARAMS)
    .promise()
    .then( data => { 
        console.log(`Successfully retrieved stationList.json`);
        return {
            'body': JSON.parse(data.Body.toString('utf-8'))
        };
    })
    .catch( err => { 
        console.log(`Failed`, err); 
        return {
            'body': []
        };
    });
};