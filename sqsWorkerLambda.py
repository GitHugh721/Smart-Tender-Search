import json
import boto3

# Initialize the Lambda client
lambda_client = boto3.client('lambda')

def lambda_handler(event, context):
    # Process each SQS message
    for record in event['Records']:
        # Parse the message body
        message_body = json.loads(record['body'])
        print(f"Received message: {message_body}")

        # Construct the payload for the scraper Lambda function
        # Ensure you pass all necessary data the scraper function needs
        payload = {
            'user_id': message_body['user_id'],
            # Include any other data needed by the EU_Czech_Tender_Search function
        }

        # Invoke the scraper Lambda function
        response = lambda_client.invoke(
            FunctionName='EU_Czech_Tender_Search',  # The name of your deployed scraper Lambda function
            InvocationType='Event',  # 'Event' for asynchronous execution
            Payload=json.dumps(payload)  # Payload must be a JSON-formatted string
        )

        # Log the response from invoking the scraper Lambda function
        print(f"Invoked EU_Czech_Tender_Search Lambda function for user_id {message_body['user_id']} with response: {response}")

    return {
        'statusCode': 200,
        'body': json.dumps('All messages handed off to EU_Czech_Tender_Search Lambda function')
    }
