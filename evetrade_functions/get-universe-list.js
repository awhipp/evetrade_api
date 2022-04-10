// Returns the EVE Online List of Universe Objects

const AWS = require('aws-sdk');
AWS.config.update({region: 'us-east-1'});

const s3 = new AWS.S3();

const resource_name = 'universeList.json'

exports.handler = async function(event, context) {
    const DOWNLOAD_PARAMS = {
        Bucket: 'evetrade',
        Key: `resources/${resource_name}`
    };

    return await s3.getObject(DOWNLOAD_PARAMS)
    .promise()
    .then( data => { 
        console.log(`Successfully retrieved ${resource_name}`);
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