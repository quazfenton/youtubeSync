#!/usr/bin/env python3
"""
YouTube Revive Monitor - Crawlee-based Version
Uses crawlee for robust browser automation and data extraction
"""

# Apply the Pydantic compatibility fix before importing Crawlee
from fix_pydantic import patch_crawlee_pydantic_issue

import re
import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from crawlee.crawlers import PlaywrightCrawler
from crawlee.configuration import Configuration

# Configuration paths
STATE_FILE = Path("./data/state.json")
SCRAPED_PLAYLISTS_FILE = Path("./data/scraped_playlists.json")
CHANNEL_URL = "https://www.youtube.com/@revive/playlists"

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
file_handler = logging.FileHandler("./data/crawlee_automation.log")
formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s")
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.addHandler(file_handler)
logger.propagate = False


def load_state() -> dict:
    """
    Load the persisted monitor state from disk; if no state file exists, return a default state.
    
    Returns:
        dict: Mapping with keys:
            - `latest_playlist_link` (str | None): URL of the most recently seen playlist, or `None`.
            - `latest_playlist_title` (str | None): Title of the most recently seen playlist, or `None`.
            - `last_checked` (str | None): ISO-formatted timestamp of the last check, or `None`.
    """
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"latest_playlist_link": None, "latest_playlist_title": None, "last_checked": None}


def save_state(state: dict) -> None:
    """
    Persist the crawler state to the configured STATE_FILE on disk.
    
    Parameters:
        state (dict): Dictionary of state values to persist. Expected keys include
            `latest_playlist_link` (str or None), `latest_playlist_title` (str or None),
            and `last_checked` (ISO-8601 timestamp string or None). The dictionary
            will be written as pretty-printed JSON to the module's STATE_FILE.
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_scraped_playlists() -> list:
    """
    Load the list of playlists previously saved to disk.
    
    Reads the JSON file at SCRAPED_PLAYLISTS_FILE and returns its contents as a list. If the file does not exist, returns an empty list.
    
    Returns:
        list: Previously scraped playlists, or an empty list if no persisted data exists.
    """
    if SCRAPED_PLAYLISTS_FILE.exists():
        with open(SCRAPED_PLAYLISTS_FILE) as f:
            return json.load(f)
    return []


def save_scraped_playlists(playlists: list) -> None:
    """
    Write the list of scraped playlists to the configured SCRAPED_PLAYLISTS_FILE in JSON format.
    
    Parameters:
        playlists (list): JSON-serializable list of playlist records (typically dicts with keys such as 'link', 'playlist_id', 'title', 'discovered_at', and 'videos').
    """
    with open(SCRAPED_PLAYLISTS_FILE, "w") as f:
        json.dump(playlists, f, indent=2)


async def extract_playlist_title(page) -> Optional[str]:
    """
    Extracts the playlist title from the YouTube page title.
    
    Strips a trailing " - YouTube" suffix when present and returns the cleaned title if its length is greater than 2; returns None if no usable title is found or an error occurs.
    
    Returns:
        title (Optional[str]): The playlist title if available, `None` otherwise.
    """
    try:
        page_title = await page.title()
        # Page title format: "Playlist Name - YouTube" or similar
        if " - YouTube" in page_title:
            title = page_title.rsplit(" - YouTube", 1)[0].strip()
            return title if title and len(title) > 2 else None
        return page_title if page_title and len(page_title) > 2 else None
    except Exception as e:
        logger.warning(f"Error extracting title: {e}")
        return None


def extract_playlist_id_from_url(url: str) -> Optional[str]:
    """
    Extract the YouTube playlist ID from a URL's `list` query parameter.
    
    Parameters:
        url (str): The URL to inspect; may be a full YouTube link or a query string containing `list=`.
    
    Returns:
        Optional[str]: The playlist ID string if a `list=` parameter is present, otherwise `None`.
    """
    match = re.search(r'list=([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else None


async def extract_videos_from_playlist(page, playlist_id: str, max_videos: int = 1000) -> list:
    """
    Extracts YouTube video IDs from the currently loaded playlist page.
    
    Parameters:
    	page: Playwright page object positioned on a YouTube playlist.
    	playlist_id (str): Playlist identifier used for logging.
    	max_videos (int): Maximum number of video IDs to return.
    
    Returns:
    	list: A list of video ID strings found on the page (up to `max_videos`). Returns an empty list if no videos are found or an error occurs.
    """
    try:
        videos = []
        
        # Scroll to load more videos
        for _ in range(5):
            # Scroll to bottom to load more items
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_load_state("networkidle", timeout=3000)
        
        # Extract video IDs from the playlist rendering data
        video_ids = await page.evaluate("""
            () => {
                const videoIds = [];
                // YouTube stores video data in various DOM structures
                // Try multiple selectors
                
                // Method 1: From ytInitialData in HTML
                const dataScript = document.querySelector('script[nonce]');
                if (window.ytInitialData?.contents?.twoColumnBrowseResultsRenderer?.tabs?.[0]?.tabRenderer?.content) {
                    const content = window.ytInitialData.contents.twoColumnBrowseResultsRenderer.tabs[0].tabRenderer.content;
                    const items = content.sectionListRenderer?.contents?.[0]?.itemSectionRenderer?.contents?.[0]?.playlistVideoListRenderer?.contents || [];
                    items.forEach(item => {
                        if (item.playlistVideoRenderer?.videoId) {
                            videoIds.push(item.playlistVideoRenderer.videoId);
                        }
                    });
                }
                
                // Method 2: From DOM attributes
                if (videoIds.length === 0) {
                    document.querySelectorAll('[data-video-id]').forEach(elem => {
                        const vid = elem.getAttribute('data-video-id');
                        if (vid && videoIds.length < 100) videoIds.push(vid);
                    });
                }
                
                return videoIds;
            }
        """)
        
        if video_ids:
            videos = video_ids[:max_videos]
            logger.info(f"Extracted {len(videos)} videos from playlist {playlist_id}")
        else:
            logger.warning(f"No videos found for playlist {playlist_id}")
        
        return videos
    except Exception as e:
        logger.error(f"Error extracting videos from playlist: {e}")
        return []


async def scrape_playlists() -> list:
    """
    Crawl the channel's playlists page and individual playlist pages to collect playlists and their videos.
    
    The function navigates the channel playlists view, discovers playlist links, visits each playlist page, and extracts metadata and video IDs for each unique playlist found. Duplicate playlists (by playlist_id) are ignored.
    
    Returns:
        list: A list of playlist dictionaries. Each dictionary contains:
            - "link" (str): Full playlist URL.
            - "playlist_id" (str): Extracted playlist identifier.
            - "title" (str): Playlist title.
            - "discovered_at" (str): ISO 8601 timestamp when the playlist was discovered.
            - "videos" (list): List of video IDs contained in the playlist.
    """
    playlists = []
    seen_ids = set()
    
    # Create configuration and set storage directory
    configuration = Configuration(storage_dir="./crawlee_storage")

    # Configure browser launch options to handle sandboxing issues
    from crawlee.router import Router

    # Create a router and define the handler
    router = Router()

    @router.default_handler
    async def request_handler(context) -> None:
        """
        Handle a Crawlee page request and discover or process YouTube playlists.
        
        When the request URL contains '/playlists' or a 'list=' query parameter, this handler:
        - For individual playlist pages (URLs with 'list='): extracts the playlist ID and title, collects video IDs, appends a playlist record to the module-level `playlists` list, and marks the playlist ID in `seen_ids`.
        - For a channel's playlists listing page (URLs containing '/playlists' and an '@' channel path): loads additional content as needed, extracts playlist links, and enqueues unseen playlist URLs for crawling while marking their IDs in `seen_ids`.
        
        Parameters:
            context: Crawlee request context object exposing `.request` and `.page`, used to read the current URL, interact with the page, and enqueue discovered links.
        """
        request = context.request
        page = context.page

        # Only process playlist pages
        if '/playlists' in request.loaded_url or 'list=' in request.loaded_url:
            logger.info(f"Processing: {request.loaded_url}")

            # If it's a specific playlist page, extract videos
            if 'list=' in request.loaded_url:
                playlist_id = extract_playlist_id_from_url(request.loaded_url)
                if playlist_id:
                    title = await extract_playlist_title(page)
                    if title and playlist_id not in seen_ids:
                        videos = await extract_videos_from_playlist(page, playlist_id)
                        playlists.append({
                            "link": request.loaded_url,
                            "playlist_id": playlist_id,
                            "title": title,
                            "discovered_at": datetime.now().isoformat(),
                            "videos": videos
                        })
                        seen_ids.add(playlist_id)
                        logger.info(f"Added playlist: {title} (ID: {playlist_id})")

            # If it's the main playlists page, extract all playlist links
            elif '/playlists' in request.loaded_url and '@' in request.loaded_url:
                # Scroll to load all playlists
                for _ in range(10):
                    try:
                        await page.evaluate("window.scrollBy(0, window.innerHeight)")
                        await page.wait_for_load_state("networkidle", timeout=2000)
                    except:
                        pass

                # Extract playlist links
                playlist_links = []
                try:
                    playlist_links = await page.evaluate("""
                        () => {
                            const links = [];
                            // Look for playlist links
                            document.querySelectorAll('a[href*="list="]').forEach(link => {
                                const href = link.getAttribute('href');
                                if (href && !href.includes('watch?v=')) {
                                    // Get the full URL
                                    const fullUrl = new URL(href, document.location.origin).href;
                                    if (!links.includes(fullUrl)) {
                                        links.push(fullUrl);
                                    }
                                }
                            });
                            return [...new Set(links)];
                        }
                    """)
                except Exception as e:
                    logger.warning(f"Error extracting playlist links: {e}")

                # Enqueue all found playlists for scraping
                logger.info(f"Found {len(playlist_links)} playlist links")
                for link in playlist_links:
                    if 'list=' in link:
                        playlist_id = extract_playlist_id_from_url(link)
                        if playlist_id and playlist_id not in seen_ids:
                            await context.enqueue_links([link], user_data={"is_playlist_page": True})
                            seen_ids.add(playlist_id)

    crawler = PlaywrightCrawler(
        configuration=configuration,
        use_session_pool=False,
        headless=True,
        max_requests_per_crawl=150,  # Limit to avoid long scraping sessions
        browser_launch_options={'args': ['--no-sandbox', '--disable-setuid-sandbox']},
        request_handler=router,  # Pass the router as the request handler
    )

    # Start crawling from the channel playlists page
    logger.info(f"Starting crawl from {CHANNEL_URL}")
    await crawler.run([CHANNEL_URL])
    
    logger.info(f"Scraping complete. Found {len(playlists)} playlists")
    return playlists


def filter_playlists(playlists: list, filter_full_album_only: bool = False) -> list:
    """
    Return playlists filtered to only those whose title contains "full album" when requested.
    
    Parameters:
        playlists (list): List of playlist dictionaries expected to include a "title" key.
        filter_full_album_only (bool): If True, only keep playlists whose title contains "full album" (case-insensitive).
    
    Returns:
        list: The filtered list when filtering is enabled; otherwise the original playlists list.
    """
    if not filter_full_album_only:
        return playlists
    
    filtered = [p for p in playlists if "full album" in p.get("title", "").lower()]
    logger.info(f"Filtered to {len(filtered)} playlists with 'Full Album' in title")
    return filtered


async def main():
    """
    Orchestrates scraping of YouTube playlists, detects newly discovered playlists, and updates persisted state and scraped-playlist storage.
    
    Loads prior run state, runs the playlist scraper, optionally filters and sorts results by discovery time (newest first), and determines which playlists are new since the last saved latest playlist. On detection of new playlists it appends them to the saved scraped playlists and updates the persisted state (latest link, title, and last_checked). On a first run it saves all discovered playlists and initializes state. When no changes are found it updates only the last_checked timestamp. Handles user interruption and logs unexpected errors.
    """
    logger.info("=" * 70)
    logger.info("YouTube Revive Monitor - Crawlee Edition")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("=" * 70)
    
    try:
        # Load previous state
        state = load_state()
        
        # Scrape playlists
        logger.info(f"Scraping playlists from {CHANNEL_URL}")
        current_playlists = await scrape_playlists()
        
        if not current_playlists:
            logger.warning("No playlists found during scraping")
            return
        
        # Filter if needed
        current_playlists = filter_playlists(current_playlists, filter_full_album_only=False)
        
        # Sort by discovered_at in reverse order (newest first)
        current_playlists.sort(
            key=lambda x: x.get("discovered_at", ""), 
            reverse=True
        )
        
        logger.info(f"Total playlists found: {len(current_playlists)}")
        
        # Check for new playlists
        prev = state.get("latest_playlist_link")
        current_latest = current_playlists[0] if current_playlists else None
        
        if current_latest:
            logger.info(f"Latest playlist: {current_latest['title']} ({current_latest['playlist_id']})")
        
        if prev and current_latest and prev != current_latest["link"]:
            logger.info("New playlists detected!")
            
            # Find all playlists since the previous latest
            new_playlists = []
            for p in current_playlists:
                if p["link"] == prev:
                    break
                new_playlists.append(p)
            
            if new_playlists:
                logger.info(f"Found {len(new_playlists)} new playlists")
                
                # Load and append to scraped playlists
                scraped = load_scraped_playlists()
                scraped.extend(new_playlists)
                save_scraped_playlists(scraped)
                
                # Update state
                state["latest_playlist_link"] = current_latest["link"]
                state["latest_playlist_title"] = current_latest["title"]
                state["last_checked"] = datetime.now().isoformat()
                save_state(state)
                
                logger.info(f"Added {len(new_playlists)} new playlists to sync queue")
            else:
                logger.info("No new playlists found beyond the previous latest")
        elif not prev and current_playlists:
            # First run - save all playlists
            logger.info("First run detected - saving all playlists")
            save_scraped_playlists(current_playlists)
            state["latest_playlist_link"] = current_latest["link"]
            state["latest_playlist_title"] = current_latest["title"]
            state["last_checked"] = datetime.now().isoformat()
            save_state(state)
        else:
            logger.info("No new playlists detected")
            state["last_checked"] = datetime.now().isoformat()
            save_state(state)
    
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user")
    except Exception as e:
        logger.error(f"Error during scraping: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())