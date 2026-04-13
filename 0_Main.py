import streamlit as st
import sys, os
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from utils import load_config, save_config, inject_global_css

st.set_page_config(
    page_title="LoadPAP Suite",
    page_icon="🚀",
    layout="wide"
)
inject_global_css()

# ============================================================
# 🎨 CSS (เฉพาะหน้า Main — font/base อยู่ใน utils.inject_global_css)
# ============================================================
st.markdown("""
<style>
/* ── CSS Variables ── */
:root {
  --bg0: #0d0f12;
  --bg1: #13161b;
  --bg2: #1a1e26;
  --bg3: #222733;
  --border: rgba(255,255,255,0.08);
  --border-hi: rgba(255,255,255,0.15);
  --text-1: #e8eaf0;
  --text-2: #8b90a0;
  --text-3: #555a6a;
  --accent-blue: #4a9eff;
  --accent-orange: #ff7a2f;
  --accent-teal: #2dd4a8;
  --accent-red: #ff4d4d;
  --accent-yellow: #ffd166;
}

/* ── ปุ่ม Override ── */
[data-testid="baseButton-secondary"] {
  background: transparent !important;
  border: 1px solid rgba(255,255,255,0.15) !important;
  color: #e8eaf0 !important;
  font-size: 13px !important;
  padding: 4px 14px !important;
  border-radius: 7px !important;
}
[data-testid="baseButton-secondary"]:hover {
  background: rgba(255,255,255,0.06) !important;
  border-color: rgba(255,255,255,0.25) !important;
}
[data-testid="baseButton-primary"] {
  background: #4a9eff !important;
  border: none !important;
  color: #fff !important;
  font-size: 13px !important;
  padding: 4px 14px !important;
  border-radius: 7px !important;
}

/* ── Tool cards ── */
.lp-tool-card {
  background: var(--bg1);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 24px;
  transition: border-color 0.2s, background 0.2s;
  height: 100%;
}
.lp-tool-card:hover {
  border-color: var(--border-hi);
  background: var(--bg2);
}
.lp-tool-card.blue  { border-top: 2px solid var(--accent-blue); }
.lp-tool-card.teal  { border-top: 2px solid var(--accent-teal); }
.lp-tool-card.orange{ border-top: 2px solid var(--accent-orange); }

.lp-tool-icon {
  font-size: 32px;
  margin-bottom: 12px;
  display: block;
}
.lp-tool-name {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.06em;
  margin-bottom: 4px;
}
.lp-tool-title {
  font-family: 'IBM Plex Sans Thai', sans-serif !important;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-1) !important;
  margin-bottom: 10px;
}
.lp-tool-desc {
  font-family: 'IBM Plex Sans Thai', sans-serif !important;
  font-size: 13px;
  color: var(--text-2) !important;
  line-height: 1.65;
  margin-bottom: 14px;
}

/* ── Badge ── */
.lp-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 20px;
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 11px;
  font-weight: 600;
  margin-right: 4px;
}
.badge-blue   { background: rgba(74,158,255,0.12); color: #4a9eff !important; border: 1px solid rgba(74,158,255,0.25); }
.badge-teal   { background: rgba(45,212,168,0.12); color: #2dd4a8 !important; border: 1px solid rgba(45,212,168,0.25); }
.badge-orange { background: rgba(255,122,47,0.12); color: #ff7a2f !important; border: 1px solid rgba(255,122,47,0.25); }
.badge-yellow { background: rgba(255,209,102,0.12); color: #ffd166 !important; border: 1px solid rgba(255,209,102,0.25); }

/* ── Stat bar ── */
.lp-stat-bar {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 20px;
  display: flex;
  gap: 32px;
  flex-wrap: wrap;
  align-items: center;
}
.lp-stat-item { text-align: center; }
.lp-stat-val {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-1) !important;
  display: block;
}
.lp-stat-lbl {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 10px;
  color: var(--text-3) !important;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

/* ── Section label ── */
.lp-section-label {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--text-3) !important;
  text-transform: uppercase;
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

/* ── Divider ── */
.lp-divider {
  height: 1px;
  background: var(--border);
  margin: 28px 0;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# 🏠 HEADER
# ============================================================
st.markdown("""
<div style="display:flex; align-items:center; gap:14px; margin-bottom:8px;">
  <div style="width:50px; height:50px; background:linear-gradient(135deg,#4a9eff,#2dd4a8,#ff7a2f);
    border-radius:11px; display:flex; align-items:center; justify-content:center;
    font-family:'IBM Plex Mono',monospace; font-size:17px; font-weight:700; color:#fff; flex-shrink:0;">
    LPF
  </div>
  <div>
    <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:26px; font-weight:800; color:#e8eaf0; line-height:1.1;">
      LoadPAP Suite
    </div>
    <div style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#555a6a; margin-top:2px; letter-spacing:0.06em;">
      LOAD PROCESS AUTOMATION PIPELINE · v2.0
    </div>
  </div>
  <div style="margin-left:auto; display:flex; gap:8px; align-items:center;">
    <span style="font-family:'IBM Plex Mono',monospace; font-size:10px; padding:3px 8px;
      background:#1a1e26; border-radius:4px; color:#555a6a; border:1px solid rgba(255,255,255,0.08);">
      Beta
    </span>
    <span style="font-family:'IBM Plex Mono',monospace; font-size:10px; padding:3px 8px;
      background:#1a1e26; border-radius:4px; color:#555a6a; border:1px solid rgba(255,255,255,0.08);">
      Mac Only
    </span>
  </div>
</div>

<div style="height:1px; background:rgba(255,255,255,0.08); margin:20px 0 28px 0;"></div>
""", unsafe_allow_html=True)

# ============================================================
# 📋 INTRO
# ============================================================
st.markdown("""
<div style="font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:0.12em;
  color:#555a6a; text-transform:uppercase; margin-bottom:14px; padding-bottom:8px;
  border-bottom:1px solid rgba(255,255,255,0.08);">
  01 — เครื่องมือทั้งหมด
</div>
""", unsafe_allow_html=True)

# ============================================================
# 🧰 TOOL CARDS
# ============================================================
col1, col2, col3 = st.columns(3, gap="medium")

with col1:
    st.markdown("""
    <div class="lp-tool-card blue">
      <span class="lp-tool-icon">🧠</span>
      <div class="lp-tool-name" style="color:#4a9eff;">PyLOAD</div>
      <div class="lp-tool-title">ระบบดาวน์โหลดฟุตเทจ</div>
      <div class="lp-tool-desc">
        สแกน Google Doc แล้วดึงฟุตเทจอัตโนมัติจากทุกแหล่ง — Getty, Reuters, YouTube, TikTok, Facebook, Instagram และ Google Drive
        โดยไม่ต้องคัดลอกลิงก์ทีละอัน
      </div>
      <div>
        <span class="lp-badge badge-blue">Getty</span>
        <span class="lp-badge badge-orange">Reuters</span>
        <span class="lp-badge badge-teal">Social</span>
        <span class="lp-badge badge-blue">Drive</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="lp-tool-card teal">
      <span class="lp-tool-icon">🎬</span>
      <div class="lp-tool-name" style="color:#2dd4a8;">PyRUSH</div>
      <div class="lp-tool-title">ระบบตัดต่ออัตโนมัติ</div>
      <div class="lp-tool-desc">
        อ่าน Google Sheet แล้วสั่ง FFmpeg ตัดวิดีโอตาม Timecode อัตโนมัติ รองรับ Trim, Multi-cut และ Auto-5s
        พร้อมลบ Black/White frame ออกอัตโนมัติ
      </div>
      <div>
        <span class="lp-badge badge-teal">FFmpeg</span>
        <span class="lp-badge badge-yellow">Auto-Cut</span>
        <span class="lp-badge badge-teal">Watchdog</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
    <div class="lp-tool-card orange">
      <span class="lp-tool-icon">📋</span>
      <div class="lp-tool-name" style="color:#ff7a2f;">PyLOG</div>
      <div class="lp-tool-title">ระบบบันทึก Log ด้วย AI</div>
      <div class="lp-tool-desc">
        สแกนไฟล์วิดีโอในโฟลเดอร์ วิเคราะห์ภาพนิ่งด้วย Gemini Vision แล้วบันทึกชื่อบุคคล
        และสรุปเนื้อหาลง Google Sheet โดยอัตโนมัติ
      </div>
      <div>
        <span class="lp-badge badge-orange">Gemini AI</span>
        <span class="lp-badge badge-yellow">Vision</span>
        <span class="lp-badge badge-orange">Sheets</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================
# DIVIDER
# ============================================================
st.markdown("""
<div style="height:1px; background:rgba(255,255,255,0.08); margin:32px 0 28px 0;"></div>
<div style="font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:0.12em;
  color:#555a6a; text-transform:uppercase; margin-bottom:20px; padding-bottom:8px;
  border-bottom:1px solid rgba(255,255,255,0.08);">
  02 — วิธีเริ่มใช้งาน
</div>
""", unsafe_allow_html=True)

# ============================================================
# 📖 HOW TO USE
# ============================================================
step1, step2, step3 = st.columns(3, gap="medium")

with step1:
    st.markdown("""
    <div style="background:#13161b; border:1px solid rgba(255,255,255,0.08);
      border-radius:12px; padding:20px;">
      <div style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#555a6a;
        text-transform:uppercase; letter-spacing:0.1em; margin-bottom:10px;">
        STEP 01
      </div>
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:15px; font-weight:700;
        color:#e8eaf0; margin-bottom:8px;">
        📂 เตรียมไฟล์ต้นทาง
      </div>
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:13px; color:#8b90a0; line-height:1.65;">
        เปิด Google Doc หรือ Google Sheet ที่มีรายการฟุตเทจที่ต้องการ
        แล้วคัดลอก URL มาวางในช่อง Settings ด้านซ้ายมือ
      </div>
    </div>
    """, unsafe_allow_html=True)

with step2:
    st.markdown("""
    <div style="background:#13161b; border:1px solid rgba(255,255,255,0.08);
      border-radius:12px; padding:20px;">
      <div style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#555a6a;
        text-transform:uppercase; letter-spacing:0.1em; margin-bottom:10px;">
        STEP 02
      </div>
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:15px; font-weight:700;
        color:#e8eaf0; margin-bottom:8px;">
        ⚙️ ตั้งค่า Destination
      </div>
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:13px; color:#8b90a0; line-height:1.65;">
        กดปุ่ม "เลือกโฟลเดอร์" เพื่อกำหนดที่เก็บไฟล์งาน ระบบจะจำค่านี้ไว้
        ไม่ต้องตั้งใหม่ทุกครั้ง
      </div>
    </div>
    """, unsafe_allow_html=True)

with step3:
    st.markdown("""
    <div style="background:#13161b; border:1px solid rgba(255,255,255,0.08);
      border-radius:12px; padding:20px;">
      <div style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#555a6a;
        text-transform:uppercase; letter-spacing:0.1em; margin-bottom:10px;">
        STEP 03
      </div>
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:15px; font-weight:700;
        color:#e8eaf0; margin-bottom:8px;">
        🚀 กด "เริ่มทำงาน"
      </div>
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:13px; color:#8b90a0; line-height:1.65;">
        ระบบจะดำเนินการให้อัตโนมัติทั้งหมด สามารถติดตามสถานะได้
        แบบ Real-time บนหน้าจอ
      </div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================
# DIVIDER
# ============================================================
st.markdown("""
<div style="height:1px; background:rgba(255,255,255,0.08); margin:32px 0 28px 0;"></div>
<div style="font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:0.12em;
  color:#555a6a; text-transform:uppercase; margin-bottom:20px; padding-bottom:8px;
  border-bottom:1px solid rgba(255,255,255,0.08);">
  03 — ข้อมูลระบบ
</div>
""", unsafe_allow_html=True)

# ============================================================
# ℹ️ SYSTEM INFO
# ============================================================
info1, info2 = st.columns([2, 1], gap="medium")

with info1:
    st.markdown("""
    <div style="background:#13161b; border:1px solid rgba(255,255,255,0.08);
      border-top: 2px solid #4a9eff; border-radius:12px; padding:20px;">
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:15px; font-weight:700;
        color:#e8eaf0; margin-bottom:14px;">
        🔐 Google Account &amp; สิทธิ์การใช้งาน
      </div>
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:13px; color:#8b90a0; line-height:1.8;">
        ครั้งแรกที่เปิดแอป ระบบจะขอ Login Google เพื่อเข้าถึง <br>
        <span style="font-family:'IBM Plex Mono',monospace; font-size:12px; color:#4a9eff;">
          Google Docs · Google Drive · Google Sheets
        </span><br><br>
        หลังจาก Login ครั้งแรกแล้ว ระบบจะจำ Session ไว้อัตโนมัติ
        ไม่ต้อง Login ซ้ำในครั้งถัดไป
      </div>
    </div>
    """, unsafe_allow_html=True)

with info2:
    st.markdown("""
    <div style="background:#13161b; border:1px solid rgba(255,255,255,0.08);
      border-radius:12px; padding:20px; height:100%;">
      <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:15px; font-weight:700;
        color:#e8eaf0; margin-bottom:14px;">
        📦 Dependencies
      </div>
      <div style="display:flex; flex-direction:column; gap:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8b90a0;">yt-dlp</span>
          <span style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#2dd4a8;">✓ bundled</span>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8b90a0;">FFmpeg</span>
          <span style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#2dd4a8;">✓ bundled</span>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8b90a0;">Gemini API</span>
          <span style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#ffd166;">key required</span>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8b90a0;">Google OAuth</span>
          <span style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#ffd166;">1st login only</span>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ============================================================
# 🔑 API KEY SECTION
# ============================================================

# โหลด config และ keys ที่บันทึกไว้
import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils import load_config, save_config

_cfg = load_config()

# โหลดค่าเดิมจาก config เข้า session_state ครั้งแรก
if 'gemini_key1' not in st.session_state:
    st.session_state.gemini_key1 = _cfg.get('gemini_key1', '')
if 'gemini_key2' not in st.session_state:
    st.session_state.gemini_key2 = _cfg.get('gemini_key2', '')

st.markdown("""
<div style="height:1px; background:rgba(255,255,255,0.08); margin:32px 0 28px 0;"></div>
<div style="font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.12em;
  color:#555a6a; text-transform:uppercase; margin-bottom:20px; padding-bottom:8px;
  border-bottom:1px solid rgba(255,255,255,0.08);">
  04 — Gemini API Keys
</div>
""", unsafe_allow_html=True)

with st.container(border=True):
    st.markdown("""
    <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:15px; font-weight:700;
      color:#e8eaf0; margin-bottom:4px;">🔑 ตั้งค่า Gemini API Keys</div>
    <div style="font-family:'IBM Plex Sans Thai',sans-serif; font-size:13px; color:#8b90a0;
      line-height:1.6; margin-bottom:8px;">
      ใส่ครั้งเดียว ระบบจะจำไว้ให้อัตโนมัติ — ใส่ 2 keys เพื่อให้ระบบสลับอัตโนมัติเมื่อ quota หมด
    </div>
    """, unsafe_allow_html=True)

    key_col1, key_col2 = st.columns(2, gap="medium")

    with key_col1:
        k1_saved = bool(st.session_state.gemini_key1)
        new_k1 = st.text_input("Gemini Key 1 — หลัก",
            value=st.session_state.gemini_key1,
            type="password", placeholder="AIzaSy...", key="input_k1")
        if k1_saved:
            st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#2dd4a8;margin-top:-10px;'>● บันทึกแล้ว</div>", unsafe_allow_html=True)

    with key_col2:
        k2_saved = bool(st.session_state.gemini_key2)
        new_k2 = st.text_input("Gemini Key 2 — สำรอง (ไม่บังคับ)",
            value=st.session_state.gemini_key2,
            type="password", placeholder="AIzaSy...", key="input_k2")
        if k2_saved:
            st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#2dd4a8;margin-top:-10px;'>● บันทึกแล้ว</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    _nc, _bc = st.columns([8.5, 1])
    with _nc:
        st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:11px;color:#555a6a;padding-top:8px;'>🔒 เก็บใน config ในเครื่อง ไม่ได้ส่งออกไปที่ไหน</div>", unsafe_allow_html=True)
    with _bc:
        _saved = st.button("💾 บันทึก Keys", key="save_keys_btn")
    if _saved:
        if not new_k1:
            st.error("❌ กรุณาใส่ Key 1 ก่อนครับ")
        else:
            st.session_state.gemini_key1 = new_k1
            st.session_state.gemini_key2 = new_k2
            _cfg['gemini_key1'] = new_k1
            _cfg['gemini_key2'] = new_k2
            save_config(_cfg)
            st.success("✅ บันทึกแล้ว!")

# ============================================================
# FOOTER
# ============================================================
st.markdown("""
<div style="height:1px; background:rgba(255,255,255,0.08); margin:32px 0 16px 0;"></div>
<div style="display:flex; justify-content:space-between; align-items:center;">
  <div style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#555a6a;">
    LoadPAP Suite · พัฒนาเพื่อลด Man-hours และ Human Error
  </div>
  <div style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#555a6a;">
    macOS · Streamlit · Python
  </div>
</div>
""", unsafe_allow_html=True)