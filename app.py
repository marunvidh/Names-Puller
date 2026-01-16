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

# ==========================================
# 0. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="ONE FC Name Scraper",
    page_icon="🥊",
    layout="wide"
)

# ==========================================
# 1. SETUP & UTILS
# ==========================================
# Headers to mimic a real browser to avoid 403 errors
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

@st.cache_resource
def get_session():
    """Creates a persistent requests session with retry logic."""
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

session = get_session()

def check_url_valid(url):
    """Checks if a URL returns a 200 OK status."""
    try:
        r = session.get(url, timeout=5)
        return r.status_code == 200
    except:
        return False

def search_onefc_link(query):
    """Finds the athlete profile URL based on a name or string."""
    query = query.strip()
    if not query: return None
    
    # 1. If user pasted a full URL, just return it
    if "onefc.com/athletes/" in query:
        return query

    # 2. Try guessing the "slug" (e.g. "Rodtang Jitmuangnon" -> "rodtang-jitmuangnon")
    slug_full = query.lower().replace(" ", "-")
    url_full = f"https://www.onefc.com/athletes/{slug_full}/"
    if check_url_valid(url_full):
        return url_full

    # 3. Try guessing just the first name (e.g. "Superlek")
    first_name_slug = query.split()[0].lower()
    url_first = f"https://www.onefc.com/athletes/{first_name_slug}/"
    if check_url_valid(url_first):
        return url_first

    # 4. Fallback: Use the ONE FC search bar
    search_url = f"https://www.onefc.com/?s={quote_plus(query)}"
    try:
        r = session.get(search_url, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # Look for links that contain "/athletes/"
        # We search inside the main content area to avoid footer/header links
        main_area = soup.find('main') or soup.body
        links = main_area.find_all('a', href=True)
        
        for link in links:
            href = link['href']
            # Ensure it's an athlete profile, not a news article about them
            if "/athletes/" in href and href.count('/') >= 4:
                return href
    except Exception as e:
        print(f"Search failed for {query}: {e}")
        pass
        
    return None

def extract_nickname_and_clean(raw_name):
    """Separates 'Name "Nickname" Surname' into parts."""
    if not raw_name or raw_name in ["Name not found", "Not Available"]:
        return "", ""

    # Regex to find text inside quotes "..." or “...”
    pattern = r'["“](.*?)["”]'
    match = re.search(pattern, raw_name)
    
    nickname = match.group(1) if match else ""
    
    # Remove the nickname from the full name
    clean_name = re.sub(pattern, '', raw_name)
    # Remove extra spaces
    clean_name = " ".join(clean_name.split())
    
    return clean_name, nickname

def fetch_athlete_data(url):
    """Fetches names from EN, TH, JP, and CN versions of the page."""
    if not url: return None
    
    # Extract slug from URL to build other language links
    parsed = urlparse(url)
    slug = parsed.path.strip('/').split('/')[-1].lower()
    
    # Define URL patterns for languages
    langs = {
        "EN": f"https://www.onefc.com/athletes/{slug}/",
        "TH": f"https://www.onefc.com/th/athletes/{slug}/",
        "JP": f"https://www.onefc.com/jp/athletes/{slug}/",
        "SC": f"https://www.onefc.com/cn/athletes/{slug}/" # Simplified Chinese
    }

    def fetch_single_name(link):
        try:
            r = session.get(link, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.content, 'html.parser')
                # Try finding the H1 tag (usually the athlete name)
                h1 = soup.find('h1')
                if h1:
                    return h1.get_text(strip=True)
        except: 
            pass
        return "" # Return empty string if failed

    # Fetch all languages concurrently to save time
    names_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_single_name, link): lang for lang, link in langs.items()}
        for future in concurrent.futures.as_completed(futures):
            names_map[futures[future]] = future.result()

    return {"url": url, "names_map": names_map}

# ==========================================
# 2. UI LAYOUT
# ==========================================

st.title("🥊 ONE FC Name Scraper")

st.markdown("""
**Instructions:**
1. Paste a list of names (e.g. *Rodtang, Superlek*) or ONEFC URLs.
2. Click **Generate Table**.
""")

# Input Area
input_raw = st.text_area(
    "Paste List (one per line)", 
    placeholder="Rodtang Jitmuangnon\nSuperlek Kiatmoo9\nhttps://www.onefc.com/athletes/stamp-fairtex/",
    height=150
)

# Button
if st.button("🚀 Generate Table", type="primary"):
    if not input_raw.strip():
        st.error("⚠️ Please paste some names first.")
    else:
        entries = [e.strip() for e in re.split(r'[,\n]', input_raw) if e.strip()]
        entries = list(set(entries)) # Remove duplicates
        
        master_data = []
        
        # UI Elements for progress
        progress_bar = st.progress(0)
        status_container = st.container()
        
        with status_container:
            for i, entry in enumerate(entries):
                st.text(f"Processing ({i+1}/{len(entries)}): {entry}...")
                
                # 1. Find URL
                url = search_onefc_link(entry)
                
                if url:
                    # 2. Fetch Data
                    data = fetch_athlete_data(url)
                    if data:
                        names = data['names_map']
                        
                        # 3. Clean Strings
                        en_clean, nickname = extract_nickname_and_clean(names.get('EN', ''))
                        th_clean, _ = extract_nickname_and_clean(names.get('TH', ''))
                        jp_clean, _ = extract_nickname_and_clean(names.get('JP', ''))
                        sc_clean, _ = extract_nickname_and_clean(names.get('SC', ''))
                        
                        row = {
                            "Search Term": entry,
                            "Name (Clean)": en_clean,
                            "Nickname": nickname,
                            "TH": th_clean,
                            "JP": jp_clean,
                            "SC": sc_clean,
                            "URL": url
                        }
                        master_data.append(row)
                
                # Update Progress
                progress_bar.progress((i + 1) / len(entries))
        
        # Final Output
        if master_data:
            st.success(f"✅ Finished! Found data for {len(master_data)} athletes.")
            
            df = pd.DataFrame(master_data)
            # Reorder columns
            cols = ["Name (Clean)", "Nickname", "TH", "JP", "SC", "URL"]
            df = df[cols]
            
            st.dataframe(df, use_container_width=True)
            
            # CSV Download
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name='onefc_names.csv',
                mime='text/csv',
            )
        else:
            st.error("❌ No data found. The website might be blocking requests or the names are misspelled.")
