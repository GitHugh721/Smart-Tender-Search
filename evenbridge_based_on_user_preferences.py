import boto3
import json
import unicodedata
import logging
import hashlib
import random

# Initialize the clients for DynamoDB and EventBridge
dynamodb = boto3.resource('dynamodb', region_name='eu-north-1')
eventbridge = boto3.client('events')
table = dynamodb.Table('UserPreferences')

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)



def lambda_handler(event, context):
    """Process user preferences to recreate EventBridge rules."""
    try:
        logger.info("Starting to clear existing EventBridge rules.")
        clear_all_rules()

        logger.info("Starting to process active users from DynamoDB.")
        response = table.scan()
        items = response.get('Items', [])
        for item in items:
            user_id = item.get('user_id')
            preferences = item.get('preferences')
            if user_id and preferences:
                logger.info(f"Processing preferences for user_id: {user_id} with preferences: {preferences}")
                process_user_preferences(user_id, preferences)

        return {'statusCode': 200, 'body': json.dumps('EventBridge rules recreated successfully')}
    except Exception as e:
        logger.error(f"Error processing items: {type(e).__name__}: {e}")
        return {'statusCode': 500, 'body': json.dumps('Error processing items')}

def clear_all_rules():
    """Deletes all EventBridge rules and their targets, except those containing 'gregi'."""
    rules = eventbridge.list_rules()['Rules']
    for rule in rules:
        rule_name = rule['Name']
        if 'gregi' in rule_name.lower():
            logger.info(f"Skipping rule: {rule_name} (contains 'gregi')")
            continue
        remove_targets_from_rule(rule_name)
        eventbridge.delete_rule(Name=rule_name)
        logger.info(f"Deleted rule: {rule_name}")

def remove_targets_from_rule(rule_name):
    """Removes all targets from a given rule."""
    targets = eventbridge.list_targets_by_rule(Rule=rule_name)['Targets']
    target_ids = [target['Id'] for target in targets]
    if target_ids:
        eventbridge.remove_targets(Rule=rule_name, Ids=target_ids)
        logger.info(f"Targets removed from rule: {rule_name}")

def process_user_preferences(user_id, preferences):
    """Create EventBridge rules based on user preferences."""
    schedule_preference = preferences.get('frekvence_zasilani')
    if schedule_preference:
        days_with_times = schedule_preference.split(', ')
        for day_with_time in days_with_times:
            process_day_with_time(user_id, day_with_time)


def create_eventbridge_rule(user_id, cron_expression, day_name):
    # Generate a random number for uniqueness
    random_number = random.randint(1000, 9999)  # This produces a four-digit random number
    rule_name = f"rule_for_user_{user_id}_{random_number}"
    lambda_arn = 'arn:aws:lambda:eu-north-1:462197742027:function:EU_Czech_Tender_Search'

    # Put or update the rule in EventBridge
    eventbridge.put_rule(
        Name=rule_name,
        ScheduleExpression=cron_expression,
        State='ENABLED'
    )
    # Set targets for the rule
    eventbridge.put_targets(
        Rule=rule_name,
        Targets=[
            {'Id': f"target_{user_id}", 'Arn': lambda_arn, 'Input': json.dumps({'user_id': user_id})}
        ]
    )
    logger.info(f"Created/Updated rule: {rule_name} with cron: {cron_expression}")

def process_day_with_time(user_id, day_with_time):
    """Process a single day or daily preference to create an EventBridge rule."""
    # Splitting the input based on space for "Každý den" or " v " for specific days
    if "Každý den" in day_with_time:
        # Set cron for daily at 10:00
        cron_expression = "cron(00 10 * * ? *)"
        day_part = "Everyday"
        logger.info(f"Processing 'Everyday' preference for user_id: {user_id} at 10:00")
    else:
        # For specific days, split by ' v ' and get the day name directly
        day_part = day_with_time.split(' v ')[0]
        cron_expression = day_to_cron(day_part)
        logger.info(f"Processing day '{day_part}' for user_id: {user_id} at 10:00")

    create_eventbridge_rule(user_id, cron_expression, day_part)

def day_to_cron(day_name):
    """Maps Czech day names to cron expressions for AWS EventBridge."""
    day_to_cron_map = {
        "Pondělí": "cron(00 10 ? * 2 *)",  # Monday
        "Úterý": "cron(00 10 ? * 3 *)",    # Tuesday
        "Středa": "cron(00 10 ? * 4 *)",   # Wednesday
        "Čtvrtek": "cron(00 10 ? * 5 *)",  # Thursday
        "Pátek": "cron(00 10 ? * 6 *)",    # Friday
        "Sobota": "cron(00 10 ? * 7 *)",   # Saturday
        "Neděle": "cron(00 10 ? * 1 *)"    # Sunday
    }
    return day_to_cron_map.get(day_name, "cron(00 10 ? * * *)")  # Default to daily if day name not matched

