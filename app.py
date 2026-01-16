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
    layout="wide"  # Changed to "wide" to let the table adapt to screen size
)

# ==========================================
# 1. VISUAL STYLING (Clean & Adaptive)
# ==========================================
st.markdown("""
    <style>
    /* 1. Remove extra top padding */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    header {visibility: hidden;}
    
    /* 2. Button Styling */
    div.stButton > button:first-child {
        width: 100%;
        font-weight: bold;
    }
    
    /* 3. Table Styling */
    div[data-testid="stDataFrame"] {
        width: 100%;
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
# 3. UI LAYOUT
# ==========================================

st.title("ONE Names Extractor")

# Using a container to limit input width so it doesn't stretch too wide
with st.container():
    col1, col2 = st.columns([1, 1])
    with col1:
        st.write("Enter a list of athlete names or profile URLs below.")
        input_raw = st.text_area(
            "Input Data", 
            placeholder="Rodtang Jitmuangnon\nSuperlek Kiatmoo9\nhttps://www.onefc.com/athletes/stamp-fairtex/",
            height=200,
            label_visibility="collapsed"
        )
        if st.button("Generate Table", type="primary"):
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
                    st.success(f"Processing Complete ({len(master_data)} found)")
                    df = pd.DataFrame(master_data)
                    
                    # Define desired columns
                    cols_to_keep = ["Name", "Nickname", "Country", "TH", "JP", "SC", "URL"]
                    
                    # Check if columns are empty and drop them if so
                    final_cols = []
                    for col in cols_to_keep:
                        if col in df.columns:
                            # If ANY row has content, keep the column.
                            # We check if empty string or None exist
                            has_data = df[col].replace("", pd.NA).notna().any()
                            if has_data:
                                final_cols.append(col)
                    
                    df_final = df[final_cols]

                    # Display Table (Full Width + Fixed Height)
                    st.dataframe(
                        df_final, 
                        use_container_width=True, 
                        height=600
                    )
                    
                    csv = df_final.to_csv(index=False).encode('utf-8')
                    st.download_button("Download CSV", csv, "onefc_data.csv", "text/csv")
                else:
                    st.error("No valid data found.")
