import sys
import os
import streamlit as st
import re, datetime, yt_dlp, json, pandas as pd, io, shutil
import html as _html
import concurrent.futures
import streamlit.components.v1 as components
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types
import subprocess
import urllib.request
import time
from streamlit_autorefresh import st_autorefresh
import requests
from PIL import Image

try: import pyperclip
except ImportError: pyperclip = None

# ✅ ดึงฟังก์ชันกลางจาก utils.py
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils import get_g_services, extract_id, select_folder_mac, load_config, save_config, sanitize_filename, inject_global_css

# ==========================================
# 🛡️ 0. INITIALIZATION
# ==========================================
def init_session_state():
    if 'history_file' not in st.session_state: st.session_state['history_file'] = 'footage_history.json'
    defaults = {
        'failed': {'drive': [], 'getty': [], 'reuters': [], 'social': [], 'others': []},
        'success_urls': [], 'success_count': 0, 'data_cache': None,
        'found_in_local': {}, 'found_in_archive': {}, 'duplicates': {'getty': [], 'reuters': []},
        'triggered': False, 'run_complete': False, 
        'start_time': None, 'elapsed_time': 0, 'current_project_path': "",
        'local_archive': "", 'last_doc': "", 'last_ep': "", 'last_p_type': "Global Focus",
        'history_data': []
    }
    for key, val in defaults.items():
        if key not in st.session_state: st.session_state[key] = val

    if os.path.exists(st.session_state['history_file']):
        try:
            with open(st.session_state['history_file'], 'r', encoding='utf-8') as f:
                st.session_state['history_data'] = json.load(f)
        except: st.session_state['history_data'] = []

init_session_state()

if st.session_state.get('triggered') and not st.session_state.get('run_complete'):
    st_autorefresh(interval=1000, key="timer_refresh")

os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"
# ดึง Gemini Key จาก config ที่บันทึกไว้ใน Main
_cfg = load_config()
_k1 = _cfg.get('gemini_key1', '')
_k2 = _cfg.get('gemini_key2', '')
MY_GEMINI_KEY = ', '.join(k for k in [_k1, _k2] if k)

# ==========================================
# 🛠️ 1. SETUP & HELPER FUNCTIONS
# ==========================================
# get_g_services, extract_id, select_folder_mac, load_config, save_config
# → ย้ายไปอยู่ใน utils.py แล้ว (import ด้านบน)

def make_open_ci_button(urls, button_text, color_hex, project_name):
    valid_urls = [u for u in urls if str(u).startswith('http')]
    if not valid_urls: return
    safe_project_name = project_name.replace("'", "\\'").replace('"', '\\"')
    js_links = " ".join([f"setTimeout(() => window.open('{u}', '_blank'), {i*400});" for i, u in enumerate(valid_urls)])
    js_code = f"navigator.clipboard.writeText('{safe_project_name}'); {js_links}"
    html = f"""
    <button onclick="{js_code}" 
    style="padding: 10px 15px; background-color: #1a1e26; color: {color_hex}; 
    border: 1px solid {color_hex}; border-radius: 8px; cursor: pointer; font-weight: bold; 
    width: 100%; margin-bottom: 8px; font-family: 'IBM Plex Sans Thai', sans-serif; transition: background-color 0.15s;"
    onmouseover="this.style.backgroundColor='{color_hex}22'"
    onmouseout="this.style.backgroundColor='#1a1e26'">
    🚀 {button_text} ({len(valid_urls)} แท็บ)
    </button>
    """
    components.html(html, height=55)

def display_social_link(url, icon_url, platform_name):
    if not url: return
    display_url = url if len(url) <= 40 else url[:37] + '...'
    html = f"""
    <div style="display: flex; align-items: center; justify-content: space-between; 
    background-color: #1a1e26; padding: 8px; border-radius: 8px; margin-bottom: 5px; border: 1px solid rgba(255,255,255,0.08);">
        <div style="display: flex; align-items: center;">
            <img src="{icon_url}" width="20" height="20" style="margin-right: 10px;">
            <a href="{url}" target="_blank" style="text-decoration: none; #e8eaf0; font-family: monospace; font-size:var(--fs-md);">{display_url}</a>
        </div>
        <button onclick="window.open('{url}', '_blank')" 
        style="padding: 3px 8px; background-color: white; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; font-size:var(--fs-sm);">เปิด</button>
    </div>
    """
    st.components.v1.html(html, height=45)

# select_folder_mac → ใช้จาก utils.py แล้ว

def find_local_file(search_term, folder_path):
    if not folder_path or not os.path.exists(folder_path): return None
    search_term = str(search_term).lower().strip()
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if search_term in f.lower(): return os.path.join(root, f)
    return None

def batch_search_drive(service, archive_id, codes):
    """ ค้นหารหัสหลายๆ ตัวพร้อมกันใน Query เดียว (ทะลวง Subfolder + กรองไฟล์ขยะ) """
    if not codes: return {}
    
    found_map = {}
    # แบ่งกลุ่มค้นหาทีละ 20 รหัส (Google Query มีความยาวจำกัด)
    for i in range(0, len(codes), 20):
        chunk = codes[i:i+20]
        # สร้างคำสั่ง: name contains 'รหัส1' or name contains 'รหัส2' ...
        query_parts = [f"name contains '{c}'" for c in chunk]
        
        # 💡 THE FIX 1: เอา '{archive_id}' in parents ออก เพื่อให้มุดหาใน Subfolder ได้หมด!
        query = f"({ ' or '. join(query_parts)}) and trashed = false"
        
        try:
            results = service.files().list(
                q=query, 
                corpora='allDrives', 
                supportsAllDrives=True, 
                includeItemsFromAllDrives=True, 
                fields="files(id, name, webViewLink)"
            ).execute()
            
            files = results.get('files', [])
            for f in files:
                # ตรวจดูว่าไฟล์ที่เจอ ตรงกับรหัสไหนใน chunk บ้าง
                for c in chunk:
                    # 💡 THE FIX 2: บังคับว่าต้องลงท้ายด้วยนามสกุลวิดีโอเท่านั้น ป้องกันไฟล์แคช .pek
                    if c.lower() in f['name'].lower() and f['name'].lower().endswith(('.mp4', '.mov', '.m4v', '.avi')):
                        found_map[c] = f
                        break
        except Exception as e:
            st.error(f"⚠️ Drive Batch Error: {e}")
            
    return found_map

def search_file_in_drive(service, archive_id, code):
    try:
        query = f"name contains '{code}' and trashed = false"
        results = service.files().list(q=query, corpora='allDrives', supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name, webViewLink)", pageSize=3).execute()
        return results.get('files', [])
    except: return []

def extract_handle_from_url(url):
    m = re.search(r'tiktok\.com/(@[\w\.-]+)', url, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'youtube\.com/(@[\w\.-]+)', url, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)/status', url, re.IGNORECASE)
    if m: return f"@{m.group(1)}"
    m = re.search(r'facebook\.com/([A-Za-z0-9_\.-]+)/(?:videos|reels|posts)', url, re.IGNORECASE)
    if m:
        val = m.group(1)
        if val.lower() not in ['watch', 'reel', 'story']: return f"@{val}"
    m = re.search(r'instagram\.com/([A-Za-z0-9_\.-]+)/(?:reel|p)/', url, re.IGNORECASE)
    if m: return f"@{m.group(1)}"
    return None

# ==========================================
# 🧠 2. DOWNLOAD ENGINE (Filename Fixer & AI)
# ==========================================
# sanitize_filename → ใช้จาก utils.py แล้ว

def get_source_tag(url):
    url_lower = url.lower()
    if 'getty' in url_lower: return 'Getty'
    if 'reuters' in url_lower: return 'Reuters'
    if 'wiki' in url_lower: return 'Wiki'
    if 'youtube' in url_lower or 'youtu.be' in url_lower: return 'YT'
    if 'tiktok' in url_lower: return 'TT'
    if 'facebook' in url_lower or 'fb.watch' in url_lower: return 'FB'
    if 'instagram' in url_lower: return 'IG'
    if 'x.com' in url_lower or 'twitter' in url_lower: return 'X'
    return 'Web'

def get_ai_caption(file_path, api_key, source_tag):
    if not api_key or len(api_key) < 20: return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        img = Image.open(file_path)
        prompt = "Describe this image in a very short, factual English phrase (3-5 words). No spaces, use underscores for spaces. No special characters."
        response = model.generate_content([prompt, img])
        caption = sanitize_filename(response.text)
        if not caption or len(caption) < 3: return None
        return f"{caption}_{source_tag}"
    except: return None

# 🧠 เครื่องยนต์ตัวเต็ม (จัดการรูปและวิดีโอแบบแยกโฟลเดอร์)
def download_worker(url, platform_name, video_dir, image_dir, gemini_key):
    clean_url = url.split('"')[0].strip()
    source_tag = get_source_tag(clean_url)
    raw_filename = clean_url.split('/')[-1].split('?')[0]
    if len(raw_filename) < 5: raw_filename = f"file_{int(time.time()*1000)}"
    
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']
    temp_path = None
    
    # 💡 1. โหลดรูปภาพ
    if any(clean_url.lower().split('?')[0].endswith(ext) for ext in image_extensions):
        try:
            ext = clean_url.split('.')[-1].split('?')[0].lower()
            temp_path = os.path.join(image_dir, f"temp_{int(time.time()*1000)}.{ext}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': '*/*', 'Referer': 'https://www.google.com/'
            }
            safe_url = clean_url.replace(' ', '%20')
            response = requests.get(safe_url, headers=headers, timeout=20, stream=True)
            response.raise_for_status()
            
            with open(temp_path, 'wb') as out_file:
                for chunk in response.iter_content(chunk_size=8192): out_file.write(chunk)
            
            ai_name = get_ai_caption(temp_path, gemini_key, source_tag)
            tracker_key = extract_handle_from_url(clean_url) or raw_filename
            safe_tracker_key = sanitize_filename(tracker_key)
            
            if ai_name: final_name = f"{ai_name}_{safe_tracker_key}.{ext}"
            else: final_name = f"{safe_tracker_key}_{source_tag}.{ext}"
            
            final_path = os.path.join(image_dir, final_name)
            counter = 1
            while os.path.exists(final_path):
                name_part = final_name.rsplit('.', 1)[0]
                final_path = os.path.join(image_dir, f"{name_part}_{counter}.{ext}")
                counter += 1
                
            shutil.move(temp_path, final_path)
            return True, clean_url
        except Exception as e:
            print(f"❌ รูปภาพพัง: {e}")
            if temp_path and os.path.exists(temp_path): os.remove(temp_path)
            return False, clean_url

    # 💡 2. Gallery-DL (Wiki, Pinterest)
    elif any(x in clean_url.lower() for x in ['wikipedia', 'wikimedia', 'pinterest', 'imgur']):
        try:
            res = subprocess.run(['gallery-dl', '--directory', image_dir, clean_url], capture_output=True, timeout=60)
            if res.returncode == 0: return True, clean_url
            else: return False, clean_url
        except: return False, clean_url

    # 💡 3. วิดีโอ (YT, TT, FB, IG)
    # 💡 3. วิดีโอ (YT, TT, FB, IG)
    else:
        # 💡 THE FIX: สอนให้โค้ดเดินหา FFmpeg ทั้งในโฟลเดอร์ Pages และโฟลเดอร์หลัก (loadpap)
        current_dir = os.path.dirname(os.path.abspath(__file__)) # โฟลเดอร์ Pages
        parent_dir = os.path.dirname(current_dir) # โฟลเดอร์หลัก loadpap
        
        ffmpeg_exe = os.path.join(current_dir, "ffmpeg") # ลองหาใน Pages ก่อน
        if not os.path.exists(ffmpeg_exe):
            ffmpeg_exe = os.path.join(parent_dir, "ffmpeg") # ถ้าไม่เจอ ให้ออกไปหาที่โฟลเดอร์หลัก
            
        # ถ้ายังไม่เจออีก ให้ลองหาจากในระบบ Mac (เผื่อลงไว้ผ่าน Homebrew)
        if not os.path.exists(ffmpeg_exe):
            ffmpeg_exe = shutil.which("ffmpeg")
            if not ffmpeg_exe and os.path.exists("/usr/local/bin/ffmpeg"): ffmpeg_exe = "/usr/local/bin/ffmpeg"
            elif not ffmpeg_exe and os.path.exists("/opt/homebrew/bin/ffmpeg"): ffmpeg_exe = "/opt/homebrew/bin/ffmpeg"

        # ตั้งค่าเครื่องยนต์โหลดวิดีโอ
        ydl_opts = {
            # 💡 THE FIX: สั่งแบน AV01 เด็ดขาด! บังคับหา H.264 (avc1) ก่อน ถ้าไม่มีก็เอา MP4 อะไรก็ได้ที่ไม่ใช่ AV01
            'format': 'bestvideo[ext=mp4][vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4][vcodec!^=av01][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best',
            'merge_output_format': 'mp4',
            'ffmpeg_location': ffmpeg_exe if (ffmpeg_exe and os.path.exists(ffmpeg_exe)) else None,
            'quiet': True, 'ignoreerrors': False, 'no_warnings': True,
            'socket_timeout': 30, 'retries': 3, 'noplaylist': True,
            'outtmpl': f'{video_dir}/%(title).30s_@%(uploader)s - {source_tag}.%(ext)s', 
            'windowsfilenames': True
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if ydl.download([clean_url]) == 0: return True, clean_url
                else: return False, clean_url
        except Exception as e:
            print(f"❌ วิดีโอพัง: {e}")
            return False, clean_url

# ==========================================
# 🖥️ 3. UI & SETTINGS
# ==========================================

st.set_page_config(page_title="PyLOAD — Footage Downloader", layout="wide")

# ============================================================
# 🎨 CSS
# ============================================================
inject_global_css()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200');
@import url('https://fonts.googleapis.com/icon?family=Material+Icons|Material+Icons+Sharp');
.material-symbols-rounded{font-family:'Material Symbols Rounded'!important;font-weight:normal!important;}
.material-icons,.material-icons-sharp{font-family:'Material Icons Sharp'!important;font-weight:normal!important;}
[data-testid="stAppViewContainer"],[data-testid="stMain"],.main .block-container{background-color:#0d0f12!important;}
[data-testid="stSidebar"]{background-color:#13161b!important;border-right:1px solid rgba(255,255,255,0.08)!important;}
#MainMenu{visibility:hidden;}footer{visibility:hidden;}

.sarn-proj{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-top:2px solid #4a9eff;border-radius:12px;padding:16px 20px;margin-bottom:4px;}
.sarn-proj-name{font-size:var(--fs-lg);font-weight:700;color:#e8eaf0;}
.sarn-proj-path{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#555a6a;margin-top:4px;}
.sarn-timer{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xl);font-weight:600;color:#ff4d4d;}

.sarn-stat-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-top:14px;}
.sarn-stat{background:#1a1e26;border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:10px;text-align:center;}
.sarn-stat-val{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-stat);font-weight:600;display:block;}
.sarn-stat-lbl{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;margin-top:2px;text-transform:uppercase;}

.sarn-codes-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
.sarn-code-card{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:16px;}
.sarn-code-card-blue{border-top:2px solid #4a9eff;}
.sarn-code-card-orange{border-top:2px solid #ff7a2f;}
.sarn-code-title{font-size:var(--fs-lg);font-weight:700;margin-bottom:10px;display:flex;align-items:center;gap:8px;}
.sarn-code-box{background:#0d0f12;border:1px solid rgba(255,255,255,0.06);border-radius:6px;padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#ff4d4d;line-height:1.8;margin-bottom:8px;}
.sarn-found-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);}
.sarn-found-id{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);font-weight:600;}

.sarn-badge{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);font-weight:600;padding:2px 9px;border-radius:20px;}
.sb-blue{background:rgba(74,158,255,.12);color:#4a9eff;border:1px solid rgba(74,158,255,.25);}
.sb-orange{background:rgba(255,122,47,.12);color:#ff7a2f;border:1px solid rgba(255,122,47,.25);}
.sb-teal{background:rgba(45,212,168,.12);color:#2dd4a8;border:1px solid rgba(45,212,168,.25);}
.sb-red{background:rgba(255,77,77,.12);color:#ff4d4d;border:1px solid rgba(255,77,77,.25);}

.sarn-social-row{display:flex;align-items:center;justify-content:space-between;background:#1a1e26;padding:8px 12px;border-radius:8px;margin-bottom:5px;border:1px solid rgba(255,255,255,0.05);}
.sarn-social-url{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#8b90a0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;margin:0 10px;}
</style>
""", unsafe_allow_html=True)

if 'failed_social_links' not in st.session_state:
    st.session_state['failed_social_links'] = []

def save_run_history(project_name, local_dir, stats, elapsed_time):
    now = datetime.datetime.now()
    entry = {
        'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
        'project_name': project_name, 'local_dir': local_dir,
        'stats': stats, 'elapsed_time_sec': elapsed_time
    }
    st.session_state['history_data'].insert(0, entry)
    st.session_state['history_data'] = st.session_state['history_data'][:50]
    try:
        with open(st.session_state['history_file'], 'w', encoding='utf-8') as f:
            json.dump(st.session_state['history_data'], f, ensure_ascii=False, indent=2)
    except: pass

# ============================================================
# 🗂️ SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding-bottom:14px;
      border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:14px;">
      <div style="width:8px;height:8px;border-radius:50%;background:#4a9eff;flex-shrink:0;"></div>
      <div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);font-weight:600;color:#e8eaf0;">PyLOAD</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;letter-spacing:.06em;">FOOTAGE DOWNLOADER</div>
      </div>
    </div>""", unsafe_allow_html=True)

    app_config = load_config()
    st.session_state['config'] = app_config

    # Gemini key จาก config (ย้ายไป Main แล้ว)
    _cfg = load_config()
    MY_GEMINI_KEY = ', '.join(k for k in [_cfg.get('gemini_key1',''), _cfg.get('gemini_key2','')] if k)
    if 'gemini_key' not in st.session_state or not st.session_state['gemini_key']:
        st.session_state['gemini_key'] = MY_GEMINI_KEY
    gemini_key = st.session_state['gemini_key']

    # Safe doc
    for k in ['safe_doc_url','safe_p_type','safe_ep_name','parsed_doc_url']:
        if k not in st.session_state:
            st.session_state[k] = '' if k != 'safe_p_type' else 'Global Focus'
    if 'local_archive' not in st.session_state or not st.session_state['local_archive']:
        st.session_state['local_archive'] = app_config.get('local_archive', '')

    def update_doc(): st.session_state['safe_doc_url'] = st.session_state['wg_doc']
    def update_ptype(): st.session_state['safe_p_type'] = st.session_state['wg_ptype']
    def update_ep(): st.session_state['safe_ep_name'] = st.session_state['wg_ep']

    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:5px;'>1 — Google Doc URL</div>", unsafe_allow_html=True)
    st.session_state['wg_doc'] = st.session_state['safe_doc_url']
    doc_url = st.text_input("Doc URL", key="wg_doc", on_change=update_doc, label_visibility="collapsed", placeholder="วาง URL Doc...")

    if st.session_state['safe_doc_url'] and st.session_state['safe_doc_url'] != st.session_state['parsed_doc_url']:
        doc_id = extract_id(st.session_state['safe_doc_url'])
        if doc_id:
            try:
                with st.spinner("⏳ กำลังอ่านชื่อเอกสาร..."):
                    docs_service, drive_service = get_g_services()
                    doc_info = docs_service.documents().get(documentId=doc_id).execute()
                    doc_title = doc_info.get('title', '')
                    matched_type = "Special"
                    p_types_list = ["Global Focus", "Key Messages", "News Digest", "The World Dialogue", "Special"]
                    for pt in p_types_list:
                        if pt.lower() in doc_title.lower(): matched_type = pt; break
                    if ":" in doc_title: ep_string = doc_title.split(":", 1)[1].strip()
                    elif "：" in doc_title: ep_string = doc_title.split("：", 1)[1].strip()
                    else: ep_string = re.sub(f"(?i){matched_type}", "", doc_title).strip(" -|_")
                    st.session_state['safe_p_type'] = matched_type
                    st.session_state['safe_ep_name'] = ep_string
                    st.session_state['parsed_doc_url'] = st.session_state['safe_doc_url']
                    st.rerun()
            except Exception as _e:
                st.warning(f"⚠️ ไม่สามารถอ่านชื่อเอกสารได้: {_e}")
                st.session_state['parsed_doc_url'] = st.session_state['safe_doc_url']

    saved_archive_url = app_config.get('archive_url', '')
    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:5px;margin-top:8px;'>2 — Drive Archive URL</div>", unsafe_allow_html=True)
    archive_url = st.text_input("Archive URL", value=saved_archive_url, label_visibility="collapsed", placeholder="วาง URL Drive...")
    if archive_url != saved_archive_url:
        app_config['archive_url'] = archive_url
        save_config(app_config)

    st.divider()
    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:5px;'>3 — Local Archive</div>", unsafe_allow_html=True)
    if st.button("📂 เลือกโฟลเดอร์คลัง", use_container_width=True):
        path = select_folder_mac("เลือกโฟลเดอร์คลังเก็บไฟล์เก่า")
        if path:
            st.session_state['local_archive'] = path
            app_config['local_archive'] = path
            save_config(app_config)
            st.rerun()
    st.markdown(f"<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;background:#1a1e26;border-radius:4px;padding:4px 8px;margin-bottom:6px;word-break:break-all;'>{st.session_state['local_archive'] or 'ยังไม่ได้เลือก'}</div>", unsafe_allow_html=True)

    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:5px;'>4 — Destination</div>", unsafe_allow_html=True)
    if 'dest_folder' not in st.session_state or not st.session_state['dest_folder']:
        st.session_state['dest_folder'] = app_config.get('dest_folder', os.path.join(os.getcwd(), "Downloads_Footage"))
    if st.button("📥 เลือกโฟลเดอร์บันทึก", use_container_width=True):
        path = select_folder_mac("เลือกโฟลเดอร์สำหรับเซฟงาน")
        if path:
            st.session_state['dest_folder'] = path
            app_config['dest_folder'] = path
            save_config(app_config)
            st.rerun()
    st.markdown(f"<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;background:#1a1e26;border-radius:4px;padding:4px 8px;margin-bottom:6px;word-break:break-all;'>{st.session_state['dest_folder'] or 'ยังไม่ได้เลือก'}</div>", unsafe_allow_html=True)

    st.divider()
    p_types_list = ["Global Focus", "Key Messages", "News Digest", "The World Dialogue", "Special"]
    if st.session_state['safe_p_type'] not in p_types_list: st.session_state['safe_p_type'] = "Special"
    st.session_state['wg_ptype'] = st.session_state['safe_p_type']
    p_type = st.selectbox("ประเภทรายการ", p_types_list, key="wg_ptype", on_change=update_ptype)
    st.session_state['wg_ep'] = st.session_state['safe_ep_name']
    ep_name = st.text_input("ชื่อตอน / EP", key="wg_ep", on_change=update_ep, placeholder="เช่น เลือกตั้งสหรัฐ")
    full_project_name = f"{p_type} - {ep_name}".strip()

    st.divider()
    run_btn = st.button("🚀 เริ่มค้นหาและดาวน์โหลด", use_container_width=True, type="primary")
    if st.button("🛑 ล้างข้อมูล / Reset แอป", use_container_width=True):
        for k in ['triggered','run_complete','data_cache','parsed_doc_url','safe_doc_url','safe_ep_name','failed_social_links']:
            if k in st.session_state:
                st.session_state[k] = False if k in ['triggered','run_complete'] else (None if k=='data_cache' else ([] if k=='failed_social_links' else ''))
        st.rerun()


# ── Progress placeholder (main area) ──
if 'prog_placeholder' not in st.session_state:
    st.session_state['prog_placeholder'] = None

def _prog(msg, icon="⚙️", done=False, pct=0):
    """แสดง progress card + bar บนหน้าหลัก"""
    container = st.session_state.get('_prog_container')
    if not container: return
    if done:
        container.markdown(
            '<div style="background:#13161b;border:1px solid rgba(45,212,168,.3);'+
            'border-left:3px solid #2dd4a8;border-radius:10px;padding:14px 18px;">'+
            '<div style="font-family:IBM Plex Sans Thai,sans-serif;font-size:var(--fs-md);color:#2dd4a8;margin-bottom:10px;">✅ เสร็จสิ้นทั้งหมด!</div>'+
            '<div style="background:rgba(45,212,168,.2);border-radius:4px;height:6px;width:100%;"></div>'+
            '</div>',
            unsafe_allow_html=True
        )
    else:
        pct_w = int(min(pct, 0.99) * 100)
        container.markdown(
            f'<div style="background:#13161b;border:1px solid rgba(255,255,255,.08);'+
            f'border-left:3px solid #4a9eff;border-radius:10px;padding:14px 18px;">'+
            f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">'+
            f'<div style="width:16px;height:16px;border:2px solid #4a9eff;border-top-color:transparent;'+
            f'border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0;"></div>'+
            f'<span style="font-family:IBM Plex Sans Thai,sans-serif;font-size:var(--fs-md);color:#e8eaf0;">{icon} {msg}</span>'+
            f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#4a9eff;margin-left:auto;">{pct_w}%</span>'+
            f'</div>'+
            f'<div style="background:#1a1e26;border-radius:4px;height:6px;overflow:hidden;">'+
            f'<div style="background:linear-gradient(90deg,#4a9eff,#2dd4a8);height:6px;width:{pct_w}%;border-radius:4px;transition:width .3s;"></div>'+
            f'</div>'+
            f'</div><style>@keyframes spin{{to{{transform:rotate(360deg)}}}}</style>',
            unsafe_allow_html=True
        )


# ============================================================
# 🖥️ MAIN HEADER
# ============================================================
# ดึงค่า local_archive_dir จาก session_state สำหรับใช้ใน workflow
local_archive_dir = st.session_state.get('local_archive', '')
st.markdown("""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <div style="font-size:var(--fs-xl);">🧠</div>
  <div>
    <div style="font-family:'IBM Plex Sans Thai',sans-serif;font-size:var(--fs-xl);font-weight:700;color:#e8eaf0;line-height:1.1;">PyLOAD</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;margin-top:2px;letter-spacing:.04em;">FOOTAGE DOWNLOADER — BETA 1.2</div>
  </div>
</div>
<div style="height:1px;background:rgba(255,255,255,0.08);margin:16px 0 20px 0;"></div>
""", unsafe_allow_html=True)



if run_btn:
    st.session_state['triggered'] = True
    st.session_state['run_complete'] = False 
    st.session_state['last_doc'] = doc_url
    st.session_state['last_ep'] = ep_name
    st.session_state['last_p_type'] = p_type
    st.session_state['last_archive_url'] = archive_url
    st.session_state['start_time'] = time.time()
    st.session_state['elapsed_time'] = 0



if st.session_state.get('triggered'):
    doc_id = extract_id(doc_url)
    archive_id = extract_id(archive_url)
    
    f_name = full_project_name if ep_name else p_type
    f_name = re.sub(r'[\\/*?:"<>|]', "", f_name).strip()
    local_dir = os.path.join(st.session_state['dest_folder'], f_name)
    st.session_state['current_project_path'] = local_dir
    
    if not doc_id: st.sidebar.error("❌ กรุณาใส่ URL Google Doc")
    else:
        try:
            docs_service, drive_service = get_g_services()
            
            if 'data_cache' not in st.session_state or run_btn or st.session_state['data_cache'] is None:
                data = {
                    'getty': [], 'reuters': [], 'artlist': [], 'envato': [], 'shutterstock': [], 
                    'wiki': [], 'youtube': [], 'facebook': [], 'instagram': [], 'tiktok': [], 'others': [], 'drive_ids': []
                }

                def classify_url(url):
                    if not url or len(url) < 10: return
                    url = url.strip().strip('[]() " \' ,\\')
                    
                    # 💡 ดักจับรูปภาพ Facebook ก่อนเลย
                    if 'facebook.com' in url.lower():
                        if '/photos/' in url or '/posts/' in url:
                            if 'video' not in url.lower():
                                # ถ้าเป็นรูป ไม่ต้องเพิ่มลงใน data['facebook']
                                return
                    
                    if 'drive.google.com' in url:
                        dr_id = extract_id(url) # ใช้ฟังก์ชัน extract_id ที่พี่เขียนไว้ตอนต้น
                        if dr_id and dr_id not in data['drive_ids']:
                            data['drive_ids'].append(dr_id)
                    elif 'gettyimages' in url:
                        # 💡 THE FIX: ให้ดึงรหัสทุกรูปแบบที่อยู่ท้ายลิงก์ (รองรับตัวอักษรและขีด)
                        m = re.search(r'/detail/[^/]+/([a-zA-Z0-9_-]+)', url)
                        if m: data['getty'].append(m.group(1))
                    elif 'reutersconnect' in url: pass 
                    elif 'artlist.io' in url: data['artlist'].append(url)
                    elif any(x in url for x in ['envato.com', 'videohive.net']): data['envato'].append(url)
                    elif 'shutterstock.com' in url: data['shutterstock'].append(url)
                    elif any(x in url for x in ['wikipedia.org', 'wikimedia.org', 'flickr.com', 'pinterest.com']): data['wiki'].append(url)
                    elif any(x in url for x in ['youtube.com', 'youtu.be']): data['youtube'].append(url)
                    elif any(x in url for x in ['facebook.com', 'fb.watch']): data['facebook'].append(url)
                    elif 'instagram.com' in url: data['instagram'].append(url)
                    elif 'tiktok.com' in url: data['tiktok'].append(url)
                    elif 'x.com' in url or 'twitter.com' in url: data['others'].append(url)
                    else: data['others'].append(url) 

                with st.sidebar.spinner("🔍 กำลังสแกนเอกสาร Google Doc..."):
                    doc = docs_service.documents().get(documentId=doc_id).execute()
                    for item in doc.get('body').get('content'):
                        if 'table' in item:
                            for row in item['table']['tableRows']:
                                cells = row['tableCells']
                                if cells:
                                    first_cell = cells[0] # ล็อคเป้าช่องแรกตามที่พี่สั่ง
                                    cell_text = ""
                                    for content in first_cell['content']:
                                        if 'paragraph' in content:
                                            for el in content['paragraph']['elements']:
                                                if 'textRun' in el:
                                                    # 1. เก็บข้อความดิบ
                                                    cell_text += el['textRun']['content']
                                                    # 2. เช็ก "ลิงก์ที่ฝัง" อยู่ในข้อความ (Hyperlink)
                                                    style = el['textRun'].get('textStyle', {})
                                                    if 'link' in style: 
                                                        classify_url(style['link'].get('url', ''))
                                                
                                                if 'richLink' in el: # เช็กพวก Google Chip
                                                    chip_url = el['richLink'].get('richLinkProperties', {}).get('uri', '')
                                                    classify_url(chip_url)

                                    cell_text_clean = cell_text.replace('\u00a0', ' ')
                                    
                                    # 💡 เก็บตก: ค้นหา URL ที่เป็นข้อความดิบๆ ใน Cell ด้วย
                                    found_urls = re.findall(r'https?://[^\s"\'\]]+', cell_text_clean)
                                    for u in found_urls: classify_url(u)

                                    cell_text_clean = cell_text.replace('\u00a0', ' ')
                                    
                                    # 💡 ขั้นที่ 1: ดึง URL ทั้งหมดออกมาก่อน แล้วส่งไปเข้ากล่องใครกล่องมัน
                                    found_urls = re.findall(r'https?://[^\s"\'\]]+', cell_text_clean)
                                    for u in found_urls: classify_url(u)
                                    
                                    # 💡 ขั้นที่ 2: ลบ URL ทิ้งออกจากข้อความให้หมด!
                                    text_no_urls = re.sub(r'https?://[^\s"\'\]]+', ' ', cell_text_clean)
                                    
                                    # 💡 ขั้นที่ 3: ดึงรหัส Reuters ก่อน
                                    reuters_codes = re.findall(r'\b(?:RW|RC)[A-Z0-9]+\b', text_no_urls, re.IGNORECASE)
                                    data['reuters'].extend([r.upper() for r in reuters_codes])
                                    
                                    # 💡 ขั้นที่ 4: ลบรหัส Reuters ทิ้ง
                                    for rc in reuters_codes:
                                         text_no_urls = text_no_urls.replace(rc, ' ')
                                    
                                    # 💡 ขั้นที่ 5: ดึง Getty — กรองทีละบรรทัด
                                    # บรรทัดไหนมี http หรือ : → ข้ามเลย (มั่วแน่ๆ)
                                    for line in text_no_urls.splitlines():
                                        line = line.strip()
                                        if not line: continue
                                        if re.search(r'https?://|:', line): continue
                                        getty_codes = re.findall(r'(?i)\b(mr_\d+|\d{2,5}-\d{1,5}|\d{8,12})\b', line)
                                        data['getty'].extend(getty_codes)

                for k in data: data[k] = list(set([str(x).strip() for x in data[k] if x]))
                st.session_state['data_cache'] = data

            raw_data = st.session_state['data_cache']

            if run_btn:
                duplicates = {'getty': [], 'reuters': []}
                found_in_local = {}
                found_in_archive = {}
                
                _prog_container = st.empty()
                st.session_state['_prog_container'] = _prog_container

                # Step 0: อัปเดต yt-dlp
                _prog("กำลังอัปเดต yt-dlp...", "🔄", pct=0.03)
                try:
                    subprocess.run(["pip3", "install", "--upgrade", "yt-dlp", "--break-system-packages"], capture_output=True, timeout=20)
                    import importlib; importlib.reload(yt_dlp)
                except: pass

                # Step 1: ควานหาไฟล์เก่า
                _prog("กำลังควานหาไฟล์เก่าในคลัง Local + Drive...", "🕵️", pct=0.10)
                if True:
                    # 🔍 1. เช็กในเครื่อง (Local) ก่อน (เร็วที่สุด)
                    codes_not_in_local = []
                    for code in raw_data['getty'] + raw_data['reuters']:
                        local_f = find_local_file(code, local_archive_dir) if local_archive_dir else None
                        if local_f:
                            found_in_local[code] = local_f
                            if code in raw_data['getty']: duplicates['getty'].append(code)
                            else: duplicates['reuters'].append(code)
                        else:
                            codes_not_in_local.append(code)

                    # 🔍 2. ถ้าในเครื่องไม่เจอ และมี Archive ID ให้ "ถาม Google Drive ทีเดียวรวมยอด"
                    if codes_not_in_local:
                        drive_results = batch_search_drive(drive_service, archive_id, codes_not_in_local)
                        for code, f_info in drive_results.items():
                            found_in_archive[code] = f_info
                            if code in raw_data['getty']: duplicates['getty'].append(code)
                            else: duplicates['reuters'].append(code)
                
                st.session_state['duplicates'] = duplicates
                st.session_state['found_in_local'] = found_in_local
                st.session_state['found_in_archive'] = found_in_archive
                
                st.session_state['failed'] = {'drive': [], 'social': [], 'others': []}
                st.session_state['success_urls'] = []
                st.session_state['success_count'] = 0

            # --- ด่าน 3: กระบวนการดาวน์โหลด ---
            if not st.session_state.get('run_complete') and run_btn:
                # 💡 1. สร้างโครงสร้างโฟลเดอร์รอไว้เลย
                dirs = {
                    'images': os.path.join(local_dir, "Images"),
                    'getty': os.path.join(local_dir, "Getty"),
                    'reuters': os.path.join(local_dir, "Reuters"),
                    'envato': os.path.join(local_dir, "Envato"),
                    'artlist': os.path.join(local_dir, "Artlist"),
                    'shutterstock': os.path.join(local_dir, "Shutterstock"),
                    'youtube': os.path.join(local_dir, "YouTube"),
                    'facebook': os.path.join(local_dir, "FB"),
                    'instagram': os.path.join(local_dir, "IG"),
                    'tiktok': os.path.join(local_dir, "TikTok"),
                    'x': os.path.join(local_dir, "X"),
                    'drive': os.path.join(local_dir, "Drive"),
                    'others': os.path.join(local_dir, "Others")
                }
                for d in dirs.values(): os.makedirs(d, exist_ok=True)
                
                # 💡 ฟังก์ชันตัวช่วย: ตัดสินใจว่าไฟล์นี้ควรลงกล่องไหน (รูปไป Images / วิดีโอไปตามค่าย)
                def get_dest(filename, source_key):
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']: return dirs['images']
                    return dirs.get(source_key, dirs['others'])

                if True:
                    if st.session_state['found_in_local']:
                        _prog(f"ขั้นที่ 1/4 — ก๊อปไฟล์เก่าจากฮาร์ดดิสก์ ({len(st.session_state['found_in_local'])} ไฟล์)", "📂", pct=0.15)
                        for code, path in st.session_state['found_in_local'].items():
                            try:
                                source_key = 'getty' if code in raw_data['getty'] else 'reuters'
                                shutil.copy2(path, get_dest(path, source_key))
                            except: pass

                    if st.session_state['found_in_archive']:
                        _prog(f"ขั้นที่ 2/4 — ดึงไฟล์เก่าจาก Drive Archive ({len(st.session_state['found_in_archive'])} ไฟล์)", "☁️", pct=0.35)
                        for code, f_info in st.session_state['found_in_archive'].items():
                            try:
                                req = drive_service.files().get_media(fileId=f_info['id'])
                                fname = sanitize_filename(f_info['name'])
                                source_key = 'getty' if code in raw_data['getty'] else 'reuters'
                                dest_path = os.path.join(get_dest(fname, source_key), fname)
                                with io.FileIO(dest_path, 'wb') as fh:
                                    downloader = MediaIoBaseDownload(fh, req)
                                    done = False
                                    while not done:
                                          _, done = downloader.next_chunk()
                                
                            except: pass
                    
                    if raw_data['drive_ids']:
                        _prog(f"ขั้นที่ 2.5/4 — ดาวน์โหลดไฟล์ Google Drive ใหม่ ({len(raw_data['drive_ids'])} ไฟล์)", "📁", pct=0.5)
                        for f_id in raw_data['drive_ids']:
                            try:
                                f_info = drive_service.files().get(fileId=f_id, fields='name', supportsAllDrives=True).execute()
                                request = drive_service.files().get_media(fileId=f_id)
                                fname = sanitize_filename(f_info['name'])
                                
                                fh = io.FileIO(os.path.join(get_dest(fname, 'drive'), fname), 'wb')
                                downloader = MediaIoBaseDownload(fh, request)
                                done = False
                                while not done: _, done = downloader.next_chunk()
                                
                                st.session_state['success_count'] += 1
                                st.session_state['success_urls'].append(f"Drive: {fname[:30]}...")
                            except Exception as e: 
                                st.session_state['failed']['drive'].append(f_id)

                    # กรองลิงก์ซ้ำเด็ดขาดก่อนโยนให้ thread
                    social_links = []
                    seen_urls = set()
                    for k in ['wiki', 'youtube', 'facebook', 'instagram', 'tiktok', 'others']:
                        sub_key = 'others' if k in ['wiki', 'others'] else k
                        for url in raw_data[k]: 
                            if url not in seen_urls:
                                # ส่ง URL, แพลตฟอร์ม, โฟลเดอร์วิดีโอ(ตามค่าย), โฟลเดอร์รูปภาพ
                                social_links.append((url, k, dirs[sub_key], dirs['images']))
                                seen_urls.add(url)
                    
                    if social_links:
                        _prog(f"ขั้นที่ 3/4 — กำลังดึง Social/Web {len(social_links)} ลิงก์...", "🚀", pct=0.55)
                        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                            # โยนพารามิเตอร์ 5 ตัวให้ตรงเป๊ะ
                            futures = {executor.submit(download_worker, link[0], link[1], link[2], link[3], gemini_key): link for link in social_links}
                            total_f = len(futures)
                            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                                link_info = futures[future]
                                url_task = link_info[0]
                                _prog(f"ขั้นที่ 3/4 — ({i+1}/{total_f}) {url_task[:55]}...", "🚀", pct=0.55 + (i+1)/total_f*0.4)
                                try:
                                    success, ret_url = future.result(timeout=60)
                                    if success: 
                                        st.session_state['success_count'] += 1
                                        st.session_state['success_urls'].append(ret_url)
                                    else: 
                                        st.session_state['failed']['social'].append(url_task)
                                        if url_task not in st.session_state['failed_social_links']:
                                            st.session_state['failed_social_links'].append(url_task)
                                except Exception as e:
                                    print(f"🔥 Thread Error: {e}") 
                                    st.session_state['failed']['social'].append(url_task)
                                    if url_task not in st.session_state['failed_social_links']:
                                        st.session_state['failed_social_links'].append(url_task)

                    _prog("เสร็จสิ้น!", done=True, pct=1.0)
                    time.sleep(1.5)
                    # เคลียร์ progress container ออกหลังเสร็จ
                    if st.session_state.get('_prog_container'):
                        st.session_state['_prog_container'].empty()

                
                st.session_state['run_complete'] = True
                st.session_state['elapsed_time'] = time.time() - st.session_state['start_time']

                run_stats = {
                    'getty_new': len(raw_data['getty']) - len(st.session_state['duplicates']['getty']),
                    'getty_arch': len(st.session_state['duplicates']['getty']),
                    'social_loaded': st.session_state['success_count']
                }
                save_run_history(full_project_name, local_dir, run_stats, st.session_state['elapsed_time'])
                st.balloons()
            
            # บรรทัดเดิมของพี่
            if run_btn and not st.session_state.get('run_complete'): 
                st.rerun()

            # ==========================================
            # 📋 5. DASHBOARD & LIVE TRACKER
            # ==========================================
            timer_mins, timer_secs = divmod(int(st.session_state['elapsed_time']), 60)

            total_getty = len(raw_data['getty'])
            total_reuters = len(raw_data['reuters'])
            total_envato = len(raw_data['envato'])
            total_artlist = len(raw_data['artlist'])
            total_shutter = len(raw_data['shutterstock'])
            total_yt = len(raw_data['youtube'])
            total_fb = len(raw_data['facebook'])
            total_ig = len(raw_data['instagram'])
            total_tiktok = len(raw_data['tiktok'])
            total_x = sum(1 for u in raw_data['others'] if 'x.com' in u.lower() or 'twitter.com' in u.lower())
            total_drive = len(raw_data['drive_ids'])
            total_web = len(raw_data['wiki']) + (len(raw_data['others']) - total_x)
            total_all = sum(len(v) for v in raw_data.values())
            # Project card + stat grid
            def _s(val, color, lbl):
                return (f'<div class="sarn-stat">'
                        f'<span class="sarn-stat-val" style="color:{color};">{val}</span>'
                        f'<div class="sarn-stat-lbl">{lbl}</div></div>')

            stat_html = (
                _s(total_all,     "#e8eaf0", "รวม")
                + _s(total_getty,   "#4a9eff", "Getty")
                + _s(total_reuters, "#ff7a2f", "Reuters")
                + _s(total_envato,  "#81B441", "Envato")
                + _s(total_artlist, "#ffd166", "Artlist")
                + _s(total_shutter, "#ff4d4d", "Shutter")
                + _s(total_yt,      "#ff4d4d", "YouTube")
                + _s(total_fb,      "#1877F2", "FB")
                + _s(total_ig,      "#E1306C", "IG")
                + _s(total_tiktok,  "#e8eaf0", "TikTok")
                + _s(total_x,       "#e8eaf0", "X")
                + _s(total_drive,   "#2dd4a8", "Drive")
                + _s(total_web,     "#8b90a0", "Web")
            )
            st.markdown(
                f'<div class="sarn-proj">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                f'<div><div class="sarn-proj-name">📝 {full_project_name}</div>'
                f'<div class="sarn-proj-path">📂 {local_dir}</div></div>'
                f'<div style="text-align:right;"><div class="sarn-timer">⏱ {timer_mins:02d}:{timer_secs:02d}</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;">เวลาที่ใช้</div></div></div>'
                f'<div class="sarn-stat-grid" style="grid-template-columns:repeat(7,1fr);">{stat_html}</div></div>',
                unsafe_allow_html=True
            )

            tab_dash, tab_social, tab_drive = st.tabs([
                "🎬 Stock & Web", "📱 Social Media", "📁 Google Drive"
            ])

            # --- Tab 1: Stock ---
            with tab_dash:
                # helper: found rows
                def _found_html(items, id_color, found_local, found_archive):
                    h = ""
                    for item in items:
                        if item in found_local:
                            loc_badge = '<span class="sarn-badge sb-teal">📂 Local</span>'
                        elif item in found_archive:
                            link = found_archive[item].get('webViewLink','#')
                            loc_badge = f'<a href="{link}" target="_blank" style="text-decoration:none;"><span class="sarn-badge sb-blue">☁️ Drive</span></a>'
                        else:
                            loc_badge = '<span class="sarn-badge sb-blue">?</span>'
                        h += (f'<div class="sarn-found-row">'
                              f'<span style="color:#2dd4a8;font-size:var(--fs-xs);">✓</span>'
                              f'<span class="sarn-found-id" style="color:{id_color};">{item}</span>'
                              f'<span style="margin-left:auto;">{loc_badge}</span></div>')
                    return h

                # Getty + Reuters side by side
                _col_g, _col_r = st.columns(2, gap="medium")

                with _col_g:
                    new_getty = [c for c in raw_data['getty'] if c not in st.session_state['duplicates']['getty']]

                    # ✅ เรียง: ID ยาว / mr_ ก่อน → dash-code ท้าย
                    _dash_set_g = set(c for c in new_getty if re.match(r'^\d{2,5}-\d{1,7}$', c))
                    new_getty_main = [c for c in new_getty if c not in _dash_set_g]
                    new_getty_dash = [c for c in new_getty if c in _dash_set_g]
                    new_getty_sorted = new_getty_main + new_getty_dash

                    miss_badge_g = (f'<span class="sarn-badge sb-red">{len(new_getty_sorted)} ต้องโหลด</span>'
                                    if new_getty_sorted else '<span class="sarn-badge sb-teal">ครบแล้ว</span>')

                    # ✅ Copy All — ใช้ st.code (มีปุ่ม copy built-in)
                    import json as _json

                    _rows_g = "".join(
                        f'<div style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#e8eaf0;padding:2px 0;">{c}</div>'
                        for c in new_getty_main
                    )
                    if new_getty_dash:
                        _rows_g += '<div style="height:1px;background:rgba(255,255,255,0.07);margin:6px 0;"></div>'
                        _rows_g += "".join(
                            f'<div style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#8b90a0;padding:2px 0;">'
                            f'{c} <span style="font-size:10px;color:#555a6a;margin-left:4px;">short</span></div>'
                            for c in new_getty_dash
                        )

                    st.markdown(
                        f'<div class="sarn-code-card sarn-code-card-blue">'
                        f'<div class="sarn-code-title">🔵 Getty Images {miss_badge_g}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    if new_getty_sorted:
                        st.code("\n".join(new_getty_sorted), language="text")
                    else:
                        st.markdown(
                            '<div style="background:rgba(45,212,168,.06);border:1px solid rgba(45,212,168,.2);'
                            'border-radius:7px;padding:10px;text-align:center;margin-bottom:10px;">'
                            '<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#2dd4a8;">'
                            '✅ มีไฟล์ Getty ครบหมดแล้ว</span></div>',
                            unsafe_allow_html=True
                        )
                    if new_getty_sorted:
                        getty_urls = [f"https://www.gettyimages.com/search/2/film?phrase={code}&family=editorial&sort=best" for code in new_getty_sorted]
                        make_open_ci_button(getty_urls, "🔗 เปิด Tab Getty ทั้งหมด", "#4a9eff", full_project_name)
                    if st.session_state['duplicates']['getty']:
                        st.markdown(_found_html(st.session_state['duplicates']['getty'], '#4a9eff',
                            st.session_state['found_in_local'], st.session_state['found_in_archive']), unsafe_allow_html=True)

                with _col_r:
                    new_reuters = [c for c in raw_data['reuters'] if c not in st.session_state['duplicates']['reuters']]
                    miss_badge_r = (f'<span class="sarn-badge sb-red">{len(new_reuters)} ต้องโหลด</span>'
                                    if new_reuters else '<span class="sarn-badge sb-teal">ครบแล้ว</span>')

                    # ✅ Copy All — ใช้ st.code (มีปุ่ม copy built-in)
                    _rows_r = "".join(
                        f'<div style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#e8eaf0;padding:2px 0;">{c}</div>'
                        for c in new_reuters
                    )
                    st.markdown(
                        f'<div class="sarn-code-card sarn-code-card-orange">'
                        f'<div class="sarn-code-title">🟠 Reuters Connect {miss_badge_r}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    if new_reuters:
                        st.code("\n".join(new_reuters), language="text")
                    else:
                        st.markdown(
                            '<div style="background:rgba(45,212,168,.06);border:1px solid rgba(45,212,168,.2);'
                            'border-radius:7px;padding:10px;text-align:center;margin-bottom:10px;">'
                            '<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#2dd4a8;">'
                            '✅ มีไฟล์ Reuters ครบหมดแล้ว</span></div>',
                            unsafe_allow_html=True
                        )
                    if new_reuters:
                        reuters_urls = [f"https://www.reutersconnect.com/all?search=all%3A{code.strip()}" for code in new_reuters]
                        make_open_ci_button(reuters_urls, "เปิด Reuters Connect", "#ff7a2f", full_project_name)
                    if st.session_state['duplicates']['reuters']:
                        st.markdown(_found_html(st.session_state['duplicates']['reuters'], '#ff7a2f',
                            st.session_state['found_in_local'], st.session_state['found_in_archive']), unsafe_allow_html=True)

                # Stock อื่นๆ
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                with st.container(border=True):
                    st.markdown("**📸 Stock อื่นๆ**")
                    _oc1, _oc2, _oc3 = st.columns(3)
                    with _oc1:
                        if raw_data['artlist']: make_open_ci_button(raw_data['artlist'], "Artlist", "#FFBE00", full_project_name)
                        else: st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#555a6a;'>ไม่มี Artlist</span>", unsafe_allow_html=True)
                    with _oc2:
                        if raw_data['envato']: make_open_ci_button(raw_data['envato'], "Envato", "#81B441", full_project_name)
                        else: st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#555a6a;'>ไม่มี Envato</span>", unsafe_allow_html=True)
                    with _oc3:
                        if raw_data['shutterstock']: make_open_ci_button(raw_data['shutterstock'], "Shutter", "#EE2B24", full_project_name)
                        else: st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#555a6a;'>ไม่มี Shutter</span>", unsafe_allow_html=True)

            # --- Tab 2: Social Media ---
            with tab_social:
                def get_pending(url_list):
                    return [u for u in url_list if u not in st.session_state.get('success_urls', [])]

                success_urls = set(st.session_state.get('success_urls', []))
                pending_yt = get_pending(raw_data['youtube'])
                pending_tt = get_pending(raw_data['tiktok'])
                pending_fb = get_pending(raw_data['facebook'])
                pending_ig = get_pending(raw_data['instagram'])
                pending_others = get_pending(raw_data['others'])
                _wiki_links   = raw_data.get('wiki', [])
                all_img_links = pending_others + [u for u in _wiki_links if u not in pending_others]
                all_img_all   = raw_data['others'] + [u for u in _wiki_links if u not in raw_data['others']]
                img_fail = [u for u in all_img_all if u not in success_urls]
                img_ok   = [u for u in all_img_all if u in success_urls]

                done_vids = [u for u in success_urls if any(x in u for x in ['youtube','youtu.be','tiktok','facebook','fb.watch','instagram'])]

                # ── VIDEO SECTION ──
                st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;'>วิดีโอ</div>", unsafe_allow_html=True)

                # Platform filter — st.pills (multiselect style)
                _plat_opts = []
                if pending_yt:  _plat_opts.append(f"▶ YT ({len(pending_yt)})")
                if pending_tt:  _plat_opts.append(f"TikTok ({len(pending_tt)})")
                if pending_fb:  _plat_opts.append(f"FB ({len(pending_fb)})")
                if pending_ig:  _plat_opts.append(f"IG ({len(pending_ig)})")

                if _plat_opts:
                    _selected = st.pills("แสดงเฉพาะ:", _plat_opts, selection_mode="multi", default=_plat_opts, key="plat_filter", label_visibility="collapsed")
                else:
                    _selected = []

                pending_filtered = []
                if _selected:
                    if any("YT" in s for s in _selected):    pending_filtered += pending_yt
                    if any("TikTok" in s for s in _selected): pending_filtered += pending_tt
                    if any("FB" in s for s in _selected):    pending_filtered += pending_fb
                    if any("IG" in s for s in _selected):    pending_filtered += pending_ig

                _vc_fail, _vc_ok = st.columns(2, gap="medium")

                with _vc_fail:
                    with st.container(border=True):
                        st.markdown("**❌ ตกค้าง — ก๊อปไป 4K Downloader**")
                        if pending_filtered:
                            st.text_area("urls", value="\n".join(pending_filtered), height=120, label_visibility="collapsed")
                        else:
                            st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#2dd4a8;'>🎉 ไม่มีวิดีโอตกค้าง!</span>", unsafe_allow_html=True)

                with _vc_ok:
                    with st.container(border=True):
                        st.markdown("**✅ โหลดสำเร็จแล้ว**")
                        if done_vids:
                            for u in done_vids:
                                plat = "YT" if "youtu" in u else ("TT" if "tiktok" in u else ("FB" if "facebook" in u or "fb.watch" in u else "IG"))
                                clr = {"YT":"#ff4d4d","TT":"#e8eaf0","FB":"#4a9eff","IG":"#E1306C"}.get(plat,"#8b90a0")
                                disp = u[:50] + "..." if len(u) > 50 else u
                                st.markdown(
                                    f'<div style="display:flex;align-items:center;gap:8px;padding:6px 10px;background:#1a1e26;border-radius:7px;margin-bottom:4px;">'
                                    f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);font-weight:600;color:{clr};padding:2px 7px;background:rgba(0,0,0,.3);border-radius:10px;">{plat}</span>'
                                    f'<a href="{u}" target="_blank" style="text-decoration:none;flex:1;overflow:hidden;">'
                                    f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#8b90a0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;">{disp}</span></a>'
                                    f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);font-weight:600;padding:2px 8px;border-radius:12px;background:rgba(45,212,168,.12);color:#2dd4a8;border:1px solid rgba(45,212,168,.25);">✅ Done</span>'
                                    f'</div>',
                                    unsafe_allow_html=True
                                )
                        else:
                            st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#555a6a;'>ยังไม่มีวิดีโอสำเร็จ</span>", unsafe_allow_html=True)

                st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

                # ── IMAGE SECTION ──
                st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;'>รูปภาพ & ลิงก์เว็บ</div>", unsafe_allow_html=True)
                with st.container(border=True):
                    def _img_src(u):
                        if 'wikipedia' in u or 'wikimedia' in u: return 'Wiki'
                        if 'flickr' in u: return 'Flickr'
                        if 'pinterest' in u: return 'Pinterest'
                        return 'Web'

                    if img_ok:
                        for u in img_ok:
                            disp = u[:55] + "..." if len(u) > 55 else u
                            st.markdown(
                                f'<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;background:#1a2620;border-radius:7px;margin-bottom:4px;border:1px solid rgba(45,212,168,.1);">'
                                f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;width:50px;flex-shrink:0;">{_img_src(u)}</span>'
                                f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#8b90a0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{disp}</span>'
                                f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);font-weight:600;padding:2px 8px;border-radius:12px;background:rgba(45,212,168,.12);color:#2dd4a8;border:1px solid rgba(45,212,168,.25);">✅ Done</span>'
                                f'</div>',
                                unsafe_allow_html=True
                            )
                    if img_fail:
                        for u in img_fail:
                            disp = u[:55] + "..." if len(u) > 55 else u
                            st.markdown(
                                f'<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;background:#201a1a;border-radius:7px;margin-bottom:4px;border:1px solid rgba(255,77,77,.1);">'
                                f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;width:50px;flex-shrink:0;">{_img_src(u)}</span>'
                                f'<a href="{u}" target="_blank" style="text-decoration:none;flex:1;overflow:hidden;">'
                                f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#8b90a0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;">{disp}</span></a>'
                                f'<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);font-weight:600;padding:2px 8px;border-radius:12px;background:rgba(255,77,77,.12);color:#ff4d4d;border:1px solid rgba(255,77,77,.25);">❌ ตกค้าง</span>'
                                f'</div>',
                                unsafe_allow_html=True
                            )
                    if not img_ok and not img_fail:
                        st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#555a6a;'>ไม่มีลิงก์รูป/เว็บ</span>", unsafe_allow_html=True)
                    if img_fail:
                        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                        make_open_ci_button(img_fail, "🚀 เปิดลิงก์ตกค้างทั้งหมด", "#555a6a", full_project_name)



            # --- Tab 3: Drive ---
            with tab_drive:
                st.markdown("""
<div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);letter-spacing:.1em;color:#555a6a;
  text-transform:uppercase;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.08);">
  📁 Google Drive
</div>""", unsafe_allow_html=True)
                c_dr1, c_dr2 = st.columns(2, gap="medium")
                with c_dr1:
                    with st.container(border=True):
                        st.markdown("**📂 ไฟล์ Drive ที่สแกนพบ**")
                        if raw_data['drive_ids']:
                            for f_id in raw_data['drive_ids']:
                                drive_link = f"https://drive.google.com/file/d/{f_id}/view"
                                st.markdown(f"📄 [`{f_id[:35]}...`]({drive_link})", unsafe_allow_html=True)
                        else:
                            st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#555a6a;'>ไม่มีไฟล์ Drive</span>", unsafe_allow_html=True)
                with c_dr2:
                    with st.container(border=True):
                        st.markdown("**⚠️ ไฟล์ Drive ที่โหลดไม่สำเร็จ**")
                        if st.session_state['failed']['drive']:
                            st.code("\n".join(st.session_state['failed']['drive']), language="text")
                        else:
                            st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#2dd4a8;'>✅ ไม่มีข้อผิดพลาด</span>", unsafe_allow_html=True)

        except Exception as e:
            st.error(f"❌ Error ระบบหลัก: {e}")