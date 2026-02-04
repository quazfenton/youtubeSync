"""Configuration file for YouTube Monitor"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Page to watch, best for a channel's playist page link (default) but could also be used for regular channel videos page by removing the playlist ID logic in monitor.py which currently parses URL for playlist?list=ID  
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://www.youtube.com/@revive/playlists")

# Filter settings for only getting playlists detected with a given string (currently set to check for music albums via "full album". You can replace any with any string to filter in monitor.py with any given phrase you want OR set to False for no filtering
FILTER_FOR=True
FILTER_FOR = os.getenv("FILTER_FOR", "True").lower() == "true"

# Browser settings
USE_PLAYWRIGHT_FOR_SCRAPE = os.getenv("USE_PLAYWRIGHT_FOR_SCRAPE", "True").lower() == "true"

# Debug settings
ENABLE_DEBUG_LOGGING = os.getenv("ENABLE_DEBUG_LOGGING", "False").lower() == "true"
SAVE_PAGE_CONTENT_FOR_INSPECTION = os.getenv("SAVE_PAGE_CONTENT_FOR_INSPECTION", "False").lower() == "true"

# Scrolling settings
CLICK_SHOW_MORE_BUTTONS = os.getenv("CLICK_SHOW_MORE_BUTTONS", "False").lower() == "true"

# Sync settings
ENABLE_YOUTUBE_API_SYNC = os.getenv("ENABLE_YOUTUBE_API_SYNC", "False").lower() == "true"  # Default to False to disable sync

# Credential rotation settings
ROTATE_CREDENTIALS_ON_QUOTA_EXHAUSTION = os.getenv("ROTATE_CREDENTIALS_ON_QUOTA_EXHAUSTION", "False").lower() == "true"
CREDENTIAL_SETS = os.getenv("CREDENTIAL_SETS", "token.json,token_alt1.json,token_alt2.json").split(",")

# Quota settings
DAILY_QUOTA_LIMIT = int(os.getenv("DAILY_QUOTA_LIMIT", "10000"))

# Rate limiting settings
VIDEO_ADD_DELAY_SECONDS = float(os.getenv("VIDEO_ADD_DELAY_SECONDS", "3"))
PLAYLIST_SYNC_DELAY_SECONDS = float(os.getenv("PLAYLIST_SYNC_DELAY_SECONDS", "25"))

# YouTube API settings
YOUTUBE_SCOPES = os.getenv(
    "YOUTUBE_SCOPES", 
    "https://www.googleapis.com/auth/youtube,https://www.googleapis.com/auth/youtube.upload,https://www.googleapis.com/auth/youtube.force-ssl"
).split(",")

# Environment variables for authentication
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "urn:ietf:wg:oauth:2.0:oob")