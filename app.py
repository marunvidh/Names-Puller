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
    page_title="ONE Championship Athlete Search",
    page_icon="🥊",
    layout="wide"
)

# ==========================================
# 1. VISUAL STYLING (Dark Theme & Centering)
# ==========================================
st.markdown("""
    <style>
    /* 1. FORCE DARK THEME */
    .stApp {
        background-color: #0e1117;
        color: #ffffff;
    }
    
    /* 2. CENTER TITLES & TEXT */
    h1 {
        text-align: center;
        color: #ffffff !important;
        font-family: sans-serif;
        font-weight: 700;
        padding-top: 1rem;
    }
    .subtext {
        text-align: center;
        color: #888888;
        font-size: 1rem;
        margin-bottom: 0.5rem;
    }
    .instruction-text {
        text-align: center;
        color: #bbbbbb;
        font-size: 0.9rem;
        margin-bottom: 1rem;
        font-style: italic;
    }
    
    /* 3. INPUT BOX STYLING (Text Area) */
    .stTextArea textarea {
        background-color: #262730 !important;
        color: #ffffff !important;
        border: 1px solid #444;
        border-radius: 4px;
        min-height: 68px; /* Fixed height for consistency */
    }
    .stTextArea textarea:focus {
        border-color: #ff4b4b;
        box-shadow: 0 0 0 1px #ff4b4b;
    }
    
    /* 4. BUTTON STYLING (Aligned with Text Area) */
    div.stButton > button:first-child {
        background-color: #ff4b4b;
        color: white;
        border: none;
        height: 68px; /* MATCH TEXT AREA HEIGHT EXACTLY */
        padding: 0 2rem;
        border-radius: 4px;
        font-weight: bold;
        width: 100%;
        margin-top: 0px; 
    }
    div.stButton > button:first-child:hover {
        background-color: #ff3333;
        color: white;
        border: none;
    }

    /* 5. TABLE STYLING */
    div[data-testid="stDataFrame"] {
        width: 100%;
        margin-top: 2rem;
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
    if "onefc.com/athletes/" in query: return query

    # Try Slug (Full Name)
    slug_full = query.lower().replace(" ", "-")
    url_full = f"https://www.onefc.com/athletes/{slug_full}/"
    if check_url_valid(url_full): return url_full

    # Try Slug (First Name only)
    first_name_slug = query.split()[0].lower()
    url_first = f"https://www.onefc.com/athletes/{first_name_slug}/"
    if check_url_valid(url_first): return url_first

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
    except: pass
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

st.title("ONE Championship Athlete Search")
st.markdown('<p class="subtext">Search for ONE Championship athletes and get their names in multiple languages</p>', unsafe_allow_html=True)
st.markdown('<p class="instruction-text">Enter athlete names (separate with commas or new lines):</p>', unsafe_allow_html=True)

# --- SEARCH ROW (Input + Button on same line) ---
c1, c2, c3, c4 = st.columns([1, 6, 1, 1])

with c2:
    # Changed to text_area to support line breaks
    input_raw = st.text_area("Search", height=68, placeholder="Paste list here...", label_visibility="collapsed")

with c3:
    # Button height is forced to match text area via CSS
    run_search = st.button("SEARCH")

# --- RESULTS AREA ---
if run_search:
    if not input_raw.strip():
        st.error("Please enter some names first.")
    else:
        # Split by comma OR newline to be safe
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
            # Force standard columns
            cols_standard = ["Name", "Nickname", "Country", "TH", "JP", "SC", "URL"]
            
            df = pd.DataFrame(master_data)
            for col in cols_standard:
                if col not in df.columns:
                    df[col] = ""
            df = df[cols_standard]
            
            # --- HARDCODE ICONS INTO HEADERS ---
            df = df.rename(columns={
                "Name": "👤 Name",
                "Nickname": "🥊 Nickname",
                "Country": "🏳️ Country",
                "TH": "🇹🇭 TH",
                "JP": "🇯🇵 JP",
                "SC": "🇨🇳 CN",
                "URL": "🔗 Link"
            })
            
            # --- DISPLAY TABLE (Auto Height & Clickable Links) ---
            st.dataframe(
                df,
                use_container_width=True,
                column_config={
                    "🔗 Link": st.column_config.LinkColumn(
                        "🔗 Link", 
                        display_text="View Profile" 
                    )
                },
                hide_index=True
            )
            
            csv = df.to_csv(index=False).encode('utf-8')
            
            # Centered Download Button
            dl_left, dl_center, dl_right = st.columns([1, 2, 1])
            with dl_center:
                st.download_button("Download CSV", csv, "onefc_global_names.csv", "text/csv", use_container_width=True)
        else:
            st.error("No valid data found.")
