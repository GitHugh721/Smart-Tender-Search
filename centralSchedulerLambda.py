import boto3
import json
from datetime import datetime, timezone, timedelta

# Initialize the DynamoDB and SQS clients
dynamodb = boto3.client('dynamodb', region_name='eu-north-1')
sqs = boto3.client('sqs')

# Your SQS queue URL
queue_url = 'https://sqs.eu-north-1.amazonaws.com/462197742027/UserTaskQueue'
table_name = 'UserPreferences'

# Mapping Czech days to datetime module's weekday() function outputs
day_mapping = {
    "Pondělí": 0,  # Monday
    "Úterý": 1,    # Tuesday
    "Středa": 2,   # Wednesday
    "Čtvrtek": 3,  # Thursday
    "Pátek": 4,    # Friday
    "Sobota": 5,   # Saturday
    "Neděle": 6    # Sunday
}

def lambda_handler(event, context):
    print("Lambda function has started execution.")
    now = datetime.now(timezone.utc) + timedelta(hours=2)  # Assuming CEST (UTC+2) for example
    
    try:
        # Query DynamoDB for user preferences
        response = dynamodb.scan(TableName=table_name)
        print(f"DynamoDB Scan response: {response}")
    except Exception as e:
        print(f"Failed to scan DynamoDB: {e}")
        return {'statusCode': 500, 'body': json.dumps(f"Failed to scan DynamoDB: {str(e)}")}

    successful_sends = 0
    for item in response['Items']:
        user_preferences = item['preferences']['M']
        frekvence_zasilani = user_preferences['frekvence_zasilani']['S']
        
        if is_scheduled_time(now, frekvence_zasilani):
            task_details = {
                'user_id': item['user_id']['S'],
                'email': user_preferences['email_pro_zasilani_vysledku']['S'],
                'keywords': user_preferences['klicova_slova']['S'],
                'description': user_preferences['popis_firmy']['S'],
                'role': item['user_role']['S'],
                'frekvence_zasilani': frekvence_zasilani
            }
            
            try:
                # Send a message to the SQS queue with the task details
                sqs_response = sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps(task_details)
                )
                print(f"Message sent to SQS for user_id {task_details['user_id']}: {sqs_response}")
                successful_sends += 1
            except Exception as e:
                print(f"Failed to send message to SQS for user_id {task_details['user_id']}: {e}")

    return {'statusCode': 200, 'body': json.dumps(f"Messages successfully sent: {successful_sends}")}

def is_scheduled_time(current_time, schedule_preference):
    current_weekday = current_time.weekday()
    current_hour = current_time.hour
    # Handling "Once daily" tasks
    if "Jednou denně" in schedule_preference:
        return current_hour == 12  # Assuming tasks should run at noon every day

    # Extract the day and check if it matches the current day
    schedule_parts = schedule_preference.split(' v ')  # Splits into ["Středa", "12:00"]
    if len(schedule_parts) == 2:
        day_name, time_str = schedule_parts
        schedule_hour = int(time_str.split(':')[0])  # Gets the hour part of "12:00"
        
        if day_name in day_mapping and current_weekday == day_mapping[day_name] and current_hour == schedule_hour:
            return True

    return False
