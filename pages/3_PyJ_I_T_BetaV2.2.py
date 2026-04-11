import sys
import os
import streamlit as st
import gspread
import time
import json
import cv2
from datetime import datetime
from google import genai
from google.genai import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils import get_g_creds, select_folder_mac, load_config, inject_global_css

# ==========================================
# 🧠 GEMINI AI ENGINE (ไม่แตะ)
# ==========================================
def analyze_video_with_gemini(video_path, gemini_key):
    import re
    if not gemini_key or len(gemini_key) < 20:
        return {"person_name": "Unknown", "confidence_score": 0, "summary": "Key ผิด"}
    temp_img_path = f"temp_{int(time.time())}.jpg"
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): raise Exception("ไฟล์วิดีโอพัง หรืออ่านไม่ได้")
        cap.set(cv2.CAP_PROP_POS_FRAMES, 60)
        success, frame = cap.read()
        cap.release()
        if not success: raise Exception("แคปภาพนิ่งจากวิดีโอไม่ได้")
        cv2.imwrite(temp_img_path, frame)
        client = genai.Client(api_key=gemini_key)
        prompt = """Analyze this image from a video.
1. Identify the main person (if famous). If not sure, say 'Unknown Person'.
2. Briefly summarize what is happening in Thai.
Return ONLY a JSON object: {"summary": "...", "person_name": "...", "confidence_score": 0.xx}"""
        with open(temp_img_path, 'rb') as f:
            image_bytes = f.read()
        MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash-lite"]
        response = None
        for model_name in MODELS:
            for attempt in range(3):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")]
                    )
                    break
                except Exception as e:
                    if "503" in str(e) and attempt < 2:
                        time.sleep(10); continue
                    elif "503" in str(e) and attempt == 2:
                        break
                    raise
            if response is not None:
                break
        if response is None:
            raise Exception("ทุก model แน่นหมด")
        match = __import__('re').search(r'\{.*\}', response.text, __import__('re').DOTALL)
        if match:
            ai_data = json.loads(match.group(0))
        else:
            raise Exception(f"AI ไม่ส่ง JSON: {response.text[:200]}")
        if os.path.exists(temp_img_path): os.remove(temp_img_path)
        return ai_data
    except Exception as e:
        if os.path.exists(temp_img_path): os.remove(temp_img_path)
        return {"person_name": "Unknown (Error)", "confidence_score": 0, "summary": f"พังเพราะ: {str(e)}"}

# ==========================================
# 🖥️ UI
# ==========================================
st.set_page_config(page_title="PyJ.I.T. — AI Logger", layout="wide")

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

.jit-stat-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;}
.jit-stat{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:14px 16px;}
.jit-stat-val{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-stat);font-weight:600;display:block;}
.jit-stat-lbl{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;text-transform:uppercase;letter-spacing:.08em;margin-top:2px;}
.jit-progress{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-top:2px solid #ff7a2f;border-radius:12px;padding:18px;margin-bottom:8px;}
.jit-prog-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;}
.jit-prog-title{font-size:var(--fs-lg);font-weight:600;color:#e8eaf0;}
.jit-prog-pct{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-lg);color:#ff7a2f;}
.jit-bar-bg{background:#1a1e26;border-radius:4px;height:6px;overflow:hidden;margin-bottom:8px;}
.jit-bar-fill{height:6px;border-radius:4px;}
.jit-prog-sub{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;}
.jit-log{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:18px;margin-top:16px;}
.jit-log-title{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);letter-spacing:.1em;color:#555a6a;text-transform:uppercase;margin-bottom:12px;}
.jit-log-row{display:flex;align-items:center;gap:10px;padding:9px 12px;background:#1a1e26;border-radius:7px;margin-bottom:6px;border:1px solid rgba(255,255,255,0.05);}
.jit-log-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
.jit-log-name{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-md);color:#e8eaf0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.jit-log-person{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#8b90a0;margin-right:8px;min-width:120px;}
.jit-badge{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);font-weight:600;padding:2px 9px;border-radius:12px;white-space:nowrap;}
.b-done{background:rgba(45,212,168,.12);color:#2dd4a8;border:1px solid rgba(45,212,168,.25);}
.b-run{background:rgba(74,158,255,.12);color:#4a9eff;border:1px solid rgba(74,158,255,.25);}
.b-wait{background:rgba(255,209,102,.12);color:#ffd166;border:1px solid rgba(255,209,102,.25);}
.b-err{background:rgba(255,77,77,.12);color:#ff4d4d;border:1px solid rgba(255,77,77,.25);}
</style>
""", unsafe_allow_html=True)

# ── Session state init ──
_cfg = load_config()
_k1 = _cfg.get('gemini_key1', '')
_k2 = _cfg.get('gemini_key2', '')
MY_GEMINI_KEY = ', '.join(k for k in [_k1, _k2] if k)

defaults = {
    'target_folder': '', 'gemini_key': MY_GEMINI_KEY,
    'p_type': 'Global Focus', 'ep_name': '',
    'is_running': False, 'is_paused': False,
    'file_queue': [],    # list ของ path ทั้งหมด
    'file_status': {},   # {path: {status, person, summary}}
    'current_idx': 0,
    'key_idx': 0,
    'done_count': 0, 'error_count': 0,
    'worksheet_url': '',
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if not st.session_state.gemini_key:
    st.session_state.gemini_key = MY_GEMINI_KEY

# ── Sidebar ──
with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding-bottom:16px;
      border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:16px;">
      <div style="width:8px;height:8px;border-radius:50%;background:#ff7a2f;flex-shrink:0;"></div>
      <div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);font-weight:600;color:#e8eaf0;">PyJ.I.T.</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;letter-spacing:.06em;">AI FOOTAGE LOGGER</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:8px;'>1 — โฟลเดอร์วิดีโอ</div>", unsafe_allow_html=True)
    if st.button("📂 เลือกโฟลเดอร์...", use_container_width=True, disabled=st.session_state.is_running):
        path = select_folder_mac("เลือกโฟลเดอร์ที่มีวิดีโอ")
        if path:
            st.session_state.target_folder = path
            st.rerun()
    st.session_state.target_folder = st.text_input("Path:", value=st.session_state.target_folder, label_visibility="collapsed")

    st.divider()
    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:8px;'>2 — ข้อมูลรายการ</div>", unsafe_allow_html=True)
    p_types = ["Global Focus", "Key Messages", "News Digest", "The World Dialogue", "Special"]
    st.session_state.p_type = st.selectbox("รายการ", p_types, index=p_types.index(st.session_state.p_type), disabled=st.session_state.is_running)
    st.session_state.ep_name = st.text_input("ชื่อตอน / EP", value=st.session_state.ep_name, placeholder="เช่น เลือกตั้งสหรัฐ EP.3", disabled=st.session_state.is_running)

    st.divider()
    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:8px;'>3 — Google Sheet</div>", unsafe_allow_html=True)
    DEFAULT_SHEET = "https://docs.google.com/spreadsheets/d/1VqdUkSsZKTsFI6bYlsbCaexJnL_3cPnIJda26l1x954/edit"
    sheet_url = st.text_input("URL:", value=DEFAULT_SHEET, label_visibility="collapsed", disabled=st.session_state.is_running)

    st.divider()
    run_btn = st.button("🚀 เริ่มสแกนด้วย AI", type="primary", use_container_width=True, disabled=st.session_state.is_running)

# ── Page header ──
st.markdown("""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <div style="font-size:var(--fs-stat);">📋</div>
  <div>
    <div style="font-family:'IBM Plex Sans Thai',sans-serif;font-size:var(--fs-xl);font-weight:700;color:#e8eaf0;line-height:1.1;">PyJ.I.T.</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;margin-top:2px;letter-spacing:.04em;">AI FOOTAGE LOGGER — GEMINI VISION</div>
  </div>
</div>
<div style="height:1px;background:rgba(255,255,255,0.08);margin:16px 0 20px 0;"></div>
""", unsafe_allow_html=True)

# ── Stat cards ──
total = len(st.session_state.file_queue)
done  = st.session_state.done_count
errs  = st.session_state.error_count
wait  = max(0, total - done - errs)

st.markdown(f"""
<div class="jit-stat-row">
  <div class="jit-stat"><span class="jit-stat-val" style="color:#e8eaf0;">{total}</span><div class="jit-stat-lbl">📦 ไฟล์ทั้งหมด</div></div>
  <div class="jit-stat"><span class="jit-stat-val" style="color:#2dd4a8;">{done}</span><div class="jit-stat-lbl">✅ สำเร็จ</div></div>
  <div class="jit-stat"><span class="jit-stat-val" style="color:#ff4d4d;">{errs}</span><div class="jit-stat-lbl">❌ ผิดพลาด</div></div>
  <div class="jit-stat"><span class="jit-stat-val" style="color:#ffd166;">{wait}</span><div class="jit-stat-lbl">⏳ รอคิว</div></div>
</div>
""", unsafe_allow_html=True)

# ── Progress bar ──
pct = int((done + errs) / total * 100) if total > 0 else 0
bar_color = "#555a6a" if st.session_state.is_paused else "linear-gradient(90deg,#ff7a2f,#ffd166)"
if not st.session_state.is_running:
    prog_label = "รอเริ่มทำงาน..."
    prog_sub   = "กด เริ่มสแกน ใน sidebar เพื่อเริ่มทำงาน"
elif st.session_state.is_paused:
    prog_label = "⏸ หยุดชั่วคราว"
    prog_sub   = f"หยุดอยู่ที่ไฟล์ที่ {st.session_state.current_idx + 1}/{total} — กด Resume เพื่อทำงานต่อ"
else:
    cur_path   = st.session_state.file_queue[st.session_state.current_idx] if st.session_state.current_idx < total else ""
    cur_fname  = os.path.basename(cur_path) if cur_path else ""
    prog_label = "กำลังวิเคราะห์..."
    prog_sub   = f"ประมวลผล: {cur_fname} ({st.session_state.current_idx + 1}/{total})"

st.markdown(f"""
<div class="jit-progress">
  <div class="jit-prog-header">
    <div class="jit-prog-title">{prog_label}</div>
    <div class="jit-prog-pct">{pct}%</div>
  </div>
  <div class="jit-bar-bg">
    <div class="jit-bar-fill" style="width:{pct}%;background:{bar_color};"></div>
  </div>
  <div class="jit-prog-sub">{prog_sub}</div>
</div>
""", unsafe_allow_html=True)

# ── Pause / Reset buttons ──
_, _pc, _rc = st.columns([8.5, 1, 1])
with _pc:
    _pause_lbl = "▶ Resume" if st.session_state.is_paused else "⏸ Pause"
    if st.button(_pause_lbl, key="pause_btn", disabled=(not st.session_state.is_running), use_container_width=True):
        st.session_state.is_paused = not st.session_state.is_paused
        st.rerun()
with _rc:
    if st.button("🛑 Reset", key="reset_btn", disabled=(not st.session_state.is_running), use_container_width=True):
        st.session_state.is_running  = False
        st.session_state.is_paused   = False
        st.session_state.file_queue  = []
        st.session_state.file_status = {}
        st.session_state.current_idx = 0
        st.session_state.key_idx     = 0
        st.session_state.done_count  = 0
        st.session_state.error_count = 0
        st.rerun()

# ── Log list (แสดงทุกไฟล์ตั้งแต่แรก อัปเดต real-time) ──
if st.session_state.file_queue:
    log_html = '<div class="jit-log"><div class="jit-log-title">Log ผลการวิเคราะห์</div>'
    for fpath in st.session_state.file_queue:
        fname  = os.path.basename(fpath)
        status = st.session_state.file_status.get(fpath, {})
        s      = status.get("status", "wait")
        person = status.get("person", "—")
        if s == "done":
            dot, badge = "#2dd4a8", '<span class="jit-badge b-done">✅ Done</span>'
        elif s == "running":
            dot, badge = "#4a9eff", '<span class="jit-badge b-run">🔥 Running</span>'
        elif s == "error":
            dot, badge = "#ff4d4d", '<span class="jit-badge b-err">❌ Error</span>'
        else:
            dot, badge = "#555a6a", '<span class="jit-badge b-wait">⏳ รอคิว</span>'
        log_html += f"""
        <div class="jit-log-row">
          <div class="jit-log-dot" style="background:{dot};"></div>
          <div class="jit-log-name">{fname}</div>
          <div class="jit-log-person">{person}</div>
          {badge}
        </div>"""
    log_html += '</div>'
    st.markdown(log_html, unsafe_allow_html=True)

# ==========================================
# ── START: สร้าง queue และ init ──
# ==========================================
if run_btn:
    if not st.session_state.gemini_key:
        st.error("❌ ยังไม่ได้ตั้งค่า Gemini Key — กลับไปหน้า Main แล้วกด บันทึก Keys ก่อนครับ")
    elif not st.session_state.target_folder:
        st.error("❌ ลืมเลือกโฟลเดอร์วิดีโอครับ!")
    elif not st.session_state.ep_name:
        st.error("❌ ลืมใส่ชื่อตอน / EP ครับ!")
    else:
        valid_exts = ('.mp4', '.mov', '.mkv', '.avi', '.m4v')
        queue = []
        for root, dirs, filenames in os.walk(st.session_state.target_folder):
            for f in sorted(filenames):
                if f.lower().endswith(valid_exts) and not f.startswith('.'):
                    queue.append(os.path.join(root, f))
        if not queue:
            st.warning("🔍 ไม่พบไฟล์วิดีโอในโฟลเดอร์นี้เลยครับ")
        else:
            st.session_state.file_queue  = queue
            st.session_state.file_status = {p: {"status": "wait", "person": "—"} for p in queue}
            st.session_state.current_idx = 0
            st.session_state.key_idx     = 0
            st.session_state.done_count  = 0
            st.session_state.error_count = 0
            st.session_state.is_running  = True
            st.session_state.is_paused   = False
            st.session_state.worksheet_url = sheet_url
            st.rerun()

# ==========================================
# ── PROCESS: ประมวลผลทีละไฟล์ต่อ rerun ──
# ==========================================
if st.session_state.is_running and not st.session_state.is_paused:
    idx   = st.session_state.current_idx
    queue = st.session_state.file_queue
    total = len(queue)

    if idx >= total:
        # เสร็จแล้ว
        st.session_state.is_running = False
        st.balloons()
        st.rerun()
    else:
        fpath = queue[idx]
        fname = os.path.basename(fpath)

        # mark running
        st.session_state.file_status[fpath] = {"status": "running", "person": "วิเคราะห์อยู่..."}
        st.session_state.current_idx = idx  # ยังไม่เพิ่ม รอเสร็จก่อน

        api_keys = [k.strip() for k in st.session_state.gemini_key.split(',') if k.strip()]
        key_idx  = st.session_state.key_idx
        current_key = api_keys[key_idx % len(api_keys)]

        ai_data = analyze_video_with_gemini(fpath, current_key)
        summary = ai_data.get("summary", "AI ตอบไม่ได้")

        # quota หมด → สลับ key แล้ว rerun ใหม่
        if "429" in summary or "Quota" in summary or "exceeded" in summary.lower():
            st.session_state.key_idx = (key_idx + 1) % len(api_keys)
            time.sleep(2)
            st.rerun()

        p_name = ai_data.get("person_name", "Unknown")
        is_err = "Error" in p_name or "พัง" in summary

        st.session_state.file_status[fpath] = {
            "status": "error" if is_err else "done",
            "person": p_name,
            "summary": summary,
        }

        if is_err:
            st.session_state.error_count += 1
        else:
            st.session_state.done_count += 1
            # บันทึก Sheet
            try:
                creds = get_g_creds()
                gc = gspread.authorize(creds)
                sh = gc.open_by_url(st.session_state.worksheet_url)
                curr_month = datetime.now().strftime("%b %Y")
                try:
                    worksheet = sh.worksheet(curr_month)
                except gspread.exceptions.WorksheetNotFound:
                    worksheet = sh.add_worksheet(title=curr_month, rows="1000", cols="10")
                    worksheet.append_row(["วันที่","รายการ","ตอน","ชื่อไฟล์","บุคคล","AI สรุปเนื้อหา","สถานะ"])
                    worksheet.format("A1:G1", {"textFormat": {"bold": True}})
                score = ai_data.get("confidence_score", 0)
                worksheet.append_row([
                    datetime.now().strftime("%d/%m/%Y"),
                    st.session_state.p_type, st.session_state.ep_name,
                    fname, f"{p_name} ({score})", summary, "🟡 Review"
                ])
            except Exception as e:
                st.warning(f"⚠️ บันทึก Sheet ไม่ได้: {e}")

        # เลื่อน index แล้ว rerun ไปไฟล์ถัดไป
        st.session_state.current_idx = idx + 1
        time.sleep(1)
        st.rerun()