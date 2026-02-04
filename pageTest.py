#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import re
import json

def test_playlist_detection():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    # Try to access the page with consent bypass parameters
    urls_to_try = [
        "https://www.youtube.com/@revive/playlists",
        "https://www.youtube.com/@revive/playlists?ucbcb=1&gl=US&hl=en",
        "https://www.youtube.com/@revive/playlists?gl=US&hl=en&cbrd=1",
        "https://www.youtube.com/@revive/playlists?disable_polymer=1&gl=US&hl=en"
    ]
    
    response = None
    for url in urls_to_try:
        try:
            print(f"Trying URL: {url}")
            response = requests.get(url, headers=headers, timeout=30)
            print(f"Status code: {response.status_code}")
            print(f"Final URL: {response.url}")
            
            if "consent" not in response.url and "consent" not in response.text.lower():
                print("Successfully loaded page without consent redirect")
                break
            else:
                print("  -> Redirected to consent page, trying next URL")
        except Exception as e:
            print(f"Error with URL {url}: {e}")
            continue
    
    if response is None:
        print("Could not load page without consent redirect")
        return
    
    if "consent" in response.url or "consent" in response.text.lower():
        print("STILL ON CONSENT PAGE")
        return
    
    # Look for playlist links in the HTML
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Look for all links that contain playlist
    all_links = soup.find_all('a', href=re.compile(r'/playlist\?list='))
    print(f"Found {len(all_links)} links with playlist IDs")
    
    for i, link in enumerate(all_links[:10]):  # First 10 links
        href = link.get('href', '')
        playlist_id_match = re.search(r'list=([A-Za-z0-9_-]+)', href)
        if playlist_id_match:
            playlist_id = playlist_id_match.group(1)
            
            # Get the link text (this is usually "View full playlist")
            link_text = link.get_text(strip=True)
            
            # Look for the actual title in the parent hierarchy
            title = "Untitled"
            parent_element = link.find_parent()
            
            if parent_element:
                # Look for the title in the parent container
                # According to the inspection, the title is in a span with dir="auto"
                title_spans = parent_element.find_all('span', {'dir': 'auto'})
                for span in title_spans:
                    span_text = span.get_text(strip=True)
                    # Make sure it's not the same as the link text ("View full playlist")
                    if span_text and span_text != link_text and "view full playlist" not in span_text.lower() and len(span_text) > 5:
                        title = span_text
                        break
                
                # If still not found, look for h3 elements which often contain the title
                if title == "Untitled" or "view full playlist" in title.lower():
                    h3_elements = parent_element.find_all('h3')
                    for h3 in h3_elements:
                        h3_title_span = h3.find('span', {'dir': 'auto'})
                        if h3_title_span:
                            h3_text = h3_title_span.get_text(strip=True)
                            if h3_text and h3_text != link_text and "view full playlist" not in h3_text.lower() and len(h3_text) > 5:
                                title = h3_text
                                break
            
            print(f"  {i+1}. Playlist ID: {playlist_id}")
            print(f"     Link text: '{link_text}'") 
            print(f"     Extracted title: '{title}'")
            print()

if __name__ == "__main__":
    test_playlist_detection()