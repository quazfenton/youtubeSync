# OAuth Setup Guide for YouTube API

## 

## Solution: Switch to Desktop Application

### Step 1: Update Google Cloud Console

1. Go to [Google Cloud Console - APIs & Services - Credentials](https://console.cloud.google.com/apis/credentials)
2. Delete your current "Web Application" OAuth 2.0 client
3. Create a **new OAuth 2.0 client** of type **"Desktop application"**
4. Download the credentials as JSON and save as `file credentials.json` in this directory

### Step 2: Authorized Redirect URIs

For a **Desktop Application**, you must authorize these redirect URIs:

```markdown
urn:ietf:wg:oauth:2.0:oob
```

This is Google's standard for out-of-band (OOB) authorization flow, which is designed for:

- Desktop applications
- Command-line tools
- Scripts running in non-web environments (like your automation)

### Step 3: Credentials File Format

Your `file credentials.json` from a Desktop Application should look like:

```json
{
  "installed": {
    "client_id": "your-client-id.apps.googleusercontent.com",
    "client_secret": "your-client-secret",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"]
  }
}
```

Note the `"installed"` key, not `"web"`.

## How the Fixed Code Works

The updated script now:

1. Reads your `file credentials.json` (or env variables `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`)
2. **Converts "web" type configs to "installed" type** for desktop flows
3. Explicitly sets the redirect URI to `urn:ietf:wg:oauth:2.0:oob`
4. Uses `InstalledAppFlow.authorization_url()` which properly includes the redirect_uri parameter
5. You manually authorize in your browser, copy the code, and paste it when prompted

## Running the Script

```bash
python monitor.py
```

First time:

- You'll see an authorization URL
- Click it and authorize your Google account
- Copy the authorization code from the browser
- Paste it when prompted in the terminal
- Credentials are saved to `file token.json` for future runs

Subsequent runs:

- The script uses the saved token.json automatically
- No need to authorize again (unless token expires)

## Troubleshooting

**Still getting redirect_uri error?**

1. Verify you're using a Desktop Application, not Web Application
2. Verify `file credentials.json` has `"installed"` key (not `"web"`)
3. Delete `file token.json` if it exists and try again

**Credentials not found?**

- Ensure `file credentials.json` is in the same directory as `file monitor.py`
- Or set environment variables: `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`