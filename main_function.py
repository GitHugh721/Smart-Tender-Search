import boto3
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Tuple
import openai
import logging
from botocore.exceptions import ClientError
from dateutil import parser
import time
from urllib.parse import quote_plus
import random
import re
import os

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ProcurementResult:
    """Data class for procurement results"""
    headline: str
    detail_link: str
    deadline_date: Optional[str] = None
    source: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'headline': self.headline,
            'detail_link': self.detail_link,
            'deadline_date': self.deadline_date,
            'source': self.source
        }

@dataclass
class UserPreferences:
    """Data class for user preferences"""
    company_description: str
    search_type: str
    keywords: List[str]
    email: str
    user_id: str

class ConfigManager:
    """Centralized configuration management"""
    
    def __init__(self):
        self.TABLE_NAME = 'UserPreferences'
        self.BREVO_API_KEY = self._get_secret('BREVO_API_KEY')
        self.OPENAI_API_KEY = self._get_secret('OPENAI_API_KEY')
        self.BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
        
        # Request configuration
        self.REQUEST_TIMEOUT = 30
        self.MAX_RETRIES = 3
        self.RATE_LIMIT_DELAY = 1
    
    def _get_secret(self, key: str) -> str:
        """Get secret from environment or fallback to hardcoded"""
        # Try environment first
        value = os.getenv(key)
        if value:
            return value
        
        # Fallback to hardcoded (update these with your actual keys)
        secrets = {
            'BREVO_API_KEY': "",
            'OPENAI_API_KEY': ""
        }
        return secrets.get(key, "")

class AWSClientManager:
    """Centralized AWS client management with error handling"""
    
    def __init__(self):
        try:
            self.lambda_client = boto3.client('lambda')
            self.dynamodb = boto3.client('dynamodb')
            self.translate = boto3.client('translate')
            self.s3 = boto3.client('s3')
            self.ses_client = boto3.client('ses', region_name='eu-north-1')
        except Exception as e:
            logger.error(f"Failed to initialize AWS clients: {e}")
            raise

class DataProcessor:
    """Handles data processing and validation"""
    
    @staticmethod
    def clean_and_split_keywords(keyword_string: str) -> List[str]:
        """Clean and split keywords with better validation"""
        if not keyword_string or not isinstance(keyword_string, str):
            return []
        
        # Remove extra spaces and normalize separators
        cleaned = keyword_string.replace(';', ',').replace('|', ',')
        cleaned = ', '.join(cleaned.split(',')).replace('  ', ' ')
        
        # Split and clean each keyword
        keywords = [
            keyword.strip() 
            for keyword in cleaned.split(', ')
            if keyword.strip() and len(keyword.strip()) > 1
        ]
        
        return keywords[:20]  # Limit to prevent abuse
    
    @staticmethod
    def extract_user_preferences(item: Dict) -> UserPreferences:
        """Extract and validate user preferences from DynamoDB item"""
        preferences = item.get('preferences', {}).get('M', {})
        
        company_description = preferences.get('popis_firmy', {}).get('S', '')
        search_type = preferences.get('druh_zakazek', {}).get('S', '')
        keyword_string = preferences.get('klicova_slova', {}).get('S', '')
        email = preferences.get('email_pro_zasilani_vysledku', {}).get('S', '')
        user_id = item.get('user_id', {}).get('S', '')
        
        keywords = DataProcessor.clean_and_split_keywords(keyword_string)
        
        return UserPreferences(
            company_description=company_description,
            search_type=search_type,
            keywords=keywords,
            email=email,
            user_id=user_id
        )

class ScrapingService:
    """Enhanced scraping service with better error handling and rate limiting"""
    
    def __init__(self, config: ConfigManager, aws_clients: AWSClientManager):
        self.config = config
        self.aws_clients = aws_clients
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def scrape_based_on_preferences(
        self, 
        search_type: str, 
        keywords: List[str], 
        description: str
    ) -> List[ProcurementResult]:
        """Main scraping orchestrator"""
        results = []
        
        try:
            if "Evropská unie" in search_type and keywords:
                logger.info("Scraping EU tenders")
                translated_keywords = self._translate_keywords_to_english(keywords)
                for keyword in translated_keywords[:5]:  # Limit to prevent timeout
                    time.sleep(self.config.RATE_LIMIT_DELAY)
                    results.extend(self.scrape_eu(keyword))
            
            if "Česká republika" in search_type and keywords:
                logger.info("Scraping Czech tenders")
                for keyword in keywords[:5]:  # Limit to prevent timeout
                    time.sleep(self.config.RATE_LIMIT_DELAY)
                    results.extend(self.scrape_czech(keyword))
                    
        except Exception as e:
            logger.error(f"Error in scraping orchestrator: {e}")
        
        return results
    
    def _translate_keywords_to_english(self, keywords: List[str]) -> List[str]:
        """Translate keywords with error handling"""
        translated_keywords = []
        
        for keyword in keywords:
            try:
                result = self.aws_clients.translate.translate_text(
                    Text=keyword,
                    SourceLanguageCode='cs',
                    TargetLanguageCode='en'
                )
                translated_keywords.append(result.get('TranslatedText', keyword))
                time.sleep(0.1)  # Small delay
                
            except Exception as e:
                logger.warning(f"Translation failed for '{keyword}': {e}")
                translated_keywords.append(keyword)  # Fallback to original
        
        return translated_keywords
    
    def scrape_czech(self, keyword: str) -> List[ProcurementResult]:
        """Enhanced Czech scraping with better error handling"""
        logger.info(f"Scraping Czech tenders for keyword: {keyword}")
        results = []
        
        try:
            current_date = datetime.now().strftime("%Y-%m-%d")
            encoded_keyword = quote_plus(keyword)
            base_url = "https://nen.nipez.cz"
            search_url = (
                f"{base_url}/verejne-zakazky/"
                f"p:vz:query={encoded_keyword}"
                f"&stavZP=planovana,neukoncena,zadana"
                f"&podaniLhuta={current_date},"
                f"&page=1-50"
            )
            
            response = self.session.get(
                search_url, 
                timeout=self.config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.find_all('tr', class_='gov-table__row')
            
            for row in rows[:25]:  # Limit results
                detail_link_element = row.find('a', class_='gov-link', href=True)
                if detail_link_element:
                    detail_link = base_url + detail_link_element['href']
                    headline_element = row.find('td', {"data-title": "Název zadávacího postupu"})
                    headline = headline_element.get_text(strip=True) if headline_element else "Bez názvu"
                    
                    results.append(ProcurementResult(
                        headline=headline,
                        detail_link=detail_link,
                        source="Czech Republic"
                    ))
            
            logger.info(f"Found {len(results)} Czech results for '{keyword}'")
            
        except requests.RequestException as e:
            logger.error(f"Network error scraping Czech tenders for '{keyword}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error scraping Czech tenders for '{keyword}': {e}")
        
        return results
    
    def scrape_eu(self, keyword: str) -> List[ProcurementResult]:
        """Enhanced EU scraping with better date handling"""
        logger.info(f"Scraping EU tenders for keyword: {keyword}")
        results = []
        
        api_url = "https://api.ted.europa.eu/v3/notices/search"
        payload = {
            "query": f"(notice-title={keyword})",
            "fields": [
                "publication-number",
                "notice-title",
                "links",
                "deadline-date-lot"
            ],
            "page": 1,
            "limit": 100,
            "scope": "ACTIVE",
            "checkQuerySyntax": False,
            "paginationMode": "PAGE_NUMBER"
        }
        
        headers = {
            "Content-Type": "application/json",
            "accept": "application/json"
        }
        
        try:
            response = self.session.post(
                api_url, 
                headers=headers, 
                json=payload,
                timeout=self.config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            notices = data.get("notices", [])
            today = datetime.now().date()
            
            for notice in notices[:25]:  # Limit results
                title = notice.get("notice-title", {}).get("eng", "No title available")
                
                ted_xml_link = (
                    notice.get("links", {})
                    .get("xml", {})
                    .get("MUL", "No Link Available")
                )
                detail_link = self._fix_ted_xml_link(ted_xml_link)
                
                # Better deadline handling
                deadline_value = notice.get("deadline-date-lot")
                if self._is_deadline_valid(deadline_value, today):
                    results.append(ProcurementResult(
                        headline=title,
                        detail_link=detail_link,
                        deadline_date=str(deadline_value) if deadline_value else None,
                        source="European Union"
                    ))
            
            logger.info(f"Found {len(results)} EU results for '{keyword}'")
            
        except requests.RequestException as e:
            logger.error(f"Network error fetching EU tenders for '{keyword}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching EU tenders for '{keyword}': {e}")
        
        return results
    
    def _fix_ted_xml_link(self, xml_link: str) -> str:
        """Fix TED XML links with validation"""
        if not xml_link or xml_link == "No Link Available":
            return xml_link
        
        if xml_link.endswith("/xml"):
            xml_link = xml_link[:-4]
        xml_link = xml_link.replace("/notice/", "/notice/-/detail/", 1)
        return xml_link
    
    def _is_deadline_valid(self, deadline_value: Any, today: datetime.date) -> bool:
        """Validate deadline dates with better error handling"""
        if not deadline_value:
            return False
        
        try:
            if isinstance(deadline_value, list) and len(deadline_value) > 0:
                first_deadline_str = deadline_value[0]
            elif isinstance(deadline_value, str):
                first_deadline_str = deadline_value.split()[0]
            else:
                return False
            
            deadline_dt = parser.isoparse(first_deadline_str)
            return deadline_dt.date() > today
            
        except (ValueError, IndexError, TypeError) as e:
            logger.debug(f"Invalid deadline format: {deadline_value}, error: {e}")
            return False

class ModernEmailService:
    """Modern email service with optimized templates and delivery"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
    
    def generate_optimized_subject(self, results_count: int = 0) -> str:
        """Generate optimized email subject line for better deliverability"""
        
        if results_count > 0:
            subjects = [
                f"📋 {results_count} nových zakázek pro vaši firmu",
                f"🎯 Nalezeno {results_count} relevantních zakázek",
                f"📈 {results_count} příležitostí k podnikání",
                f"✅ Denní přehled: {results_count} zakázek",
                f"🔍 Výsledky vyhledávání - {results_count} zakázek"
            ]
        else:
            subjects = [
                "📋 Denní přehled veřejných zakázek",
                "🔍 Výsledky vašeho vyhledávání",
                "📈 Přehled nových příležitostí",
                "✉️ Váš pravidelný update zakázek"
            ]
        
        return random.choice(subjects)
    
    def send_email(
        self, 
        response_content: str, 
        preferences: UserPreferences,
        results_count: int = 0
    ) -> bool:
        """Send email with modern template and optimized deliverability"""
        
        if not preferences.email:
            logger.error(f"No email address for user {preferences.user_id}")
            return False
        
        try:
            # Generate optimized subject
            subject = self.generate_optimized_subject(results_count)
            
            # Generate modern email template
            email_body = self._generate_modern_email_template(
                response_content, 
                preferences.user_id,
                results_count
            )
            
            payload = {
                "sender": {
                    "name": "Vyhledávač Zakázek",
                    "email": "vyhledavac@vyhledej-zakazky.cz"
                },
                "to": [{"email": preferences.email}],
                "subject": subject,
                "htmlContent": email_body,
                "textContent": self._generate_text_version(response_content, results_count),
                "headers": {
                    "X-Mailer": "VyhledejZakazky-v2.0",
                    "List-Unsubscribe": "<https://vyhledej-zakazky.cz/odhlasit/>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"
                },
                "tags": ["procurement", "daily-digest"]
            }
            
            headers = {
                "accept": "application/json",
                "api-key": self.config.BREVO_API_KEY,
                "content-type": "application/json"
            }
            
            response = requests.post(
                self.config.BREVO_API_URL, 
                headers=headers, 
                json=payload,
                timeout=self.config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            response_data = response.json()
            message_id = response_data.get("messageId")
            
            if message_id:
                logger.info(f"Email sent successfully to {preferences.email}. Message ID: {message_id}")
                return True
            else:
                logger.error("Failed to send email. No message ID received.")
                return False
                
        except requests.RequestException as e:
            logger.error(f"Failed to send email to {preferences.email}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending email to {preferences.email}: {e}")
            return False
    
    def _generate_modern_email_template(
        self, 
        response_content: str, 
        user_id: str,
        results_count: int
    ) -> str:
        """Generate modern, clean email template"""
        
        current_date = datetime.now().strftime("%d.%m.%Y")
        
        return f"""
<!DOCTYPE html>
<html lang="cs">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>Výsledky vyhledávání zakázek</title>
    <!--[if mso]>
    <noscript>
        <xml>
            <o:OfficeDocumentSettings>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <![endif]-->
    <style>
        /* Reset and base styles */
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body, table, td, p, a, li, blockquote {{
            -webkit-text-size-adjust: 100%;
            -ms-text-size-adjust: 100%;
        }}
        
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
        img {{ -ms-interpolation-mode: bicubic; border: 0; outline: none; }}
        
        /* Main styles */
        body {{
            margin: 0 !important;
            padding: 0 !important;
            background-color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #374151;
        }}
        
        .email-container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 40px 30px;
            text-align: center;
        }}
        
        .header img {{
            max-width: 200px;
            height: auto;
            margin-bottom: 20px;
        }}
        
        .header h1 {{
            color: #ffffff;
            font-size: 24px;
            font-weight: 600;
            margin: 0;
            text-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        .header .date {{
            color: #e2e8f0;
            font-size: 14px;
            margin-top: 8px;
        }}
        
        .content {{
            padding: 40px 30px;
        }}
        
        .greeting {{
            font-size: 16px;
            color: #1f2937;
            margin-bottom: 30px;
            line-height: 1.5;
        }}
        
        .results-container {{
            background-color: #f9fafb;
            border-radius: 12px;
            padding: 30px;
            margin: 30px 0;
            border-left: 4px solid #667eea;
        }}
        
        .results-header {{
            display: flex;
            align-items: center;
            margin-bottom: 20px;
            gap: 10px;
        }}
        
        .results-icon {{
            width: 24px;
            height: 24px;
            background-color: #667eea;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            font-size: 14px;
        }}
        
        .results-title {{
            font-size: 18px;
            font-weight: 600;
            color: #1f2937;
            margin: 0;
        }}
        
        .vysledky, .results-found, .no-results {{
            font-size: 15px;
            line-height: 1.7;
            color: #374151;
        }}
        
        .vysledky a, .results-found a, .tender-link {{
            color: #667eea;
            text-decoration: none;
            font-weight: 500;
            transition: color 0.2s ease;
        }}
        
        .vysledky a:hover, .results-found a:hover, .tender-link:hover {{
            color: #5a6acf;
            text-decoration: underline;
        }}
        
        .tender-item {{
            background-color: #ffffff;
            border-radius: 8px;
            padding: 20px;
            margin: 15px 0;
            border-left: 3px solid #667eea;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        
        .tender-title {{
            font-size: 16px;
            font-weight: 600;
            color: #1f2937;
            margin: 0 0 10px 0;
        }}
        
        .tender-description {{
            font-size: 14px;
            color: #6b7280;
            margin: 0 0 15px 0;
        }}
        
        .stats {{
            background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            text-align: center;
        }}
        
        .stats-number {{
            font-size: 32px;
            font-weight: 700;
            color: #0369a1;
            margin-bottom: 5px;
        }}
        
        .stats-label {{
            font-size: 14px;
            color: #0f172a;
            font-weight: 500;
        }}
        
        .actions {{
            background-color: #ffffff;
            border: 2px solid #e5e7eb;
            border-radius: 12px;
            padding: 25px;
            margin: 30px 0;
            text-align: center;
        }}
        
        .btn {{
            display: inline-block;
            padding: 12px 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #ffffff !important;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}
        
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }}
        
        .help-section {{
            background-color: #fef3c7;
            border-radius: 8px;
            padding: 20px;
            margin: 25px 0;
            border-left: 4px solid #f59e0b;
        }}
        
        .help-title {{
            font-size: 16px;
            font-weight: 600;
            color: #92400e;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .help-text {{
            font-size: 14px;
            color: #a16207;
            line-height: 1.5;
        }}
        
        .footer {{
            background-color: #f9fafb;
            padding: 30px;
            text-align: center;
            border-top: 1px solid #e5e7eb;
        }}
        
        .footer p {{
            font-size: 13px;
            color: #6b7280;
            margin: 8px 0;
        }}
        
        .footer a {{
            color: #667eea;
            text-decoration: none;
        }}
        
        .footer a:hover {{
            text-decoration: underline;
        }}
        
        .unsubscribe {{
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #e5e7eb;
        }}
        
        .suggestions ul {{
            margin: 10px 0;
            padding-left: 20px;
        }}
        
        .suggestions li {{
            margin: 5px 0;
        }}
        
        /* Mobile responsive */
        @media only screen and (max-width: 600px) {{
            .email-container {{ width: 100% !important; }}
            .header, .content, .footer {{ padding: 20px !important; }}
            .header h1 {{ font-size: 20px !important; }}
            .results-container {{ padding: 20px !important; }}
            .stats-number {{ font-size: 24px !important; }}
            .btn {{ padding: 10px 20px !important; font-size: 13px !important; }}
            .results-header {{ flex-direction: column; text-align: center; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <!-- Header -->
        <div class="header">
            <img src="https://vyhledej-zakazky.cz/wp-content/uploads/2024/05/cropped-vyhledej-zakazky.cz_-1.png" 
                 alt="Vyhledávač Zakázek" 
                 style="filter: brightness(0) invert(1);">
            <h1>Přehled nových zakázek</h1>
            <div class="date">{current_date}</div>
        </div>
        
        <!-- Content -->
        <div class="content">
            <div class="greeting">
                <strong>Dobrý den,</strong><br>
                připravili jsme pro vás přehled nových veřejných zakázek na základě vašich preferencí.
            </div>
            
            {self._generate_stats_section(results_count)}
            
            <div class="results-container">
                <div class="results-header">
                    <div class="results-icon">🎯</div>
                    <h2 class="results-title">Nalezené příležitosti</h2>
                </div>
                {response_content}
            </div>
            
            <div class="actions">
                <a href="https://vyhledej-zakazky.cz/admin/" class="btn">
                    ⚙️ Upravit nastavení
                </a>
            </div>
            
            <div class="help-section">
                <div class="help-title">
                    <span>💡</span> Potřebujete pomoct?
                </div>
                <div class="help-text">
                    Máte otázky nebo potřebujete upravit vyhledávací kritéria? 
                    Kontaktujte nás na <a href="mailto:info@vyhledej-zakazky.cz">info@vyhledej-zakazky.cz</a>
                </div>
            </div>
        </div>
        
        <!-- Footer -->
        <div class="footer">
            <p><strong>Vyhledávač zakázek</strong> - váš spolehlivý partner pro veřejné zakázky</p>
            <p>Tento email je generován automaticky na základě vašich nastavení.</p>
            
            <div class="unsubscribe">
                <p>
                    <a href="https://vyhledej-zakazky.cz/muj-ucet/">Spravovat odběr</a> | 
                    <a href="https://vyhledej-zakazky.cz/odhlasit/">Odhlásit se</a>
                </p>
            </div>
        </div>
    </div>
</body>
</html>
        """
    
    def _generate_stats_section(self, results_count: int) -> str:
        """Generate statistics section for the email"""
        if results_count > 0:
            return f"""
            <div class="stats">
                <div class="stats-number">{results_count}</div>
                <div class="stats-label">
                    {"nová zakázka" if results_count == 1 else 
                     "nové zakázky" if 2 <= results_count <= 4 else 
                     "nových zakázek"}
                </div>
            </div>
            """
        else:
            return """
            <div class="stats">
                <div class="stats-number">0</div>
                <div class="stats-label">nových zakázek dnes</div>
            </div>
            """
    
    def _generate_text_version(self, response_content: str, results_count: int) -> str:
        """Generate plain text version for better deliverability"""
        current_date = datetime.now().strftime("%d.%m.%Y")
        
        # Strip HTML tags from response_content for text version
        clean_content = re.sub('<[^<]+?>', '', response_content)
        clean_content = clean_content.replace('&nbsp;', ' ').strip()
        
        return f"""
VYHLEDÁVAČ ZAKÁZEK - PŘEHLED {current_date.upper()}

Dobrý den,

připravili jsme pro vás přehled nových veřejných zakázek.

VÝSLEDKY:
{clean_content}

NALEZENO: {results_count} {'zakázka' if results_count == 1 else 'zakázky' if 2 <= results_count <= 4 else 'zakázek'}

UPRAVIT NASTAVENÍ:
https://vyhledej-zakazky.cz/admin/

KONTAKT:
info@vyhledej-zakazky.cz

ODHLÁSIT SE:
https://vyhledej-zakazky.cz/odhlasit/

---
Tento email je generován automaticky. Prosím neodpovídejte na tuto zprávu.
        """

class EnhancedOpenAIService:
    """Enhanced OpenAI service with better HTML formatting"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        openai.api_key = config.OPENAI_API_KEY
    
    def generate_response(
        self, 
        preferences: UserPreferences, 
        results: List[ProcurementResult]
    ) -> Tuple[Optional[str], int]:
        """Generate AI response and return content with results count"""
        
        if not results:
            return self._generate_no_results_response(), 0
        
        try:
            prompt = self._generate_enhanced_prompt(preferences, results)
            
            if not prompt or len(prompt) > 15000:
                logger.error("Prompt is empty or too long")
                return None, 0
            
            response = openai.ChatCompletion.create(
                model="gpt-4",
                temperature=0.3,
                max_tokens=2000,
                messages=[{
                    "role": "system",
                    "content": """Jste odborný asistent pro hodnocení relevance veřejných zakázek. 
                    Odpovídejte pouze v českém jazyce a používejte čisté HTML formátování."""
                }, {
                    "role": "user", 
                    "content": prompt
                }]
            )
            
            content = response['choices'][0]['message']['content']
            
            # Count relevant results from the response
            relevant_count = content.count('tender-item') if 'tender-item' in content else len([r for r in results if 'relevantní' in content])
            
            logger.info("Successfully generated OpenAI response")
            return content, relevant_count
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None, 0
    
    def _generate_enhanced_prompt(
        self, 
        preferences: UserPreferences, 
        results: List[ProcurementResult]
    ) -> str:
        """Generate enhanced prompt with modern HTML output requirements"""
        
        results_text = "\n".join([
            f"• {result.headline} - {result.detail_link} (Zdroj: {result.source})"
            for result in results[:50]
        ])
        
        return f"""
Na základě následujících informací o firmě vyhodnoť relevantní zakázky:

FIRMA:
Popis: {preferences.company_description}
Klíčová slova: {', '.join(preferences.keywords)}

INSTRUKCE:
1. Vyber pouze zakázky, které jsou skutečně relevantní pro danou firmu
2. Zaměř se na klíčová slova a předmět podnikání
3. Pokud firma má široký předmět podnikání, zvaž různé oblasti
4. Jazyk nabídky není rozhodující faktor

FORMÁT HTML ODPOVĚDI:
Pokud najdeš relevantní zakázky, použij tento formát:

<div class="results-found">
    <p><strong>Nalezli jsme následující relevantní zakázky:</strong></p>
    <div class="tender-list">
        <div class="tender-item">
            <h4 class="tender-title">NÁZEV ZAKÁZKY</h4>
            <p class="tender-description">Krátký popis proč je relevantní</p>
            <a href="ODKAZ" class="tender-link">📋 Více informací zde</a>
        </div>
    </div>
</div>

Pokud není žádná relevantní:
<div class="no-results">
    <p><strong>Dnes jsme nenašli žádné nové zakázky odpovídající vašim kritériím.</strong></p>
    <p>💡 Tip: Zkuste rozšířit klíčová slova nebo upravit popis firmy pro lepší výsledky.</p>
</div>

NALEZENÉ ZAKÁZKY:
{results_text}
        """
    
    def _generate_no_results_response(self) -> str:
        """Generate modern no results response"""
        return """
        <div class="no-results">
            <p><strong>Dnes jsme nenašli žádné nové zakázky odpovídající vašim kritériím.</strong></p>
            <div class="suggestions">
                <p>💡 <strong>Doporučení pro lepší výsledky:</strong></p>
                <ul>
                    <li>Zkontrolujte a rozšiřte klíčová slova</li>
                    <li>Upravte popis firmy pro širší pokrytí</li>
                    <li>Zkuste vyhledávání za několik dní</li>
                </ul>
            </div>
        </div>
        """

class ProcurementLambdaHandler:
    """Main Lambda handler with improved architecture"""
    
    def __init__(self):
        self.config = ConfigManager()
        self.aws_clients = AWSClientManager()
        self.data_processor = DataProcessor()
        self.scraping_service = ScrapingService(self.config, self.aws_clients)
        self.email_service = ModernEmailService(self.config)
        self.openai_service = EnhancedOpenAIService(self.config)
    
    def handle(self, event: Dict, context: Any) -> Dict[str, Any]:
        """Main handler method with comprehensive error handling"""
        logger.info(f"Processing event for Lambda: {event}")
        
        try:
            # Extract and validate user ID
            user_id = event.get('user_id')
            if not user_id:
                return self._error_response(400, 'User ID is required')
            
            # Get user preferences
            preferences = self._get_user_preferences(user_id)
            if not preferences:
                return self._error_response(404, 'User preferences not found')
            
            # Validate preferences
            if not preferences.keywords:
                return self._error_response(400, 'No valid keywords found')
            
            # Scrape data
            logger.info(f"Starting scraping for user {user_id}")
            results = self.scraping_service.scrape_based_on_preferences(
                preferences.search_type,
                preferences.keywords,
                preferences.company_description
            )
            
            logger.info(f"Found {len(results)} total results")
            
            # Generate AI response with count
            ai_response, relevant_count = self.openai_service.generate_response(preferences, results)
            if not ai_response:
                return self._error_response(500, 'Failed to generate AI response')
            
            # Send email with results count for better subject line
            email_sent = self.email_service.send_email(
                ai_response,
                preferences,
                relevant_count
            )
            
            if not email_sent:
                logger.warning(f"Failed to send email to user {user_id}")
            
            return self._success_response({
                'message': 'Processing completed successfully',
                'total_results_found': len(results),
                'relevant_results': relevant_count,
                'email_sent': email_sent,
                'response': ai_response
            })
            
        except Exception as e:
            logger.error(f"Unexpected error in lambda handler: {e}")
            return self._error_response(500, f'Internal server error: {str(e)}')
    
    def _get_user_preferences(self, user_id: str) -> Optional[UserPreferences]:
        """Get and parse user preferences from DynamoDB"""
        try:
            response = self.aws_clients.dynamodb.get_item(
                TableName=self.config.TABLE_NAME,
                Key={'user_id': {'S': str(user_id)}}
            )
            
            item = response.get('Item', {})
            if not item:
                return None
            
            return self.data_processor.extract_user_preferences(item)
            
        except Exception as e:
            logger.error(f"Error getting user preferences for {user_id}: {e}")
            return None
    
    def _success_response(self, data: Dict) -> Dict[str, Any]:
        """Generate success response"""
        return {
            'statusCode': 200,
            'body': json.dumps(data, ensure_ascii=False),
            'headers': {
                'Content-Type': 'application/json; charset=utf-8'
            }
        }
    
    def _error_response(self, status_code: int, message: str) -> Dict[str, Any]:
        """Generate error response"""
        return {
            'statusCode': status_code,
            'body': json.dumps({
                'error': message,
                'timestamp': datetime.now().isoformat()
            }, ensure_ascii=False),
            'headers': {
                'Content-Type': 'application/json; charset=utf-8'
            }
        }

# Backward compatibility functions (keeping original function names)
def clean_and_split_keywords(keyword_string: str) -> List[str]:
    """Backward compatibility wrapper"""
    return DataProcessor.clean_and_split_keywords(keyword_string)

def handle_no_results() -> Dict[str, Any]:
    """Backward compatibility wrapper"""
    return {
        'statusCode': 200, 
        'body': json.dumps("No scraping results found.", ensure_ascii=False)
    }

# Lambda entry point
def lambda_handler(event, context):
    """AWS Lambda entry point"""
    handler = ProcurementLambdaHandler()
    return handler.handle(event, context)
