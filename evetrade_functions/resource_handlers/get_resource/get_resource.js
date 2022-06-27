// Grabs S3 file and returns contents as JSON

const AWS = require('aws-sdk');
AWS.config.update({region: 'us-east-1'});

const s3 = new AWS.S3();

exports.handler = async function(event, context) {
    console.log(event);

    const resource_name = event['queryStringParameters']['file']

    const DOWNLOAD_PARAMS = {
        Bucket: 'evetrade',
        Key: `resources/${resource_name}`
    };

    return await s3.getObject(DOWNLOAD_PARAMS)
    .promise()
    .then( data => { 
        console.log(`Successfully retrieved ${resource_name}`);
        return {
            headers: {
              'Access-Control-Allow-Origin': '*'
            },
            'body': data.Body.toString('utf-8')
        };
    })
    .catch( err => { 
        console.log(`Failed`, err); 
        return {
            headers: {
              'Access-Control-Allow-Origin': '*'
            },
            'body': {}
        };
    });
};