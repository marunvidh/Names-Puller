import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime
import hashlib

st.set_page_config(page_title="ONE Athlete Search", page_icon="🥊", layout="wide")

if 'search_history' not in st.session_state:
    st.session_state.search_history = []
if 'cache' not in st.session_state:
    st.session_state.cache = {}

CACHE_DURATION = 3600
MAX_WORKERS = 4
REQUEST_TIMEOUT = 10
RATE_LIMIT_DELAY = 0.1

COUNTRY_FLAGS = {
    "Thailand": "🇹🇭", "Philippines": "🇵🇭", "Japan": "🇯🇵", "China": "🇨🇳",
    "Singapore": "🇸🇬", "United States": "🇺🇸", "Malaysia": "🇲🇾", "Brazil": "🇧🇷",
    "India": "🇮🇳", "Russia": "🇷🇺", "South Korea": "🇰🇷", "Vietnam": "🇻🇳",
    "France": "🇫🇷", "Canada": "🇨🇦", "United Kingdom": "🇬🇧", "Australia": "🇦🇺",
    "Indonesia": "🇮🇩", "Myanmar": "🇲🇲", "Germany": "🇩🇪", "Netherlands": "🇳🇱",
    "Argentina": "🇦🇷", "Colombia": "🇨🇴", "Kazakhstan": "🇰🇿", "Ukraine": "🇺🇦",
    "New Zealand": "🇳🇿", "Spain": "🇪🇸", "Poland": "🇵🇱", "Egypt": "🇪🇬",
    "Morocco": "🇲🇦", "Algeria": "🇩🇿", "Taiwan": "🇹🇼", "Mongolia": "🇲🇳",
}

LANGUAGES = {
    "English": {"code": "", "flag": "🇬🇧"},
    "Thai": {"code": "th", "flag": "🇹🇭"},
    "Japanese": {"code": "jp", "flag": "🇯🇵"},
    "Chinese": {"code": "cn", "flag": "🇨🇳"}
}

def extract_nickname_and_clean(full_name: str):
    """
    Extracts the nickname (between “curly” or "straight" quotes) and returns (clean_name, nickname).
    Example: 'Fabricio “Wonder Boy” Andrade' -> ('Fabricio Andrade', 'Wonder Boy')
    """
    if not full_name or full_name == "Not found":
        return full_name, "-"

    text = full_name.strip()

    # Try curly quotes first: “ … ”
    m = re.search(r'“([^”]+)”', text)
    if not m:
        # Fall back to straight double quotes: " … "
        m = re.search(r'"([^"]+)"', text)

    if m:
        nickname = m.group(1).strip()
        # Remove the matched portion and normalize spaces
        cleaned = (text[:m.start()] + text[m.end():]).strip()
        cleaned = re.sub(r'\s{2,}', ' ', cleaned)  # collapse double spaces if any
        cleaned = cleaned.replace(" ,", ",").strip()
        if not cleaned:
            cleaned = full_name  # safety fallback
        return cleaned, nickname if nickname else "-"
    else:
        return text, "-"

class AthleteSearcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_cache_key(self, name):
        return hashlib.md5(name.lower().strip().encode()).hexdigest()
    
    def is_cache_valid(self, cache_entry):
        if not cache_entry:
            return False
        cache_time = cache_entry.get('timestamp', 0)
        return (time.time() - cache_time) < CACHE_DURATION
    
    def name_to_slug_variations(self, name):
        name = name.strip().lower()
        name = re.sub(r'[^\w\s-]', '', name)
        
        variations = []
        full_slug = re.sub(r'\s+', '-', name)
        variations.append(full_slug)
        
        parts = name.split()
        if parts:
            variations.append(parts[0])
            if len(parts) > 1:
                variations.append(parts[-1])
                variations.append(f"{parts[0]}-{parts[-1]}")
        
        variations.append(''.join(parts))
        return list(dict.fromkeys(variations))
    
    # No Streamlit caching decorators to avoid UnhashableParamError
    def fetch_athlete_page(self, slug):
        url = f"https://www.onefc.com/athletes/{slug}/"
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return slug, response.content
        except Exception as e:
            st.warning(f"Network error for {slug}: {str(e)}", icon="⚠️")
        return None, None
    
    def find_athlete(self, name):
        cache_key = self.get_cache_key(name)
        if cache_key in st.session_state.cache:
            cache_entry = st.session_state.cache[cache_key]
            if self.is_cache_valid(cache_entry):
                return cache_entry['slug'], cache_entry['content']
        
        slugs = self.name_to_slug_variations(name)
        for slug in slugs:
            found_slug, content = self.fetch_athlete_page(slug)
            if found_slug and content:
                st.session_state.cache[cache_key] = {
                    'slug': found_slug,
                    'content': content,
                    'timestamp': time.time()
                }
                return found_slug, content
        return None, None
    
    def parse_nationality(self, content):
        try:
            soup = BeautifulSoup(content, 'html.parser')
            attr_blocks = soup.select("div.attr")
            for block in attr_blocks:
                title = block.find("h5", class_="title")
                if title and "country" in title.get_text(strip=True).lower():
                    value = block.find("div", class_="value")
                    if value:
                        countries = [a.get_text(strip=True) for a in value.find_all("a")]
                        if countries:
                            return countries
            return ["Not found"]
        except Exception as e:
            return [f"Error: {str(e)}"]
    
    def fetch_localized_name(self, slug, lang_code=""):
        """
        Returns (clean_name_without_nickname, nickname_or_dash)
        """
        if lang_code:
            url = f"https://www.onefc.com/{lang_code}/athletes/{slug}/"
        else:
            url = f"https://www.onefc.com/athletes/{slug}/"
        
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                h1 = soup.find('h1', {'class': 'use-letter-spacing-hint my-4'}) or soup.find('h1')
                if h1:
                    full = h1.get_text(strip=True)
                    return extract_nickname_and_clean(full)
        except:
            pass
        return "Not found", "-"
    
    def fetch_all_names(self, slug):
        """
        Returns dict:
        {
          "English": {"name": "<clean>", "nickname": "<nick|->"},
          "Thai": {...}, ...
        }
        """
        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_lang = {
                executor.submit(self.fetch_localized_name, slug, lang_data['code']): lang
                for lang, lang_data in LANGUAGES.items()
            }
            for future in as_completed(future_to_lang):
                lang = future_to_lang[future]
                try:
                    clean_name, nick = future.result()
                    results[lang] = {"name": clean_name, "nickname": nick}
                except:
                    results[lang] = {"name": "Error", "nickname": "-"}
        return results

def search_athletes(names, searcher):
    all_results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, name in enumerate(names):
        progress = (idx + 1) / len(names)
        progress_bar.progress(progress)
        status_text.text(f"🔍 Searching: {name} ({idx + 1}/{len(names)})")
        
        slug, content = searcher.find_athlete(name)
        
        if slug and content:
            countries = searcher.parse_nationality(content)
            flags = [COUNTRY_FLAGS.get(c, "🏳️") for c in countries]
            nationality_str = " / ".join(f"{f} {c}" for c, f in zip(countries, flags))
            name_data = searcher.fetch_all_names(slug)

            # Consolidated nickname: first available (prefer English), else from any lang
            nickname = "-"
            # prefer English if present
            if "English" in name_data and name_data["English"]["nickname"] not in ("-", "", "Not found"):
                nickname = name_data["English"]["nickname"]
            else:
                # fall back to first non-empty nickname among other languages
                for lang in LANGUAGES.keys():
                    if lang in name_data and name_data[lang]["nickname"] not in ("-", "", "Not found"):
                        nickname = name_data[lang]["nickname"]
                        break

            # Build result row with cleaned names only (no nicknames)
            result = {
                "Query": name,
                "Status": "✅",
                "Nickname": nickname,
                "Nationality": nationality_str,
                **{
                    f"{lang} {LANGUAGES[lang]['flag']}": name_data.get(lang, {}).get("name", "N/A")
                    for lang in LANGUAGES.keys()
                },
                "Profile": f"https://www.onefc.com/athletes/{slug}/"
            }
        else:
            result = {
                "Query": name,
                "Status": "❌",
                "Nickname": "-",
                "Nationality": "-",
                **{f"{lang} {LANGUAGES[lang]['flag']}": "-" for lang in LANGUAGES.keys()},
                "Profile": "-"
            }
        
        all_results.append(result)
        if idx < len(names) - 1:
            time.sleep(RATE_LIMIT_DELAY)
    
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(all_results)

def main():
    st.title("🥊 ONE Championship Athlete Search")
    st.markdown("Search for ONE Championship athletes and get their names in multiple languages")
    
    with st.sidebar:
        st.header("📖 Instructions")
        st.markdown("""
        1. Enter athlete names (comma-separated)
        2. Click **Search Athletes**
        3. View results with names in 4 languages
        4. Download results as CSV
        """)
        
        if st.session_state.cache:
            st.divider()
            st.info(f"📦 Cache: {len(st.session_state.cache)} athletes stored")
            if st.button("Clear Cache"):
                st.session_state.cache.clear()
                st.rerun()
    
    col1, col2 = st.columns([4, 1])
    
    with col1:
        names_input = st.text_area(
            "Enter athlete names (separate with commas):",
            value="Rodtang, Demetrious Johnson, Angela Lee",
            height=80,
            help="Enter one or more athlete names separated by commas"
        )
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        search_button = st.button("🔍 Search Athletes", type="primary", use_container_width=True)
    
    if search_button:
        names = [name.strip() for name in names_input.split(',') if name.strip()]
        
        if not names:
            st.error("⚠️ Please enter at least one athlete name")
        else:
            searcher = AthleteSearcher()
            
            with st.spinner("Searching..."):
                df = search_athletes(names, searcher)
            
            st.session_state.search_history.append({
                'timestamp': datetime.now(),
                'query': names_input,
                'results': len(df[df['Status'] == '✅'])
            })
            
            found_count = len(df[df['Status'] == '✅'])
            st.success(f"✅ Found {found_count} of {len(names)} athletes")
            
            st.subheader("📊 Search Results")
            
            column_config = {
                "Profile": st.column_config.LinkColumn("Profile", help="Click to view profile"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Query": st.column_config.TextColumn("Search Query", width="medium"),
                "Nickname": st.column_config.TextColumn("Nickname", width="medium"),
            }
            
            st.dataframe(df, column_config=column_config, hide_index=True, use_container_width=True)
            
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"one_athletes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
            
            with st.expander("📈 Statistics & Analysis"):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Total Searched", len(names))
                with col2:
                    st.metric("Found", found_count, f"{found_count/len(names)*100:.0f}%")
                with col3:
                    st.metric("Not Found", len(names) - found_count)
                
                if found_count > 0:
                    st.subheader("🌍 Country Distribution")
                    countries_list = []
                    for _, row in df.iterrows():
                        if row['Nationality'] != "-":
                            countries = re.findall(r'[A-Za-z\s]+', row['Nationality'])
                            countries_list.extend([c.strip() for c in countries if c.strip()])
                    
                    if countries_list:
                        country_df = pd.DataFrame(countries_list, columns=['Country'])
                        country_counts = country_df['Country'].value_counts()
                        st.bar_chart(country_counts)
    
    if st.session_state.search_history:
        with st.expander("🕐 Recent Searches"):
            for search in reversed(st.session_state.search_history[-5:]):
                st.text(f"{search['timestamp'].strftime('%H:%M')} - {search['query'][:50]}... ({search['results']} found)")

if __name__ == "__main__":
    main()
