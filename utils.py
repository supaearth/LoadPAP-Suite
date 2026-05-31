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
import shutil
import html as _html

# ==========================================
# 📍 PATH CONFIG — แก้ที่เดียว ใช้ได้ทุกที่
# ==========================================
ROOT_DIR         = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(ROOT_DIR, "credentials.json")
TOKEN_FILE       = os.path.join(ROOT_DIR, "token.pickle")   # account 0 (backward compat)
CONFIG_FILE      = os.path.join(ROOT_DIR, "vmaster_config.json")

# ==========================================
# 🔑 GOOGLE AUTH — ใช้ร่วมกันทั้ง 3 ระบบ
# ==========================================
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/documents.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
]

# ==========================================
# 💾 CACHE
# ==========================================
_creds_cache    = {}   # {account_idx: creds}
_services_cache = {}   # {account_idx: {name: service}}
_last_config_error = ""

LOADPAP_PAGE_ROUTES = {
    "PyLOAD_V3.0": "pages/1_PyLOAD_V3.0.py",
    "PyRUSH_V3.0": "pages/2_PyRUSH_V3.0.py",
    "PyLOG_V3.0": "pages/3_PyLOG_V3.0.py",
    "PyLIVE_Test1.0": "pages/4_PyLIVE_Test1.0.py",
    "PyCUT_BetaV1.0": "pages/5_PyCUT_BetaV1.0.py",
}


def get_last_config_error() -> str:
    """คืน error ล่าสุดจาก load_config/save_config เพื่อให้ UI แสดงผลได้"""
    return _last_config_error

def resolve_loadpap_page(slug: str) -> str | None:
    """Resolve public Streamlit page slug to a repo page file."""
    return LOADPAP_PAGE_ROUTES.get(str(slug or "").strip().strip("/"))


def has_nonempty_text(value) -> bool:
    """Return True when a UI text value contains non-whitespace content."""
    return bool(str(value or "").strip())


def get_token_file(idx: int) -> str:
    """คืน path ของ token file สำหรับ account idx"""
    if idx == 0:
        return TOKEN_FILE   # backward compat
    return os.path.join(ROOT_DIR, f"token_{idx}.pickle")


def get_active_account_index() -> int:
    """คืน index ของ active account จาก config"""
    return int(load_config().get('active_account', 0))


def set_active_account(idx: int):
    """เปลี่ยน active account แล้วล้าง services cache"""
    global _services_cache
    cfg = load_config()
    cfg['active_account'] = idx
    save_config(cfg)
    _services_cache = {}


def get_g_creds(account_idx: int = None):
    """คืนค่า Google credentials — โหลดครั้งแรกครั้งเดียว หลังจากนั้นใช้ cache"""
    global _creds_cache
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    if account_idx is None:
        account_idx = get_active_account_index()

    cached = _creds_cache.get(account_idx)
    if cached and cached.valid:
        return cached

    token_file = get_token_file(account_idx)
    creds = None

    if os.path.exists(token_file):
        with open(token_file, 'rb') as f:
            creds = pickle.load(f)

    try:
        if creds and not creds.has_scopes(SCOPES):
            creds = None
    except Exception:
        creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, 'wb') as f:
                pickle.dump(creds, f)
        else:
            # account 0 = first-time setup, trigger OAuth อัตโนมัติ
            # account อื่น = ต้องใช้ add_account() โดยตรง
            if account_idx == 0:
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
                with open(token_file, 'wb') as f:
                    pickle.dump(creds, f)
            else:
                raise FileNotFoundError(
                    f"ไม่พบ token สำหรับ account {account_idx} — กรุณาเพิ่ม account ผ่านหน้า Main"
                )

    _creds_cache[account_idx] = creds
    return creds


def add_account() -> int:
    """เพิ่ม Google Account ใหม่ด้วย OAuth — คืนค่า index ของ account ใหม่"""
    global _creds_cache

    idx = 0
    while os.path.exists(get_token_file(idx)):
        idx += 1

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"ไม่พบ credentials.json ที่ {CREDENTIALS_FILE}")

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    port = 8765 + idx
    flow.redirect_uri = f'http://localhost:{port}/'
    auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')

    def _open_chrome():
        time.sleep(1.5)
        subprocess.Popen(['open', '-a', 'Google Chrome', auth_url])
    threading.Thread(target=_open_chrome, daemon=True).start()

    creds = flow.run_local_server(
        port=port, open_browser=False,
        state=state, access_type='offline', prompt='consent'
    )
    with open(get_token_file(idx), 'wb') as f:
        pickle.dump(creds, f)

    _creds_cache[idx] = creds
    return idx


def remove_account(idx: int) -> bool:
    """ลบ account และ token — คืน True ถ้าสำเร็จ"""
    global _creds_cache, _services_cache
    _creds_cache.pop(idx, None)
    _services_cache.pop(idx, None)
    try:
        tf = get_token_file(idx)
        if os.path.exists(tf):
            os.remove(tf)
        cfg = load_config()
        cfg.get('account_emails', {}).pop(str(idx), None)
        if int(cfg.get('active_account', 0)) == idx:
            cfg['active_account'] = 0
        save_config(cfg)
        return True
    except Exception:
        return False


def get_all_accounts_info() -> list:
    """คืนรายชื่อ accounts ทั้งหมด [{idx, email, active}]
    email ถูก cache ใน config เพื่อไม่ต้องยิง API ทุกครั้ง"""
    import requests as _req
    cfg = load_config()
    active_idx = int(cfg.get('active_account', 0))
    emails_cache = cfg.get('account_emails', {})
    accounts = []
    needs_save = False

    for idx in range(10):
        if not os.path.exists(get_token_file(idx)):
            continue
        email = emails_cache.get(str(idx))
        if not email:
            try:
                creds = get_g_creds(idx)
                if creds and creds.valid:
                    resp = _req.get(
                        'https://www.googleapis.com/oauth2/v3/userinfo',
                        headers={'Authorization': f'Bearer {creds.token}'},
                        timeout=5
                    )
                    if resp.status_code == 200:
                        email = resp.json().get('email', f'Account {idx}')
                        emails_cache[str(idx)] = email
                        needs_save = True
            except Exception:
                email = f'Account {idx}'
        accounts.append({'idx': idx, 'email': email or f'Account {idx}', 'active': idx == active_idx})

    if needs_save:
        cfg['account_emails'] = emails_cache
        save_config(cfg)

    return accounts


def get_all_drive_services() -> list:
    """คืน drive services ของทุก account ที่ valid — ใช้สำหรับค้นหา Drive แบบ multi-account"""
    from googleapiclient.discovery import build

    services = []
    for idx in range(10):
        if not os.path.exists(get_token_file(idx)):
            continue
        try:
            creds = get_g_creds(idx)
            if creds and creds.valid:
                services.append(build('drive', 'v3', credentials=creds))
        except Exception:
            continue
    return services


def _get_service(name, api, version, account_idx=None):
    """สร้าง service object ครั้งเดียว แล้ว cache ไว้ใช้ซ้ำ"""
    global _services_cache
    from googleapiclient.discovery import build

    if account_idx is None:
        account_idx = get_active_account_index()
    if account_idx not in _services_cache:
        _services_cache[account_idx] = {}
    if name not in _services_cache[account_idx]:
        _services_cache[account_idx][name] = build(api, version, credentials=get_g_creds(account_idx))
    return _services_cache[account_idx][name]


def get_docs_service():
    return _get_service('docs', 'docs', 'v1')

def get_drive_service():
    return _get_service('drive', 'drive', 'v3')

def get_sheets_service():
    return _get_service('sheets', 'sheets', 'v4')

def get_g_services():
    """คืน (docs_service, drive_service) — ใช้สำหรับ PyLOAD"""
    return get_docs_service(), get_drive_service()


def get_logged_in_email(account_idx: int = None) -> str | None:
    """คืน email ของ Google account ที่ login อยู่ — None ถ้ายังไม่ได้ login"""
    try:
        import requests as _req
        if account_idx is None:
            account_idx = get_active_account_index()
        creds = get_g_creds(account_idx)
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


def logout_google(account_idx: int = None):
    """ลบ token เพื่อบังคับ login ใหม่ครั้งถัดไป"""
    global _creds_cache, _services_cache
    if account_idx is None:
        account_idx = get_active_account_index()
    _creds_cache.pop(account_idx, None)
    _services_cache.pop(account_idx, None)
    try:
        if os.path.exists(get_token_file(account_idx)):
            os.remove(get_token_file(account_idx))
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

def escape_html(value) -> str:
    """Escape text before inserting it into unsafe HTML/Markdown."""
    return _html.escape(str(value), quote=True)

def js_literal(value) -> str:
    """Serialize a value for safe insertion into JavaScript source."""
    return json.dumps(value, ensure_ascii=False)

def escape_drive_query_value(value) -> str:
    """Escape a literal value for Google Drive query strings."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")

def build_drive_name_contains_query(codes) -> str:
    """Build a Drive query for multiple filename code fragments."""
    clean_codes = []
    for code in codes or []:
        if code is None:
            continue
        code = str(code).strip()
        if code:
            clean_codes.append(code)
    if not clean_codes:
        return "trashed = false"
    query_parts = [
        f"name contains '{escape_drive_query_value(code)}'"
        for code in clean_codes
    ]
    return f"({' or '.join(query_parts)}) and trashed = false"

def build_drive_name_equals_query(filename) -> str:
    """Build a Drive query for one exact filename."""
    return f"name = '{escape_drive_query_value(str(filename).strip())}' and trashed = false"

def escape_applescript_string(value: str) -> str:
    """Escape a Python string before embedding it in an AppleScript string."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')

def parse_timecode_seconds(value, default=None):
    """Parse LoadPAP timecode text into seconds.

    Dot notation is newsroom shorthand: `MM.SS` or `HH.MM.SS`.
    Colon notation accepts `MM:SS` or `HH:MM:SS`.
    """
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan"} or text in {"-", "–"}:
        return default

    def _number(part):
        if part == "":
            return 0.0
        return float(part)

    def _valid_clock(minutes, seconds, has_hours=False):
        if seconds < 0 or seconds >= 60:
            return False
        if has_hours and (minutes < 0 or minutes >= 60):
            return False
        return minutes >= 0

    try:
        if ":" in text:
            parts = text.split(":")
            if len(parts) == 3:
                hours, minutes, seconds = (_number(p) for p in parts)
                if not _valid_clock(minutes, seconds, has_hours=True):
                    return default
                return hours * 3600.0 + minutes * 60.0 + seconds
            if len(parts) == 2:
                minutes, seconds = (_number(p) for p in parts)
                if not _valid_clock(minutes, seconds):
                    return default
                return minutes * 60.0 + seconds
            return default

        if "." in text:
            parts = text.split(".")
            if len(parts) == 3:
                hours = _number(parts[0])
                minutes = _number(parts[1])
                seconds = _number(parts[2].ljust(2, "0")[:2])
                if not _valid_clock(minutes, seconds, has_hours=True):
                    return default
                return hours * 3600.0 + minutes * 60.0 + seconds
            if len(parts) == 2:
                minutes = _number(parts[0])
                seconds = _number(parts[1].ljust(2, "0")[:2])
                if not _valid_clock(minutes, seconds):
                    return default
                return minutes * 60.0 + seconds
            return default

        seconds = float(text)
        return seconds if seconds >= 0 else default
    except (TypeError, ValueError):
        return default

def select_folder_mac(prompt_text: str = "เลือกโฟลเดอร์") -> str | None:
    """เปิด Mac Finder dialog ให้เลือกโฟลเดอร์"""
    try:
        script = f'return POSIX path of (choose folder with prompt "{escape_applescript_string(prompt_text)}")'
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None

# ==========================================
# ⚙️ CONFIG
# ==========================================

def load_config() -> dict:
    """โหลด config จากฮาร์ดดิสก์"""
    global _last_config_error
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _last_config_error = ""
            return data
        except Exception as e:
            backup = f"{CONFIG_FILE}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}.bak"
            try:
                shutil.copy2(CONFIG_FILE, backup)
                _last_config_error = f"อ่าน config ไม่สำเร็จ: {CONFIG_FILE} ({e}); backup: {backup}"
            except Exception as backup_error:
                _last_config_error = (
                    f"อ่าน config ไม่สำเร็จ: {CONFIG_FILE} ({e}); "
                    f"backup ไม่สำเร็จ: {backup_error}"
                )
    return {}

def save_config(data: dict):
    """บันทึก config ลงฮาร์ดดิสก์"""
    global _last_config_error
    tmp_file = f"{CONFIG_FILE}.tmp"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_file, CONFIG_FILE)
        _last_config_error = ""
        return True
    except Exception as e:
        _last_config_error = f"บันทึก config ไม่สำเร็จ: {CONFIG_FILE} ({e})"
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except Exception:
            pass
        return False

# ==========================================
# 🎨 GLOBAL CSS
# ==========================================

def inject_global_css():
    import streamlit as st

    st.markdown("""
<style>
/* ══════════════════════════════════════════
   🔤 TYPOGRAPHY TOKENS — แก้ที่นี่ที่เดียว
   ══════════════════════════════════════════ */
:root {
  --fs-base  : 16px;
  --fs-xs    : 10px;
  --fs-sm    : 12px;
  --fs-md    : 14px;
  --fs-lg    : 17px;
  --fs-xl    : 30px;
  --fs-stat  : 22px;
  --fs-hero  : 30px;
}

html, body, [class*="css"] { font-size: var(--fs-base) !important; }

p,h1,h2,h3,h4,h5,h6,li,a,td,th,label,button>div>p,
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] li,
[data-testid="stSidebarNavItems"] span:not(.material-icons):not(.material-icons-sharp):not(.material-symbols-rounded),
[data-testid="baseButton-secondary"] p,[data-testid="baseButton-primary"] p{
  font-family:'IBM Plex Sans Thai',sans-serif!important;}

p, li, label,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li{
  color:#e8eaf0!important;}

code,pre,[data-testid="stCodeBlock"] *{font-family:'IBM Plex Mono',monospace!important;}
#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"]{
  visibility:hidden!important;
  height:0!important;
}
</style>
""", unsafe_allow_html=True)
