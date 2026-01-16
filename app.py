import streamlit as st
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus
import pandas as pd
import time
import re
import concurrent.futures

# --- CONFIGURATION & ASSETS ---
st.set_page_config(page_title="ONE Athlete Profile", page_icon="🥊", layout="wide")

# Headers to mimic a real browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Country Flags Dictionary (Same as before)
COUNTRY_FLAGS = {
    "Thailand": "🇹🇭", "Philippines": "🇵🇭", "Japan": "🇯🇵", "China": "🇨🇳", "Singapore": "🇸🇬",
    "United States": "🇺🇸", "Malaysia": "🇲🇾", "Brazil": "🇧🇷", "India": "🇮🇳", "Russia": "🇷🇺",
    "South Korea": "🇰🇷", "Vietnam": "🇻🇳", "France": "🇫🇷", "United Kingdom": "🇬🇧",
    "Australia": "🇦🇺", "Germany": "🇩🇪", "Netherlands": "🇳🇱", "Italy": "🇮🇹", "Canada": "🇨🇦",
    "Myanmar": "🇲🇲", "Indonesia": "🇮🇩", "Kazakhstan": "🇰🇿", "Ukraine": "🇺🇦", "Turkey": "🇹🇷",
    "Iran": "🇮🇷", "Belarus": "🇧🇾", "Sweden": "🇸🇪", "Norway": "🇳🇴", "Denmark": "🇩🇰",
    "Finland": "🇫🇮", "Poland": "🇵🇱", "Mongolia": "🇲🇳", "Spain": "🇪🇸", "Portugal": "🇵🇹",
    "Cambodia": "🇰🇭", "Laos": "🇱🇦", "Taiwan": "🇹🇼", "Hong Kong SAR China": "🇭🇰",
    "Algeria": "🇩🇿", "Morocco": "🇲🇦", "South Africa": "🇿🇦", "Argentina": "🇦🇷",
    # Add other flags as needed...
}

# --- NETWORK SESSION SETUP ---
def get_session():
    """
    Creates a requests session with retries and browser headers.
    This helps prevent 'No Results' due to network blips or rate limits.
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # Retry strategy: retry 3 times on connection errors or 5xx/429 server errors
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=1, # Wait 1s, 2s, 4s between retries
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Initialize session
session = get_session()

# --- BACKEND LOGIC ---

@st.cache_data(ttl=3600)
def search_onefc_link(query):
    """
    Smart Search:
    1. Checks if input is already a URL.
    2. Tries to guess the URL (e.g. "Rodtang" -> /athletes/rodtang/).
    3. If guess fails, searches ONEFC.com search page for the link.
    """
    query = query.strip()
    if not query:
        return None

    # 1. Is it already a link?
    if "onefc.com/athletes/" in query:
        return query

    # 2. Try Direct Guess (Fastest)
    # Convert "Rodtang Jitmuangnon" -> "rodtang-jitmuangnon"
    slug = query.lower().replace(" ", "-")
    direct_url = f"https://www.onefc.com/athletes/{slug}/"
    
    try:
        # Use HEAD request to check if page exists without downloading body
        r = session.head(direct_url, timeout=5)
        if r.status_code == 200:
            return direct_url
    except:
        pass # If error, move to search strategy

    # 3. Search the Website (Slower but Smarter)
    # This finds names where the slug doesn't match the name exactly
    search_url = f"https://www.onefc.com/?s={quote_plus(query)}"
    try:
        r = session.get(search_url, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # Find all links that point to an athlete profile
        # We filter for hrefs containing "/athletes/" and avoid generic index pages
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            # ONE FC structure: /athletes/slug/ (3 slashes after domain)
            if "/athletes/" in href and href.count('/') >= 4:
                return href
    except Exception as e:
        print(f"Search error: {e}")
        
    return None

def fetch_athlete_data(url):
    """
    Fetches flags and localized names for a specific athlete URL.
    """
    if not url:
        return None
        
    # Extract slug
    parsed = urlparse(url)
    # Handle trailing slashes carefully
    path_parts = parsed.path.strip('/').split('/')
    if not path_parts:
        return None
    slug = path_parts[-1].lower()
    
    langs = {
        "English": f"https://www.onefc.com/athletes/{slug}/",
        "Thai": f"https://www.onefc.com/th/athletes/{slug}/",
        "Japanese": f"https://www.onefc.com/jp/athletes/{slug}/",
        "Chinese": f"https://www.onefc.com/cn/athletes/{slug}/"
    }

    # Helper for concurrent fetching
    def fetch_single_lang(lang_url):
        try:
            r = session.get(lang_url, timeout=10)
            if r.status_code != 200:
                return "Not Available"
            soup = BeautifulSoup(r.content, 'html.parser')
            h1 = soup.find('h1', {'class': 'use-letter-spacing-hint my-4'}) or soup.find('h1')
            return h1.get_text(strip=True) if h1 else "Name not found"
        except:
            return "Error"

    # 1. Fetch Nationality (English page)
    countries = []
    try:
        r = session.get(langs["English"], timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        attr_blocks = soup.select("div.attr")
        for block in attr_blocks:
            title = block.find("h5", class_="title")
            if title and "country" in title.get_text(strip=True).lower():
                value = block.find("div", class_="value")
                if value:
                    countries = [a.get_text(strip=True) for a in value.find_all("a")]
                break
    except:
        countries = ["Unknown"]

    # 2. Fetch Names Concurrently (Speed boost)
    names_data = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_lang = {executor.submit(fetch_single_lang, link): lang for lang, link in langs.items()}
        for future in concurrent.futures.as_completed(future_to_lang):
            lang = future_to_lang[future]
            names_data[lang] = future.result()

    # Format Flags
    flags = [COUNTRY_FLAGS.get(c, "🏳️") for c in countries]
    nationality_str = " ".join(f"{f} {c}" for c, f in zip(countries, flags))

    return {
        "url": url,
        "nationality": nationality_str,
        "names": names_data,
        "original_slug": slug
    }

# --- FRONTEND UI ---

st.title("🥊 ONE Athlete Profile")

with st.expander("ℹ️ How to use", expanded=False):
    st.markdown("""
    **Paste names or links below.**
    - Separate multiple athletes using **Commas (`,`)** or **New Lines (Enter)**.
    - You can type Full Names (e.g., `Rodtang Jitmuangnon`), Slugs (`rodtang`), or URLs.
    """)

# Input Area
default_text = "https://www.onefc.com/athletes/rodtang/\nSuperlek Kiatmoo9, John Lineker"
raw_input = st.text_area("Input Data:", value=default_text, height=150)

if st.button("🔍 Search & Process"):
    if not raw_input.strip():
        st.warning("Please enter some names or links.")
    else:
        # Split by Newline OR Comma
        # re.split(r'[,\n]', text) handles both separators
        entries = [e.strip() for e in re.split(r'[,\n]', raw_input) if e.strip()]
        
        # Remove duplicates
        entries = list(set(entries))
        
        st.write(f"Processing {len(entries)} athletes...")
        progress_bar = st.progress(0)
        
        for idx, entry in enumerate(entries):
            # 1. Search
            found_url = search_onefc_link(entry)
            
            if found_url:
                # 2. Fetch
                data = fetch_athlete_data(found_url)
                
                if data:
                    # 3. Display Result Card
                    with st.expander(f"✅ {data['names'].get('English', entry).upper()}", expanded=True):
                        c1, c2 = st.columns([1, 2])
                        with c1:
                            st.markdown(f"**Nationality:**")
                            st.info(data['nationality'])
                            st.markdown(f"[🔗 Open Profile]({data['url']})")
                        with c2:
                            df = pd.DataFrame(data['names'].items(), columns=["Language", "Name"])
                            st.dataframe(df, hide_index=True, use_container_width=True)
                else:
                    st.error(f"❌ Found link but failed to parse: {entry}")
            else:
                st.warning(f"⚠️ Could not find athlete: '{entry}' (Try using the exact full name or URL)")
            
            # Update progress
            progress_bar.progress((idx + 1) / len(entries))
            time.sleep(0.2) # Small buffer to be polite to the server

        st.success("All done!")
