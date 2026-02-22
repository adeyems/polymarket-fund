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
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=x"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            out = []
            if "text" in data:
               out.append(data["text"])
               
            if "article" in data and "content" in data["article"]:
                article_html = data["article"]["content"]
                parser = TextExtractor()
                parser.feed(article_html)
                text = parser.get_text()
                text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
                import re
                text = re.sub(r'\n{3,}', '\n\n', text)
                out.append("\n--- ARTICLE CONTENT ---\n")
                out.append(text)
            
            with open(f"article-2026-02-20/{tweet_id}.md", "w") as f:
                f.write("".join(out))
            print(f"Successfully saved to article-2026-02-20/{tweet_id}.md")
            
    except Exception as e:
        print(f"Error for {tweet_id}: {e}")

get_twitter_gql_article("2024773899792101630")
