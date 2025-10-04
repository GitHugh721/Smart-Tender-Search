import json
import boto3
import urllib.request
import os

# Initialize DynamoDB client and table
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('UserPreferences')

# Custom WordPress API endpoint to fetch user roles
wordpress_api_url = 'https://vyhledej-zakazky.cz/wp-json/custom-endpoints/v1/user-role'
api_key = os.environ['MY_API_KEY']

def lambda_handler(event, context):
    headers = {'x-api-key': api_key}

    # Loop through user IDs from 1 to 100
    for user_id in range(1, 100):
        req_role = urllib.request.Request(
            f"{wordpress_api_url}/{user_id}",
            headers=headers
        )
        try:
            with urllib.request.urlopen(req_role) as response:
                user_roles = json.loads(response.read().decode())
                print(f"User {user_id} Roles: {user_roles}")

                # Check if the user has either 'customer' or 'administrator' role
                if 'customer' in user_roles or 'administrator' in user_roles:
                    print(f"User {user_id} is a customer or administrator. Not deleting from DynamoDB.")
                else:
                    print(f"Deleting user {user_id} who is neither customer nor administrator from DynamoDB.")
                    table.delete_item(Key={'user_id': str(user_id)})
        except urllib.error.HTTPError as e:
            print(f"Failed to get roles for user {user_id} with error {e.code}: {str(e)}")
            if e.code == 404:
                print(f"User {user_id} not found in WordPress, deleting from DynamoDB.")
                table.delete_item(Key={'user_id': str(user_id)})
        except Exception as e:
            print(f"Unhandled exception for user {user_id}: {str(e)}")

    return {
        'statusCode': 200,
        'body': json.dumps('Cleanup process completed successfully.')
    }
