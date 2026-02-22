import urllib.request
import json
import ssl
from html.parser import HTMLParser

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
    
    def handle_starttag(self, tag, attrs):
        if tag in ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div", "br"]:
            self.result.append("\n")
            
    def handle_data(self, d):
        self.result.append(d)
        
    def get_text(self):
        return "".join(self.result).strip()

def get_twitter_gql_article(tweet_id):
    try:
        # bypass ssl verification
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=x"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            print(f"--- TWEET {tweet_id} ---")
            
            # Print main text first
            if "text" in data:
               print(data["text"])
               
            # Check for article
            if "article" in data and "content" in data["article"]:
                print("\n\n--- FULL ARTICLE ---")
                article_html = data["article"]["content"]
                parser = TextExtractor()
                parser.feed(article_html)
                text = parser.get_text()
                # Unescape standard HTML entities manually for cleaner output 
                text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
                # Remove excessive newlines
                import re
                text = re.sub(r'\n{3,}', '\n\n', text)
                print(text)
            
            # Check for parent / thread
            if "parent" in data:
               print("\n\n--- PARENT TWEET ---")
               print(data["parent"].get("text", ""))
               
            print("-----------------------\n")
            
    except Exception as e:
        print(f"Error for {tweet_id}: {e}")

print("Running...")
get_twitter_gql_article("2024509163632533826") # may.crypto (619k)
get_twitter_gql_article("2023781142663754049") # RohOnChain (prediction markets)
get_twitter_gql_article("2024492068647600546") # mikita_crypto (kelly monte carlo)
get_twitter_gql_article("2024525141179306143") # Riazi_Cafe_en (math cafe)
get_twitter_gql_article("2024530270116880485") # quantscience_ (time series momentum)
