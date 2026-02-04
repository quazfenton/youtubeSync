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
    """Load state from previous runs"""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"latest_playlist_link": None, "latest_playlist_title": None, "last_checked": None}


def save_state(state: dict) -> None:
    """Save state for next run"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_scraped_playlists() -> list:
    """Load previously scraped playlists"""
    if SCRAPED_PLAYLISTS_FILE.exists():
        with open(SCRAPED_PLAYLISTS_FILE) as f:
            return json.load(f)
    return []


def save_scraped_playlists(playlists: list) -> None:
    """Save scraped playlists to file"""
    with open(SCRAPED_PLAYLISTS_FILE, "w") as f:
        json.dump(playlists, f, indent=2)


async def extract_playlist_title(page) -> Optional[str]:
    """
    Extract the playlist title from the current page.
    The page_title attribute contains the full YouTube page title.
    Extract the playlist name from it.
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
    """Extract playlist ID from URL"""
    match = re.search(r'list=([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else None


async def extract_videos_from_playlist(page, playlist_id: str, max_videos: int = 1000) -> list:
    """
    Extract video IDs from a playlist page using JavaScript evaluation.
    YouTube loads videos dynamically, so we extract from the JavaScript data.
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
    Main scraping function using Crawlee.
    Navigates to the channel playlists page and extracts all playlists.
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
        """Process each crawled page"""
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
    Filter playlists based on criteria.
    If filter_full_album_only is True, only keep playlists with "Full Album" in title.
    """
    if not filter_full_album_only:
        return playlists
    
    filtered = [p for p in playlists if "full album" in p.get("title", "").lower()]
    logger.info(f"Filtered to {len(filtered)} playlists with 'Full Album' in title")
    return filtered


async def main():
    """Main function"""
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
