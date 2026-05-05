#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse

def bypass_consent_and_get_playlists():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    session = requests.Session()
    
    # First, visit the main YouTube page to establish session
    try:
        main_resp = session.get("https://www.youtube.com/", headers=headers, timeout=15)
        print(f"Main page response: {main_resp.status_code}")
    except Exception as e:
        print(f"Could not access main page: {e}")

    # Try to access the playlists page
    url = "https://www.youtube.com/@revive/playlists"
    
    try:
        response = session.get(url, headers=headers, timeout=30)
        print(f"Initial request status: {response.status_code}")
        print(f"Initial URL: {response.url}")
        
        # Check if we're on a consent page
        if "consent.youtube.com" in response.url or "consent" in response.text.lower():
            print("On consent page, attempting to bypass...")

            # Extract the continue URL from the consent page
            continue_match = re.search(r'continue=([^&\'\"<>]*)', response.text)
            if continue_match:
                continue_url_encoded = continue_match.group(1)
                continue_url = urllib.parse.unquote(continue_url_encoded)

                print(f"Found continue URL: {continue_url}")

                # Try to access the page with consent accepted parameters directly
                # Construct the accept URL with the correct parameters
                accept_url = f"https://consent.youtube.com/m?gl=US&hl=en&m=0&pc=yt&continue={continue_url_encoded}"

                # Make a GET request to accept consent and continue
                accept_response = session.get(accept_url, headers=headers, timeout=30)

                print(f"Accept response status: {accept_response.status_code}")
                print(f"Accept final URL: {accept_response.url}")

                # If we're still on consent page, try a different approach
                if "consent" in accept_response.url or "consent" in accept_response.text.lower():
                    # Try with different parameters that might work
                    alt_continue_url = continue_url.replace("cbrd=1", "").replace("?&", "?").rstrip("&")
                    alt_continue_encoded = urllib.parse.quote(alt_continue_url, safe='')

                    alt_accept_url = f"https://consent.youtube.com/m?gl=US&hl=en&m=0&pc=yt&src=1&x=6&bl=boq_identityfrontenduiserver_20260114.02_p0&continue={alt_continue_encoded}"

                    alt_accept_response = session.get(alt_accept_url, headers=headers, timeout=30)
                    print(f"Alt accept response status: {alt_accept_response.status_code}")
                    print(f"Alt accept final URL: {alt_accept_response.url}")

                    if "consent" not in alt_accept_response.url and "consent" not in alt_accept_response.text.lower():
                        print("Successfully bypassed consent page with alternative approach!")
                        process_page_content(alt_accept_response.text)
                        return
                    else:
                        # If still on consent page, try to access the original URL with cookies from session
                        final_response = session.get(continue_url, headers=headers, timeout=30)
                        print(f"Session-based request status: {final_response.status_code}")
                        print(f"Session-based URL: {final_response.url}")

                        if "consent" not in final_response.url and "consent" not in final_response.text.lower():
                            print("Successfully bypassed consent page using session cookies!")
                            process_page_content(final_response.text)
                            return
                        else:
                            print("Still on consent page after all attempts")
                            process_page_content(final_response.text)
                            return
                else:
                    print("Successfully bypassed consent page!")
                    process_page_content(accept_response.text)
                    return
            else:
                print("Could not find continue URL in consent page")
                process_page_content(response.text)
        else:
            print("No consent redirect, processing page normally")
            process_page_content(response.text)
    
    except Exception as e:
        print(f"Error accessing page: {e}")
        import traceback
        traceback.print_exc()

def process_page_content(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Look for all links that contain playlist
    all_links = soup.find_all('a', href=re.compile(r'/playlist\?list='))
    print(f"Found {len(all_links)} links with playlist IDs")
    
    for i, link in enumerate(all_links[:20]):  # First 20 links
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
    bypass_consent_and_get_playlists()