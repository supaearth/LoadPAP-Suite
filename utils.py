"""
utils.py — LoadPAP Family Shared Utilities
=========================================
ฟังก์ชันกลางที่ทุก Page ใช้ร่วมกัน
import ด้วย: from utils import get_g_services, extract_id, ...
"""

import os
import re
import json
import pickle
import subprocess
import threading
import time

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ==========================================
# 📍 PATH CONFIG — แก้ที่เดียว ใช้ได้ทุกที่
# ==========================================
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(ROOT_DIR, "credentials.json")
TOKEN_FILE       = os.path.join(ROOT_DIR, "token.pickle")
CONFIG_FILE      = os.path.join(ROOT_DIR, "vmaster_config.json")

# ==========================================
# 🔑 GOOGLE AUTH — ใช้ร่วมกันทั้ง 3 ระบบ
# ==========================================
# SCOPES รวมสิทธิ์ทั้งหมดที่ทุก Page ต้องการ
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/documents.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
]

# ==========================================
# 💾 CACHE — อ่านครั้งเดียว ใช้ซ้ำได้เลย
# ==========================================
_creds_cache = None        # เก็บ credentials object ไว้ใน memory
_services_cache = {}       # เก็บ service objects { 'docs': ..., 'drive': ..., 'sheets': ... }

def get_g_creds():
    """คืนค่า Google credentials — โหลดครั้งแรกครั้งเดียว หลังจากนั้นใช้ cache"""
    global _creds_cache

    # ✅ ถ้ามี cache อยู่แล้วและยังใช้งานได้ → คืนค่าเลย ไม่ต้องอ่านไฟล์ซ้ำ
    if _creds_cache and _creds_cache.valid:
        return _creds_cache

    creds = None
    # ใน utils.py — บรรทัดหลัง โหลด token เก่ามาแล้ว
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        except Exception:
            creds = None

# 💡 THE FIX: ถ้า token เก่า SCOPES ไม่ครบ → ล้างทิ้ง บังคับ auth ใหม่
    try:
       if creds and not creds.has_scopes(SCOPES):
        creds = None  # ← บรรทัดนี้มีอยู่แล้วใน utils.py ของพี่ ✅
    except Exception:
       creds = None
    

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"❌ ไม่พบไฟล์ credentials.json ที่ {CREDENTIALS_FILE}\n"
                    "กรุณาดาวน์โหลดจาก Google Cloud Console แล้ววางในโฟลเดอร์หลัก"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)

            port = 8765
            flow.redirect_uri = f'http://localhost:{port}/'
            auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')

            def _open_chrome_delayed():
                time.sleep(1.5)
                subprocess.Popen(['open', '-a', 'Google Chrome', auth_url])

            threading.Thread(target=_open_chrome_delayed, daemon=True).start()

            creds = flow.run_local_server(
                port=port, open_browser=False,
                state=state, access_type='offline', prompt='consent'
            )

        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    _creds_cache = creds   # บันทึกลง cache
    return creds

def _get_service(name, api, version):
    """สร้าง service object ครั้งเดียว แล้ว cache ไว้ใช้ซ้ำ"""
    global _services_cache
    if name not in _services_cache:
        _services_cache[name] = build(api, version, credentials=get_g_creds())
    return _services_cache[name]

def get_docs_service():
    return _get_service('docs', 'docs', 'v1')

def get_drive_service():
    return _get_service('drive', 'drive', 'v3')

def get_sheets_service():
    return _get_service('sheets', 'sheets', 'v4')

def get_g_services():
    """คืน (docs_service, drive_service) — ใช้สำหรับ PyS.A.R.N."""
    return get_docs_service(), get_drive_service()

def get_logged_in_email() -> str | None:
    """คืน email ของ Google account ที่ login อยู่ — None ถ้ายังไม่ได้ login"""
    try:
        import requests as _req
        creds = get_g_creds()
        if not creds or not creds.valid:
            return None
        resp = _req.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {creds.token}'},
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json().get('email')
    except Exception:
        pass
    return None


def logout_google():
    """ลบ token.pickle เพื่อบังคับ login ใหม่ครั้งถัดไป"""
    global _creds_cache, _services_cache
    _creds_cache = None
    _services_cache = {}
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
            return True
    except Exception:
        pass
    return False

# ==========================================
# 🛠️ UTILITY FUNCTIONS
# ==========================================

def extract_id(url_or_id: str) -> str | None:
    """ดึง Google ID จาก URL ทุกรูปแบบ"""
    if not url_or_id:
        return None
    match = re.search(r'/(?:d|folders)/([a-zA-Z0-9-_]+)', url_or_id)
    if match:
        return match.group(1)
    match_id = re.search(r'id=([a-zA-Z0-9-_]+)', url_or_id)
    if match_id:
        return match_id.group(1)
    return url_or_id.strip()

def sanitize_filename(name: str) -> str:
    """ทำความสะอาดชื่อไฟล์ ลบอักขระต้องห้าม"""
    if not name:
        return "untitled"
    clean = re.sub(r'[/\\:*?"<>|]', '_', str(name))
    clean = re.sub(r'[\s]+', '_', clean)
    return clean.strip()[:100]

def select_folder_mac(prompt_text: str = "เลือกโฟลเดอร์") -> str | None:
    """เปิด Mac Finder dialog ให้เลือกโฟลเดอร์"""
    try:
        script = f'return POSIX path of (choose folder with prompt "{prompt_text}")'
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None

# ==========================================
# ⚙️ CONFIG — จำค่า Sidebar ไม่ให้หายตอน Refresh
# ==========================================

def load_config() -> dict:
    """โหลด config จากฮาร์ดดิสก์"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(data: dict):
    """บันทึก config ลงฮาร์ดดิสก์"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"❌ บันทึก config ไม่สำเร็จ: {e}")

# ==========================================
# 🎨 GLOBAL CSS — typography scale กลาง
# แก้ที่นี่ที่เดียว = เปลี่ยนทุกหน้าพร้อมกัน
# ==========================================
import streamlit as st

def inject_global_css():
    """
    เรียกหลัง st.set_page_config() ในทุกหน้า
    ประกาศ CSS custom properties (tokens) ไว้ที่ :root
    แต่ละ class ใน CSS ของแต่ละหน้าใช้ var(--fs-...) แทน hardcode
    """
    st.markdown("""
<style>
/* ══════════════════════════════════════════
   🔤 TYPOGRAPHY TOKENS — แก้ที่นี่ที่เดียว
   ══════════════════════════════════════════ */
:root {
  --fs-base  : 16px;   /* body ทั่วไป, button, input          */
  --fs-xs    : 10px;   /* label uppercase เล็กมาก, sidebar tag */
  --fs-sm    : 12px;   /* mono detail, badge, path display     */
  --fs-md    : 14px;   /* section content, table row text      */
  --fs-lg    : 17px;   /* card title, section header           */
  --fs-xl    : 30px;   /* timer, project name, sub-hero        */
  --fs-stat  : 22px;   /* big number stat cards                */
  --fs-hero  : 30px;   /* page title (PyL.A.D., PyS.A.R.N.)   */
}

/* ── Base size ── */
html, body, [class*="css"] { font-size: var(--fs-base) !important; }

/* ── Font family ทุก element — ไม่บังคับ color ── */
p,h1,h2,h3,h4,h5,h6,li,a,td,th,label,button>div>p,
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] li,
[data-testid="stSidebarNavItems"] span:not(.material-icons):not(.material-icons-sharp):not(.material-symbols-rounded),
[data-testid="baseButton-secondary"] p,[data-testid="baseButton-primary"] p{
  font-family:'IBM Plex Sans Thai',sans-serif!important;}

/* ── สีขาวเฉพาะ prose ทั่วไป — ไม่แตะ td/th/a/span ที่ class จัดการสีเองอยู่แล้ว ── */
p, li, label,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li{
  color:#e8eaf0!important;}

/* ── Mono font สำหรับ code ── */
code,pre,[data-testid="stCodeBlock"] *{font-family:'IBM Plex Mono',monospace!important;}
</style>
""", unsafe_allow_html=True)
