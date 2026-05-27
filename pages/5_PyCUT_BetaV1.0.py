import sys
import os
import re
import math
import shutil
import subprocess
import threading
import time
import io
import platform
import streamlit as st
import streamlit.components.v1 as components
from googleapiclient.http import MediaIoBaseDownload
from google import genai
import yt_dlp

# ──────────────────────────────────────────────────────────────
# ROOT PATH
# ──────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from utils import (
    get_docs_service,
    get_drive_service,
    extract_id,
    sanitize_filename,
    select_folder_mac,
    load_config,
    save_config,
    ROOT_DIR,
    inject_global_css,
)

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"


def _get_ffmpeg():
    arch = platform.machine()
    candidates = [
        os.path.join(ROOT_DIR, f"ffmpeg_{arch}"),
        os.path.join(ROOT_DIR, "ffmpeg"),
        shutil.which("ffmpeg"),
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "ffmpeg"


FFMPEG_EXE = _get_ffmpeg()
GAP_SEC = 3 / 25        # 3 frames @ 25fps = 0.120s
MAX_CHARS_VERTICAL = 18  # DaVinci auto-wrap ที่ ~19-20 chars — ต้องต่ำกว่านี้
GEMINI_MODEL = "gemini-2.0-flash-lite"

_cfg = load_config()
_k1 = _cfg.get("gemini_key1", "")
_k2 = _cfg.get("gemini_key2", "")

# ──────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PyCUT — LoadPAP Suite",
    page_icon="✂️",
    layout="wide",
)
inject_global_css()

# ──────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────
def _init():
    defaults = {
        "pycut_doc_url": "",
        "pycut_parsed": None,
        "pycut_settings": {
            "make_srt": True,
            "is_vertical": True,
            "download_footage": True,
            "cut_by_tc": True,
            "pad_cut": True,
        },
        "pycut_output_folder": load_config().get("pycut_output_folder", ""),
        "pycut_stock_watch_folder": load_config().get("pycut_stock_watch_folder", ""),
        "pycut_row_status": {},
        "pycut_srt_content": "",
        "pycut_srt_editor": "",
        "pycut_running": False,
        "pycut_watchdog_stop": None,
        "pycut_error": "",
        "pycut_result_holder": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init()

# ── sync result_holder → session_state (main loop อ่านผล thread) ──
if st.session_state["pycut_running"]:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=2000, key="pycut_refresh")
    holder = st.session_state.get("pycut_result_holder")
    if holder is not None:
        if holder.get("srt_content"):
            new_srt = holder["srt_content"]
            if st.session_state.get("pycut_srt_content") != new_srt:
                st.session_state["pycut_srt_content"] = new_srt
                st.session_state["pycut_srt_editor"] = new_srt  # reset editor เมื่อ SRT ใหม่มา
        if holder.get("error"):
            st.session_state["pycut_error"] = holder["error"]
            st.session_state["pycut_running"] = False
        if holder.get("done"):
            st.session_state["pycut_running"] = False

# ──────────────────────────────────────────────────────────────
# GEMINI CLIENT
# ──────────────────────────────────────────────────────────────
def _gemini_client():
    cfg = load_config()
    key = cfg.get("gemini_key1", "") or cfg.get("gemini_key2", "")
    if not key:
        return None
    try:
        return genai.Client(api_key=key)
    except Exception:
        return None

def _gemini_keys() -> list[str]:
    cfg = load_config()
    return [k for k in [cfg.get("gemini_key1", ""), cfg.get("gemini_key2", "")] if k]

_whisper_model_cache: dict = {}

def _get_whisper_model(size: str = "medium"):
    """Load faster-whisper model (cache ไว้ ไม่ load ซ้ำ)"""
    if size not in _whisper_model_cache:
        from faster_whisper import WhisperModel
        _whisper_model_cache[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _whisper_model_cache[size]


# (model_id, api_version)
_SOT_MODELS = [
    ("gemini-2.5-flash",          "v1beta"),  # RPD 20 ✅
    ("gemini-2.5-flash-lite",     "v1beta"),  # RPD 20 ✅
    ("gemini-2.0-flash-lite",     "v1beta"),  # RPD 0 บาง account
    ("gemini-1.5-flash-latest",   "v1"),      # legacy fallback
]

# ──────────────────────────────────────────────────────────────
# DOC PARSER
# ──────────────────────────────────────────────────────────────
def parse_tc(tc_str: str) -> float | None:
    tc_str = str(tc_str).strip()
    if not tc_str or tc_str in ("", "nan", "None", "-", "–"):
        return None
    if "." in tc_str:
        parts = tc_str.split(".")
        minutes = float(parts[0]) if parts[0] else 0.0
        sec_str = parts[1].ljust(2, "0")[:2]
        return minutes * 60.0 + float(sec_str)
    try:
        return float(tc_str)
    except Exception:
        return None


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff", ".tif"}

def detect_footage_type(raw: str) -> str:
    if not raw or not raw.strip():
        return "none"
    rl = raw.lower().strip()
    if "drive.google.com" in rl:
        return "drive"
    if "getty" in rl or re.match(r"^\d{7,12}$", raw.strip()):
        return "getty"
    if "reuters" in rl or re.match(r'^(?:RW|RC)[A-Z0-9]+$', raw.strip(), re.IGNORECASE):
        return "reuters"
    if any(x in rl for x in ["youtube.com", "youtu.be", "facebook.com", "fb.watch",
                               "instagram.com", "tiktok.com", "x.com", "twitter.com"]):
        return "social"
    # URL ที่ path ลงท้ายด้วย image extension
    if rl.startswith("http"):
        from urllib.parse import urlparse as _up
        _path_ext = os.path.splitext(_up(raw).path)[1].lower()
        if _path_ext in _IMAGE_EXTS:
            return "image"
    return "other"


def _cell_text(cell: dict) -> str:
    """ดึง plain text / URL จาก tableCells — รองรับ textRun และ richLink (ลิ้งซ่อน)"""
    out = []
    for para in cell.get("content", []):
        for elem in para.get("paragraph", {}).get("elements", []):
            if "textRun" in elem:
                out.append(elem["textRun"].get("content", ""))
            elif "richLink" in elem:
                uri = elem["richLink"].get("richLinkProperties", {}).get("uri", "")
                if uri:
                    out.append(uri)
    return "".join(out).strip()


def _is_footage_url(url: str) -> bool:
    """คืน True ถ้า URL เป็นแหล่ง footage จริง — กรอง homepage/เครดิต/auto-link ออก"""
    if not url or not url.startswith("http"):
        return False
    u = url.lower()

    # Google Drive — path ต้องมี /file/ /folders/ /open หรือ id ท้าย
    if "drive.google.com" in u:
        return any(x in u for x in ("/file/", "/folders/", "/open?", "id="))

    # Getty
    if "gettyimages." in u:
        return True

    # Reuters
    if "reutersconnect.com" in u or "reuters.com" in u:
        return True

    # YouTube — ต้องมี video/playlist id
    if "youtube.com" in u:
        return any(x in u for x in ("watch?", "/shorts/", "/live/", "/embed/", "list="))
    if "youtu.be" in u:
        # youtu.be/<id> — path ต้องยาวกว่า /
        from urllib.parse import urlparse as _up
        return len(_up(url).path.strip("/")) > 4

    # Facebook — ต้องเป็น video/reel/post จริง ไม่ใช่ homepage
    if "facebook.com" in u or "fb.watch" in u:
        return any(x in u for x in (
            "/videos/", "/watch/", "watch?", "/reel/", "/reels/",
            "/posts/", "/story/", "fb.watch/",
        ))

    # Instagram — ต้องเป็น post/reel
    if "instagram.com" in u:
        return any(x in u for x in ("/p/", "/reel/", "/tv/"))

    # TikTok — ต้องมี /video/
    if "tiktok.com" in u:
        return "/video/" in u

    # X / Twitter — ต้องมี /status/
    if "x.com" in u or "twitter.com" in u:
        return "/status/" in u

    return False


def _cell_footage_list(cell: dict) -> list[str]:
    """ดึง footage list จาก Footages cell — 1 paragraph = 1 footage

    รับเฉพาะ:
    1. richLink (Google Smart Chip) → เฉพาะ domain ที่เป็น footage จริง
    2. textRun ที่มี hyperlink → เฉพาะ URL ที่ตรง _FOOTAGE_URL_DOMAINS
    3. textRun plain text → URL ดิบที่ตรง domain / Getty code / Reuters code / ปล่อยเสียง
    ทิ้งทั้งหมด: display text, เครดิต, ชื่อที่มาที่ไม่เป็นลิงก์
    """
    # returns list of (value, display_name)
    results = []
    for para in cell.get("content", []):
        para_vals = []   # list of (value, display)
        plain_parts = []
        display_parts = []
        for elem in para.get("paragraph", {}).get("elements", []):
            if "richLink" in elem:
                props = elem["richLink"].get("richLinkProperties", {})
                uri = props.get("uri", "")
                title = props.get("title", "")
                if uri and _is_footage_url(uri):
                    para_vals.append((uri, title or ""))
            elif "textRun" in elem:
                tr = elem["textRun"]
                style = tr.get("textStyle", {})
                content = tr.get("content", "")
                if "link" in style:
                    url = style["link"].get("url", "")
                    if url and _is_footage_url(url):
                        para_vals.append((url, content.strip()))
                else:
                    plain_parts.append(content)

        if plain_parts:
            plain = "".join(plain_parts).strip()
            if plain:
                for raw_url in re.findall(r'https?://[^\s"\']+', plain):
                    if _is_footage_url(raw_url):
                        para_vals.append((raw_url, ""))
                leftover = re.sub(r'https?://[^\s"\']+', '', plain).strip()
                if leftover:
                    if re.fullmatch(r'(?i)(mr_)?\d[\d\-]+', leftover):
                        para_vals.append((leftover, leftover))
                    elif re.fullmatch(r'(?i)(RW|RC)[A-Z0-9]+', leftover):
                        para_vals.append((leftover, leftover))
                    elif leftover.lower().startswith("ปล่อยเสียง"):
                        para_vals.append((leftover, leftover))

        results.extend(para_vals)

    return [(v.strip(), d.strip()) for v, d in results if v.strip()]


def _cell_bullets(cell: dict) -> list[str]:
    """ดึง bullets (1 paragraph = 1 bullet) จาก cell"""
    bullets = []
    for para in cell.get("content", []):
        line = ""
        for elem in para.get("paragraph", {}).get("elements", []):
            line += elem.get("textRun", {}).get("content", "")
        line = line.strip()
        if line:
            bullets.append(line)
    return bullets


_SOT_MAX_CHARS = 40  # ความยาวสูงสุดต่อ 1 subtitle block

# ── Thai clause-boundary markers ──
# split BEFORE: conjunction/discourse word ที่นำหน้า clause ใหม่
# split AFTER:  sentence-final particle เมื่อมีข้อความต่อ
_THAI_CLAUSE_RE = re.compile(
    r'\s+(?=ซึ่ง|แต่(?!ง)|โดย(?!ย)|เพราะ|ถ้า|หาก|อีกทั้ง|นอกจาก|ดังนั้น|อย่างไรก็)'
    r'|(นะครับ|นะค่ะ|นะคะ|ครับ|ค่ะ|คะ|ล่ะ)\s+(?=[ก-๙A-Za-z0-9])',
    re.UNICODE,
)


def _split_at_thai_clauses(src: str) -> list[str]:
    """แยกที่ clause boundary ก่อน conjunction / หลัง particle
    คืน list ถ้าแบ่งได้ >1 ชิ้น, คืน [] ถ้าแบ่งไม่ได้
    """
    def _mark(m: re.Match) -> str:
        # กลุ่มที่ 1 = particle → เก็บ particle ไว้ แล้วใส่ marker
        return (m.group(1) + "\x00") if m.group(1) else "\x00"

    marked = _THAI_CLAUSE_RE.sub(_mark, src)
    parts = [p.strip() for p in marked.split("\x00") if p.strip()]
    return parts if len(parts) > 1 else []


def _chunk_by_words(src: str) -> list[str]:
    """แบ่ง src ที่ยาวเกิน _SOT_MAX_CHARS → pieces ตาม word boundary"""
    if len(src) <= _SOT_MAX_CHARS:
        return [src]
    # Thai word tokenize
    try:
        from pythainlp.tokenize import word_tokenize
        words = word_tokenize(src, engine='newmm')
        pieces, buf = [], ""
        for w in words:
            if buf and len(buf) + len(w) > _SOT_MAX_CHARS:
                pieces.append(buf)
                buf = w
            else:
                buf += w
        if buf:
            pieces.append(buf)
        # คืนผลเฉพาะเมื่อ tokenizer แบ่งได้จริง (>1 ชิ้น)
        # ถ้าได้ชิ้นเดียว (ยังยาว) → fall through ไป hard-cut
        if len(pieces) > 1:
            return pieces
    except Exception:
        pass
    # space-split (English / mixed)
    words = src.split()
    if len(words) > 1:
        pieces, buf = [], ""
        for w in words:
            candidate = (buf + " " + w).strip()
            if buf and len(candidate) > _SOT_MAX_CHARS:
                pieces.append(buf)
                buf = w
            else:
                buf = candidate
        if buf:
            pieces.append(buf)
        if len(pieces) > 1:
            return pieces
    # hard cut fallback
    return [src[i:i+_SOT_MAX_CHARS] for i in range(0, len(src), _SOT_MAX_CHARS)]


def _process_sot_lines(lines: list[str]) -> list[str]:
    """ซอยทุก line ที่ยาวเกิน _SOT_MAX_CHARS"""
    result = []
    for line in lines:
        result.extend(_chunk_by_words(line) if len(line) > _SOT_MAX_CHARS else [line])
    return result


_FINAL_PARTICLES = {
    # ไม่รวม 'นะ' เพราะ word_tokenize แยก 'นะครับ' → 'นะ'+'ครับ' ทำให้ตัดผิด
    # ไม่รวม 'ล่ะ','สิ','หน่า','จ้ะ','จ้า' — ปรากฏกลางประโยคได้
    'ครับ', 'ค่ะ', 'คะ', 'นะครับ', 'นะค่ะ', 'นะคะ',
}
_CLAUSE_STARTERS = {
    # เก็บเฉพาะ boundary ที่แข็งแรงจริง — ตัด โดย/ถ้า/หาก/อีกทั้ง/นอกจาก/ดังนั้น/อย่างไรก็ ออก
    'ซึ่ง', 'แต่', 'เพราะ',
}


_MIN_SENT_CHARS = 15  # ตัดเมื่อ accumulate >= 15 chars เท่านั้น (ป้องกัน particle โดดๆ และประโยคสั้นเกิน)


def _word_sent_split(src: str) -> list[str]:
    """ใช้ word_tokenize → แบ่งที่ particle / conjunction
    คืน list ถ้าแบ่งได้ >1 ชิ้น, คืน [] ถ้าแบ่งไม่ได้
    """
    try:
        from pythainlp.tokenize import word_tokenize
        words = word_tokenize(src, engine='newmm')
    except Exception:
        return []

    sentences, current = [], []
    for w in words:
        ws = w.strip()
        accumulated = ''.join(current).strip()

        # split BEFORE clause starters (มีเนื้อหาพอ)
        if ws in _CLAUSE_STARTERS and len(accumulated) >= _MIN_SENT_CHARS:
            sentences.append(accumulated)
            current = [w]
        else:
            current.append(w)
            # split AFTER sentence-final particle (มีเนื้อหาพอ)
            if ws in _FINAL_PARTICLES:
                sent = ''.join(current).strip()
                if len(sent) >= _MIN_SENT_CHARS:
                    sentences.append(sent)
                    current = []

    if current:
        sent = ''.join(current).strip()
        if sent:
            sentences.append(sent)

    return sentences if len(sentences) > 1 else []


def _split_sot_sentences(text: str) -> list[str]:
    """แยก paragraph → subtitle lines ≤ _SOT_MAX_CHARS chars
    1. \\n split
    2. word_tokenize + particle/conjunction split
    2.5 Thai clause boundaries (regex fallback)
    3. English punctuation split (. ! ?)
    4. word-boundary chunk
    """
    # ขั้น 1: newline
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) > 1:
        return _process_sot_lines(lines)

    src = lines[0] if lines else text.strip()

    # ขั้น 2: word_tokenize + particle/conjunction
    sents = _word_sent_split(src)
    if sents:
        return _process_sot_lines(sents)

    # ขั้น 2.5: Thai clause boundaries (regex)
    clause_parts = _split_at_thai_clauses(src)
    if clause_parts:
        return _process_sot_lines(clause_parts)

    # ขั้น 3: English/other punctuation
    parts = [p.strip() for p in re.split(r'(?<=[.!?])\s+', src) if p.strip()]
    if len(parts) > 1:
        return _process_sot_lines(parts)

    # ขั้น 4: chunk
    return _chunk_by_words(src)


def parse_pycut_doc(doc_id: str) -> dict:
    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id).execute()
    body = doc.get("body", {}).get("content", [])

    tables = [b for b in body if "table" in b]
    if not tables:
        raise ValueError("ไม่พบตารางใน Google Doc")

    result = {"format": "vertical", "has_subtitle": True, "title": "", "rows": []}

    info_table = None
    script_table = None

    for tbl in tables:
        raw_rows = tbl["table"].get("tableRows", [])
        if not raw_rows:
            continue
        header_text = " ".join(
            _cell_text(c) for c in raw_rows[0].get("tableCells", [])
        ).lower()
        if "footages" in header_text or "sub" in header_text:
            script_table = tbl
        else:
            info_table = tbl  # ตารางแรกที่ไม่ใช่ script = info

    # ── Info Table ──
    if info_table:
        for row in info_table["table"].get("tableRows", []):
            cells = row.get("tableCells", [])
            if len(cells) < 2:
                continue
            key = _cell_text(cells[0]).lower()
            val = _cell_text(cells[1])
            val_lower = val.lower()
            # Title
            if "title" in key and "text" not in key:
                result["title"] = val
            # Brief field — มีทั้ง format และ subtitle ในช่องเดียว
            elif "brief" in key or "format" in key:
                result["format"] = "horizontal" if ("นอน" in val_lower or "horizontal" in val_lower) else "vertical"
                result["has_subtitle"] = "subtitle" in val_lower or "ซับ" in val_lower

    # ── Script Table (fallback: ตารางใหญ่สุด) ──
    if not script_table:
        script_table = max(tables, key=lambda t: len(t["table"].get("tableRows", [])))

    sub_idx = 1  # global row index นับต่อเนื่อง
    last_footage: dict | None = None  # {"footage_raw": ..., "footage_type": ..., "file_id": ...}

    # ── ตรวจ column index ของ Insert จาก header row ──
    insert_col_idx: int | None = None
    _header_cells = script_table["table"].get("tableRows", [])[0].get("tableCells", [])
    for _ci, _hcell in enumerate(_header_cells):
        if "insert" in _cell_text(_hcell).lower():
            insert_col_idx = _ci
            break

    for row in script_table["table"].get("tableRows", [])[1:]:
        cells = row.get("tableCells", [])
        if len(cells) < 3:
            continue
        raw_footage_pairs = _cell_footage_list(cells[0])  # [(value, display), ...]
        tc_in_raw = _cell_text(cells[1])
        tc_out_raw = _cell_text(cells[2]) if len(cells) > 2 else ""
        bullets = _cell_bullets(cells[-1]) if len(cells) >= 2 else []
        tc_in = parse_tc(tc_in_raw)
        tc_out = parse_tc(tc_out_raw)

        # ── Extract Insert footage จาก dedicated column ──
        insert_footage_pairs = []
        if insert_col_idx is not None and insert_col_idx < len(cells):
            insert_footage_pairs = _cell_footage_list(cells[insert_col_idx])

        # ข้าม row ว่างเปล่าทั้งหมด (ไม่มี footage / TC / bullets / insert)
        if not raw_footage_pairs and tc_in is None and tc_out is None and not bullets and not insert_footage_pairs:
            continue

        # ตรวจ SOT marker ("ปล่อยเสียง:" ใน footage cell)
        sot = any(v.strip().lower().startswith("ปล่อยเสียง") for v, _ in raw_footage_pairs)
        footage_pairs = [(v, d) for v, d in raw_footage_pairs if not v.strip().lower().startswith("ปล่อยเสียง")]

        # ซอยทุก bullet ให้ ≤ _SOT_MAX_CHARS เสมอ (ทั้ง SOT และ VO)
        if bullets:
            split = []
            for b in bullets:
                split.extend(_split_sot_sentences(b))
            bullets = split

        if not footage_pairs:
            # ไม่มี footage — ถ้ามี TC ให้ใช้ footage ล่าสุด (inherit)
            has_tc = tc_in is not None or tc_out is not None
            if has_tc and last_footage:
                result["rows"].append({
                    "index": sub_idx,
                    **last_footage,
                    "tc_in": tc_in,
                    "tc_out": tc_out,
                    "bullets": bullets,
                    "sot": sot,
                    "inherited_footage": True,
                    "is_insert": False,
                })
            else:
                result["rows"].append({
                    "index": sub_idx,
                    "footage_raw": "",
                    "footage_display": "",
                    "footage_type": "none",
                    "file_id": None,
                    "tc_in": tc_in,
                    "tc_out": tc_out,
                    "bullets": bullets,
                    "sot": sot,
                    "is_insert": False,
                })
            sub_idx += 1
        else:
            for fi, (footage_raw, footage_display) in enumerate(footage_pairs):
                ft = detect_footage_type(footage_raw)
                result["rows"].append({
                    "index": sub_idx,
                    "footage_raw": footage_raw,
                    "footage_display": footage_display,
                    "footage_type": ft,
                    "file_id": extract_id(footage_raw) if ft == "drive" else None,
                    "tc_in": tc_in,
                    "tc_out": tc_out,
                    "bullets": bullets if fi == 0 else [],
                    "sot": sot if fi == 0 else False,
                    "is_insert": False,
                })
                sub_idx += 1
            # อัปเดต last_footage จากฟุตสุดท้ายใน row นี้
            last_raw, last_disp = footage_pairs[-1]
            last_ft = detect_footage_type(last_raw)
            last_footage = {
                "footage_raw": last_raw,
                "footage_display": last_disp,
                "footage_type": last_ft,
                "file_id": extract_id(last_raw) if last_ft == "drive" else None,
            }

        # ── Insert column: เพิ่มแถวแยกต่างหาก is_insert=True ──
        for footage_raw, footage_display in insert_footage_pairs:
            ft = detect_footage_type(footage_raw)
            result["rows"].append({
                "index": sub_idx,
                "footage_raw": footage_raw,
                "footage_display": footage_display,
                "footage_type": ft,
                "file_id": extract_id(footage_raw) if ft == "drive" else None,
                "tc_in": None,
                "tc_out": None,
                "bullets": [],
                "sot": False,
                "is_insert": True,
            })
            sub_idx += 1

    return result

# ──────────────────────────────────────────────────────────────
# SRT GENERATOR
# ──────────────────────────────────────────────────────────────
def _srt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _calc_duration(text: str) -> float:
    n = len(text.replace("\n", ""))
    return max(n / 16.0, 1.0)


def _split_line(text: str, is_vertical: bool, client) -> str:
    """ตัดบรรทัดภาษาไทยให้พอดีจอแนวตั้ง (เกิน MAX_CHARS_VERTICAL)

    ลำดับ priority:
    1. มี space → ตัดที่ space ใกล้กึ่งกลาง (ชื่อ + ตำแหน่ง, ทำงาน offline)
    2. ไม่มี space → PyThaiNLP tokenize → หา word boundary ใกล้กึ่งกลาง (offline)
    3. fallback → คืน text เดิม (ดีกว่าตัดกลางคำ)
    """
    if not is_vertical or len(text) <= MAX_CHARS_VERTICAL:
        return text

    # ── case 1: มี space (เช่น "เอกนิติ นิติทัณฑ์ประภาศ รองนายกรัฐมนตรี") ──
    if ' ' in text:
        spaces = [i for i, c in enumerate(text) if c == ' ']
        mid = len(text) / 2
        best = min(spaces, key=lambda i: abs(i - mid))
        return text[:best] + "\n" + text[best + 1:]

    # ── case 2: ไม่มี space → PyThaiNLP word tokenize ──
    try:
        from pythainlp.tokenize import word_tokenize
        words = word_tokenize(text, engine='newmm')
        if len(words) >= 2:
            # นับตัวอักษรสะสม หาจุดตัดที่ใกล้กึ่งกลางที่สุด
            total = sum(len(w) for w in words)
            mid = total / 2
            cumulative = 0
            best_idx = 0
            best_diff = float('inf')
            for i, w in enumerate(words):
                cumulative += len(w)
                diff = abs(cumulative - mid)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
            line1 = ''.join(words[:best_idx + 1])
            line2 = ''.join(words[best_idx + 1:])
            if line1 and line2:
                return f"{line1}\n{line2}"
    except Exception:
        pass

    return text


def build_srt(rows: list[dict], is_vertical: bool, client) -> str:
    """สร้าง SRT ด้วย CRLF (\\r\\n) ตาม spec — รองรับทุกโปรแกรมตัดต่อ

    - VO rows  (sot=False): reading speed (~16 chars/sec)
    - SOT rows (sot=True):  แบ่ง clip duration (tc_out - tc_in) ให้ bullets เท่าๆ กัน
                            ถ้าไม่มี TC → fallback reading speed
    """
    CRLF = "\r\n"
    blocks = []
    cursor = 0.0
    n = 1

    for row in rows:
        bullets = [b.strip() for b in row.get("bullets", []) if b.strip()]
        sot = row.get("sot", False)
        tc_in = row.get("tc_in")
        tc_out = row.get("tc_out")

        if not bullets:
            # SOT row ไม่มีซับ — เลื่อน cursor ตาม clip duration
            if sot and tc_in is not None and tc_out is not None and tc_out > tc_in:
                cursor += (tc_out - tc_in) + GAP_SEC
            continue

        if sot and tc_in is not None and tc_out is not None and tc_out > tc_in:
            clip_dur = tc_out - tc_in
            timestamps = row.get("sot_timestamps")  # [(ts, te)] จาก Gemini

            if timestamps and len(timestamps) >= len(bullets):
                # ── Gemini timing + script text ──
                for text, (ts, te) in zip(bullets, timestamps):
                    formatted = _split_line(text, is_vertical, client).replace("\n", CRLF)
                    block = (
                        f"{n}{CRLF}"
                        f"{_srt_ts(cursor + ts)} --> {_srt_ts(cursor + te)}{CRLF}"
                        f"{formatted}{CRLF}"
                    )
                    blocks.append(block)
                    n += 1
            else:
                # ── Fallback: แบ่ง clip duration เท่าๆ กัน ──
                each_dur = clip_dur / max(len(bullets), 1)
                for i, text in enumerate(bullets):
                    formatted = _split_line(text, is_vertical, client).replace("\n", CRLF)
                    block = (
                        f"{n}{CRLF}"
                        f"{_srt_ts(cursor + i * each_dur)} --> {_srt_ts(cursor + (i+1) * each_dur)}{CRLF}"
                        f"{formatted}{CRLF}"
                    )
                    blocks.append(block)
                    n += 1
            cursor += clip_dur + GAP_SEC
        else:
            # ── VO: reading speed ──
            for text in bullets:
                formatted = _split_line(text, is_vertical, client).replace("\n", CRLF)
                dur = _calc_duration(text)
                block = (
                    f"{n}{CRLF}"
                    f"{_srt_ts(cursor)} --> {_srt_ts(cursor + dur)}{CRLF}"
                    f"{formatted}{CRLF}"
                )
                blocks.append(block)
                cursor += dur + GAP_SEC
                n += 1

    return (CRLF).join(blocks)

# ──────────────────────────────────────────────────────────────
# DOWNLOAD ENGINE (social/web — yt-dlp)
# ──────────────────────────────────────────────────────────────

def get_source_tag(url: str) -> str:
    u = url.lower()
    if "youtube" in u or "youtu.be" in u: return "YT"
    if "facebook" in u or "fb.watch" in u: return "FB"
    if "instagram" in u: return "IG"
    if "tiktok" in u: return "TT"
    if "x.com" in u or "twitter" in u: return "X"
    if "getty" in u: return "Getty"
    if "reuters" in u: return "Reuters"
    return "Web"


def download_social(url: str, out_folder: str, log: list, status_cb=None) -> str | None:
    """ดาวน์โหลด social/web URL ด้วย yt-dlp → คืน path ไฟล์ที่โหลดได้ หรือ None"""
    clean_url = url.split('"')[0].strip()
    source_tag = get_source_tag(clean_url)
    os.makedirs(out_folder, exist_ok=True)

    downloaded_path: list[str] = []

    def _progress_hook(d):
        if d["status"] == "downloading":
            pct_str = d.get("_percent_str", "").strip().replace("\x1b[0;94m", "").replace("\x1b[0m", "")
            if status_cb and pct_str:
                status_cb(f"⬇️  {source_tag}  {pct_str}")
        elif d["status"] == "finished":
            downloaded_path.append(d["filename"])

    ydl_opts = {
        "format": (
            "bestvideo[ext=mp4][vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]"
            "/bestvideo[ext=mp4][vcodec!^=av01][height<=1080]+bestaudio[ext=m4a]"
            "/best[ext=mp4][height<=1080]/best"
        ),
        "merge_output_format": "mp4",
        "ffmpeg_location": FFMPEG_EXE if os.path.isfile(FFMPEG_EXE) else None,
        "quiet": True, "ignoreerrors": False, "no_warnings": True,
        "socket_timeout": 30, "retries": 3, "noplaylist": True,
        "outtmpl": os.path.join(out_folder, f"%(title).40s_{source_tag}.%(ext)s"),
        "windowsfilenames": True,
        "progress_hooks": [_progress_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            if info:
                final = ydl.prepare_filename(info)
                # yt-dlp อาจเปลี่ยน ext เป็น .mp4 หลัง merge
                for candidate in [final, os.path.splitext(final)[0] + ".mp4"]:
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                        log.append(f"    ✅ {source_tag}: {os.path.basename(candidate)}")
                        return candidate
                if downloaded_path:
                    p = downloaded_path[-1]
                    if os.path.exists(p) and os.path.getsize(p) > 0:
                        log.append(f"    ✅ {source_tag}: {os.path.basename(p)}")
                        return p
        log.append(f"    ❌ {source_tag}: ไม่พบไฟล์หลัง download")
        return None
    except Exception as e:
        log.append(f"    ❌ {source_tag} error: {e}")
        return None


def download_image_url(url: str, out_folder: str, log: list) -> str | None:
    """ดาวน์โหลดภาพจาก URL → คืน path หรือ None"""
    import requests as _req
    from urllib.parse import urlparse as _up
    os.makedirs(out_folder, exist_ok=True)
    clean_url = url.strip()
    ext = os.path.splitext(_up(clean_url).path)[1].lower() or ".jpg"
    fname = sanitize_filename(os.path.splitext(os.path.basename(_up(clean_url).path))[0] or "image") + ext
    out_path = os.path.join(out_folder, fname)
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        log.append(f"    → ใช้ภาพ cache: {fname}")
        return out_path
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "image/*,*/*;q=0.8",
        }
        r = _req.get(clean_url, headers=headers, timeout=30, stream=True)
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        if os.path.getsize(out_path) == 0:
            os.remove(out_path)
            log.append(f"    ❌ ภาพว่างเปล่า: {fname}")
            return None
        log.append(f"    ✅ ภาพ: {fname}")
        return out_path
    except Exception as e:
        log.append(f"    ❌ download ภาพล้มเหลว: {e}")
        if os.path.exists(out_path):
            os.remove(out_path)
        return None


# ──────────────────────────────────────────────────────────────
# FOOTAGE PIPELINE
# ──────────────────────────────────────────────────────────────
_DRIVE_VIDEO_MIMES = {
    "video/mp4", "video/quicktime", "video/x-msvideo",
    "video/x-matroska", "video/mxf", "video/x-m4v",
}

def _download_single_file(service, file_id: str, out_path: str, log, label: str, status_cb=None) -> bool:
    """ดาวน์โหลด 1 ไฟล์ → out_path คืน True ถ้าสำเร็จ"""
    req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.FileIO(out_path, "wb")
    dl = MediaIoBaseDownload(fh, req)
    done = False
    while not done:
        status, done = dl.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log(f"    → {label}: {pct}%")
            if status_cb:
                status_cb(f"⬇️  {label}  {pct}%")
    fh.close()
    size = os.path.getsize(out_path)
    if size == 0:
        os.remove(out_path)
        log(f"    ❌ {label} — 0 bytes")
        return False
    log(f"    ✅ {label} ({size:,} bytes)")
    return True


def _find_cached_file(folder: str, drive_name: str) -> str | None:
    """ค้นหาไฟล์ใน folder ที่ชื่อตรงกับ drive_name (เปรียบเทียบ stem ไม่สน case/sanitize)"""
    if not os.path.isdir(folder):
        return None
    target = os.path.splitext(sanitize_filename(drive_name).lower())[0]
    for fname in os.listdir(folder):
        if fname.startswith('.'):
            continue
        stem = os.path.splitext(fname.lower())[0]
        if stem == target:
            full = os.path.join(folder, fname)
            if os.path.isfile(full) and os.path.getsize(full) > 0:
                return full
    return None


def download_drive_file(service, file_id: str, row_idx: int, out_folder: str, log: list | None = None, status_cb=None) -> str | None:
    def _log(msg):
        if log is not None:
            log.append(msg)
    try:
        meta = service.files().get(
            fileId=file_id, fields="name,mimeType", supportsAllDrives=True
        ).execute()
        mime = meta.get("mimeType", "")
        name = meta.get("name", f"footage_{row_idx:02d}")
        _log(f"    → meta: {name} ({mime})")

        # ── Folder: ดึงไฟล์วิดีโอข้างใน ──
        if mime == "application/vnd.google-apps.folder":
            _log(f"    → เป็น Folder — list files ข้างใน...")
            results = service.files().list(
                q=f"'{file_id}' in parents and trashed=false",
                corpora="allDrives", supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="files(id,name,mimeType)",
                orderBy="name",
            ).execute()
            children = results.get("files", [])
            video_files = [f for f in children if f.get("mimeType", "") in _DRIVE_VIDEO_MIMES]
            if not video_files:
                video_files = [f for f in children if f.get("mimeType", "") != "application/vnd.google-apps.folder"]
            if not video_files:
                _log(f"    ❌ ไม่พบไฟล์วิดีโอใน folder")
                return None
            if len(video_files) > 1:
                file_names = [f["name"] for f in video_files]
                _log(f"    ⚠️ folder มี {len(video_files)} ไฟล์: {file_names}")
                return {"conflict": True, "folder_name": name, "files": file_names}
            child = video_files[0]
            _log(f"    → พบ 1 ไฟล์ใน folder: {child['name']}")
            cached = _find_cached_file(out_folder, child["name"])
            if cached:
                _log(f"    → ใช้ไฟล์ cache: {os.path.basename(cached)}")
                if status_cb: status_cb(f"📦  {child['name']}  (cache)")
                return cached
            out_path = os.path.join(out_folder, sanitize_filename(child["name"]))
            ok = _download_single_file(service, child["id"], out_path, _log, child["name"], status_cb=status_cb)
            return out_path if ok else None

        # ── ไฟล์ปกติ ──
        cached = _find_cached_file(out_folder, name)
        if cached:
            _log(f"    → ใช้ไฟล์ cache: {os.path.basename(cached)}")
            if status_cb: status_cb(f"📦  {name}  (cache)")
            return cached
        out_path = os.path.join(out_folder, sanitize_filename(name))
        ok = _download_single_file(service, file_id, out_path, _log, name, status_cb=status_cb)
        return out_path if ok else None

    except Exception as e:
        _log(f"    ❌ download error: {e}")
        return None


def _unique_cut_path(folder: str, name: str) -> str:
    """คืน path ที่ไม่ซ้ำใน folder — ถ้าซ้ำ ต่อท้าย _01, _02, ..."""
    base, ext = os.path.splitext(name)
    candidate = os.path.join(folder, name)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{base}_{n:02d}{ext}")
        n += 1
    return candidate


def cut_video(input_path: str, out_path: str, tc_in: float | None, tc_out: float | None, log: list | None = None, pad: bool = True) -> bool:
    def _log(msg):
        if log is not None:
            log.append(msg)

    if tc_in is None and tc_out is None:
        shutil.copy(input_path, out_path)
        return True

    _PAD = 1.0 if pad else 0.0
    start = max(0.0, float(tc_in) - _PAD) if tc_in is not None else 0.0
    dur = (float(tc_out) + _PAD) - start if tc_out is not None else None

    # ── ขั้น 1: re-encode (รองรับไฟล์ใหญ่, MXF, keyframe ไม่ตรง) ──
    temp_out = out_path.rsplit(".", 1)[0] + "_temp.mp4"
    cmd = [FFMPEG_EXE, "-y"]
    if start > 0:
        cmd += ["-ss", str(start)]
    cmd += ["-i", input_path]
    if dur is not None and dur > 0:
        cmd += ["-t", str(dur)]
    cmd += ["-threads", "0", "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast", "-c:a", "aac", temp_out]

    res = subprocess.run(cmd, capture_output=True)
    stderr = res.stderr.decode("utf-8", errors="ignore")

    if res.returncode == 0 and os.path.exists(temp_out) and os.path.getsize(temp_out) > 1024:
        os.rename(temp_out, out_path)
        return True

    # ── error: log ffmpeg stderr tail ──
    err_tail = stderr.strip().splitlines()
    err_tail = err_tail[-3:] if err_tail else [f"returncode={res.returncode}"]
    _log(f"    ❌ ffmpeg cut error: {' | '.join(err_tail)}")
    if os.path.exists(temp_out):
        os.remove(temp_out)

    # ── fallback: -c copy (เผื่อ re-encode ไม่ได้เพราะ codec แปลก) ──
    _log(f"    → fallback -c copy...")
    cmd2 = [FFMPEG_EXE, "-y", "-ss", str(start), "-i", input_path]
    if dur is not None and dur > 0:
        cmd2 += ["-t", str(dur)]
    cmd2 += ["-c", "copy", out_path]
    res2 = subprocess.run(cmd2, capture_output=True)
    if res2.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
        return True

    err2 = res2.stderr.decode("utf-8", errors="ignore").strip().splitlines()
    _log(f"    ❌ fallback error: {' | '.join(err2[-2:]) if err2 else 'unknown'}")
    if os.path.exists(out_path):
        os.remove(out_path)
    return False


def _extract_audio_clip(video_path: str, fmt: str = "wav") -> str | None:
    """แปลง video → mono 16kHz audio (wav สำหรับ Whisper, mp3 สำหรับ Gemini)"""
    tmp = video_path.rsplit(".", 1)[0] + f"_sot_audio.{fmt}"
    if fmt == "wav":
        cmd = [FFMPEG_EXE, "-y", "-i", video_path,
               "-vn", "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", tmp]
    else:
        cmd = [FFMPEG_EXE, "-y", "-i", video_path,
               "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", tmp]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
        return tmp
    return None


def _analyze_sot_timing_whisper(
    audio_path: str, sentences: list[str], log: list
) -> list[tuple[str, float, float]]:
    """Transcribe audio → [(text, start_sec, end_sec), ...] subtitle blocks

    Thai speech   → ใช้ Whisper segment text + timestamps โดยตรง (sync แม่น)
    Non-Thai      → ใช้ script sentences + proportional timing (เสียงแปลไทย)
    """
    try:
        model = _get_whisper_model("medium")
    except ImportError:
        log.append("  ⚠️ faster-whisper ไม่ได้ติดตั้ง — pip install faster-whisper")
        return []

    try:
        log.append("  🔊 Whisper transcribing...")
        segs, info = model.transcribe(
            audio_path,
            word_timestamps=True,
            language=None,
            beam_size=5,
            vad_filter=True,
        )
        seg_list = list(segs)  # consume generator

        if not seg_list:
            log.append("  ⚠️ Whisper: ไม่พบเสียงพูด")
            return []

        log.append(
            f"  🔊 Whisper: {len(seg_list)} segs | lang={info.language} ({info.language_probability:.0%})"
        )

        # ── Thai speech: ใช้ Whisper segments โดยตรง ──
        if info.language == "th":
            blocks: list[tuple[str, float, float]] = []
            for seg in seg_list:
                text = seg.text.strip()
                if not text:
                    continue
                pieces = _split_sot_sentences(text)
                if len(pieces) == 1:
                    blocks.append((text, seg.start, seg.end))
                else:
                    dur = seg.end - seg.start
                    total_c = sum(len(p) for p in pieces)
                    t = seg.start
                    for piece in pieces:
                        d = len(piece) / max(total_c, 1) * dur
                        blocks.append((piece, t, t + d))
                        t += d
            return blocks

        # ── Non-Thai (เสียงต่างประเทศ ซับไทย): proportional alignment ──
        words: list[tuple[str, float, float]] = [
            (w.word, w.start, w.end)
            for seg in seg_list for w in (seg.words or [])
        ]
        if not words:
            return []

        total_chars = sum(len(s) for s in sentences)
        total_words = len(words)
        blocks = []
        word_cursor = 0

        for i, sent in enumerate(sentences):
            if word_cursor >= total_words:
                last = blocks[-1][2] if blocks else words[-1][2]
                blocks.append((sent, last + 0.05, last + 1.0))
                continue
            if i == len(sentences) - 1:
                chunk = words[word_cursor:]
            else:
                ratio = len(sent) / max(total_chars, 1)
                n = max(1, round(ratio * total_words))
                max_n = total_words - word_cursor - (len(sentences) - i - 1)
                n = min(n, max_n)
                chunk = words[word_cursor:word_cursor + n]
                word_cursor += n
            if chunk:
                blocks.append((sent, chunk[0][1], chunk[-1][2]))
            else:
                last = blocks[-1][2] if blocks else 0.0
                blocks.append((sent, last + 0.05, last + 1.0))

        return blocks

    except Exception as e:
        log.append(f"  ⚠️ Whisper error: {e}")
        return []


def _analyze_sot_timing(audio_path: str, sentences: list[str], client, log: list) -> list[tuple[float, float]]:
    """ส่ง audio clip → Gemini → คืน [(start_sec, end_sec), ...] ต่อ sentence
    - rotate key เมื่อ 429
    - fallback model ถ้า key หมด
    - คืน [] ถ้าทุก attempt ล้มเหลว (caller จะ fallback แบ่งเวลาเท่ากัน)
    """
    import json as _json
    from google.genai import types as _gtypes

    if not sentences:
        return []

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
    if len(audio_bytes) > 19 * 1024 * 1024:
        log.append(f"  ⚠️ SOT audio ใหญ่เกิน 19 MB — ข้าม Gemini timing")
        return []

    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))
    prompt = (
        "ในไฟล์เสียงนี้มีเสียงพูด โปรดระบุว่าแต่ละประโยคต่อไปนี้เริ่มและจบที่กี่วินาทีใน audio\n\n"
        f"ประโยค:\n{numbered}\n\n"
        "ตอบเป็น JSON array เท่านั้น ไม่ต้องอธิบาย ตัวอย่าง:\n"
        '[{"idx":1,"start":0.0,"end":3.5},{"idx":2,"start":3.8,"end":7.1}]'
    )

    keys = _gemini_keys()
    if not keys:
        log.append(f"  ⚠️ ไม่มี Gemini key")
        return []

    for model, api_ver in _SOT_MODELS:
        for key in keys:
            try:
                c = genai.Client(api_key=key, http_options={"api_version": api_ver})
                resp = c.models.generate_content(
                    model=model,
                    contents=[
                        _gtypes.Part.from_bytes(data=audio_bytes, mime_type="audio/mpeg"),
                        prompt,
                    ],
                )
                raw = resp.text.strip()
                m = re.search(r'\[.*?\]', raw, re.DOTALL)
                if not m:
                    log.append(f"  ⚠️ {model}: ไม่พบ JSON")
                    continue
                data = _json.loads(m.group())
                result: list[tuple[float, float]] = []
                for item in sorted(data, key=lambda x: x.get("idx", 0)):
                    s = float(item.get("start", 0))
                    e = float(item.get("end", s + 2.0))
                    result.append((s, e))
                while len(result) < len(sentences):
                    last_end = result[-1][1] if result else 0.0
                    result.append((last_end + 0.2, last_end + 2.2))
                log.append(f"  🎙️ SOT timing: {len(result)} timestamps ← {model}")
                return result[:len(sentences)]
            except Exception as _e:
                err_str = str(_e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    log.append(f"  ↩ {model} key[...{key[-4:]}] quota หมด — ลอง key ถัดไป")
                    continue
                log.append(f"  ⚠️ {model}: {err_str[:120]}")
                break  # error อื่น (404 etc.) → ข้ามไป model ถัดไปเลย

    log.append(f"  ⚠️ SOT timing: ทุก key/model ล้มเหลว — ใช้ fallback แบ่งเวลาเท่ากัน")
    return []

# ──────────────────────────────────────────────────────────────
# CUT + SOT HELPER (ใช้ซ้ำทุก footage type)
# ──────────────────────────────────────────────────────────────

def _do_cut_and_sot(raw: str, idx: int, row: dict, cut_folder: str,
                    cut_by_tc: bool, pad_cut: bool, gclient,
                    log: list, status_ref: dict, key: str, set_status) -> str | None:
    """ตัดตาม TC (ถ้ามี) + วิเคราะห์ SOT timing → คืน final_path หรือ None ถ้าล้มเหลว
    insert rows: copy ไปยัง cut_folder โดยไม่ตัด TC
    """
    log.append(f"    → พร้อม: {os.path.basename(raw)}")
    final_path = raw
    is_insert = row.get("is_insert", False)

    if is_insert:
        # insert: copy ทั้งไฟล์ไปยัง Cut Footages ไม่ตัด TC
        orig_stem = os.path.splitext(os.path.basename(raw))[0]
        copy_path = _unique_cut_path(cut_folder, f"{idx:02d}_{orig_stem}{os.path.splitext(raw)[1]}")
        shutil.copy2(raw, copy_path)
        log.append(f"    → INSERT copy: {os.path.basename(copy_path)}")
        return copy_path

    if cut_by_tc and (row["tc_in"] is not None or row["tc_out"] is not None):
        orig_stem = os.path.splitext(os.path.basename(raw))[0]
        cut_path = _unique_cut_path(cut_folder, f"{idx:02d}_{orig_stem}.mp4")
        tc_disp = (f"{row['tc_in']:.1f}s → {row['tc_out']:.1f}s"
                   if row["tc_in"] is not None and row["tc_out"] is not None else "—")
        set_status(f"✂️  #{idx:02d} — ตัด {tc_disp}")
        ok = cut_video(raw, cut_path, row["tc_in"], row["tc_out"], log, pad=pad_cut)
        if ok:
            log.append(f"    → ตัดสำเร็จ: {os.path.basename(cut_path)}")
            final_path = cut_path
        else:
            log.append(f"    ⚠️ ตัดล้มเหลว — ใช้ไฟล์ต้นฉบับ")
            status_ref[key] = "error"
            return None

    if row.get("sot") and row["bullets"] and gclient:
        log.append(f"    🎙️ วิเคราะห์ SOT timing row {idx}...")
        set_status(f"🎙️  #{idx:02d} — วิเคราะห์ SOT เสียง...")
        audio_mp3 = _extract_audio_clip(final_path, fmt="mp3")
        if audio_mp3:
            timing = _analyze_sot_timing(audio_mp3, row["bullets"], gclient, log)
            try:
                os.remove(audio_mp3)
            except Exception:
                pass
            if timing:
                row["sot_timestamps"] = timing

    return final_path


# ──────────────────────────────────────────────────────────────
# STOCK HELPERS
# ──────────────────────────────────────────────────────────────
VIDEO_EXTS = ('.mp4', '.mov', '.m4v', '.avi', '.mxf', '.mkv')


def _extract_stock_code(footage_raw: str, footage_type: str) -> str:
    """ดึง search_id สำหรับ match ชื่อไฟล์ — ใช้ logic เดียวกับ PyRUSH scan_file_location"""
    raw = footage_raw.strip()
    if footage_type == "reuters":
        # Reuters: RW201719052026RP1 → ดึงเฉพาะตัวเลขยาวที่สุด → "201719052026"
        # เหมือน PyRUSH: strip RW/RC แล้ว search filename ด้วย numeric part
        m = re.search(r'\b(?:RW|RC)([0-9]{6,})', raw, re.IGNORECASE)
        if m:
            return m.group(1).lower()
        # fallback: strip RW/RC แล้วเอาทั้งหมด
        m2 = re.search(r'\b((?:RW|RC)[A-Z0-9]+)\b', raw, re.IGNORECASE)
        code = m2.group(1) if m2 else raw
        if code.lower().startswith(('rw', 'rc')):
            code = code[2:]
        return code.lower()
    if footage_type == "getty":
        m = re.search(r'/detail/[^/]+/([a-zA-Z0-9_-]+)', raw)
        if m:
            return m.group(1).lower()
        if re.match(r'^\d{7,12}$', raw):
            return raw.lower()
        return raw.rstrip('/').split('/')[-1].split('?')[0].lower()
    return raw.lower()


MAX_OPEN_TABS = 10

def make_open_ci_button(urls, button_text, color_hex, project_name="PyCUT"):
    valid_urls = [u for u in urls if str(u).startswith('http')]
    if not valid_urls: return
    total = len(valid_urls)
    safe_project_name = project_name.replace("'", "\\'").replace('"', '\\"')

    if total <= MAX_OPEN_TABS:
        js_links = " ".join([f"setTimeout(() => window.open('{u}', '_blank'), {i*400});" for i, u in enumerate(valid_urls)])
        js_code = f"navigator.clipboard.writeText('{safe_project_name}'); {js_links}"
        html = f"""
        <button onclick="{js_code}"
        style="padding: 10px 15px; background-color: #1a1e26; color: {color_hex};
        border: 1px solid {color_hex}; border-radius: 8px; cursor: pointer; font-weight: bold;
        width: 100%; margin-bottom: 8px; font-family: 'IBM Plex Sans Thai', sans-serif; transition: background-color 0.15s;"
        onmouseover="this.style.backgroundColor='{color_hex}22'"
        onmouseout="this.style.backgroundColor='#1a1e26'">
        🚀 {button_text} ({total} แท็บ)
        </button>
        """
        components.html(html, height=55)
    else:
        batches = [valid_urls[i:i+MAX_OPEN_TABS] for i in range(0, total, MAX_OPEN_TABS)]
        n = len(batches)
        safe_key = re.sub(r'[^\w]', '_', button_text + '_' + project_name[:15])[:40]

        buttons_html = ""
        restore_js_parts = []
        for i, batch in enumerate(batches):
            start = i * MAX_OPEN_TABS + 1
            end = start + len(batch) - 1
            lbl = f"{start}–{end}"
            sk = f"pycut_{safe_key}_{i}"
            js_links = " ".join([f"setTimeout(()=>window.open('{u}','_blank'),{j*400});" for j, u in enumerate(batch)])
            js_click = (
                f"navigator.clipboard.writeText('{safe_project_name}');"
                f"{js_links}"
                f"localStorage.setItem('{sk}','1');"
                f"this.classList.add('opened');"
                f"this.querySelector('.lbl').textContent='✅ {lbl}';"
            )
            buttons_html += (
                f'<button id="b{i}" class="batch-btn" onclick="{js_click}">'
                f'<span class="lbl">🚀 {lbl}</span>'
                f'</button>'
            )
            restore_js_parts.append(
                f"if(localStorage.getItem('{sk}')){{var b=document.getElementById('b{i}');"
                f"if(b){{b.classList.add('opened');b.querySelector('.lbl').textContent='✅ {lbl}';}}}}"
            )

        restore_js = "\n".join(restore_js_parts)
        height = 30 + ((n + 4) // 5) * 44

        html = f"""
        <style>
        .batch-btn{{padding:7px 11px;background:#1a1e26;color:{color_hex};border:1px solid {color_hex};
        border-radius:8px;cursor:pointer;font-weight:bold;font-family:'IBM Plex Sans Thai',sans-serif;
        font-size:12px;transition:all .15s;margin:0 4px 6px 0;}}
        .batch-btn:hover{{background:{color_hex}22;}}
        .batch-btn.opened{{background:{color_hex}18;opacity:.5;border-style:dashed;cursor:default;}}
        .bh{{color:{color_hex}99;font-family:'IBM Plex Sans Thai',sans-serif;font-size:11px;margin-bottom:4px;}}
        </style>
        <div class="bh">🚀 {button_text} — {total} รายการ · {n} ชุด</div>
        <div style="display:flex;flex-wrap:wrap;">{buttons_html}</div>
        <script>(function(){{{restore_js}}})();</script>
        """
        components.html(html, height=height)


# ──────────────────────────────────────────────────────────────
# WATCHDOG LOOP
# ──────────────────────────────────────────────────────────────
def watchdog_loop(
    watch_folder: str,
    pending: dict,
    output_folder: str,
    stop_event: threading.Event,
    cut_by_tc: bool,
    status_ref: dict,
    result_holder: dict,
    gclient=None,
    parsed_rows: list | None = None,
    is_vertical: bool = False,
    srt_save_path: str | None = None,
    pad_cut: bool = True,
):
    """สแกน watch_folder ทุก 2 วิ — match ชื่อไฟล์ที่มี stock code → ตัด → output_folder
    pending = { stock_code: [ {row_key, row_idx, tc_in, tc_out, sot, sot_sentences}, ... ] }
    ถ้า row มี sot=True และมี gclient → วิเคราะห์ timing ด้วย Gemini Audio หลัง cut
    """
    log = result_holder.setdefault("log", [])
    # สร้าง index: row_key → row dict เพื่อ update sot_blocks ภายหลัง
    row_index = {str(r["index"]): r for r in (parsed_rows or [])}

    while not stop_event.is_set():
        done_codes = []
        try:
            if not os.path.isdir(watch_folder):
                time.sleep(2)
                continue
            files = [f for f in os.listdir(watch_folder)
                     if not f.startswith('.') and os.path.splitext(f)[1].lower() in VIDEO_EXTS]
        except Exception:
            time.sleep(2)
            continue

        for code, info_list in list(pending.items()):
            matched_file = None
            for fname in files:
                if fname.startswith('._'):
                    continue
                if code in fname.lower() and os.path.getsize(os.path.join(watch_folder, fname)) > 0:
                    matched_file = fname
                    break
            if not matched_file:
                continue
            src = os.path.join(watch_folder, matched_file)
            ext = os.path.splitext(matched_file)[1].lower()

            # ── copy ไฟล์ต้นฉบับเข้า Raw Footages/<Getty|Reuters> ──
            # ใช้ stock_dir จาก info แรกของ code (ทุก info ใน code เดียวกันมี stock_dir เดียวกัน)
            _stock_dir = info_list[0].get("stock_dir") or os.path.join(output_folder, "Raw Footages")
            os.makedirs(_stock_dir, exist_ok=True)
            raw_copy = os.path.join(_stock_dir, matched_file)
            if not os.path.exists(raw_copy):
                try:
                    shutil.copy2(src, raw_copy)
                    log.append(f"  → บันทึก Raw ({os.path.basename(_stock_dir)}): {matched_file}")
                except Exception as _ce:
                    log.append(f"  ⚠️ copy Raw ล้มเหลว: {_ce}")

            all_done = True
            for info in info_list:
                orig_stem = os.path.splitext(matched_file)[0]
                cut_dir = info.get("insert_out_dir") if info.get("is_insert") else os.path.join(output_folder, "Cut Footages")
                os.makedirs(cut_dir, exist_ok=True)
                if info.get("is_insert"):
                    out_path = _unique_cut_path(cut_dir, f"{orig_stem}{ext}")
                else:
                    _cut_n = info.get("cut_idx", info["row_idx"])
                    out_path = _unique_cut_path(cut_dir, f"{_cut_n:02d}_{orig_stem}.mp4")
                out_name = os.path.basename(out_path)
                try:
                    if cut_by_tc and (info["tc_in"] is not None or info["tc_out"] is not None):
                        _tc_disp = f"{info['tc_in']:.1f}s → {info['tc_out']:.1f}s" if info["tc_in"] is not None and info["tc_out"] is not None else "—"
                        result_holder["status_text"] = f"✂️  #{info['row_idx']:02d} — ตัด {_tc_disp}"
                        ok = cut_video(src, out_path, info["tc_in"], info["tc_out"], log, pad=pad_cut)
                        if not ok:
                            all_done = False
                            log.append(f"  ❌ watchdog cut ล้มเหลว: row{info['row_idx']}")
                            status_ref[info["row_key"]] = "error"
                            continue
                    else:
                        shutil.copy(src, out_path)
                    status_ref[info["row_key"]] = "done"
                    log.append(f"  ✅ watchdog ตัด: {matched_file} → {out_name}")

                    # ── SOT timing: Gemini Audio ──
                    if info.get("sot") and info.get("sot_sentences") and gclient and os.path.exists(out_path):
                        log.append(f"  🎙️ วิเคราะห์ SOT timing row {info['row_idx']}...")
                        audio_mp3 = _extract_audio_clip(out_path, fmt="mp3")
                        if audio_mp3:
                            timing = _analyze_sot_timing(audio_mp3, info["sot_sentences"], gclient, log)
                            try:
                                os.remove(audio_mp3)
                            except Exception:
                                pass
                            if timing:
                                rk = info["row_key"]
                                if rk in row_index:
                                    row_index[rk]["sot_timestamps"] = timing

                except Exception as e:
                    all_done = False
                    log.append(f"  ❌ watchdog error {code} row{info['row_idx']}: {e}")
            if all_done:
                done_codes.append(code)

        for c in done_codes:
            pending.pop(c, None)

        if not pending:
            # ── Rebuild SRT ถ้ามี SOT timestamps ใหม่ ──
            if parsed_rows and any(r.get("sot_timestamps") for r in parsed_rows):
                log.append("  🔄 Rebuild SRT พร้อม SOT timestamps...")
                try:
                    new_srt = build_srt(parsed_rows, is_vertical, gclient)
                    result_holder["srt_content"] = new_srt
                    if srt_save_path:
                        with open(srt_save_path, "w", encoding="utf-8-sig", newline="") as f:
                            f.write(new_srt)
                        log.append(f"  ✅ SRT อัปเดต → {srt_save_path}")
                except Exception as e:
                    log.append(f"  ⚠️ Rebuild SRT error: {e}")

            stop_event.set()
            result_holder["done"] = True
            result_holder["status_text"] = "✅  เสร็จแล้ว!"
            break

        time.sleep(2)

# ──────────────────────────────────────────────────────────────
# RUN ORCHESTRATOR
# ──────────────────────────────────────────────────────────────
def run_pycut(parsed: dict, settings: dict, output_folder: str, stock_watch_folder: str, status_ref: dict, result_holder: dict):
    """Thread target — ห้ามแตะ st.session_state โดยตรง ใช้ status_ref / result_holder แทน"""
    is_vertical = settings["is_vertical"]
    do_srt = settings["make_srt"]
    do_dl = settings["download_footage"]
    cut_by_tc = settings["cut_by_tc"]
    pad_cut = settings.get("pad_cut", True)
    log = result_holder.setdefault("log", [])

    def _set_status(text: str):
        result_holder["status_text"] = text

    has_stock = False
    try:
        log.append(f"▶ เริ่ม — do_srt={do_srt} do_dl={do_dl} cut_by_tc={cut_by_tc} pad={pad_cut}")
        log.append(f"  rows: {len(parsed['rows'])} รายการ")
        _set_status("🔄  เริ่มต้น...")

        gclient = _gemini_client() if do_srt else None
        drive_svc = get_drive_service() if do_dl else None
        title_safe = sanitize_filename(parsed.get("title", "subtitle"))
        srt_path = os.path.join(output_folder, f"{title_safe}.srt")

        # สร้าง subfolders
        raw_folder   = os.path.join(output_folder, "Raw Footages")
        cut_folder   = os.path.join(output_folder, "Cut Footages")
        raw_drive    = os.path.join(raw_folder, "Drive")
        raw_social   = os.path.join(raw_folder, "Social")
        raw_others   = os.path.join(raw_folder, "Others")
        raw_getty    = os.path.join(raw_folder, "Getty")
        raw_reuters  = os.path.join(raw_folder, "Reuters")
        raw_images   = os.path.join(raw_folder, "Images")
        for _d in [raw_folder, cut_folder, raw_drive, raw_social, raw_others, raw_getty, raw_reuters, raw_images]:
            os.makedirs(_d, exist_ok=True)

        def _save_srt():
            """Build + save SRT — เรียกหลัง Drive SOT timestamps พร้อมแล้ว"""
            if not do_srt:
                return
            srt_rows = parsed["rows"]
            total_bullets = sum(len(r["bullets"]) for r in srt_rows)
            sot_count = sum(1 for r in srt_rows if r.get("sot"))
            log.append(f"  📝 Build SRT: {total_bullets} bullets | SOT rows: {sot_count}")
            if total_bullets == 0:
                return
            _set_status("✍️  สร้าง SRT...")
            srt_text = build_srt(srt_rows, is_vertical, gclient)
            result_holder["srt_content"] = srt_text
            try:
                with open(srt_path, "w", encoding="utf-8-sig", newline="") as f:
                    f.write(srt_text)
                log.append(f"  ✅ บันทึก SRT → {srt_path}")
            except Exception as e:
                log.append(f"  ⚠️ บันทึก SRT ล้มเหลว: {e}")

        # Footage
        insert_folder = os.path.join(output_folder, "Insert Footages")
        stock_pending = {}
        main_idx = 0
        for row in parsed["rows"]:
            if row.get("is_insert"):
                continue  # Insert rows processed separately below
            idx = row["index"]
            key = str(idx)
            ft = row["footage_type"]
            if ft != "none":
                main_idx += 1
            log.append(f"  row {idx:02d}: type={ft} file_id={row.get('file_id')} do_dl={do_dl}")

            if not do_dl:
                status_ref[key] = "skipped"
                continue

            if ft == "drive" and row["file_id"]:
                status_ref[key] = "downloading"
                log.append(f"    → download Drive {row['file_id']}")
                _set_status(f"⬇️  #{idx:02d} — กำลังโหลด (Drive)...")
                raw = download_drive_file(drive_svc, row["file_id"], idx, raw_drive, log, status_cb=_set_status)

                if isinstance(raw, dict) and raw.get("conflict"):
                    status_ref[key] = "folder_conflict"
                    conflicts = result_holder.setdefault("folder_conflicts", [])
                    conflicts.append({
                        "row_idx": idx,
                        "file_id": row["file_id"],
                        "folder_name": raw["folder_name"],
                        "files": raw["files"],
                        "tc_in": row["tc_in"],
                        "tc_out": row["tc_out"],
                    })
                    log.append(f"    ⚠️ รอผู้ใช้เปลี่ยน link เป็นไฟล์เดียว")
                elif raw and os.path.exists(raw):
                    raw = _do_cut_and_sot(raw, main_idx, row, cut_folder, cut_by_tc, pad_cut, gclient, log, status_ref, key, _set_status)
                    if raw:
                        status_ref[key] = "done"
                else:
                    log.append(f"    ❌ ดาวน์โหลดล้มเหลว (raw={raw})")
                    status_ref[key] = "error"

            elif ft in ("social", "other") and row["footage_raw"].strip():
                url = row["footage_raw"].strip()
                src_dir = raw_social if ft == "social" else raw_others
                src_tag = get_source_tag(url)
                status_ref[key] = "downloading"
                log.append(f"    → download {src_tag}: {url[:50]}")
                _set_status(f"⬇️  #{idx:02d} — กำลังโหลด ({src_tag})...")
                raw = download_social(url, src_dir, log, status_cb=_set_status)
                if raw and os.path.exists(raw):
                    raw = _do_cut_and_sot(raw, main_idx, row, cut_folder, cut_by_tc, pad_cut, gclient, log, status_ref, key, _set_status)
                    if raw:
                        status_ref[key] = "done"
                else:
                    log.append(f"    ❌ ดาวน์โหลดล้มเหลว")
                    status_ref[key] = "error"

            elif ft == "image" and row["footage_raw"].strip():
                url = row["footage_raw"].strip()
                status_ref[key] = "downloading"
                log.append(f"    → download ภาพ: {url[:50]}")
                _set_status(f"⬇️  #{idx:02d} — กำลังโหลดภาพ...")
                raw = download_image_url(url, raw_images, log)
                if raw and os.path.exists(raw):
                    # copy ไปยัง Cut Footages พร้อม index prefix
                    img_ext = os.path.splitext(raw)[1]
                    orig_stem = os.path.splitext(os.path.basename(raw))[0]
                    cut_img = _unique_cut_path(cut_folder, f"{main_idx:02d}_{orig_stem}{img_ext}")
                    shutil.copy2(raw, cut_img)
                    log.append(f"    → ภาพ → Cut Footages: {os.path.basename(cut_img)}")
                    status_ref[key] = "done"
                else:
                    log.append(f"    ❌ โหลดภาพล้มเหลว")
                    status_ref[key] = "error"

            elif ft in ("getty", "reuters") and row["footage_raw"].strip():
                status_ref[key] = "waiting_stock"
                stock_dir = raw_getty if ft == "getty" else raw_reuters
                code = _extract_stock_code(row["footage_raw"], ft)
                if code not in stock_pending:
                    stock_pending[code] = []
                stock_pending[code].append({
                    "row_key": key,
                    "row_idx": idx,
                    "cut_idx": main_idx,
                    "tc_in": row["tc_in"],
                    "tc_out": row["tc_out"],
                    "sot": row.get("sot", False),
                    "sot_sentences": row["bullets"] if row.get("sot") else [],
                    "stock_dir": stock_dir,
                })
                log.append(f"    → รอ stock ({ft}): {row['footage_raw'][:40]} (code={code})")
            else:
                status_ref[key] = "no_footage"
                log.append(f"    → ไม่มี footage")

        log.append(f"  stock_pending: {list(stock_pending.keys())}")

        # SRT: build หลัง Drive rows ทั้งหมดเสร็จ (มี SOT timestamps แล้ว)
        _save_srt()

        # ── Insert rows: download-only ไปยัง Insert Footages (ไม่ตัด TC) ──
        _insert_rows = [r for r in parsed["rows"] if r.get("is_insert")]
        if _insert_rows and do_dl:
            os.makedirs(insert_folder, exist_ok=True)
            log.append(f"  📌 Insert rows: {len(_insert_rows)} รายการ")
            for row in _insert_rows:
                idx = row["index"]
                key = str(idx)
                ft = row["footage_type"]
                log.append(f"  insert row {idx:02d}: type={ft}")
                if ft == "drive" and row["file_id"]:
                    status_ref[key] = "downloading"
                    _set_status(f"⬇️  INSERT #{idx:02d} — Drive...")
                    raw = download_drive_file(drive_svc, row["file_id"], idx, insert_folder, log, status_cb=_set_status)
                    if isinstance(raw, dict) and raw.get("conflict"):
                        status_ref[key] = "folder_conflict"
                        result_holder.setdefault("folder_conflicts", []).append({
                            "row_idx": idx, "file_id": row["file_id"],
                            "folder_name": raw["folder_name"], "files": raw["files"],
                            "tc_in": None, "tc_out": None,
                        })
                    elif raw and os.path.exists(raw):
                        status_ref[key] = "done"
                    else:
                        status_ref[key] = "error"
                elif ft in ("social", "other") and row["footage_raw"].strip():
                    url = row["footage_raw"].strip()
                    src_tag = get_source_tag(url)
                    status_ref[key] = "downloading"
                    _set_status(f"⬇️  INSERT #{idx:02d} — {src_tag}...")
                    raw = download_social(url, insert_folder, log, status_cb=_set_status)
                    status_ref[key] = "done" if (raw and os.path.exists(raw)) else "error"
                elif ft == "image" and row["footage_raw"].strip():
                    status_ref[key] = "downloading"
                    _set_status(f"⬇️  INSERT #{idx:02d} — ภาพ...")
                    raw = download_image_url(row["footage_raw"].strip(), insert_folder, log)
                    status_ref[key] = "done" if (raw and os.path.exists(raw)) else "error"
                elif ft in ("getty", "reuters") and row["footage_raw"].strip():
                    status_ref[key] = "waiting_stock"
                    code = _extract_stock_code(row["footage_raw"], ft)
                    if code not in stock_pending:
                        stock_pending[code] = []
                    stock_pending[code].append({
                        "row_key": key, "row_idx": idx,
                        "tc_in": None, "tc_out": None,
                        "sot": False, "sot_sentences": [],
                        "stock_dir": raw_getty if ft == "getty" else raw_reuters,
                        "is_insert": True,
                        "insert_out_dir": insert_folder,
                    })
                    log.append(f"    → รอ stock (insert/{ft}): {row['footage_raw'][:40]} (code={code})")
                else:
                    status_ref[key] = "no_footage"
        elif _insert_rows:
            for row in _insert_rows:
                status_ref[str(row["index"])] = "skipped"

        # Watchdog สำหรับ stock
        if stock_pending:
            has_stock = True
            stop_ev = threading.Event()
            result_holder["watchdog_stop"] = stop_ev
            watch_src = stock_watch_folder if stock_watch_folder and os.path.isdir(stock_watch_folder) else output_folder
            srt_save_path = srt_path
            log.append(f"  🐕 watchdog เริ่ม — scan: {watch_src}")
            _set_status(f"🐕  รอ Stock Footage  ({len(stock_pending)} รายการ)...")
            threading.Thread(
                target=watchdog_loop,
                args=(watch_src, stock_pending, output_folder, stop_ev, cut_by_tc, status_ref, result_holder),
                kwargs={
                    "gclient": gclient,
                    "parsed_rows": parsed["rows"],
                    "is_vertical": is_vertical,
                    "srt_save_path": srt_save_path,
                    "pad_cut": pad_cut,
                },
                daemon=True,
            ).start()

    except Exception as e:
        import traceback
        result_holder["error"] = str(e)
        log.append(f"❌ Exception: {traceback.format_exc()}")
    finally:
        if not has_stock:
            result_holder["done"] = True
            log.append("✅ เสร็จสิ้น")
            _set_status("✅  เสร็จแล้ว!")

# ──────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
.pc-step { font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.12em; color:#555a6a; text-transform:uppercase;
           margin-top:24px; margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid rgba(255,255,255,0.08); }
.pc-mono { font-family:'IBM Plex Mono',monospace; font-size:12px; color:#8b90a0; }
.pc-stat-row { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:20px; }
.pc-stat { background:#13161b; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:12px 14px; }
.pc-stat-val { font-family:'IBM Plex Mono',monospace; font-size:var(--fs-stat,22px); font-weight:600; display:block; }
.pc-stat-lbl { font-family:'IBM Plex Mono',monospace; font-size:var(--fs-xs,10px); color:#555a6a; text-transform:uppercase; letter-spacing:.08em; margin-top:2px; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────
_sb_label = "<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs,10px);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:6px;'>{}</div>"
_sb_path  = "<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs,10px);color:#555a6a;background:#1a1e26;border-radius:4px;padding:4px 8px;margin-bottom:8px;word-break:break-all;'>{}</div>"

with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding-bottom:14px;
      border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:14px;">
      <div style="width:8px;height:8px;border-radius:50%;background:#ff7a2f;flex-shrink:0;"></div>
      <div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm,12px);font-weight:600;color:#e8eaf0;">PyCUT</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs,10px);color:#555a6a;letter-spacing:.06em;">SUBTITLE + FOOTAGE CUTTER</div>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── 1: Doc URL ──
    st.markdown(_sb_label.format("1 — Google Doc URL"), unsafe_allow_html=True)
    doc_url = st.text_input("doc_url_sb", value=st.session_state["pycut_doc_url"],
                            placeholder="วาง URL Doc...", label_visibility="collapsed")
    st.session_state["pycut_doc_url"] = doc_url

    if st.button("📖 อ่าน Doc", type="primary", use_container_width=True, disabled=not doc_url.strip()):
        with st.spinner("กำลังอ่าน..."):
            try:
                doc_id = extract_id(doc_url.strip())
                _parsed = parse_pycut_doc(doc_id)
                st.session_state["pycut_parsed"] = _parsed
                st.session_state["pycut_settings"]["is_vertical"] = _parsed["format"] == "vertical"
                st.session_state["pycut_settings"]["make_srt"] = _parsed["has_subtitle"]
                st.session_state["pycut_row_status"] = {}
                st.session_state["pycut_srt_content"] = ""
                st.session_state["pycut_running"] = False
                st.rerun()
            except Exception as _e:
                st.error(f"❌ {_e}")

    st.divider()

    # ── 2: ตั้งค่า ──
    st.markdown(_sb_label.format("2 — ตั้งค่า"), unsafe_allow_html=True)
    _s = st.session_state["pycut_settings"]
    make_srt  = st.checkbox("✍️ สร้าง SRT",        value=_s["make_srt"],          key="chk_srt")
    is_vertical = st.checkbox("📐 แนวตั้ง (Vertical)", value=_s["is_vertical"],    key="chk_v")
    do_dl     = st.checkbox("⬇️ โหลดฟุตเทจ",       value=_s["download_footage"],  key="chk_dl")
    cut_tc    = st.checkbox("✂️ ตัดตาม TC",         value=_s["cut_by_tc"],         key="chk_tc")
    pad_cut   = st.checkbox("⏱ เผื่อหัวท้าย 1 วิ",  value=_s.get("pad_cut", True), key="chk_pad",
                            disabled=not cut_tc)
    st.session_state["pycut_settings"].update({
        "make_srt": make_srt, "is_vertical": is_vertical,
        "download_footage": do_dl, "cut_by_tc": cut_tc, "pad_cut": pad_cut,
    })

    st.divider()

    # ── 3: Folders ──
    st.markdown(_sb_label.format("3 — Folders"), unsafe_allow_html=True)

    if st.button("📂 เลือก Output Folder", use_container_width=True):
        _p = select_folder_mac("เลือกโฟลเดอร์ Output สำหรับ PyCUT")
        if _p:
            st.session_state["pycut_output_folder"] = _p
            _cfg2 = load_config(); _cfg2["pycut_output_folder"] = _p; save_config(_cfg2)
            st.rerun()
    st.markdown(_sb_path.format(st.session_state["pycut_output_folder"] or "ยังไม่ได้เลือก"), unsafe_allow_html=True)

    if st.button("📂 เลือก Stock Watch Folder", use_container_width=True):
        _p = select_folder_mac("เลือกโฟลเดอร์ที่วาง Stock Footage ที่ดาวน์โหลดแล้ว")
        if _p:
            st.session_state["pycut_stock_watch_folder"] = _p
            _cfg2 = load_config(); _cfg2["pycut_stock_watch_folder"] = _p; save_config(_cfg2)
            st.rerun()
    st.markdown(
        _sb_path.format(st.session_state["pycut_stock_watch_folder"] or "ใช้ Output folder (default)"),
        unsafe_allow_html=True,
    )

    st.divider()

    # ── Run / Stop ──
    _parsed_now = st.session_state.get("pycut_parsed")
    _can_run = bool(_parsed_now and st.session_state["pycut_output_folder"]) and not st.session_state["pycut_running"]

    if not st.session_state["pycut_output_folder"]:
        st.warning("⚠️ กรุณาเลือก Output Folder")

    if st.session_state["pycut_running"]:
        st.markdown(
            "<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs,10px);color:#ff7a2f;"
            "margin-bottom:8px;'>🔄 กำลังทำงาน...</div>",
            unsafe_allow_html=True,
        )
        if st.button("⏹ Stop", use_container_width=True):
            _h = st.session_state.get("pycut_result_holder")
            if _h:
                _ev = _h.get("watchdog_stop")
                if _ev: _ev.set()
            st.session_state["pycut_running"] = False
            st.rerun()
    else:
        if st.button("▶️ Run PyCUT", type="primary", use_container_width=True, disabled=not _can_run):
            _parsed_run = st.session_state["pycut_parsed"]
            _status_ref = {}
            _result_holder = {"srt_content": "", "error": "", "done": False, "watchdog_stop": None, "status_text": ""}
            st.session_state["pycut_running"] = True
            st.session_state["pycut_row_status"] = _status_ref
            st.session_state["pycut_srt_content"] = ""
            st.session_state["pycut_srt_editor"] = ""
            st.session_state["pycut_error"] = ""
            st.session_state["pycut_result_holder"] = _result_holder
            threading.Thread(
                target=run_pycut,
                args=(
                    _parsed_run,
                    st.session_state["pycut_settings"].copy(),
                    st.session_state["pycut_output_folder"],
                    st.session_state["pycut_stock_watch_folder"],
                    _status_ref,
                    _result_holder,
                ),
                daemon=True,
            ).start()
            st.rerun()

# ──────────────────────────────────────────────────────────────
# MAIN — HEADER
# ──────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <div style="font-size:var(--fs-hero,36px);">✂️</div>
  <div>
    <div style="font-family:'IBM Plex Sans Thai',sans-serif;font-size:var(--fs-hero,36px);font-weight:700;color:#e8eaf0;line-height:1.1;">PyCUT</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm,12px);color:#555a6a;margin-top:2px;letter-spacing:.04em;">SUBTITLE GENERATOR + FOOTAGE CUTTER — VERTICAL CLIP AUTOMATION</div>
  </div>
</div>
<div style="height:1px;background:rgba(255,255,255,0.08);margin:16px 0 20px 0;"></div>
""", unsafe_allow_html=True)

parsed = st.session_state.get("pycut_parsed")

if not parsed:
    st.markdown(
        "<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm,12px);"
        "color:#555a6a;margin-top:40px;text-align:center;'>"
        "วาง URL Google Doc ในแถบด้านซ้าย แล้วกด <b style='color:#e8eaf0;'>📖 อ่าน Doc</b></div>",
        unsafe_allow_html=True,
    )
else:
    # ── Stat cards ──
    _main_rows   = [r for r in parsed["rows"] if not r.get("is_insert")]
    _insert_rows = [r for r in parsed["rows"] if r.get("is_insert")]
    _rs = st.session_state["pycut_row_status"]
    _total   = len(_main_rows)
    _done_n  = sum(1 for r in _main_rows if _rs.get(str(r["index"])) in ("done", "no_footage", "skipped"))
    _wait_n  = sum(1 for r in _main_rows if _rs.get(str(r["index"])) == "waiting_stock")
    _err_n   = sum(1 for r in _main_rows if _rs.get(str(r["index"])) == "error")
    st.markdown(
        f'<div class="pc-stat-row">'
        f'<div class="pc-stat"><span class="pc-stat-val" style="color:#e8eaf0;">{_total}</span><div class="pc-stat-lbl">📦 ทั้งหมด</div></div>'
        f'<div class="pc-stat"><span class="pc-stat-val" style="color:#2dd4a8;">{_done_n}</span><div class="pc-stat-lbl">✅ เสร็จแล้ว</div></div>'
        f'<div class="pc-stat"><span class="pc-stat-val" style="color:#ffd166;">{_wait_n}</span><div class="pc-stat-lbl">⏳ รอ Stock</div></div>'
        f'<div class="pc-stat"><span class="pc-stat-val" style="color:#ff4d4d;">{_err_n}</span><div class="pc-stat-lbl">❌ Error</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Preview Table ──
    st.markdown('<div class="pc-step">Preview — ตาราง footage</div>', unsafe_allow_html=True)

    _STATUS_ICON = {
        "done": "✅", "error": "❌", "waiting_stock": "⏳",
        "downloading": "⬇️", "no_footage": "—", "skipped": "⏭️", "pending": "⬜",
        "folder_conflict": "⚠️",
    }

    h1, h2, h3, h4, h5 = st.columns([0.5, 2.5, 1.5, 3, 0.8])
    for _col, _lbl in zip([h1, h2, h3, h4, h5], ["#", "Footage", "TC", "SUB", "Status"]):
        _col.markdown(
            f"<div style='font-family:IBM Plex Mono,monospace;font-size:10px;"
            f"color:#555a6a;padding-bottom:4px;border-bottom:1px solid rgba(255,255,255,0.08);'>"
            f"{_lbl}</div>",
            unsafe_allow_html=True,
        )

    _ui_seq = 0
    for row in _main_rows:
        key = str(row["index"])
        status = st.session_state["pycut_row_status"].get(key, "pending")
        icon = _STATUS_ICON.get(status, "⬜")
        ft = row["footage_type"]
        if ft != "none":
            _ui_seq += 1

        sot_badge = " 🎙️" if row.get("sot") else ""
        inherit_badge = " ↩" if row.get("inherited_footage") else ""
        insert_badge = " 📌" if row.get("is_insert") else ""
        _disp = row.get("footage_display", "") or ""
        _sfx = f"{sot_badge}{inherit_badge}{insert_badge}"
        if ft == "drive":
            _label = _disp or (row["file_id"] or "")[:20]
            footage_disp = f"🟢 {_label}{_sfx}"
        elif ft == "getty":
            _label = _disp or row["footage_raw"][:28]
            footage_disp = f"🔗 Getty `{_label}`{_sfx}"
        elif ft == "reuters":
            _label = _disp or row["footage_raw"][:24]
            footage_disp = f"🔗 Reuters `{_label}`{_sfx}"
        elif ft == "image":
            _label = _disp or row["footage_raw"][:30]
            footage_disp = f"🖼 {_label}{_sfx}"
        elif ft == "social":
            src_tag = get_source_tag(row["footage_raw"])
            _label = _disp or row["footage_raw"][:26]
            footage_disp = f"📱 {src_tag} {_label}{_sfx}"
        elif ft == "other":
            _label = _disp or row["footage_raw"][:28]
            footage_disp = f"🌐 {_label}{_sfx}"
        elif ft == "none" and row.get("sot"):
            footage_disp = "🎙️ ปล่อยเสียง"
        else:
            footage_disp = "—"

        if row["tc_in"] is not None and row["tc_out"] is not None:
            tc_disp = f"{row['tc_in']:.1f}s → {row['tc_out']:.1f}s"
        elif row["tc_in"] is not None:
            tc_disp = f"{row['tc_in']:.1f}s →"
        else:
            tc_disp = "—"

        bullets = row["bullets"]
        b_disp = " / ".join(bullets[:2])
        if len(bullets) > 2:
            b_disp += f" (+{len(bullets)-2})"

        c1, c2, c3, c4, c5 = st.columns([0.5, 2.5, 1.5, 3, 0.8])
        c1.markdown(
            f"<div class='pc-mono' style='text-align:center;padding-top:6px;'>{f'{_ui_seq:02d}' if ft != 'none' else '—'}</div>",
            unsafe_allow_html=True,
        )
        c2.markdown(
            f"<div class='pc-mono' style='padding-top:6px;'>{footage_disp}</div>",
            unsafe_allow_html=True,
        )
        c3.markdown(
            f"<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#4a9eff;padding-top:6px;'>{tc_disp}</div>",
            unsafe_allow_html=True,
        )
        c4.markdown(
            f"<div style='font-family:IBM Plex Sans Thai,sans-serif;font-size:12px;color:#8b90a0;padding-top:6px;'>{b_disp or '—'}</div>",
            unsafe_allow_html=True,
        )
        c5.markdown(
            f"<div style='font-size:14px;padding-top:5px;text-align:center;'>{icon}</div>",
            unsafe_allow_html=True,
        )

    # ── Insert Footages ──
    if _insert_rows:
        st.markdown('<div class="pc-step">📌 Insert Footages</div>', unsafe_allow_html=True)
        _ih1, _ih2 = st.columns([5, 0.8])
        for _col, _lbl in zip([_ih1, _ih2], ["Footage", "Status"]):
            _col.markdown(
                f"<div style='font-family:IBM Plex Mono,monospace;font-size:10px;"
                f"color:#555a6a;padding-bottom:4px;border-bottom:1px solid rgba(255,255,255,0.08);'>"
                f"{_lbl}</div>",
                unsafe_allow_html=True,
            )
        for row in _insert_rows:
            _ikey = str(row["index"])
            _istatus = _rs.get(_ikey, "pending")
            _iicon = _STATUS_ICON.get(_istatus, "⬜")
            _ift = row["footage_type"]
            _idisp = row.get("footage_display", "") or ""
            if _ift == "drive":
                _ifoot = f"🟢 {_idisp or (row.get('file_id') or '')[:20]}"
            elif _ift == "getty":
                _ifoot = f"🔗 Getty `{_idisp or row['footage_raw'][:28]}`"
            elif _ift == "reuters":
                _ifoot = f"🔗 Reuters `{_idisp or row['footage_raw'][:24]}`"
            elif _ift == "image":
                _ifoot = f"🖼 {_idisp or row['footage_raw'][:30]}"
            elif _ift == "social":
                _ifoot = f"📱 {get_source_tag(row['footage_raw'])} {_idisp or row['footage_raw'][:26]}"
            elif _ift == "other":
                _ifoot = f"🌐 {_idisp or row['footage_raw'][:28]}"
            else:
                _ifoot = _idisp or "—"
            _ic1, _ic2 = st.columns([5, 0.8])
            _ic1.markdown(
                f"<div class='pc-mono' style='padding-top:6px;'>{_ifoot}</div>",
                unsafe_allow_html=True,
            )
            _ic2.markdown(
                f"<div style='font-size:14px;padding-top:5px;text-align:center;'>{_iicon}</div>",
                unsafe_allow_html=True,
            )

    # ── Progress + Status ──
    has_results = any(
        v not in ("pending", "")
        for v in st.session_state["pycut_row_status"].values()
    )
    if st.session_state["pycut_running"] or has_results:
        st.markdown('<div class="pc-step">ผลลัพธ์</div>', unsafe_allow_html=True)

        _holder = st.session_state.get("pycut_result_holder")
        _status_txt = (_holder or {}).get("status_text", "")
        _err_txt = (_holder or {}).get("error", "") or st.session_state.get("pycut_error", "")

        if _total > 0:
            st.progress(_done_n / _total)

        if _err_txt:
            st.markdown(
                f"<div style='font-family:IBM Plex Mono,monospace;font-size:12px;"
                f"color:#ff4d4d;margin:6px 0 12px 2px;'>❌  {_err_txt}</div>",
                unsafe_allow_html=True,
            )
        elif _status_txt:
            _color = "#2dd4a8" if _status_txt.startswith("✅") else \
                     "#ffd166" if _status_txt.startswith("🐕") else "#8b90a0"
            st.markdown(
                f"<div style='font-family:IBM Plex Mono,monospace;font-size:12px;"
                f"color:{_color};margin:6px 0 12px 2px;letter-spacing:.02em;'>{_status_txt}</div>",
                unsafe_allow_html=True,
            )

        # ── Folder conflict warning ──
        _conflicts = (st.session_state.get("pycut_result_holder") or {}).get("folder_conflicts", [])
        if _conflicts:
            st.markdown(
                "<div style='background:#13161b;border:1px solid rgba(255,209,102,0.5);"
                "border-top:3px solid #ffd166;border-radius:12px;padding:16px;margin-bottom:16px;'>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div style='font-family:IBM Plex Mono,monospace;font-size:12px;font-weight:700;"
                "color:#ffd166;margin-bottom:10px;'>⚠️ Folder มีหลายไฟล์ — ต้องเปลี่ยน Link</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#8b90a0;margin-bottom:12px;'>"
                "Row เหล่านี้ link ไปยัง Drive Folder ที่มีหลายไฟล์ แต่ตั้ง TC ไว้<br>"
                "กรุณาเปลี่ยน link ใน Google Doc ให้ชี้ไปที่ <b style='color:#e8eaf0;'>ไฟล์วิดีโอโดยตรง</b> แล้ว อ่าน Doc ใหม่</div>",
                unsafe_allow_html=True,
            )
            for cf in _conflicts:
                tc_txt = ""
                if cf.get("tc_in") is not None:
                    tc_txt = f" · TC {cf['tc_in']}s → {cf['tc_out']}s"
                st.markdown(
                    f"<div style='background:#0d0f12;border:1px solid rgba(255,255,255,0.08);"
                    f"border-left:3px solid #ffd166;border-radius:8px;padding:10px 14px;margin-bottom:8px;'>"
                    f"<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#ffd166;font-weight:600;'>"
                    f"#{cf['row_idx']:02d} — {cf['folder_name']}{tc_txt}</div>"
                    f"<div style='font-family:IBM Plex Mono,monospace;font-size:10px;color:#555a6a;margin-top:4px;'>"
                    f"ไฟล์ใน folder: {'  ·  '.join(cf['files'])}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

        # Stock section
        stock_rows = [
            r for r in parsed["rows"]
            if st.session_state["pycut_row_status"].get(str(r["index"])) == "waiting_stock"
        ]
        if stock_rows:
            watch_dir = st.session_state.get("pycut_stock_watch_folder") or st.session_state.get("pycut_output_folder") or ""
            proj_title = parsed.get("title", "PyCUT")

            getty_codes, reuters_codes = [], []
            seen_getty, seen_reuters = set(), set()
            for sr in stock_rows:
                ft = sr["footage_type"]
                code = _extract_stock_code(sr["footage_raw"], ft)
                if not code:
                    continue
                if ft == "getty" and code not in seen_getty:
                    getty_codes.append(code); seen_getty.add(code)
                elif ft == "reuters" and code not in seen_reuters:
                    reuters_codes.append(code); seen_reuters.add(code)

            st.markdown(
                "<div style='background:#13161b;border:1px solid rgba(255,255,255,0.08);"
                "border-top:2px solid #ffd166;border-radius:12px;padding:16px;margin-bottom:16px;'>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#ffd166;font-weight:600;margin-bottom:2px;'>⏳ รอ Stock Footage</div>"
                f"<div style='font-family:IBM Plex Mono,monospace;font-size:10px;color:#555a6a;margin-bottom:12px;'>"
                f"🐕 Watchdog สแกน: <b style='color:#8b90a0;'>{watch_dir or '—'}</b></div>",
                unsafe_allow_html=True,
            )

            _col_l, _col_r = st.columns(2)
            with _col_l:
                st.markdown(
                    "<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#ffd166;font-weight:600;margin-bottom:8px;'>🖼 Getty Images</div>",
                    unsafe_allow_html=True,
                )
                if getty_codes:
                    st.code("\n".join(getty_codes), language=None)
                    make_open_ci_button(
                        [f"https://www.gettyimages.com/search/2/film?phrase={c}&family=editorial&sort=best" for c in getty_codes],
                        "เปิด Tab Getty ทั้งหมด", "#ffd166", proj_title,
                    )
                else:
                    st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:12px;color:#555a6a;'>ไม่มี Getty</span>", unsafe_allow_html=True)

            with _col_r:
                st.markdown(
                    "<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#ff7a2f;font-weight:600;margin-bottom:8px;'>📡 Reuters Connect</div>",
                    unsafe_allow_html=True,
                )
                if reuters_codes:
                    st.code("\n".join(reuters_codes), language=None)
                    make_open_ci_button(
                        [f"https://www.reutersconnect.com/all?search=all%3A{c.strip()}" for c in reuters_codes],
                        "เปิด Reuters Connect", "#ff7a2f", proj_title,
                    )
                else:
                    st.markdown("<span style='font-family:IBM Plex Mono,monospace;font-size:12px;color:#555a6a;'>ไม่มี Reuters</span>", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

        # SRT Editor
        srt = st.session_state.get("pycut_srt_content", "")
        if srt:
            title_safe = sanitize_filename(parsed.get("title", "subtitle"))
            st.markdown(
                "<div style='font-family:IBM Plex Mono,monospace;font-size:11px;"
                "color:#555a6a;margin:12px 0 4px 0;'>SRT Preview — แก้ไขได้</div>",
                unsafe_allow_html=True,
            )
            st.text_area(
                label="srt_editor",
                key="pycut_srt_editor",
                height=300,
                label_visibility="collapsed",
            )
            _edited = st.session_state.get("pycut_srt_editor", srt)
            _dl_col, _reset_col, _ = st.columns([2, 1.5, 3.5])
            with _dl_col:
                st.download_button(
                    label="⬇️ ดาวน์โหลด .srt",
                    data=_edited.encode("utf-8"),
                    file_name=f"{title_safe}.srt",
                    mime="text/plain",
                    use_container_width=True,
                )
            with _reset_col:
                if st.button("↺ Reset", use_container_width=True):
                    st.session_state["pycut_srt_editor"] = srt
                    st.rerun()
