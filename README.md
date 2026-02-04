# Playlist Monitor & Sync

A Python script to monitor and sync YouTube playlists from a given channel, with advanced filtering and quota management capabilities.

## Features

- **Playlist Scraping**: Automatically scrapes playlists from a YouTube channel
- **Filtering**: Option to only process playlists containing "Full Album" in the title
- **Spam Filtering**: Automatically filters out spam videos from Music playlists such as "Best Summer Songs Playlists" videos usually inserted fpr views
- **Quota Management**: Tracks and manages YouTube API quota usage (10,000 units/day)
- **Credential Rotation**: Option to rotate between multiple Google Cloud projects when quota is exhausted
- **Rate Limiting**: Built-in delays to prevent API rate limiting
- **Selenium Support**: Uses Selenium for reliable playlist scraping
- **Video Order Preservation**: Maintains the original order of videos in playlists

## Installation

1. Clone the repository:

   ```bash
   git clone <repository-url>
   cd youtubeSync
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. For syncing to another channel (optional), set up your Google Cloud credentials:

   - Create a Google Cloud Project
   - Enable the YouTube Data API v3
   - Create OAuth 2.0 credentials for a Desktop Application
   - Download the credentials as `file credentials.json` OR export environment variables OR export / add to lines to .env with your credentials :
   - YOUTUBE_CLIENT_ID=\*\*\*\*
   - YOUTUBE_CLIENT_SECRET=\*\*\*\*

## Configuration

### Environment Variables

Copy the `.env.example` to `.env` and customize the settings:

```bash
cp .env.example .env
```

Key configuration options:

- `FILTER_FOR`: Set to `True` to only process playlists detected with a chosen phrase in the title (currently set to filter for "Full Album" playlists, which you can replace with any string in monitor.py, but can also be set to False for no filter)
- `ROTATE_CREDENTIALS_ON_QUOTA_EXHAUSTION`: Set to `True` to enable credential rotation when quota is exhausted
- `DAILY_QUOTA_LIMIT`: Maximum API units per day for optional syncing (default: 10000)
- `VIDEO_ADD_DELAY_SECONDS`: Delay between video additions (default: 3)
- `PLAYLIST_SYNC_DELAY_SECONDS`: Delay between playlist syncs (default: 25)

### Credential Files

- `file token.json`: Main authentication token (generated after first OAuth flow)
- `file token_alt1.json`, `file token_alt2.json`: Alternative tokens for rotation (optional)

## Usage

1. Run the monitor:

   ```bash
   python monitor.py
   ```

2. On first run, you'll need to complete the OAuth flow in your browser

3. The script will:

   - Scrape new playlists from the channel
   - Filter out spam videos
   - Sync playlists to your YouTube account
   - Track API quota usage

## Advanced Features

### n8n automation

To automate this script running daily/hourly/on whatever time schedule you want, use n8n or any similar self-hostable workflows to run a cron job

```bash
npx n8n
```

Import youtubeSyncMonitor-workflow.json , a pre-made workflow that auto-runs at chosen times oif the day and is able to send emails notifying you on the playlists detected and synced on each run.

### Credential Rotation

To enable credential rotation across multiple Google Cloud projects:

1. Set up multiple Google Cloud projects with YouTube Data API enabled
2. Generate token files for each project (`file token_alt1.json`, `file token_alt2.json`, etc.)
3. Set `ROTATE_CREDENTIALS_ON_QUOTA_EXHAUSTION=True` in your `.env` file
4. Add your token files to the `CREDENTIAL_SETS` variable

### Playlist Filtering

The script can filter to only process playlists containing whatever phrase you choose;  replace "full album" in monitor.py for the following logic to change the filter phrase (ctrl+f)  :


```python
"full album" not in p['title'].lower()
```


- Set `FILTER_FOR=True` to enable this feature
- Set to `False` to process all playlists

### Quota Management

- Each playlist creation consumes 50 API units
- Each video addition consumes 50 API units
- Daily limit is 10,000 units (allowing \~200 actions per day)
- Quota usage is tracked in `file quota_usage.json`
- When enabled, credential rotation allows continued operation across multiple projects

## Files

- `file monitor.py`: Main script
- `file config.py`: Configuration settings
- `.env`: Environment variables
- `file state.json`: Current state tracking
- `file scraped_playlists.json`: List of scraped playlists
- `file synced_playlists.json`: List of synced playlists
- `file token.json`: Authentication token
- `file quota_usage.json`: Daily quota tracking

## Security Best Practices

### Token and Credential Security

- **Never commit sensitive files** to version control:

  - `file token.json`, `file credentials.json`, and `.env` are in your `.gitignore`
  - These files contain sensitive authentication information

- **Secure token storage**:

  - Store `file token.json` in a secure location with restricted access
  - Regularly rotate your API credentials
  - Monitor your Google Cloud project for unauthorized usage

- **Environment variables**:

  - Don't hardcode credentials in source code
  - Use environment variables or secure vaults for sensitive data
  - The `.env` file should never be committed to version control

## Troubleshooting

- If you encounter quota errors, check `file data/quota_usage.json` to see current usage
- If credential rotation is enabled, ensure all token files exist and are valid
- Check `automation.log` for detailed error messages
- For OAuth issues, delete `file data/token.json` and restart the script
- Make sure the `data/` directory exists and has proper permissions

## License

MIT