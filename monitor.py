#!/usr/bin/env python3
import re
import os
import json
import logging
import time
import sys
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Import configuration
from config import (
    CHANNEL_URL,
    FILTER_FOR,
    USE_PLAYWRIGHT_FOR_SCRAPE,
    ROTATE_CREDENTIALS_ON_QUOTA_EXHAUSTION,
    CREDENTIAL_SETS,
    DAILY_QUOTA_LIMIT,
    VIDEO_ADD_DELAY_SECONDS,
    PLAYLIST_SYNC_DELAY_SECONDS,
    YOUTUBE_SCOPES,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REDIRECT_URI
)

# Import configuration
from config import (
    CHANNEL_URL,
    FILTER_FOR,
    USE_PLAYWRIGHT_FOR_SCRAPE,
    ROTATE_CREDENTIALS_ON_QUOTA_EXHAUSTION,
    CREDENTIAL_SETS,
    DAILY_QUOTA_LIMIT,
    VIDEO_ADD_DELAY_SECONDS,
    PLAYLIST_SYNC_DELAY_SECONDS,
    YOUTUBE_SCOPES,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REDIRECT_URI,
    ENABLE_DEBUG_LOGGING,
    SAVE_PAGE_CONTENT_FOR_INSPECTION,
    CLICK_SHOW_MORE_BUTTONS,
    ENABLE_YOUTUBE_API_SYNC
)

# Create a custom logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if ENABLE_DEBUG_LOGGING else logging.INFO)

# Create handlers
console_handler = logging.StreamHandler()
file_handler = logging.FileHandler("/home/workspace/Automations/youtubeSync/data/automation.log")
debug_file_handler = logging.FileHandler("/home/workspace/Automations/youtubeSync/data/debug.log")

# Create formatters and add to handlers
formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s")
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)
debug_file_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)
logger.addHandler(debug_file_handler)

# Prevent propagation to avoid duplicate logs
logger.propagate = False

STATE_FILE = Path("./data/state.json")
SCRAPED_PLAYLISTS_FILE = Path("./data/scraped_playlists.json")
SYNCED_PLAYLISTS_FILE = Path("./data/synced_playlists.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def _normalize_playlist_title_candidate(candidate):
    if not candidate:
        return None
    cleaned = re.sub(r"\s+", " ", candidate).strip()
    if not cleaned:
        return None
    if "view full playlist" in cleaned.lower():
        return None
    return cleaned


def derive_playlist_title_from_link(link, playlist_id=None):
    if not link:
        return None
    candidates = []

    h3 = link.find_parent('h3', class_=lambda c: c and 'yt-lockup-metadata-view-model__heading-reset' in c)
    if h3:
        candidates.append(h3.get_text(' ', strip=True))
        span = h3.find('span', class_=lambda c: c and 'yt-core-attributed-string' in c)
        if span:
            candidates.insert(0, span.get_text(' ', strip=True))

    span = link.find('span', class_=lambda c: c and 'yt-core-attributed-string' in c)
    if span:
        candidates.append(span.get_text(' ', strip=True))

    aria_label = link.get('aria-label')
    if aria_label:
        candidates.append(aria_label)

    title_attr = link.get('title')
    if title_attr:
        candidates.append(title_attr)

    link_text = link.get_text(' ', strip=True)
    if link_text:
        candidates.append(link_text)

    for candidate in candidates:
        normalized = _normalize_playlist_title_candidate(candidate)
        if normalized:
            return normalized

    if playlist_id:
        logger.debug(f"Using fallback title for playlist {playlist_id}")
        return f"Playlist {playlist_id}"
    return None


def fetch_playlist_title_from_page(playlist_id):
    """Fetch the actual title from the individual playlist page"""
    try:
        url = f"https://www.youtube.com/playlist?list={playlist_id}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Look for the title in yt-dynamic-text-view-model with page-header-title class
        title_elem = soup.find('yt-dynamic-text-view-model', class_=lambda c: c and 'yt-page-header-view-model__page-header-title' in c)
        if title_elem:
            title_text = title_elem.get_text(strip=True)
            if title_text and 'view full playlist' not in title_text.lower():
                if ENABLE_DEBUG_LOGGING:
                    logger.debug(f"Fetched title from playlist page: '{title_text}'")
                return title_text
        
        # Fallback: look for h1 with similar class pattern
        h1 = soup.find('h1', class_=lambda c: c and 'page-header-title' in c if c else False)
        if h1:
            title_text = h1.get_text(strip=True)
            if title_text and 'view full playlist' not in title_text.lower():
                if ENABLE_DEBUG_LOGGING:
                    logger.debug(f"Fetched title from h1: '{title_text}'")
                return title_text
        
        # Fallback: look in any span with yt-core-attributed-string inside header
        header = soup.find('yt-page-header-view-model')
        if header:
            span = header.find('span', class_=lambda c: c and 'yt-core-attributed-string' in c if c else False)
            if span:
                title_text = span.get_text(strip=True)
                if title_text and 'view full playlist' not in title_text.lower():
                    if ENABLE_DEBUG_LOGGING:
                        logger.debug(f"Fetched title from header span: '{title_text}'")
                    return title_text
        
        # Last resort: look for meta og:title tag
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title_text = og_title['content'].strip()
            if title_text and 'view full playlist' not in title_text.lower():
                if ENABLE_DEBUG_LOGGING:
                    logger.debug(f"Fetched title from og:title: '{title_text}'")
                return title_text
        
        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"Could not fetch title from playlist page {playlist_id}")
        return None
        
    except Exception as e:
        logger.warning(f"Error fetching playlist title for {playlist_id}: {e}")
        return None

# Module-level variable to track current token file
CURRENT_TOKEN_FILE = "token.json"  # Main token file in root directory

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"latest_playlist_link": None, "latest_playlist_title": None, "last_checked": None}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_scraped_playlists():
    if SCRAPED_PLAYLISTS_FILE.exists():
        with open(SCRAPED_PLAYLISTS_FILE) as f:
            return json.load(f)
    return []

def save_scraped_playlists(playlists):
    with open(SCRAPED_PLAYLISTS_FILE, "w") as f:
        json.dump(playlists, f, indent=2)

def load_synced_playlists():
    if SYNCED_PLAYLISTS_FILE.exists():
        with open(SYNCED_PLAYLISTS_FILE) as f:
            return json.load(f)
    return []

def save_synced_playlists(playlists):
    with open(SYNCED_PLAYLISTS_FILE, "w") as f:
        json.dump(playlists, f, indent=2)

def scrape_playlists_with_selenium():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import WebDriverException, TimeoutException
        import shutil
        import tempfile

        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins-discovery")
        chrome_options.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
        chrome_options.add_argument("--disable-features=VizDisplayCompositor")
        chrome_options.add_argument("--disable-ipc-flooding-protection")
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        chrome_options.add_argument("--disable-features=TranslateUI")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

        # Try to create the driver with proper error handling
        driver = None
        try:
            # First, try to find chromedriver in PATH
            chromedriver_path = shutil.which("chromedriver")

            if chromedriver_path:
                service = Service(chromedriver_path)
                driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                # If not found in PATH, try to initialize without specifying path
                driver = webdriver.Chrome(options=chrome_options)

            logger.info("Chrome driver initialized successfully")
        except WebDriverException as e:
            logger.error(f"Failed to initialize Chrome driver: {e}")
            # Try with a temporary workaround for DevToolsActivePort issues
            try:
                # Set a custom user data directory to avoid conflicts
                temp_dir = tempfile.mkdtemp()
                chrome_options.add_argument(f"--user-data-dir={temp_dir}")

                chromedriver_path = shutil.which("chromedriver")
                if chromedriver_path:
                    service = Service(chromedriver_path)
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                else:
                    driver = webdriver.Chrome(options=chrome_options)

                logger.info("Chrome driver initialized with custom user data dir successfully")
            except Exception as service_error:
                logger.error(f"Failed to initialize Chrome driver with custom settings: {service_error}")
                return []

        if driver is None:
            logger.error("Chrome driver could not be initialized")
            return []

        try:
            logger.debug(f"Loading page: {CHANNEL_URL}")
            driver.get(CHANNEL_URL)

            # Wait for the page to load with more robust conditions
            try:
                WebDriverWait(driver, 15).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except TimeoutException:
                logger.warning("Page didn't load completely, continuing anyway...")

            # Wait for Angular/React to render content
            time.sleep(10)

            # Check if we're on a consent page and handle it
            page_title = driver.title
            logger.debug(f"Page title: {page_title}")

            # Check if we're on the consent page that says "Before you continue to YouTube"
            body_text = driver.find_element(By.TAG_NAME, "body").text
            logger.debug(f"Body text preview (first 200 chars): {body_text[:200]}...")

            # If we're on the consent page, try to accept the terms
            if "before you continue to youtube" in body_text.lower() or "consent" in body_text.lower():
                logger.info("Detected consent page, attempting to accept terms...")

                try:
                    # Look for the "Accept all" button
                    accept_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept all') or contains(text(), 'Accept All')]"))
                    )
                    accept_button.click()
                    logger.info("Clicked 'Accept all' button on consent page")

                    # Wait for the page to reload after accepting
                    time.sleep(10)

                    # Re-check the page title and content after accepting
                    page_title = driver.title
                    logger.debug(f"Page title after consent: {page_title}")
                    body_text = driver.find_element(By.TAG_NAME, "body").text
                    logger.debug(f"Body text after consent (first 200 chars): {body_text[:200]}...")

                except Exception as consent_error:
                    logger.warning(f"Could not find or click 'Accept all' button: {consent_error}")

                    # Try alternative selectors for the accept button
                    try:
                        # Try clicking the button by data attribute or other common selectors
                        alternative_accept = driver.find_element(By.CSS_SELECTOR, "button[aria-label*='accept' i], button[data-testid*='accept' i], .consent-button, .accept-btn")
                        alternative_accept.click()
                        logger.info("Clicked alternative accept button")

                        # Wait for the page to reload after accepting
                        time.sleep(10)
                    except:
                        logger.warning("Could not find alternative accept button")

            # Check for presence of playlist-related elements
            playlist_elements = driver.find_elements(By.CSS_SELECTOR, "[href*='/playlist']")
            logger.debug(f"Found {len(playlist_elements)} elements with playlist links")

            # Try to click "Show more" buttons if they exist (only if enabled in config)
            if CLICK_SHOW_MORE_BUTTONS:
                try:
                    # Look for "Show more" or similar buttons using JavaScript
                    show_more_script = """
                    var buttons = Array.from(document.querySelectorAll('button'));
                    var showMoreButtons = buttons.filter(btn =>
                        btn.textContent.toLowerCase().includes('show') ||
                        btn.textContent.toLowerCase().includes('more') ||
                        btn.textContent.toLowerCase().includes('load')
                    );
                    if (showMoreButtons.length > 0) {
                        showMoreButtons[0].scrollIntoView();
                        showMoreButtons[0].click();
                        return true;
                    } else {
                        // Try to find other types of load buttons
                        var otherButtons = Array.from(document.querySelectorAll('*[onclick*="load"], *[data-uix-load-more], button'));
                        var loadButtons = otherButtons.filter(btn =>
                            btn.getAttribute('data-uix-load-more') !== null ||
                            btn.getAttribute('aria-label') && btn.getAttribute('aria-label').toLowerCase().includes('load')
                        );
                        if (loadButtons.length > 0) {
                            loadButtons[0].scrollIntoView();
                            loadButtons[0].click();
                            return true;
                        }
                    }
                    return false;
                    """
                    # Try clicking show more buttons up to 3 times
                    for i in range(3):
                        clicked = driver.execute_script(show_more_script)
                        logger.debug(f"Tried clicking 'Show more' button #{i+1}, success: {clicked}")
                        if clicked:
                            time.sleep(5)  # Wait for content to load after clicking
                        else:
                            break
                except Exception as e:
                    logger.debug(f"No 'Show more' buttons found or error clicking them: {e}")

            # Scroll multiple times to trigger lazy loading
            last_height = driver.execute_script("return document.body.scrollHeight")
            logger.debug(f"Initial page height: {last_height}")

            for i in range(5):  # Increase scroll attempts
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(5)  # Wait longer for content to load

                # Check if page height has changed
                new_height = driver.execute_script("return document.body.scrollHeight")
                logger.debug(f"Scroll #{i+1} - Previous height: {last_height}, New height: {new_height}")

                if new_height == last_height:
                    logger.debug(f"No more content loaded after scroll #{i+1}")
                    break  # No more content to load
                last_height = new_height

            # Additional wait for content to appear
            time.sleep(5)

            page_source = driver.page_source

            # Save page content for inspection
            save_page_content_for_inspection(page_source, "selenium")

        except WebDriverException as e:
            logger.error(f"Error interacting with Chrome driver: {e}")
            return []
        finally:
            try:
                driver.quit()
                logger.info("Chrome driver closed successfully")
            except Exception as close_error:
                logger.warning(f"Could not close Chrome driver properly: {close_error}")

        soup = BeautifulSoup(page_source, "html.parser")
        playlists = []
        seen_ids = set()

        # Debug logging
        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"Page content length: {len(page_source)}")

        # Find all links first to see what's available
        all_links = soup.find_all('a', href=True)
        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"Found {len(all_links)} total links on the page")

        # Look for any links that might contain playlist information
        playlist_links = []
        for link in all_links:
            href = link.get('href', '')
            if 'playlist' in href.lower():
                if ENABLE_DEBUG_LOGGING:
                    logger.debug(f"Found potential playlist link: {href}")
                playlist_links.append(link)

        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"Found {len(playlist_links)} potential playlist links before regex matching")

        # Find all links that match the playlist pattern
        playlist_links = soup.find_all('a', href=re.compile(r'/playlist\?list='))
        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"Found {len(playlist_links)} playlist links matching regex pattern")

        # Debug: print some sample links
        if ENABLE_DEBUG_LOGGING:
            for i, link in enumerate(playlist_links[:5]):  # Just first 5 for debugging
                logger.debug(f"Playlist link {i+1}: {link.get('href')} - Text: {link.get_text(strip=True)[:50]}...")

        for link in playlist_links:
            href = link.get('href', '')
            match = re.search(r'list=([A-Za-z0-9_-]+)', href)
            if match:
                playlist_id = match.group(1)
                logger.debug(f"Found playlist ID: {playlist_id}")

                if playlist_id not in seen_ids:
                    title = derive_playlist_title_from_link(link, playlist_id)
                    # Don't apply filter here - let detect_new_playlists() handle filtering after title correction
                    logger.debug(f"Including playlist: '{title}' (ID: {playlist_id}) for potential processing")
                    playlists.append({
                        "link": f"https://www.youtube.com/playlist?list={playlist_id}",
                        "playlist_id": playlist_id,
                        "title": title,
                        "discovered_at": datetime.now().isoformat()
                    })
                    seen_ids.add(playlist_id)
            else:
                logger.debug(f"No playlist ID match for href: {href}")

        # If we didn't find any playlists with the above method, try a more aggressive search
        if not playlists:
            logger.debug("Performing fallback search for playlists...")
            # Search for all playlist links on the page
            all_links = soup.find_all('a', href=re.compile(r'/playlist\?list='))
            logger.debug(f"Fallback search found {len(all_links)} playlist links")

            for link in all_links:
                href = link.get('href', '')
                match = re.search(r'list=([A-Za-z0-9_-]+)', href)
                if match:
                    playlist_id = match.group(1)
                    logger.debug(f"Fallback: Found playlist ID: {playlist_id}")

                    if playlist_id not in seen_ids:
                        title = derive_playlist_title_from_link(link, playlist_id)
                        # Don't apply filter here - let detect_new_playlists() handle filtering after title correction
                        logger.debug(f"Including playlist: '{title}' (ID: {playlist_id}) for potential processing")
                        playlists.append({
                            "link": f"https://www.youtube.com/playlist?list={playlist_id}",
                            "playlist_id": playlist_id,
                            "title": title,
                            "discovered_at": datetime.now().isoformat()
                        })
                        seen_ids.add(playlist_id)

        logger.info(f"Found {len(playlists)} playlists with Selenium")
        return playlists
    except Exception as e:
        logger.error(f"Selenium error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return []

def scrape_playlists_with_playwright():
    """Scrape playlists using Playwright as a backup method"""
    try:
        from playwright.sync_api import sync_playwright
        import tempfile
        import os

        playlists = []
        seen_ids = set()

        with sync_playwright() as p:
            # Launch browser with stealth settings
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-extensions",
                    "--disable-plugins-discovery",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding"
                ]
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36",
                viewport={'width': 1920, 'height': 1080},
                java_script_enabled=True,
                bypass_csp=True  # Bypass content security policy
            )

            page = context.new_page()

            # Navigate to the page
            page.goto(CHANNEL_URL, wait_until="networkidle")

            # Wait for page to load and execute JavaScript
            page.wait_for_timeout(10000)  # Wait longer for content to load

            # Check if we're on a consent page and handle it
            page_title = page.title()
            logger.debug(f"Playwright page title: {page_title}")

            # Get body text to check for consent page
            body_text = page.inner_text('body')
            logger.debug(f"Playwright body text preview (first 200 chars): {body_text[:200]}...")

            # If we're on the consent page, try to accept the terms
            if "before you continue to youtube" in body_text.lower() or "consent" in body_text.lower():
                logger.info("Playwright: Detected consent page, attempting to accept terms...")

                try:
                    # Look for and click the "Accept all" button
                    accept_button = page.locator("button:has-text('Accept all')").first
                    if accept_button.count() > 0:
                        accept_button.click(timeout=10000)
                        logger.info("Playwright: Clicked 'Accept all' button on consent page")

                        # Wait for the page to reload after accepting
                        page.wait_for_timeout(10000)
                    else:
                        # Try alternative selectors
                        alternative_accept = page.locator("button:has-text('Accept')").first
                        if alternative_accept.count() > 0:
                            alternative_accept.click(timeout=10000)
                            logger.info("Playwright: Clicked 'Accept' button on consent page")

                            # Wait for the page to reload after accepting
                            page.wait_for_timeout(10000)
                        else:
                            logger.warning("Playwright: Could not find accept button on consent page")

                except Exception as consent_error:
                    logger.warning(f"Playwright: Could not handle consent page: {consent_error}")

            # Try to click "Show more" buttons if they exist (only if enabled in config)
            if CLICK_SHOW_MORE_BUTTONS:
                try:
                    # Look for "Show more" or similar buttons
                    show_more_buttons = page.locator('button:has-text("Show")').all()
                    for button in show_more_buttons[:3]:  # Click up to 3 show more buttons
                        try:
                            button.scroll_into_view_if_needed()
                            button.click(force=True)  # Use force click to bypass visibility checks
                            page.wait_for_timeout(5000)  # Wait for content to load after clicking
                        except:
                            continue  # Continue if button click fails
                except:
                    pass  # Continue if no show more buttons found

            # Scroll multiple times to load more content
            for i in range(5):  # Increase scroll attempts
                previous_height = page.evaluate("document.body.scrollHeight")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                page.wait_for_timeout(5000)  # Wait longer for content to load

                # Check if page height has changed (new content loaded)
                current_height = page.evaluate("document.body.scrollHeight")
                if current_height == previous_height:
                    logger.debug(f"No more content loaded after scroll #{i+1}")
                    break  # No more content to load

            # Additional wait for any dynamic content
            page.wait_for_timeout(5000)

            # Get the page content after all interactions
            content = page.content()

            # Save page content for inspection
            save_page_content_for_inspection(content, "playwright")

            browser.close()

            # Log the content length for debugging
            logger.debug(f"Playwright page content length: {len(content)}")

            # Parse with BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")

            # Look for playlist links using multiple selectors
            playlist_selectors = [
                'a[href*="/playlist?list="]',
                '[href*="playlist?list="]',
                'ytd-playlist-renderer a',
                'ytd-grid-playlist-renderer a',
                'ytd-playlist-video-list-renderer a',
                'ytd-playlist-renderer',
                'ytd-grid-playlist-renderer'
            ]

            found_elements = []
            for selector in playlist_selectors:
                found_elements.extend(soup.select(selector))

            # If no elements found with specific selectors, try a broader search
            if not found_elements:
                found_elements = soup.find_all('a', href=re.compile(r'/playlist\?list='))

            logger.info(f"Found {len(found_elements)} potential playlist elements with Playwright")

            # Debug logging
            if ENABLE_DEBUG_LOGGING:
                logger.debug(f"Playwright page content length: {len(content)}")

            # Find all links first to see what's available
            all_links = soup.find_all('a', href=True)
            if ENABLE_DEBUG_LOGGING:
                logger.debug(f"Playwright: Found {len(all_links)} total links on the page")

            # Look for any links that might contain playlist information
            playlist_links = []
            for link in all_links:
                href = link.get('href', '')
                if 'playlist' in href.lower():
                    if ENABLE_DEBUG_LOGGING:
                        logger.debug(f"Playwright: Found potential playlist link: {href}")
                    playlist_links.append(link)

            if ENABLE_DEBUG_LOGGING:
                logger.debug(f"Playwright: Found {len(playlist_links)} potential playlist links before regex matching")

            # Find all links that match the playlist pattern
            playlist_links = soup.find_all('a', href=re.compile(r'/playlist\?list='))
            if ENABLE_DEBUG_LOGGING:
                logger.debug(f"Playwright: Found {len(playlist_links)} playlist links matching regex pattern")

            # Debug: print some sample links
            if ENABLE_DEBUG_LOGGING:
                for i, link in enumerate(playlist_links[:5]):  # Just first 5 for debugging
                    logger.debug(f"Playwright playlist link {i+1}: {link.get('href')} - Text: {link.get_text(strip=True)[:50]}...")

            for link in playlist_links:
                href = link.get('href', '')
                match = re.search(r'list=([A-Za-z0-9_-]+)', href)
                if match:
                    playlist_id = match.group(1)
                    logger.debug(f"Playwright: Found playlist ID: {playlist_id}")

                    if playlist_id not in seen_ids:
                        title = derive_playlist_title_from_link(link, playlist_id)
                        # Don't apply filter here - let detect_new_playlists() handle filtering after title correction
                        logger.debug(f"Including playlist: '{title}' (ID: {playlist_id}) for potential processing")
                        playlists.append({
                            "link": f"https://www.youtube.com/playlist?list={playlist_id}",
                            "playlist_id": playlist_id,
                            "title": title,
                            "discovered_at": datetime.now().isoformat()
                        })
                        seen_ids.add(playlist_id)

        logger.info(f"Found {len(playlists)} playlists with Playwright")
        return playlists

    except ImportError:
        logger.warning("Playwright not installed, skipping Playwright-based scraping")
        return []
    except Exception as e:
        logger.error(f"Playwright error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return []

def scrape_playlists_with_api():
    try:
        # Import required modules locally to ensure they're available
        import urllib3
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Add more robust headers
        enhanced_headers = HEADERS.copy()
        enhanced_headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
        })

        # Create a session with retry strategy
        session = requests.Session()

        # Define retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=2,  # Increased backoff factor
            status_forcelist=[429, 500, 502, 503, 504],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Try multiple URLs with different consent bypass parameters
        urls_to_try = [
            CHANNEL_URL,
            f"{CHANNEL_URL}?cbrd=1&hl=en&gl=US",
            f"{CHANNEL_URL}?gl=US&hl=en&ucbcb=1",
            f"{CHANNEL_URL}?gl=US&hl=en&cbrd=1&ucbcb=1",
            f"{CHANNEL_URL}?disable_polymer=1&hl=en&gl=US",
            f"{CHANNEL_URL}?gl=US&hl=en&bpctr=9999999999&has_verified=1"
        ]

        # First, try to get a session cookie by visiting the main YouTube domain
        logger.debug("Getting initial session from YouTube...")
        try:
            # Visit the main YouTube page first to establish session
            main_page_response = session.get(
                "https://www.youtube.com/",
                headers=enhanced_headers,
                timeout=15,
                verify=False
            )
            logger.debug(f"Main page response status: {main_page_response.status_code}")
        except Exception as e:
            logger.debug(f"Could not access main YouTube page: {e}")

        response = None
        for url in urls_to_try:
            try:
                logger.debug(f"Trying API URL: {url}")
                response = session.get(
                    url,
                    headers=enhanced_headers,
                    timeout=30,
                    verify=False,  # Temporarily disable SSL verification to avoid SSL errors
                    allow_redirects=True
                )

                # Check if we're still on a consent page
                if "consent.youtube.com" not in response.url and "consent" not in response.text.lower():
                    logger.debug(f"Successfully loaded page without consent redirect, final URL: {response.url}")
                    break
                else:
                    logger.debug(f"Still on consent page with URL: {url}, trying next...")
                    continue
            except Exception as e:
                logger.debug(f"Error trying URL {url}: {e}")
                continue

        # If all URLs lead to consent page, try to handle it programmatically
        if response is None or "consent.youtube.com" in response.url or "consent" in response.text.lower():
            logger.info("All attempts led to consent page, trying to handle it programmatically...")

            # Try to access via a different approach - maybe using the embed endpoint or other bypass methods
            consent_bypass_urls = [
                f"https://www.youtube-nocookie.com/embed/?listType=playlist&list=PLxA687tYuMWj8dw7ZvBCe6-VIstTwGFnk",  # Use a known playlist ID as example
                f"https://www.youtube.com/iframe_api"
            ]

            for consent_url in consent_bypass_urls:
                try:
                    logger.debug(f"Trying consent bypass URL: {consent_url}")
                    response = session.get(
                        consent_url,
                        headers=enhanced_headers,
                        timeout=30,
                        verify=False,
                        allow_redirects=True
                    )

                    if "consent.youtube.com" not in response.url:
                        logger.info(f"Successfully bypassed consent with URL: {consent_url}")
                        break
                except Exception as e:
                    logger.debug(f"Error with consent bypass URL {consent_url}: {e}")
                    continue

        if response is None:
            logger.error("Could not load page without consent redirect after trying multiple URLs")
            return []

        response.raise_for_status()

        # Debug logging
        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"API response length: {len(response.text)}")
            logger.debug(f"Final API URL: {response.url}")

        # Save response content for inspection if enabled
        save_page_content_for_inspection(response.text, "api_response")

        # Try multiple patterns to extract initial data
        patterns = [
            r'var ytInitialData = ({.*?});',
            r'ytInitialData = ({.*?});',
            r'window\["ytInitialData"\] = ({.*?});',
            r'ytcfg\.set\([^)]*"INNERTUBE_CONTEXT_CLIENT_VERSION"[^)]*\);\s*ytcfg\.set\([^)]*"INNERTUBE_API_KEY"[^)]*\);\s*var ytInitialData = ({.*?});',
            r'id="initial-data">({.*?})</script>',
            r'ytInitialData\s*=\s*({.*?});',
            r'window\[\"ytInitialData\"\]\s*=\s*({.*?});',
            r'ytInitialPlayerResponse\s*=\s*({.*?});'
        ]

        for i, pattern in enumerate(patterns):
            if ENABLE_DEBUG_LOGGING:
                logger.debug(f"Trying pattern {i+1}: {pattern[:50]}...")
            match = re.search(pattern, response.text, re.DOTALL)
            if match:
                if ENABLE_DEBUG_LOGGING:
                    logger.debug(f"Pattern {i+1} found a match")
                try:
                    data_str = match.group(1)
                    # Clean up the JSON string
                    data_str = data_str.rstrip('; \t\n\r')
                    if ENABLE_DEBUG_LOGGING:
                        logger.debug(f"Attempting to parse JSON from pattern {i+1}, length: {len(data_str)}")
                    data = json.loads(data_str)
                    playlists = extract_playlists_from_data(data)
                    if playlists:
                        logger.info(f"Successfully parsed {len(playlists)} playlists using pattern {i+1}")
                        return playlists
                    else:
                        if ENABLE_DEBUG_LOGGING:
                            logger.debug(f"Pattern {i+1} matched but returned 0 playlists")
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON decode error with pattern {i+1}: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"Error parsing playlist data with pattern {i+1}: {e}")
                    continue
            else:
                if ENABLE_DEBUG_LOGGING:
                    logger.debug(f"Pattern {i+1} did not match")

        # If regex patterns fail, try to find JSON in script tags
        if ENABLE_DEBUG_LOGGING:
            logger.debug("Trying to find JSON in script tags...")
        soup = BeautifulSoup(response.text, "html.parser")
        script_tags = soup.find_all('script')
        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"Found {len(script_tags)} script tags")

        for i, script in enumerate(script_tags):
            if script.string:
                # Look for JSON objects in script tags
                json_matches = re.findall(r'({.*?"responseContext".*?})', script.string, re.DOTALL)
                if ENABLE_DEBUG_LOGGING:
                    logger.debug(f"Script tag {i+1} has {len(json_matches)} potential JSON matches")

                for j, json_str in enumerate(json_matches):
                    try:
                        # Clean up the JSON string
                        cleaned_json = json_str.rstrip('; \t\n\r')
                        if ENABLE_DEBUG_LOGGING:
                            logger.debug(f"Attempting to parse JSON from script tag {i+1}, match {j+1}, length: {len(cleaned_json)}")
                        data = json.loads(cleaned_json)
                        playlists = extract_playlists_from_data(data)
                        if playlists:
                            logger.info(f"Successfully parsed {len(playlists)} playlists from script tag JSON (tag {i+1}, match {j+1})")
                            return playlists
                    except json.JSONDecodeError as e:
                        if ENABLE_DEBUG_LOGGING:
                            logger.debug(f"JSON decode error in script tag {i+1}, match {j+1}: {e}")
                        continue
                    except Exception as e:
                        if ENABLE_DEBUG_LOGGING:
                            logger.debug(f"Error parsing playlist data from script tag {i+1}, match {j+1}: {e}")
                        continue

        # Try to find JSON in other ways
        logger.debug("Trying alternative JSON extraction methods...")
        # Look for JSON in inline script tags that might contain the data
        all_scripts = soup.find_all('script')
        for i, script in enumerate(all_scripts):
            if script.string:
                # Look for any large JSON-like structures
                potential_jsons = re.findall(r'(\{.*?"contents".*?\})', script.string, re.DOTALL)
                for j, potential_json in enumerate(potential_jsons):
                    try:
                        cleaned_json = potential_json.rstrip('; \t\n\r')
                        # Limit the size to prevent memory issues
                        if len(cleaned_json) > 1000000:  # Skip if too large
                            continue
                        data = json.loads(cleaned_json)
                        playlists = extract_playlists_from_data(data)
                        if playlists:
                            logger.info(f"Successfully parsed {len(playlists)} playlists from alternative JSON extraction (script {i+1}, match {j+1})")
                            return playlists
                    except json.JSONDecodeError:
                        continue
                    except Exception:
                        continue

        logger.info("Could not parse playlists from API response")
        return []  # Return empty list to indicate failure
    except requests.exceptions.SSLError as e:
        logger.error(f"SSL error when fetching playlists: {e}")
        return []  # Return empty list to indicate failure
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error when fetching playlists: {e}")
        return []  # Return empty list to indicate failure
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error when fetching playlists: {e}")
        return []  # Return empty list to indicate failure
    except Exception as e:
        logger.error(f"Unexpected error fetching playlists: {e}")
        return []  # Return empty list to indicate failure

def save_page_content_for_inspection(content, filename_suffix=""):
    """Save page content to a file for inspection"""
    if not SAVE_PAGE_CONTENT_FOR_INSPECTION:
        return  # Skip saving if the config variable is False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"/home/workspace/Automations/youtubeSync/data/page_content_{timestamp}_{filename_suffix}.html"

    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        logger.debug(f"Saved page content to {filename} for inspection")
    except Exception as e:
        logger.error(f"Error saving page content for inspection: {e}")

def extract_playlists_from_data(data):
    playlists = []
    try:
        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"Starting to extract playlists from data, data type: {type(data)}, length: {len(str(data)) if hasattr(str(data), '__len__') else 'unknown'}")

        # Recursive search for playlistId in the data
        def find_playlists(obj, depth=0):
            if depth > 10:  # Prevent deep recursion
                return
            if isinstance(obj, dict):
                # Look for playlist renderer objects which contain the most complete information
                if obj.get("playlistRenderer") or obj.get("gridPlaylistRenderer"):
                    renderer = obj.get("playlistRenderer") or obj.get("gridPlaylistRenderer")
                    if "playlistId" in renderer:
                        pid = renderer["playlistId"]
                        if ENABLE_DEBUG_LOGGING:
                            logger.debug(f"Found playlist ID: {pid}")

                        # Extract title with multiple fallback strategies
                        title = "Untitled"

                        # Look for title in various possible locations
                        title_obj = renderer.get("title") or renderer.get("headline")
                        if title_obj:
                            if ENABLE_DEBUG_LOGGING:
                                logger.debug(f"Title object found: {type(title_obj)}, content preview: {str(title_obj)[:100]}")
                            if isinstance(title_obj, dict):
                                if "simpleText" in title_obj:
                                    title = title_obj["simpleText"]
                                    if ENABLE_DEBUG_LOGGING:
                                        logger.debug(f"Found title from simpleText: '{title}'")
                                elif "runs" in title_obj:
                                    # Concatenate all runs to form the title
                                    title_runs = title_obj["runs"]
                                    title_parts = [run.get("text", "") for run in title_runs if "text" in run and run.get("text")]
                                    title = "".join(title_parts).strip()
                                    if ENABLE_DEBUG_LOGGING:
                                        logger.debug(f"Found title from runs: '{title}'")
                                else:
                                    # Look for any text field in the title object
                                    for key, value in title_obj.items():
                                        if isinstance(value, str) and len(value) > 0 and "view full playlist" not in value.lower():
                                            title = value
                                            if ENABLE_DEBUG_LOGGING:
                                                logger.debug(f"Found title from other dict key: '{title}'")
                                            break
                            else:
                                title = str(title_obj)
                                if ENABLE_DEBUG_LOGGING:
                                    logger.debug(f"Found title from direct conversion: '{title}'")

                        # Additional fallbacks for title
                        if (title == "Untitled" or not title or "view full playlist" in title.lower()):
                            # Check secondary title fields
                            secondary_title = renderer.get("shortBylineText", {})
                            if secondary_title and isinstance(secondary_title, dict):
                                if ENABLE_DEBUG_LOGGING:
                                    logger.debug(f"Checking secondary title: {secondary_title}")
                                if "runs" in secondary_title:
                                    # Extract text from runs
                                    runs = secondary_title["runs"]
                                    secondary_text = ""
                                    for run in runs:
                                        if "text" in run and run["text"] and "view full playlist" not in run["text"].lower():
                                            secondary_text += run["text"]
                                    if secondary_text:
                                        title = secondary_text.strip()
                                        if ENABLE_DEBUG_LOGGING:
                                            logger.debug(f"Found title from secondary runs: '{title}'")
                                elif "simpleText" in secondary_title and "view full playlist" not in secondary_title["simpleText"].lower():
                                    title = secondary_title["simpleText"]
                                    if ENABLE_DEBUG_LOGGING:
                                        logger.debug(f"Found title from secondary simpleText: '{title}'")

                        if (title == "Untitled" or not title or "view full playlist" in title.lower()) and "titleText" in obj:
                            title_text_obj = obj["titleText"]
                            if isinstance(title_text_obj, dict) and "simpleText" in title_text_obj:
                                title = title_text_obj["simpleText"]
                                logger.debug(f"Found title from titleText: '{title}'")

                        if (title == "Untitled" or not title or "view full playlist" in title.lower()) and "headline" in obj:
                            headline_obj = obj["headline"]
                            if isinstance(headline_obj, dict) and "simpleText" in headline_obj:
                                title = headline_obj["simpleText"]
                                logger.debug(f"Found title from headline: '{title}'")

                        # Clean up the title
                        if title == "Untitled" or not title or "view full playlist" in title.lower():
                            title = f"Playlist {pid}"  # Use ID as fallback title
                            if ENABLE_DEBUG_LOGGING:
                                logger.debug(f"Using fallback title for playlist {pid}: {title}")

                        if pid and not any(p["playlist_id"] == pid for p in playlists):
                            # Don't apply filter here - let detect_new_playlists() handle filtering after title correction
                            if ENABLE_DEBUG_LOGGING:
                                logger.debug(f"Including playlist: '{title}' (ID: {pid}) for potential processing")
                            playlists.append({
                                "link": f"https://www.youtube.com/playlist?list={pid}",
                                "playlist_id": pid,
                                "title": title,
                                "discovered_at": datetime.now().isoformat()
                            })

                # General case: look for playlistId anywhere in the object
                if "playlistId" in obj:
                    pid = obj["playlistId"]
                    logger.debug(f"Found playlist ID (general case): {pid}")

                    # Extract title with multiple fallback strategies
                    title = "Untitled"

                    # Check if title exists in the object
                    if "title" in obj:
                        title_obj = obj["title"]
                        logger.debug(f"General case - Title object found: {type(title_obj)}, content preview: {str(title_obj)[:100]}")
                        if isinstance(title_obj, dict):
                            # Handle different possible title structures
                            if "simpleText" in title_obj:
                                title = title_obj["simpleText"]
                                logger.debug(f"General case - Found title from simpleText: '{title}'")
                            elif "runs" in title_obj:
                                # Concatenate all runs to form the title
                                title_runs = title_obj["runs"]
                                title_parts = [run.get("text", "") for run in title_runs if "text" in run and run.get("text")]
                                title = "".join(title_parts).strip()
                                logger.debug(f"General case - Found title from runs: '{title}'")
                            else:
                                # Fallback to first available text value
                                for key, value in title_obj.items():
                                    if isinstance(value, str) and "view full playlist" not in value.lower():
                                        title = value
                                        logger.debug(f"General case - Found title from other dict key: '{title}'")
                                        break
                        else:
                            title = str(title_obj)
                            logger.debug(f"General case - Found title from direct conversion: '{title}'")

                    # Additional title extraction from other possible fields
                    if (title == "Untitled" or not title or "view full playlist" in title.lower()) and "titleText" in obj:
                        title_text_obj = obj["titleText"]
                        if isinstance(title_text_obj, dict) and "simpleText" in title_text_obj:
                            title = title_text_obj["simpleText"]
                            logger.debug(f"General case - Found title from titleText: '{title}'")

                    if (title == "Untitled" or not title or "view full playlist" in title.lower()) and "headline" in obj:
                        headline_obj = obj["headline"]
                        if isinstance(headline_obj, dict) and "simpleText" in headline_obj:
                            title = headline_obj["simpleText"]
                            logger.debug(f"General case - Found title from headline: '{title}'")

                    # Another common location for the actual title
                    if (title == "Untitled" or not title or "view full playlist" in title.lower()) and "shortBylineText" in obj:
                        short_byline_obj = obj["shortBylineText"]
                        if isinstance(short_byline_obj, dict) and "runs" in short_byline_obj:
                            # Extract text from runs
                            runs = short_byline_obj["runs"]
                            byline_text = ""
                            for run in runs:
                                if "text" in run and run["text"] and "view full playlist" not in run["text"].lower():
                                    byline_text += run["text"]
                            if byline_text:
                                title = byline_text.strip()
                                logger.debug(f"General case - Found title from shortBylineText runs: '{title}'")

                    # Check accessibility title
                    if (title == "Untitled" or not title or "view full playlist" in title.lower()) and "accessibility" in obj:
                        accessibility_obj = obj["accessibility"]
                        if isinstance(accessibility_obj, dict):
                            accessibility_data = accessibility_obj.get("accessibilityData", {})
                            if isinstance(accessibility_data, dict):
                                label = accessibility_data.get("label")
                                if label and isinstance(label, str) and "view full playlist" not in label.lower():
                                    title = label
                                    logger.debug(f"General case - Found title from accessibility: '{title}'")

                    # Clean up the title
                    if title == "Untitled" or not title or "view full playlist" in title.lower():
                        title = f"Playlist {pid}"  # Use ID as fallback title
                        logger.debug(f"General case - Using fallback title for playlist {pid}: {title}")

                    if pid and not any(p["playlist_id"] == pid for p in playlists):
                        # Don't apply filter here - let detect_new_playlists() handle filtering after title correction
                        logger.debug(f"Including playlist: '{title}' (ID: {pid}) for potential processing")
                        playlists.append({
                            "link": f"https://www.youtube.com/playlist?list={pid}",
                            "playlist_id": pid,
                            "title": title,
                            "discovered_at": datetime.now().isoformat()
                        })
                for k, v in obj.items():
                    find_playlists(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    find_playlists(item, depth + 1)

        find_playlists(data)
        if ENABLE_DEBUG_LOGGING:
            logger.debug(f"Finished extracting playlists, found {len(playlists)} playlists")
    except Exception as e:
        logger.error(f"Error in extract_playlists_from_data: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
    return playlists

def is_spam_video_by_title(title):
    """Check if a video title indicates it's spam based on keywords"""
    if not title:
        return False

    title_lower = title.lower()

    # Check for spam keywords in the title
    spam_keywords = ['top', 'songs', '2025', '2026', 'mix', 'playlist', 'best']
    keyword_matches = sum(1 for keyword in spam_keywords if keyword in title_lower)

    # If 2 or more spam keywords are in the title, consider it spam
    if keyword_matches >= 2:
        return True
    return False



def _extract_text_from_title_obj(title_obj):
    if not title_obj:
        return ""
    if isinstance(title_obj, str):
        return title_obj
    if isinstance(title_obj, dict):
        if "simpleText" in title_obj and isinstance(title_obj["simpleText"], str):
            return title_obj["simpleText"]
        if "runs" in title_obj and isinstance(title_obj["runs"], list):
            return "".join(run.get("text", "") for run in title_obj["runs"] if isinstance(run, dict) and run.get("text"))
        for key in ("text", "value", "title", "label"):
            value = title_obj.get(key)
            if isinstance(value, str):
                return value
    return ""


def _collect_playlist_video_entries(obj, entries):
    if isinstance(obj, dict):
        renderer = obj.get("playlistVideoRenderer")
        if renderer:
            video_id = renderer.get("videoId")
            title = _extract_text_from_title_obj(renderer.get("title"))
            if not title:
                title = _extract_text_from_title_obj(renderer.get("shortBylineText"))
            entries.append((video_id, title))
        for value in obj.values():
            _collect_playlist_video_entries(value, entries)
    elif isinstance(obj, list):
        for item in obj:
            _collect_playlist_video_entries(item, entries)


def _filter_playlist_video_entries(entries):
    filtered = []
    seen = set()
    for video_id, title in entries:
        if not video_id:
            continue
        if video_id in seen:
            continue
        if title and is_spam_video_by_title(title):
            logger.info(f"Filtered out spam video by title: {title} (ID: {video_id})")
            continue
        seen.add(video_id)
        filtered.append(video_id)
    return filtered


def extract_video_ids_from_initial_data(text):
    patterns = [
        r'var ytInitialData = ({.*?});',
        r'ytInitialData = ({.*?});',
        r'window\["ytInitialData"\] = ({.*?});'
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                data_str = match.group(1).rstrip('; \n\t')
                data = json.loads(data_str)
            except (json.JSONDecodeError, TypeError):
                continue
            entries = []
            _collect_playlist_video_entries(data, entries)
            filtered = _filter_playlist_video_entries(entries)
            if filtered:
                return filtered
    return []

def extract_videos_from_playlist(url):
    try:
        # Use the global requests module that's imported at the top
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()  # Raise an exception for bad status codes

        # First, try to extract using the API-based approach by looking for ytInitialData
        video_ids = extract_video_ids_from_initial_data(resp.text)
        if video_ids:
            return video_ids

        # Fallback to regex approach
        # Extract video IDs and titles using multiple patterns
        patterns = [
            r'"videoId":"([A-Za-z0-9_-]{11})"[^}]*?"title"[^}]*?"simpleText":"([^"]+)"',
            r'"videoId":"([A-Za-z0-9_-]{11})"[^}]*?"title"[^}]*?"runs"[^}]*(?:"text":"([^"]+)")',
            r'"videoId":"([A-Za-z0-9_-]{11})"',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, resp.text)
            if matches:
                if len(matches[0]) == 2:  # videoId and title
                    valid_videos = []
                    for vid, title in matches:
                        if not is_spam_video_by_title(title):
                            valid_videos.append(vid)
                        else:
                            logger.info(f"Filtered out spam video by title: {title} (ID: {vid})")
                    # Remove duplicates while preserving order
                    unique_valid = list(dict.fromkeys(valid_videos))
                    return unique_valid
                elif len(matches[0]) == 1:  # Only videoId
                    vids = [match[0] for match in matches]
                    # Remove duplicates while preserving order
                    unique_vids = list(dict.fromkeys(vids))
                    # Filter based on position (remove likely spam at the end)
                    if len(unique_vids) > 3:
                        return unique_vids[:-1]  # Remove last video which might be spam
                    else:
                        return unique_vids

        # If regex patterns don't work, try BeautifulSoup approach
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Look for video IDs in data-video-id attributes or in script tags
        video_elements = soup.find_all(attrs={"data-video-id": True})
        video_ids = [elem.get("data-video-id") for elem in video_elements if elem.get("data-video-id")]

        if video_ids:
            # Remove duplicates while preserving order
            unique_video_ids = list(dict.fromkeys(video_ids))
            if len(unique_video_ids) > 3:
                return unique_video_ids[:-1]  # Remove potential spam at the end
            else:
                return unique_video_ids

        # Last resort: simple regex for video IDs
        vids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', resp.text)
        unique_vids = list(dict.fromkeys(vids))
        if len(unique_vids) > 3:
            return unique_vids[:-3]  # Remove potential spam at the end
        else:
            return unique_vids

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error when extracting videos from {url}: {e}")
        # Fallback to the original method without filtering
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            vids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', resp.text)
            # Remove duplicates while preserving order
            unique_vids = list(dict.fromkeys(vids))
            if len(unique_vids) > 3:
                return unique_vids[:-3]
            else:
                return unique_vids
        except:
            return []
    except Exception as e:
        logger.error(f"Error extracting videos from {url}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return []

def get_authenticated_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow, Flow
    from googleapiclient.discovery import build
    import google.auth.exceptions
    import socket
    from urllib.parse import urlparse, parse_qs
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import time

    SCOPES = YOUTUBE_SCOPES
    global CURRENT_TOKEN_FILE
    token_file = CURRENT_TOKEN_FILE
    creds = None

    # Check if token file exists and load credentials
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            logger.info("Loaded existing credentials from token file")
        except Exception as e:
            logger.error(f"Error loading existing credentials: {e}")
            # If there's an error with the existing token, remove it and start fresh
            try:
                os.remove(token_file)
                logger.info("Removed invalid token file")
            except:
                pass

    # If there are no valid credentials, initiate the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Refreshing expired credentials...")
                creds.refresh(Request())
                logger.info("Credentials refreshed successfully")
            except google.auth.exceptions.RefreshError as e:
                logger.error(f"Failed to refresh credentials: {e}")
                creds = None
            except Exception as e:
                logger.error(f"Unexpected error during credential refresh: {e}")
                creds = None

        # If still no valid credentials, start the OAuth flow
        if not creds:
            # Use configured API key values
            client_id = YOUTUBE_CLIENT_ID
            client_secret = YOUTUBE_CLIENT_SECRET

            # Try to load from credentials.json if environment variables are not set
            credentials_file = "credentials.json"
            if (not client_id or not client_secret) and os.path.exists(credentials_file):
                try:
                    with open(credentials_file, 'r') as f:
                        cred_data = json.load(f)
                        if 'web' in cred_data:
                            client_id = cred_data['web'].get('client_id')
                            client_secret = cred_data['web'].get('client_secret')
                        elif 'installed' in cred_data:
                            client_id = cred_data['installed'].get('client_id')
                            client_secret = cred_data['installed'].get('client_secret')
                    logger.info("Loaded credentials from credentials.json")
                except Exception as e:
                    logger.error(f"Error loading credentials.json: {e}")

            # Validate that we have the required credentials
            if not client_id or not client_secret:
                logger.error("Missing required credentials. Please set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET environment variables or ensure credentials.json exists.")
                logger.info("Alternatively, download credentials from Google Cloud Console as 'credentials.json'")
                return None

            # Load the original configuration from credentials.json
            credentials_file = "credentials.json"
            original_config = {}
            client_config = None

            # Try to load the original configuration
            if os.path.exists(credentials_file):
                try:
                    with open(credentials_file, 'r') as f:
                        original_config = json.load(f)

                    if 'web' in original_config:
                        # Use web credentials for web application flow
                        client_config = {
                            "web": {
                                "client_id": original_config['web']['client_id'],
                                "client_secret": original_config['web']['client_secret'],
                                "auth_uri": original_config['web'].get('auth_uri', 'https://accounts.google.com/o/oauth2/auth'),
                                "token_uri": original_config['web'].get('token_uri', 'https://oauth2.googleapis.com/token'),
                                "redirect_uris": original_config['web'].get('redirect_uris', [])
                            }
                        }
                        logger.info("Loaded web application credentials for OAuth flow")
                    elif 'installed' in original_config:
                        # Use installed flow for desktop applications
                        # Ensure there's a redirect URI for installed apps (typically out-of-band)
                        redirect_uris = original_config['installed'].get('redirect_uris', [])
                        if not redirect_uris:
                            redirect_uris = ['urn:ietf:wg:oauth:2.0:oob']  # Default for installed apps

                        client_config = {
                            "installed": {
                                "client_id": original_config['installed']['client_id'],
                                "client_secret": original_config['installed']['client_secret'],
                                "auth_uri": original_config['installed'].get('auth_uri', 'https://accounts.google.com/o/oauth2/auth'),
                                "token_uri": original_config['installed'].get('token_uri', 'https://oauth2.googleapis.com/token'),
                                "redirect_uris": redirect_uris
                            }
                        }
                        logger.info("Loaded installed application credentials for OAuth flow")
                except Exception as e:
                    logger.error(f"Error loading original credentials config: {e}")

            if not client_config:
                fallback_redirect = YOUTUBE_REDIRECT_URI or 'urn:ietf:wg:oauth:2.0:oob'
                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [fallback_redirect]
                    }
                }

            # Determine if we should use web flow or installed app flow
            is_web_flow = 'web' in client_config and len(client_config['web'].get('redirect_uris', [])) > 0

            if is_web_flow:
                logger.info("Starting OAuth flow with web application credentials:")

                # Find a suitable redirect URI from the web config
                redirect_uris = client_config['web'].get('redirect_uris', [])

                # Look for localhost redirect URI first
                local_redirect_uri = None
                for uri in redirect_uris:
                    if 'localhost' in uri or '127.0.0.1' in uri:
                        local_redirect_uri = uri
                        break

                # If no localhost URI found, try to find a suitable one or use a default localhost
                if not local_redirect_uri:
                    # For your use case, you mentioned wanting to use https://veli.zo.computer/rest/oauth2-credential/callback
                    # Let's check if this is in the redirect URIs
                    for uri in redirect_uris:
                        if 'veli.zo.computer' in uri:
                            # This is your server's domain, but we need to run a local server to catch the callback
                            # So we'll use a local server approach
                            parsed = urlparse(uri)
                            # Use localhost with a random port to catch the callback
                            port = 8080
                            while port <= 9000:
                                try:
                                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                                        sock.bind(('localhost', port))
                                        local_redirect_uri = f"http://localhost:{port}/callback"
                                    break
                                except OSError:
                                    port += 1
                            break

                # If still no local redirect URI found, use a default
                if not local_redirect_uri:
                    port = 8080
                    while port <= 9000:
                        try:
                            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                                sock.bind(('localhost', port))
                                local_redirect_uri = f"http://localhost:{port}/callback"
                            break
                        except OSError:
                            port += 1

                    if not local_redirect_uri:
                        logger.error("Could not find an available port for local server")
                        return None

                # Parse the local redirect URI to get host and port
                parsed_uri = urlparse(local_redirect_uri)
                host = parsed_uri.hostname or 'localhost'
                port = parsed_uri.port or 8080

                # Create the OAuth flow with the local redirect URI
                flow = Flow.from_client_config(
                    client_config,
                    scopes=SCOPES,
                    redirect_uri=local_redirect_uri
                )

                # Generate authorization URL
                auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')

                # Create a simple HTTP server to handle the callback
                class OAuthCallbackHandler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        try:
                            # Parse the authorization code from the callback URL
                            query_params = parse_qs(urlparse(self.path).query)
                            code = query_params.get('code', [None])[0]

                            if code:
                                # Exchange the authorization code for credentials
                                flow.fetch_token(code=code)
                                self.send_response(200)
                                self.send_header('Content-type', 'text/html')
                                self.end_headers()
                                self.wfile.write(b'<html><body><h1>Authentication successful! You can close this window.</h1></body></html>')

                                # Store the credentials
                                nonlocal creds
                                creds = flow.credentials
                                logger.info("Authorization code processed successfully")
                            else:
                                self.send_response(400)
                                self.send_header('Content-type', 'text/html')
                                self.end_headers()
                                self.wfile.write(b'<html><body><h1>Authentication failed!</h1></body></html>')
                        except Exception as e:
                            logger.error(f"Error processing callback: {e}")
                            self.send_response(500)
                            self.send_header('Content-type', 'text/html')
                            self.end_headers()
                            self.wfile.write(b'<html><body><h1>Error processing authentication!</h1></body></html>')

                    def log_message(self, format, *args):
                        # Suppress server log messages
                        pass

                # Start the server in a separate thread
                server = HTTPServer((host, port), OAuthCallbackHandler)
                server_thread = threading.Thread(target=server.serve_forever)
                server_thread.daemon = True
                server_thread.start()

                logger.info(f"OAuth server started at {local_redirect_uri}")
                logger.info(f"Please visit this URL to authorize: {auth_url}")
                logger.info("After authorizing, the callback will be handled automatically.")

                # Wait for the credentials to be set
                timeout = 120  # Wait up to 120 seconds
                start_time = time.time()
                while not creds and time.time() - start_time < timeout:
                    time.sleep(0.5)

                # Stop the server
                server.shutdown()

                if not creds:
                    logger.error("OAuth flow timed out or failed to get credentials")
                    return None

            else:  # Desktop/Installed app flow
                logger.info("Starting OAuth flow with installed application credentials:")

                # For installed apps that use manual authorization (copy/paste),
                # we should use the out-of-band URI regardless of what's in the config
                redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'

                # Create the installed app flow - the redirect_uri will be handled internally
                flow = InstalledAppFlow.from_client_config(
                    client_config,
                    scopes=SCOPES
                )
                # Set the redirect URI on the flow object
                flow.redirect_uri = redirect_uri

                try:
                    # Use 'select_account' and 'consent' to force a fresh authorization
                    # This ensures we get a token with only the scopes we're requesting
                    auth_url, _ = flow.authorization_url(
                        prompt='consent',
                        access_type='offline',
                        include_granted_scopes='false'  # Don't include previously granted scopes
                    )
                    logger.info(f"Authorization URL: {auth_url}")
                    logger.info("Sign in and copy the authorization code")
                    logger.info("After authorizing, copy only the 'code' parameter value from the redirect URL")
                    logger.info("Example: If redirected to urn:ietf:wg:oauth:2.0:oob?code=abcd1234..., copy only 'abcd1234...' part")
                    logger.info("Make sure to copy the entire code without extra characters")
                    logger.info("Then paste the code below:")

                    # Print the authorization URL
                    print(f"Please visit this URL to authorize: {auth_url}")

                    # Check if we're in a non-interactive environment
                    if not sys.stdin.isatty():
                        logger.info("Non-interactive environment detected. Skipping OAuth flow.")
                        logger.info("Please run this script in an environment where you can complete the OAuth flow.")
                        return None

                    # Get the authorization code from user input
                    code_input = input("Enter the authorization code: ")
                    code = code_input.strip()

                    # Validate that the code is not empty
                    if not code:
                        logger.error("No authorization code entered")
                        return None

                    logger.info(f"Attempting to exchange authorization code for tokens...")

                    # Exchange the code for credentials
                    # The redirect_uri is already set on the flow object
                    flow.fetch_token(code=code)
                    creds = flow.credentials
                    logger.info("Authorization code processed successfully")

                except KeyboardInterrupt:
                    logger.info("OAuth flow interrupted by user")
                    return None
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Error during OAuth setup: {e}")

                    # If the error is related to scope mismatch, remove the token file and try again
                    if "Scope has changed" in error_msg or "scope" in error_msg.lower():
                        logger.info("Scope mismatch detected. Removing existing token file and restarting OAuth flow.")
                        try:
                            if os.path.exists(token_file):
                                os.remove(token_file)
                                logger.info("Token file removed. Please restart the script to begin a fresh OAuth flow.")
                        except:
                            pass

                    return None

            # Save the credentials for next run
            with open(token_file, 'w') as f:
                f.write(creds.to_json())
                logger.info(f"Credentials saved to {token_file}")

    try:
        # Build and return the YouTube service
        service = build("youtube", "v3", credentials=creds)
        logger.info("YouTube API service created successfully")
        return service
    except Exception as e:
        logger.error(f"Error building YouTube API service: {e}")
        return None

def sync_playlists_to_youtube():
    try:
        scraped = load_scraped_playlists()
        synced = load_synced_playlists()

        if not scraped:
            logger.info("No playlists to sync")
            return

        # Check if daily quota is full before initializing API use
        if not check_daily_quota():
            logger.info("Daily quota is full. Skipping sync process.")
            return

        youtube = get_authenticated_service()
        if not youtube:
            logger.error("Failed to authenticate with YouTube API")
            logger.info("To sync playlists, you need to authenticate with YouTube API.")
            logger.info("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET environment variables,")
            logger.info("then run the script in an environment where you can complete the OAuth flow.")
            return

        logger.info(f"Starting sync for {len(scraped)} playlists...")

        for playlist in scraped[:]:
            try:
                # Check if this playlist has already been synced
                if any(s["original_playlist_id"] == playlist["playlist_id"] for s in synced):
                    logger.debug(f"Playlist {playlist['title']} already synced, removing from scraped list")
                    scraped.remove(playlist)
                    save_scraped_playlists(scraped)
                    continue

                # Check daily quota before creating a new playlist (costs 50 units)
                if not check_daily_quota():
                    logger.info("Daily quota limit reached. Stopping sync process.")
                    break

                logger.info(f"Syncing playlist: {playlist['title']}")

                # Create the new playlist on YouTube with description assuming it's an album playlist
                playlist_body = {
                    "snippet": {
                        "title": playlist["title"][:50],  # YouTube title limit
                        "description": f"{playlist['title']} - Full Album\n{playlist['title']} - New Album - {datetime.now().year}\n{playlist['title']} - Full Album Playlist"
                    },
                    "status": {
                        "privacyStatus": "public"
                    }
                }

                # Create playlist without retry mechanism (as requested)
                try:
                    res = youtube.playlists().insert(
                        part="snippet,status",
                        body=playlist_body
                    ).execute()
                    new_id = res["id"]
                    logger.info(f"Created new playlist: {new_id}")

                    # Consume 50 quota units for playlist creation
                    consume_quota(50)
                except Exception as e:
                    logger.error(f"Failed to create playlist {playlist['title']}: {e}")
                    continue  # Skip to the next playlist if creation failed

                # Add videos to the new playlist
                videos = playlist.get("videos", [])
                if videos:
                    logger.info(f"Adding {len(videos)} videos to playlist {new_id}")

                    for idx, v_id in enumerate(videos):
                        # Check daily quota before adding each video (costs 50 units)
                        if not check_daily_quota():
                            logger.info("Daily quota limit reached. Stopping sync process.")
                            return  # Exit the function entirely

                        try:
                            # Add video to playlist without retry mechanism (as requested)
                            youtube.playlistItems().insert(
                                part="snippet",
                                body={
                                    "snippet": {
                                        "playlistId": new_id,
                                        "resourceId": {
                                            "kind": "youtube#video",
                                            "videoId": v_id
                                        }
                                    }
                                }
                            ).execute()

                            # Consume 50 quota units for each video addition
                            consume_quota(50)

                            logger.info(f"Added video {v_id} to playlist {new_id}")

                        except Exception as video_error:
                            logger.error(f"Failed to add video {v_id} to playlist {new_id}: {video_error}")
                            continue  # Continue with the next video even if one fails

                        # Add delay between video additions to avoid rate limiting
                        # Only sleep if the video was added successfully
                        if idx < len(videos) - 1:  # Don't sleep after the last video
                            time.sleep(VIDEO_ADD_DELAY_SECONDS)  # Configurable delay between video additions

                # Record the sync completion
                synced.append({
                    "original_playlist_id": playlist["playlist_id"],
                    "new_playlist_id": new_id,
                    "synced_at": datetime.now().isoformat(),
                    "title": playlist["title"],
                    "videos": playlist.get("videos", [])
                })

                # Remove from scraped list and save both lists
                scraped.remove(playlist)
                save_scraped_playlists(scraped)
                save_synced_playlists(synced)
                logger.info(f"Successfully synced: {playlist['title']} -> {new_id}")

                # Add delay between playlist syncs to avoid rate limiting
                time.sleep(PLAYLIST_SYNC_DELAY_SECONDS)  # Configurable delay between playlist syncs

            except Exception as e:
                logger.error(f"Sync error for {playlist['title']}: {e}")
                # Continue with the next playlist even if one fails
                continue

        logger.info(f"Sync process completed. {len(scraped)} playlists remaining to sync.")
    except Exception as e:
        logger.error(f"Error in sync_playlists_to_youtube function: {e}")

# Quota tracking
QUOTA_USAGE_FILE = Path("./data/quota_usage.json")

def load_quota_usage():
    """Load daily quota usage from file"""
    if QUOTA_USAGE_FILE.exists():
        with open(QUOTA_USAGE_FILE) as f:
            return json.load(f)
    return {"date": None, "used_units": 0}

def save_quota_usage(date, used_units):
    """Save daily quota usage to file"""
    with open(QUOTA_USAGE_FILE, "w") as f:
        json.dump({"date": date, "used_units": used_units}, f, indent=2)

def check_daily_quota():
    """Check if we've exceeded the daily quota (configurable limit)"""
    today = datetime.now().strftime("%Y-%m-%d")
    quota_data = load_quota_usage()

    # Reset quota if it's a new day
    if quota_data["date"] != today:
        quota_data = {"date": today, "used_units": 0}

    # Check if we've exceeded the daily limit (configurable)
    if quota_data["used_units"] >= DAILY_QUOTA_LIMIT:
        logger.warning(f"Daily quota of {DAILY_QUOTA_LIMIT} units reached. Used: {quota_data['used_units']}")

        # If credential rotation is enabled, try to switch to a different token file
        if ROTATE_CREDENTIALS_ON_QUOTA_EXHAUSTION:
            logger.info("Credential rotation enabled. Checking for alternate token files...")
            return rotate_credentials_if_available()
        return False

    return True

def rotate_credentials_if_available():
    """Rotate to a different token file if available and quota is not exhausted"""
    global CURRENT_TOKEN_FILE  # Update the module-level token file variable

    # Cycle through available credential sets
    for cred_file in CREDENTIAL_SETS:
        if cred_file != CURRENT_TOKEN_FILE and os.path.exists(cred_file):
            # Check the quota for this alternate credential set
            alt_quota_file = f"quota_usage_{cred_file.replace('.json', '')}.json"
            alt_quota_path = f"./data/{alt_quota_file}"
            if os.path.exists(alt_quota_path):
                with open(alt_quota_path) as f:
                    alt_quota_data = json.load(f)
                today = datetime.now().strftime("%Y-%m-%d")

                # Reset quota if it's a new day
                if alt_quota_data["date"] != today:
                    save_alt_quota_usage(alt_quota_file, today, 0)
                    alt_quota_data = {"date": today, "used_units": 0}

                # If this alternate credential set has quota available, switch to it
                if alt_quota_data["used_units"] < 10000:
                    logger.info(f"Switching to alternate credentials: {cred_file}")
                    CURRENT_TOKEN_FILE = cred_file  # Update the module-level token file variable
                    return True  # Indicate that we can continue with new credentials
            else:
                # If no quota file exists for this credential set, assume it has quota available
                logger.info(f"Switching to alternate credentials: {cred_file}")
                CURRENT_TOKEN_FILE = cred_file  # Update the module-level token file variable
                return True  # Indicate that we can continue with new credentials

    # No alternate credentials with available quota found
    logger.warning("No alternate credentials with available quota found")
    return False

def save_alt_quota_usage(quota_file, date, used_units):
    """Save alternate quota usage to file"""
    # Ensure the data directory exists
    os.makedirs("./data", exist_ok=True)
    with open(f"./data/{quota_file}", "w") as f:
        json.dump({"date": date, "used_units": used_units}, f, indent=2)

def consume_quota(units):
    """Consume specified number of quota units"""
    global CURRENT_TOKEN_FILE  # Access the module-level token file variable
    today = datetime.now().strftime("%Y-%m-%d")
    quota_data = load_quota_usage()

    # Reset quota if it's a new day
    if quota_data["date"] != today:
        quota_data = {"date": today, "used_units": 0}

    quota_data["used_units"] += units
    save_quota_usage(today, quota_data["used_units"])

    # Also update the quota file for the current token file if it's not the default
    current_token_base = CURRENT_TOKEN_FILE.replace('.json', '')
    if current_token_base != 'token':
        alt_quota_file = f"quota_usage_{current_token_base}.json"
        alt_quota_data = {"date": today, "used_units": 0}
        alt_quota_path = f"./data/{alt_quota_file}"
        if os.path.exists(alt_quota_path):
            with open(alt_quota_path) as f:
                alt_quota_data = json.load(f)

        # Reset quota if it's a new day
        if alt_quota_data["date"] != today:
            save_alt_quota_usage(alt_quota_file, today, 0)
            alt_quota_data = {"date": today, "used_units": 0}

        alt_quota_data["used_units"] += units
        save_alt_quota_usage(alt_quota_file, today, alt_quota_data["used_units"])

    logger.info(f"Consumed {units} quota units. Total used today: {quota_data['used_units']}/10000")

def detect_new_playlists():
    logger.info(f"Fetching page from {CHANNEL_URL}")

    try:
        state = load_state()
        # Try Selenium-based scraping first (more reliable for dynamic content)
        current = scrape_playlists_with_selenium()

        # If Selenium fails or returns no results, try Playwright as backup (if enabled)
        if not current and USE_PLAYWRIGHT_FOR_SCRAPE:
            logger.info("Selenium scraping returned no results, trying Playwright-based scraping...")
            current = scrape_playlists_with_playwright()

        # If both methods fail, try API method again as a last resort
        if not current:
            logger.info("Selenium and Playwright scraping returned no results, trying API-based scraping...")
            current = scrape_playlists_with_api()

        if not current:
            logger.warning("Could not detect any new playlists this run, but processing existing scraped playlists")

        prev = state.get("latest_playlist_link")
        logger.info(f"Previous latest playlist: {prev}")
        logger.info(f"Current latest playlist: {current[0]['link'] if current else 'None'}")

        if prev and current and prev != current[0]["link"]:
            logger.info("New playlists detected!")
            new_items = []

            for p in current:
                if p["link"] == prev:
                    break
                logger.info(f"Processing new playlist: {p['title']}")

                # Fetch the real title from the playlist page
                real_title = fetch_playlist_title_from_page(p['playlist_id'])
                if real_title:
                    p['title'] = real_title
                    logger.info(f"Updated title: {p['title']}")

                # Apply filter after title correction to ensure accurate filtering
                if FILTER_FOR and "full album" not in p['title'].lower():
                    logger.debug(f"Filtering out playlist '{p['title']}' (ID: {p['playlist_id']}) - does not seem to be a music album")
                    continue  # Skip this playlist if it doesn't match the filter

                try:
                    p["videos"] = extract_videos_from_playlist(p["link"])
                    new_items.append(p)
                except Exception as video_error:
                    logger.error(f"Error extracting videos for playlist {p['title']}: {video_error}")
                    continue

            if new_items:
                logger.info(f"Found {len(new_items)} new playlists to add to scraping queue")
                scraped = load_scraped_playlists()
                scraped.extend(new_items)
                save_scraped_playlists(scraped)
                state["latest_playlist_link"] = current[0]["link"]
                state["latest_playlist_title"] = current[0]["title"]
                state["last_checked"] = datetime.now().isoformat()
                save_state(state)
                logger.info(f"Added {len(new_items)} new playlists to sync queue")
            else:
                logger.info("No new playlists found beyond the previous latest")
        else:
            logger.info("No new playlists detected since last check")
            # Still update the last checked time
            state["last_checked"] = datetime.now().isoformat()
            save_state(state)

    except Exception as e:
        logger.error(f"Error detecting new playlists: {e}")
        logger.warning("Could not detect any new playlists this run, but processing existing scraped playlists")

def main():
    logger.info("=" * 70)
    logger.info("YouTube Monitor - Automation Run")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("=" * 70)

    try:
        logger.info("Starting playlist detection...")
        detect_new_playlists()

        # Load scraped playlists to see if there are any to sync
        scraped = load_scraped_playlists()
        logger.info(f"Playlists awaiting sync: {len(scraped)}")

        # Only sync if the feature is enabled
        if ENABLE_YOUTUBE_API_SYNC:
            if scraped:
                logger.info("Starting playlist sync to YouTube...")
                sync_playlists_to_youtube()
            else:
                logger.info("No playlists awaiting sync")
        else:
            logger.info("YouTube API sync is disabled (ENABLE_YOUTUBE_API_SYNC=False), skipping sync process")
            if scraped:
                logger.info(f"Found {len(scraped)} playlists that would have been synced if sync was enabled:")
                for playlist in scraped:
                    logger.info(f"  - '{playlist.get('title', 'Unknown')}' (ID: {playlist.get('playlist_id', 'Unknown')})")

    except KeyboardInterrupt:
        logger.info("Automation run interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error during automation run: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
    finally:
        logger.info("Automation run complete")
        logger.info("=" * 70)

if __name__ == "__main__":
    main()



