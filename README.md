# Smart Tender Search

An automated procurement tender search system that monitors Czech Republic and European Union public procurement opportunities, analyzes their relevance using AI, and delivers personalized email notifications to users.

## System Architecture

This system consists of AWS Lambda functions and a WordPress plugin working together to provide automated tender discovery and notifications.

### Architecture Flow

```
WordPress Website → DynamoDB → EventBridge/Scheduler → Lambda Functions → Email Notifications
```

## Components

### 1. WordPress Plugin: Custom REST Endpoints (`wordpress_plugin_front_end`)

**Purpose:** Exposes a secure REST API endpoint for retrieving WordPress user roles.

**Features:**
- Custom REST endpoint: `/wp-json/custom-endpoints/v1/user-role/{id}`
- API key authentication via `x-api-key` header
- Returns user roles by user ID

**Configuration:**
- Set `MY_API_KEY` constant in WordPress configuration

### 2. DynamoDB Handler (`DynamoDB_handler.py`)

**Purpose:** Processes user preference submissions from WordPress forms and stores them in DynamoDB.

**Handles:**
- Type of procurement (Czech/EU)
- Keywords for searching
- Company description
- Email preferences
- Notification frequency

**DynamoDB Table:** `UserPreferences`

### 3. User Role Checker (`CheckUserRole.py`)

**Purpose:** Validates user subscriptions by checking WordPress user roles and cleaning up expired users.

**Behavior:**
- Checks users 1-100 against WordPress API
- Keeps users with `customer` or `administrator` roles
- Removes users without valid roles from DynamoDB

**Schedule:** Runs periodically to maintain data integrity

### 4. Central Scheduler (`centralSchedulerLambda.py`)

**Purpose:** Main orchestrator that checks user preferences and schedules scraping tasks.

**Features:**
- Scans DynamoDB for active users
- Matches current time with user notification preferences
- Sends tasks to SQS queue for processing

**Configuration:**
- SQS Queue: `UserTaskQueue`
- Region: `eu-north-1`

### 5. SQS Worker (`sqsWorkerLambda.py`)

**Purpose:** Processes messages from SQS queue and triggers the main scraping function.

**Behavior:**
- Reads messages from SQS
- Invokes `EU_Czech_Tender_Search` Lambda asynchronously
- Logs all invocations

### 6. Main Scraping Function (`main_function.py`)

**Purpose:** Core business logic - scrapes tenders, analyzes relevance with AI, and sends emails.

**Key Classes:**

#### `ConfigManager`
- Centralizes configuration (API keys, timeouts, URLs)
- Manages secrets from environment variables

#### `ScrapingService`
- Scrapes Czech procurement portal (nen.nipez.cz)
- Scrapes EU TED API (api.ted.europa.eu)
- Translates keywords using AWS Translate
- Implements rate limiting and error handling

#### `EnhancedOpenAIService`
- Uses GPT-4 to analyze tender relevance
- Generates HTML-formatted responses
- Compares tenders against company description and keywords

#### `ModernEmailService`
- Sends professional HTML emails via Brevo API
- Optimized email templates
- Dynamic subject lines based on results
- Unsubscribe links and email best practices

**Data Sources:**
1. **Czech Republic:** https://nen.nipez.cz
2. **European Union:** https://api.ted.europa.eu/v3/notices/search

### 7. EventBridge Rule Manager (`evenbridge_based_on_user_preferences.py`)

**Purpose:** Creates and manages EventBridge rules for user-specific scheduling.

**Features:**
- Clears existing rules (except those containing 'gregi')
- Creates rules based on user preferences
- Maps Czech day names to cron expressions
- Supports daily and specific day scheduling

### 8. OpenAI Layer (`openai_layer.py`)

**Purpose:** Simplified OpenAI API wrapper (appears to be legacy/testing code).

## Environment Variables

Required environment variables for Lambda functions:

```bash
BREVO_API_KEY=your_brevo_api_key
OPENAI_API_KEY=your_openai_api_key
MY_API_KEY=your_wordpress_api_key
```

## AWS Resources

### Lambda Functions
- `EU_Czech_Tender_Search` - Main scraping and processing
- `DynamoDB_Handler` - User preference storage
- `CheckUserRole` - User validation
- `CentralScheduler` - Task orchestration
- `SQSWorker` - Queue processing
- `EventBridgeRuleManager` - Schedule management

### DynamoDB
- **Table:** `UserPreferences`
- **Primary Key:** `user_id` (String)
- **Attributes:**
  - `user_email`
  - `user_role`
  - `preferences` (Map)

### SQS
- **Queue:** `UserTaskQueue`
- **URL:** `https://sqs.eu-north-1.amazonaws.com/462197742027/UserTaskQueue`

### EventBridge
- Dynamic rules created per user schedule

### AWS Services Used
- Lambda
- DynamoDB
- SQS
- EventBridge
- AWS Translate
- S3 (referenced but not actively used)

## Installation & Deployment

### Prerequisites
- AWS Account with appropriate permissions
- WordPress site with WooCommerce
- Brevo (formerly SendInBlue) account
- OpenAI API account

### WordPress Setup

1. Install the custom REST endpoints plugin
2. Define `MY_API_KEY` in `wp-config.php`:
```php
define('MY_API_KEY', 'your-secure-api-key');
```

### Lambda Deployment

1. Package each Lambda function with dependencies:
```bash
pip install -r requirements.txt -t .
zip -r function.zip .
```

2. Deploy using AWS CLI or Console:
```bash
aws lambda create-function \
  --function-name EU_Czech_Tender_Search \
  --runtime python3.9 \
  --handler main_function.lambda_handler \
  --zip-file fileb://function.zip
```

3. Set environment variables for each function

### DynamoDB Setup

Create table:
```bash
aws dynamodb create-table \
  --table-name UserPreferences \
  --attribute-definitions AttributeName=user_id,AttributeType=S \
  --key-schema AttributeName=user_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

## Dependencies

### Python Packages
```
boto3
requests
beautifulsoup4
openai
python-dateutil
```

### WordPress
- WordPress 5.0+
- Custom user roles (customer, administrator)

## Usage Flow

1. **User Registration:** User signs up on WordPress site and sets preferences
2. **Preference Storage:** Form submission triggers DynamoDB handler
3. **Schedule Creation:** EventBridge rules created based on frequency
4. **Daily Execution:** Central scheduler checks for due tasks
5. **Queue Processing:** Tasks sent to SQS queue
6. **Tender Scraping:** Main function scrapes Czech and EU sources
7. **AI Analysis:** OpenAI evaluates relevance to user's company
8. **Email Delivery:** Personalized email sent via Brevo
9. **Role Validation:** Periodic checks ensure only paying customers receive service

## Email Template Features

- Modern, responsive HTML design
- Gradient header with branding
- Statistics section showing results count
- Individual tender cards with descriptions
- Call-to-action buttons
- Unsubscribe functionality
- Plain text fallback for accessibility

## Error Handling

- Comprehensive logging throughout
- Graceful degradation for API failures
- Rate limiting for external APIs
- Retry logic for transient failures
- User-friendly error messages

## Security Considerations

- API key authentication for WordPress endpoints
- Environment variables for sensitive data
- IAM roles with least privilege
- Input validation and sanitization
- No storage of API keys in code

## Monitoring & Logging

All functions use Python's logging module with CloudWatch integration:
- INFO level for normal operations
- WARNING for degraded functionality
- ERROR for failures requiring attention

## Cost Optimization

- Pay-per-request DynamoDB billing
- Asynchronous Lambda invocations
- SQS for decoupling and buffering
- Result limiting to prevent timeouts
- Efficient scraping with timeouts

## Future Improvements

- [ ] Add Redis caching for scraped results
- [ ] Implement webhook notifications
- [ ] Add more procurement sources
- [ ] Enhanced AI prompt engineering
- [ ] User dashboard for result history
- [ ] A/B testing for email templates
- [ ] Multi-language support


## Author

Bohuslav Sedláček

## Support

For issues and questions, contact: info@inetio.cz
