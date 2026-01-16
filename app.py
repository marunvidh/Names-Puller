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
    page_title="ONE Names Extractor",
    page_icon="🥊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==========================================
# 1. VISUAL STYLING (ONE CHAMPIONSHIP THEME)
# ==========================================
# This block injects Custom CSS to match the images provided
st.markdown("""
    <style>
    /* MAIN BACKGROUND */
    .stApp {
        background-color: #1a1a1a;
        color: #ffffff;
    }
    
    /* INPUT TEXT AREA */
    .stTextArea textarea {
        background-color: #2d2d2d;
        color: #ffffff;
        border: 1px solid #444;
        border-radius: 4px;
    }
    .stTextArea textarea:focus {
        border-color: #fece00;
        box-shadow: 0 0 5px #fece00;
    }
    
    /* PRIMARY BUTTON (Gold/Yellow) */
    div.stButton > button:first-child {
        background-color: #fece00;
        color: #000000;
        font-weight: 800;
        font-size: 16px;
        text-transform: uppercase;
        border-radius: 2px;
        border: none;
        padding: 10px 24px;
        transition: all 0.2s ease;
    }
    div.stButton > button:first-child:hover {
        background-color: #e6b800;
        color: #000000;
        border: none;
        transform: scale(1.02);
    }
    
    /* DOWNLOAD BUTTON (Outline/Dark) */
    div.stDownloadButton > button:first-child {
        background-color: transparent;
        color: #fece00;
        border: 2px solid #fece00;
        font-weight: 700;
        text-transform: uppercase;
    }
    div.stDownloadButton > button:first-child:hover {
        background-color: #fece00;
        color: #000000;
    }

    /* HEADERS */
    h1, h2, h3 {
        color: #ffffff !important;
        font-family: 'Arial Black', sans-serif;
        text-transform: uppercase;
        letter-spacing: -0.5px;
    }
    
    /* DATAFRAME / TABLE */
    div[data-testid="stDataFrame"] {
        background-color: #2d2d2d;
        border: 1px solid #444;
    }

    /* PROGRESS BAR */
    .stProgress > div > div > div > div {
        background-color: #fece00;
    }
    
    /* ALERTS/SUCCESS */
    .stAlert {
        background-color: #2d2d2d;
        color: #fff;
        border: 1px solid #444;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. NETWORK & LOGIC
# ==========================================
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
    try:
        r = session.get(url, timeout=5)
        return r.status_code == 200
    except:
        return False

def search_onefc_link(query):
    query = query.strip()
    if not query: return None
    
    # 1. Direct URL check
    if "onefc.com/athletes/" in query:
        return query

    # 2. Slug Guessing (Full Name)
    slug_full = query.lower().replace(" ", "-")
    url_full = f"https://www.onefc.com/athletes/{slug_full}/"
    if check_url_valid(url_full):
        return url_full

    # 3. Slug Guessing (First Name only)
    first_name_slug = query.split()[0].lower()
    url_first = f"https://www.onefc.com/athletes/{first_name_slug}/"
    if check_url_valid(url_first):
        return url_first

    # 4. Site Search Fallback
    search_url = f"https://www.onefc.com/?s={quote_plus(query)}"
    try:
        r = session.get(search_url, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        main_area = soup.find('main') or soup.body
        links = main_area.find_all('a', href=True)
        for link in links:
            href = link['href']
            if "/athletes/" in href and href.count('/') >= 4:
                return href
    except:
        pass
    return None

def extract_nickname_and_clean(raw_name):
    if not raw_name or raw_name in ["Name not found", "Not Available"]:
        return "", ""
    pattern = r'["“](.*?)["”]'
    match = re.search(pattern, raw_name)
    nickname = match.group(1) if match else ""
    clean_name = re.sub(pattern, '', raw_name)
    clean_name = " ".join(clean_name.split())
    return clean_name, nickname

def fetch_athlete_data(url):
    if not url: return None
    parsed = urlparse(url)
    slug = parsed.path.strip('/').split('/')[-1].lower()
    
    langs = {
        "EN": f"https://www.onefc.com/athletes/{slug}/",
        "TH": f"https://www.onefc.com/th/athletes/{slug}/",
        "JP": f"https://www.onefc.com/jp/athletes/{slug}/",
        "SC": f"https://www.onefc.com/cn/athletes/{slug}/"
    }

    # Helper to fetch name and country (only from English)
    def fetch_page_content(link, is_main=False):
        data = {"name": "", "country": ""}
        try:
            r = session.get(link, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.content, 'html.parser')
                
                # Get Name
                h1 = soup.find('h1')
                if h1: data["name"] = h1.get_text(strip=True)
                
                # Get Country (Only needed for English page usually)
                if is_main:
                    attr_blocks = soup.select("div.attr")
                    for block in attr_blocks:
                        title = block.find("h5", class_="title")
                        if title and "country" in title.get_text(strip=True).lower():
                            val = block.find("div", class_="value")
                            if val: data["country"] = val.get_text(strip=True)
                            break
        except: pass
        return data

    # Concurrently fetch all languages
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # Submit tasks
        future_to_lang = {
            executor.submit(fetch_page_content, link, lang=="EN"): lang 
            for lang, link in langs.items()
        }
        
        for future in concurrent.futures.as_completed(future_to_lang):
            lang = future_to_lang[future]
            results[lang] = future.result()

    return {
        "url": url,
        "names_map": {k: v["name"] for k, v in results.items()},
        "country": results["EN"]["country"] # Take country from English page
    }

# ==========================================
# 3. UI LAYOUT
# ==========================================

# Add a Logo or Branding Header (Optional, using text for now)
st.markdown("<h1 style='color: #fece00; font-size: 3em;'>ATHLETE DATA EXTRACTOR</h1>", unsafe_allow_html=True)
st.markdown("Enter a list of athlete names or profile URLs below to extract multilingual data.", unsafe_allow_html=True)

st.write("") # Spacer

input_raw = st.text_area(
    "INPUT DATA (One per line)", 
    placeholder="Rodtang Jitmuangnon\nSuperlek Kiatmoo9\nhttps://www.onefc.com/athletes/stamp-fairtex/",
    height=200
)

st.write("") # Spacer

# Using columns to center the button if desired, or keep it full width
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    search_clicked = st.button("SEARCH ATHLETES", type="primary", use_container_width=True)

if search_clicked:
    if not input_raw.strip():
        st.error("⚠️ Please paste some names first.")
    else:
        entries = [e.strip() for e in re.split(r'[,\n]', input_raw) if e.strip()]
        entries = list(set(entries))
        
        master_data = []
        retry_queue = []
        
        progress_bar = st.progress(0)
        status = st.empty()
        
        # --- PHASE 1: INITIAL PASS ---
        total_items = len(entries)
        
        for i, entry in enumerate(entries):
            status.markdown(f"**SCANNING:** `{entry}`")
            url = search_onefc_link(entry)
            
            success = False
            if url:
                data = fetch_athlete_data(url)
                if data and data['names_map'].get('EN'):
                    names = data['names_map']
                    en_clean, nickname = extract_nickname_and_clean(names.get('EN', ''))
                    th_clean, _ = extract_nickname_and_clean(names.get('TH', ''))
                    jp_clean, _ = extract_nickname_and_clean(names.get('JP', ''))
                    sc_clean, _ = extract_nickname_and_clean(names.get('SC', ''))
                    
                    master_data.append({
                        "Name": en_clean,
                        "Nickname": nickname,
                        "Country": data['country'],
                        "TH": th_clean,
                        "JP": jp_clean,
                        "SC": sc_clean,
                        "URL": url
                    })
                    success = True
            
            if not success:
                retry_queue.append(entry)
            
            progress_bar.progress((i + 1) / total_items)

        # --- PHASE 2: RETRY PASS ---
        if retry_queue:
            status.markdown(f"⏳ **RETRYING {len(retry_queue)} FAILED ITEMS...**")
            time.sleep(1) # Give server a tiny break
            
            for i, entry in enumerate(retry_queue):
                status.markdown(f"**RETRY SCAN:** `{entry}`")
                
                # Try search again (sometimes effective if network blipped)
                url = search_onefc_link(entry)
                
                if url:
                    data = fetch_athlete_data(url)
                    if data and data['names_map'].get('EN'):
                        names = data['names_map']
                        en_clean, nickname = extract_nickname_and_clean(names.get('EN', ''))
                        th_clean, _ = extract_nickname_and_clean(names.get('TH', ''))
                        jp_clean, _ = extract_nickname_and_clean(names.get('JP', ''))
                        sc_clean, _ = extract_nickname_and_clean(names.get('SC', ''))
                        
                        master_data.append({
                            "Name": en_clean,
                            "Nickname": nickname,
                            "Country": data['country'],
                            "TH": th_clean,
                            "JP": jp_clean,
                            "SC": sc_clean,
                            "URL": url
                        })

        status.success("✅ **PROCESSING COMPLETE**")
        
        # --- DISPLAY ---
        if master_data:
            df = pd.DataFrame(master_data)
            # Reorder for better view
            df = df[["Name", "Nickname", "Country", "TH", "JP", "SC", "URL"]]
            
            st.markdown("### EXTRACTED DATA")
            st.dataframe(df, use_container_width=True)
            
            csv = df.to_csv(index=False).encode('utf-8')
            
            st.write("")
            st.download_button(
                "DOWNLOAD CSV FILE", 
                csv, 
                "onefc_data.csv", 
                "text/csv",
                use_container_width=True
            )
        else:
            st.error("No valid data found. Please check spelling or try direct URLs.")
