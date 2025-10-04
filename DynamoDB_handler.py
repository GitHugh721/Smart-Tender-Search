import json
import boto3
import base64
import urllib.parse

# Initialize a DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('UserPreferences')

def lambda_handler(event, context):
    try:
        print("Received event:", event)  # Log the entire incoming event for debugging

        # Decode the incoming data
        body = base64.b64decode(event['body']) if event.get('isBase64Encoded', False) else event['body']

        # Parse the URL-encoded data
        parsed_body = urllib.parse.parse_qs(body.decode('utf-8'), keep_blank_values=True)

        # Log the parsed body to see structured data
        print("Parsed body:", json.dumps(parsed_body))

        # Adjust the field names to correctly map the descriptive form field names
        druh_zakazek = ', '.join(parsed_body.get("Vyberte druh zakázek:", []))
        klicova_slova = ', '.join(parsed_body.get("Vyhledávaná klíčová slova (Max.15 klíčových slov):", []))
        
        frekvence_zasilani = ', '.join(parsed_body.get("Časová frekvence odesílání:", []))
        email_pro_zasilani_vysledku = ', '.join(parsed_body.get("Emailová adresa pro zasílání výsledků:", []))
        popis_firmy = ', '.join(parsed_body.get("Popis vaší firmy:", []))
        user_email = parsed_body.get("user_email", [""])[0]
        user_id = parsed_body.get("user_id", [""])[0]
        user_role = parsed_body.get("user_role", [""])[0]

        # Write to the DynamoDB table
        response = table.put_item(
            Item={
                'user_id': user_id,
                'user_email': user_email,
                'user_role': user_role,
                'preferences': {
                    'druh_zakazek': druh_zakazek,
                    'klicova_slova': klicova_slova,
                    
                    'frekvence_zasilani': frekvence_zasilani,
                    'email_pro_zasilani_vysledku': email_pro_zasilani_vysledku,
                    'popis_firmy': popis_firmy
                }
            }
        )

        return {
            'statusCode': 200,
            'body': json.dumps('User preferences updated successfully')
        }

    except Exception as e:
        print(f"Error processing lambda function: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps('Error processing data')
        }
