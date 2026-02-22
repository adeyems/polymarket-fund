import asyncio
from playwright.async_api import async_playwright

async def scrape_article(url, file_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        
        text_content = []
        
        try:
            expand_button = await page.query_selector('text="Read article"')
            if expand_button:
                await expand_button.click()
                await page.wait_for_timeout(3000)
                
            for _ in range(15):
                await page.keyboard.press('PageDown')
                await page.wait_for_timeout(800)
                
            article_elements = await page.query_selector_all('[data-testid="articleBody"]')
            if article_elements:
                for el in article_elements:
                    text = await el.inner_text()
                    if text and text not in text_content:
                        text_content.append(text)
            
            tweet_elements = await page.query_selector_all('[data-testid="tweetText"]')
            for el in tweet_elements:
                text = await el.inner_text()
                if text and text not in text_content:
                    text_content.append(text)
                    
        except Exception as e:
            print(f"Error during interaction: {e}")
            
        await browser.close()
        
        if text_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                for chunk in text_content:
                    f.write(chunk + "\n\n")
            print(f"✅ Saved word-for-word text to {file_path}")
        else:
            print(f"❌ Failed to extract text for {url}")

if __name__ == "__main__":
    asyncio.run(scrape_article("https://x.com/AleiahLock/status/2024773899792101630", "article-2026-02-20/clawdbot_polymarket_arbitrage.md"))
