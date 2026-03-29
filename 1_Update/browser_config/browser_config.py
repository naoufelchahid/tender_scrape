import os
from playwright.async_api import async_playwright, Browser
from dotenv import load_dotenv

load_dotenv()

async def create_browser(headless: bool = True) -> Browser:
    """
    Create a Playwright browser instance with enhanced stealth settings.
    """
    playwright = await async_playwright().start()
    
    proxy_config = None
    if os.getenv("PROXY_ENABLED", "false").lower() == "true":
        server = os.getenv("PROXY_SERVER")
        username = os.getenv("PROXY_USERNAME")
        password = os.getenv("PROXY_PASSWORD")
        
        if server:
            proxy_config = {
                "server": server,
                "username": username,
                "password": password
            }
            print(f"Proxy enabled: {server}")

    browser = await playwright.chromium.launch(
        headless=headless,
        proxy=proxy_config,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-infobars',
            '--window-position=0,0',
            '--ignore-certificate-errors',
            '--ignore-certificate-errors-spki-list',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu',
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            '--allow-running-insecure-content',
            '--disable-blink-features=AutomationControlled',
            '--disable-features=VizDisplayCompositor',
            '--start-maximized',
            '--disable-extensions',
            '--disable-default-apps',
            '--disable-component-extensions-with-background-pages',
            '--no-default-browser-check',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-hang-monitor',
            '--disable-prompt-on-repost',
            '--metrics-recording-only',
            '--safebrowsing-disable-auto-update',
            '--password-store=basic',
            '--use-mock-keychain',
            '--lang=fr-FR'
        ]
    )
    return browser
