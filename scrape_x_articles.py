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
        # Wait for domcontentloaded instead of networkidle to avoid timeouts on X
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        
        text_content = []
        
        try:
            # Check for "Read article" button and click it to expand
            expand_button = await page.query_selector('text="Read article"')
            if expand_button:
                print("Found 'Read article' button, clicking...")
                await expand_button.click()
                await page.wait_for_timeout(3000)
                
            print("Scrolling to load content...")
            # Scroll down multiple times to render the full article and replies
            for _ in range(15):
                await page.keyboard.press('PageDown')
                await page.wait_for_timeout(800)
                
            print("Extracting text...")
            # X Articles use 'articleBody' or specific div structures. We will grab both.
            article_elements = await page.query_selector_all('[data-testid="articleBody"]')
            if article_elements:
                for el in article_elements:
                    text = await el.inner_text()
                    if text and text not in text_content:
                        text_content.append(text)
            
            # Also grab standard tweet text (for the main post and replies)
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

async def main():
    await scrape_article("https://x.com/xmayeth/status/2024509163632533826", "article-2026-02-20/619k_polymarket_sports_arbitrage_bot.md")
    await scrape_article("https://x.com/RohOnChain/status/2023781142663754049", "article-2026-02-20/prediction_market_data_like_hedge_funds.md")
    await scrape_article("https://x.com/mikita_crypto/status/2024492068647600546", "article-2026-02-20/kelly_monte_carlo_formula.md")

if __name__ == "__main__":
    asyncio.run(main())
