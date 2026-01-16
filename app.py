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
    page_title="ONEFC Global Name Search",
    page_icon="🥊",
    layout="wide"
)

# ==========================================
# 1. VISUAL STYLING
# ==========================================
st.markdown("""
    <style>
    /* Remove extra header padding */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    header {visibility: hidden;}
    
    /* Center the title */
    h1 {
        text-align: center;
        font-size: 2.5rem;
        margin-bottom: 0.5rem;
    }
    
    /* Center the subtext */
    .subtext {
        text-align: center;
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 1.5rem;
    }

    /* Button Styling */
    div.stButton > button:first-child {
        width: 100%;
        font-weight: bold;
        border-radius: 4px;
        margin-top: 10px;
    }
    
    /* Input Styling - Minimalist */
    .stTextArea textarea {
        font-size: 14px;
        color: #333;
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
    
    if "onefc.com/athletes/" in query:
        return query

    # Try Slug (Full Name)
    slug_full = query.lower().replace(" ", "-")
    url_full = f"https://www.onefc.com/athletes/{slug_full}/"
    if check_url_valid(url_full):
        return url_full

    # Try Slug (First Name only)
    first_name_slug = query.split()[0].lower()
    url_first = f"https://www.onefc.com/athletes/{first_name_slug}/"
    if check_url_valid(url_first):
        return url_first

    # Search Fallback
    search_url = f"https://www.onefc.com/?s={quote_plus(query)}"
    try:
        r = session.get(search_url, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        main_area = soup.find('main') or soup.find('div', id='content') or soup.body
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

    def fetch_page_content(link, is_main=False):
        data = {"name": "", "country": ""}
        try:
            r = session.get(link, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.content, 'html.parser')
                h1 = soup.find('h1')
                if h1: data["name"] = h1.get_text(strip=True)
                
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

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
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
        "country": results["EN"]["country"]
    }

# ==========================================
# 3. UI LAYOUT (TOP CENTER ALIGN)
# ==========================================

st.title("ONEFC Global Name Search")
st.markdown('<p class="subtext">Input Names to start..</p>', unsafe_allow_html=True)

# Center the search bar using columns
# col1 (Spacer), col2 (Content), col3 (Spacer)
left, center, right = st.columns([1, 2, 1])

with center:
    input_raw = st.text_area(
        "Search", 
        value="", 
        height=68, # Minimal height (approx 1 line appearance)
        placeholder="", # Removed placeholder
        label_visibility="collapsed"
    )
    
    run_search = st.button("SEARCH", type="primary")

if run_search:
    if not input_raw.strip():
        st.error("Please paste some names first.")
    else:
        entries = [e.strip() for e in re.split(r'[,\n]', input_raw) if e.strip()]
        entries = list(set(entries))
        
        master_data = []
        retry_queue = []
        
        progress_bar = st.progress(0)
        status = st.empty()
        
        # --- PHASE 1 ---
        total_items = len(entries)
        for i, entry in enumerate(entries):
            status.text(f"Scanning: {entry}...")
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

        # --- PHASE 2 (Retry) ---
        if retry_queue:
            status.text(f"Retrying {len(retry_queue)} items...")
            time.sleep(1)
            for i, entry in enumerate(retry_queue):
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

        status.empty() # Clear status
        
        if master_data:
            # Force standard columns even if empty
            cols_standard = ["Name", "Nickname", "Country", "TH", "JP", "SC", "URL"]
            
            df = pd.DataFrame(master_data)
            
            # Ensure all columns exist (fill missing with empty strings)
            for col in cols_standard:
                if col not in df.columns:
                    df[col] = ""
            
            # Reorder
            df = df[cols_standard]
            
            st.success(f"Processing Complete ({len(master_data)} found)")
            
            # Display Table (Full Width)
            st.dataframe(
                df, 
                use_container_width=True, 
                height=600
            )
            
            csv = df.to_csv(index=False).encode('utf-8')
            
            # Center the download button
            dl_col1, dl_col2, dl_col3 = st.columns([1, 2, 1])
            with dl_col2:
                st.download_button("Download CSV", csv, "onefc_global_names.csv", "text/csv", use_container_width=True)
        else:
            st.error("No valid data found.")
