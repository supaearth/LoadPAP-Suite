import sys
import os

import numpy as np
import pandas as pd
import streamlit as st
import subprocess
import re
import webbrowser
import io
import time
import concurrent.futures
from googleapiclient.http import MediaIoBaseDownload

# ✅ ดึงฟังก์ชันกลางจาก utils.py (ไม่ต้องเขียนซ้ำอีกแล้ว)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from utils import (
    get_sheets_service,
    get_drive_service,
    extract_id,
    sanitize_filename,
    select_folder_mac as get_folder_path,
    load_config,
    save_config,
    ROOT_DIR,
    inject_global_css,
)

# ==========================================
# 📍 0. ตั้งค่าตำแหน่ง FFmpeg
# ==========================================
FFMPEG_EXE = os.path.join(ROOT_DIR, "ffmpeg")

def parse_sheet_time(t_str):
    t_str = str(t_str).strip()
    if not t_str or t_str == "0" or t_str.lower() in ["none", "nan"]: return 0.0
    if ":" in t_str:
        parts = t_str.split(":")
        if len(parts) == 3: return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
        elif len(parts) == 2: return float(parts[0])*60 + float(parts[1])
    if "." in t_str:
        parts = t_str.split(".")
        minutes = float(parts[0]) if parts[0] else 0.0
        sec_str = parts[1]
        if len(sec_str) == 1: sec_str += "0"
        seconds = float(sec_str)
        return (minutes * 60.0) + seconds
    try: return float(t_str)
    except (ValueError, TypeError): return 0.0

def update_sheet_status_by_name(service, spreadsheet_id, target_name, status_text):
    if not spreadsheet_id or not target_name: return
    try:
        result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="Sheet1!A:B").execute()
        rows = result.get('values', [])
        target_row = None
        for i, row in enumerate(rows):
            if not row: continue
            col_a = str(row[0]).strip() if len(row) > 0 else ""
            col_b = str(row[1]).strip() if len(row) > 1 else ""
            target_str = str(target_name).strip()
            if target_str and (target_str in col_a or target_str in col_b):
                target_row = i + 1
                break
        if target_row:
            range_name = f"Sheet1!F{target_row}"
            body = {'values': [[status_text]]}
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id, range=range_name,
                valueInputOption="USER_ENTERED", body=body).execute()
    except Exception as e:
        print(f"Warning: Error updating sheet: {e}")

def read_sheet_data(service, spreadsheet_id, range_name="Sheet1!A2:E"):
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    return result.get('values', [])

def force_open_tab(url):
    try: subprocess.run(['open', '-a', 'Google Chrome', url], check=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError): webbrowser.open_new_tab(url)

def get_bad_segments(file_path):
    def _detect(vf):
        cmd = [FFMPEG_EXE, '-i', file_path, '-vf', vf, '-f', 'null', '-']
        res = subprocess.run(cmd, capture_output=True)
        stderr = res.stderr.decode('utf-8', errors='ignore')
        starts = re.findall(r'black_start:\s*([\d.]+)', stderr)
        ends   = re.findall(r'black_end:\s*([\d.]+)',   stderr)
        return [(float(starts[i]), float(ends[i]) if i < len(ends) else 99999.0)
                for i in range(len(starts))]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_black = ex.submit(_detect, 'blackdetect=d=0.05:pic_th=0.98:pix_th=0.10')
        f_white = ex.submit(_detect, 'negate,blackdetect=d=0.05:pic_th=0.98:pix_th=0.10')
        segments = f_black.result() + f_white.result()

    segments.sort(key=lambda x: x[0])
    # Merge overlapping/adjacent segments
    merged = []
    for s, e in segments:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(str(s), str(e)) for s, e in merged]

def run_ffmpeg_process(input_p, output_p, start=None, end=None, duration=None, is_none=False):
    temp_out = output_p.replace(".mp4", "_temp.mp4")
    if is_none:
        # copy โดยตรง ไม่ต้อง detect (ไม่มีการ re-encode)
        res = subprocess.run([FFMPEG_EXE, '-y', '-i', input_p, '-c', 'copy', output_p], capture_output=True)
        return res.returncode == 0 and os.path.exists(output_p) and os.path.getsize(output_p) > 1024
    cmd = [FFMPEG_EXE, '-y']
    start_sec = float(start) if start is not None else 0.0
    if start_sec > 0: cmd += ['-ss', str(start_sec)]
    cmd += ['-i', input_p]
    if end is not None:
        calc_dur = float(end) - start_sec
        if calc_dur > 0: cmd += ['-t', str(calc_dur)]
    elif duration is not None: cmd += ['-t', str(duration)]
    cmd += ['-threads', '0', '-c:v', 'libx264', '-crf', '18', '-preset', 'ultrafast', '-c:a', 'aac', temp_out]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0 or not os.path.exists(temp_out) or os.path.getsize(temp_out) <= 1024:
        if os.path.exists(temp_out): os.remove(temp_out)
        return False
    bads = get_bad_segments(temp_out)
    if not bads:
        os.rename(temp_out, output_p); return True
    probe_res_raw = subprocess.run([FFMPEG_EXE, '-i', temp_out], capture_output=True)
    has_audio = "Audio:" in probe_res_raw.stderr.decode('utf-8', errors='ignore')
    filter_str = "not(" + " + ".join([f"between(t,{s},{e})" for s, e in bads]) + ")"
    cmd_clean = [FFMPEG_EXE, '-y', '-i', temp_out, '-vf', f"select='{filter_str}',setpts=N/FRAME_RATE/TB"]
    if has_audio: cmd_clean += ['-af', f"aselect='{filter_str}',asetpts=N/SR/TB", '-c:a', 'aac']
    cmd_clean += ['-threads', '0', '-c:v', 'libx264', '-crf', '18', '-preset', 'ultrafast', output_p]
    res_clean = subprocess.run(cmd_clean, capture_output=True)
    if res_clean.returncode == 0 and os.path.exists(output_p) and os.path.getsize(output_p) > 1024:
        os.remove(temp_out); return True
    # clean pass ล้มเหลว — fallback ใช้ temp แทน
    if os.path.exists(output_p): os.remove(output_p)
    os.rename(temp_out, output_p); return True

def run_ffmpeg_multi_trim(input_p, output_p, segments):
    list_file = output_p.replace(".mp4", "_list.txt")
    probe_res = subprocess.run([FFMPEG_EXE, '-i', input_p], capture_output=True)
    has_audio = "Audio:" in probe_res.stderr.decode('utf-8', errors='ignore')

    def _trim_part(args):
        i, s, e = args
        part_name = output_p.replace(".mp4", f"_part{i}.mp4")
        dur = float(e) - float(s)
        cmd_trim = [FFMPEG_EXE, '-y', '-ss', str(s), '-i', input_p, '-t', str(dur),
                    '-threads', '0', '-c:v', 'libx264', '-crf', '18', '-preset', 'ultrafast']
        if has_audio: cmd_trim += ['-c:a', 'aac']
        cmd_trim.append(part_name)
        res = subprocess.run(cmd_trim, capture_output=True)
        if res.returncode == 0 and os.path.exists(part_name) and os.path.getsize(part_name) > 1024:
            return part_name
        return None

    temp_files = []
    try:
        max_workers = min(len(segments), os.cpu_count() or 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            # map รักษาลำดับตาม input → concat ถูกต้องเสมอ
            results = list(ex.map(_trim_part, [(i, s, e) for i, (s, e) in enumerate(segments)]))
        temp_files = [r for r in results if r is not None]
        if not temp_files: return False
        with open(list_file, 'w', encoding='utf-8') as f:
            for t in temp_files:
                f.write("file '" + t + "'\n")
        temp_out = output_p.replace(".mp4", "_multi_temp.mp4")
        subprocess.run([FFMPEG_EXE, '-y', '-f', 'concat', '-safe', '0', '-i', list_file, '-c', 'copy', temp_out], capture_output=True)
        if os.path.exists(temp_out) and os.path.getsize(temp_out) > 1024:
            bads = get_bad_segments(temp_out)
            if not bads:
                os.rename(temp_out, output_p); return True
            else:
                filter_str_bad = "not(" + " + ".join([f"between(t,{bs},{be})" for bs, be in bads]) + ")"
                cmd_clean = [FFMPEG_EXE, '-y', '-i', temp_out,
                             '-vf', f"select='{filter_str_bad}',setpts=N/FRAME_RATE/TB"]
                if has_audio: cmd_clean += ['-af', f"aselect='{filter_str_bad}',asetpts=N/SR/TB", '-c:a', 'aac']
                cmd_clean += ['-threads', '0', '-c:v', 'libx264', '-crf', '18', '-preset', 'ultrafast', output_p]
                res_clean = subprocess.run(cmd_clean, capture_output=True)
                if res_clean.returncode == 0 and os.path.exists(output_p) and os.path.getsize(output_p) > 1024:
                    os.remove(temp_out)
                else:
                    if os.path.exists(output_p): os.remove(output_p)
                    os.rename(temp_out, output_p)
                return True
        return False
    finally:
        for t in temp_files:
            if os.path.exists(t): os.remove(t)
        if os.path.exists(list_file): os.remove(list_file)

def batch_scan_drive(all_ids, drive_service):
    if not drive_service or not all_ids: return {}
    valid_exts = ('.mp4', '.mov', '.m4v', '.avi')
    found_map = {}
    for i in range(0, len(all_ids), 20):
        chunk = all_ids[i:i+20]
        query_parts = [f"name contains '{c}'" for c in chunk]
        query = f"({' or '.join(query_parts)}) and trashed = false"
        try:
            results = drive_service.files().list(
                q=query, corpora='allDrives', supportsAllDrives=True,
                includeItemsFromAllDrives=True, fields="files(id, name, webViewLink)"
            ).execute()
            for f in results.get('files', []):
                if not f['name'].lower().endswith(valid_exts): continue
                for c in chunk:
                    if c.lower() in f['name'].lower():
                        found_map[c] = f; break
        except Exception as e:
            print(f"Warning: Batch Drive Search Error: {e}")
    return found_map

def scan_file_location(video_id, src_f, arc_f, drive_service):
    search_id = str(video_id).lower().strip()
    if search_id.startswith(('rw', 'rc')): search_id = search_id[2:]
    valid_exts = ('.mp4', '.mov', '.m4v', '.avi')
    if src_f and os.path.exists(src_f):
        for f in os.listdir(src_f):
            if f.lower().endswith(valid_exts) and search_id in f.lower():
                return "Source", os.path.join(src_f, f)
    if arc_f and os.path.exists(arc_f):
        for f in os.listdir(arc_f):
            if f.lower().endswith(valid_exts) and search_id in f.lower():
                return "Archive", os.path.join(arc_f, f)
    if drive_service:
        result = batch_scan_drive([search_id], drive_service)
        if result:
            return "Drive", list(result.values())[0]
    return None, None

def download_from_drive(drive_file_id, drive_file_name, dest_folder, drive_service):
    try:
        file_path = os.path.join(dest_folder, sanitize_filename(drive_file_name))
        if os.path.exists(file_path): return file_path
        request = drive_service.files().get_media(fileId=drive_file_id)
        fh = io.FileIO(file_path, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        return file_path
    except Exception as e:
        print(f"Warning: Drive Download Error: {e}")
        return None

def check_status(video_id, new_name=None):
    # 1. cutting ก่อนเสมอ
    proc = st.session_state.get('processing_id')
    if proc and str(video_id).strip().upper() == str(proc).strip().upper():
        return "cutting"
    # 2. done — ไฟล์ output มีอยู่แล้ว
    dst_f = st.session_state.get('dst_folder', '')
    if dst_f and new_name:
        if os.path.exists(os.path.join(dst_f, f"{sanitize_filename(new_name)}.mp4")):
            return "done"
    # 3. ready — มีไฟล์ต้นทาง
    src_f = st.session_state.get('src_folder')
    arc_f = st.session_state.get('archive_folder')
    loc, _ = scan_file_location(video_id, src_f, arc_f, None)
    if loc in ["Source", "Archive"]: return "ready"
    return "waiting"


st.set_page_config(page_title="PyRUSH — Auto Cutter", layout="wide")

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

.lad-stat-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:4px;}
.lad-stat{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:14px 16px;}
.lad-stat-val{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-stat);font-weight:600;display:block;}
.lad-stat-lbl{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;text-transform:uppercase;letter-spacing:.08em;margin-top:2px;}

.lad-codes-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
.lad-codes-card{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:18px;}
.lad-codes-r{border-top:2px solid #ff7a2f;}
.lad-codes-g{border-top:2px solid #4a9eff;}
.lad-codes-title{font-size:var(--fs-lg);font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:8px;}
.lad-code-box{background:#0d0f12;border:1px solid rgba(255,255,255,0.06);border-radius:6px;padding:8px 12px;margin-bottom:10px;font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#ff4d4d;line-height:1.8;}
.lad-open-btn{width:100%;background:rgba(74,158,255,.1);border:1px solid rgba(74,158,255,.25);border-radius:6px;padding:7px;color:#4a9eff;font-size:var(--fs-sm);cursor:pointer;font-family:'IBM Plex Sans Thai',sans-serif;}
.lad-found-row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);}
.lad-found-id{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);font-weight:600;}

.lad-task{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-top:2px solid #2dd4a8;border-radius:12px;padding:18px;}
.lad-task-hdr{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);letter-spacing:.1em;color:#555a6a;text-transform:uppercase;margin-bottom:12px;display:flex;justify-content:space-between;}
.lad-task-row{display:flex;align-items:center;gap:10px;padding:9px 12px;background:#1a1e26;border-radius:7px;margin-bottom:6px;border:1px solid rgba(255,255,255,0.05);}
.lad-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
.lad-id{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#8b90a0;width:120px;flex-shrink:0;}
.lad-name{font-size:var(--fs-md);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lad-act{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;width:70px;flex-shrink:0;text-align:right;}
.lad-badge{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);font-weight:600;padding:2px 9px;border-radius:12px;}
.b-done{background:rgba(45,212,168,.12);color:#2dd4a8;border:1px solid rgba(45,212,168,.25);}
.b-cut{background:rgba(74,158,255,.12);color:#4a9eff;border:1px solid rgba(74,158,255,.25);}
.b-ready{background:rgba(255,209,102,.12);color:#ffd166;border:1px solid rgba(255,209,102,.25);}
.b-wait{background:rgba(255,77,77,.12);color:#ff4d4d;border:1px solid rgba(255,77,77,.25);}
.b-loc{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);font-weight:600;padding:2px 8px;border-radius:12px;}
.b-local{background:rgba(45,212,168,.12);color:#2dd4a8;border:1px solid rgba(45,212,168,.25);}
.b-drive{background:rgba(74,158,255,.12);color:#4a9eff;border:1px solid rgba(74,158,255,.25);}
</style>
""", unsafe_allow_html=True)

# ============================================================
# ⚙️ SESSION STATE
# ============================================================
if 'processing_id' not in st.session_state: st.session_state.processing_id = None
app_config = load_config()
for k, v in [
    ('archive_folder', app_config.get('archive_folder', '')),
    ('src_folder',     app_config.get('src_folder', '')),
    ('dst_folder',     app_config.get('dst_folder', '')),
]:
    if k not in st.session_state: st.session_state[k] = v

# ============================================================
# 🗂️ SIDEBAR
# ============================================================
sheet_url = ""  # declare ก่อน เพื่อให้ watchdog section เข้าถึงได้
with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding-bottom:14px;
      border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:14px;">
      <div style="width:8px;height:8px;border-radius:50%;background:#2dd4a8;flex-shrink:0;"></div>
      <div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);font-weight:600;color:#e8eaf0;">PyRUSH</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;letter-spacing:.06em;">AUTO VIDEO CUTTER</div>
      </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:6px;'>1 — Google Sheet URL</div>", unsafe_allow_html=True)
    sheet_url = st.text_input("Sheet URL", label_visibility="collapsed", placeholder="วาง URL Sheet...")

    st.divider()
    st.markdown("<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);letter-spacing:.12em;color:#555a6a;text-transform:uppercase;margin-bottom:6px;'>2 — โฟลเดอร์</div>", unsafe_allow_html=True)

    if st.button("📁 Source Folder", use_container_width=True):
        p = get_folder_path("Select Source Folder")
        if p:
            st.session_state.src_folder = p
            app_config['src_folder'] = p
            save_config(app_config)
            st.rerun()
    st.markdown(f"<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;background:#1a1e26;border-radius:4px;padding:4px 8px;margin-bottom:6px;word-break:break-all;'>{st.session_state.src_folder or 'ยังไม่ได้เลือก'}</div>", unsafe_allow_html=True)

    if st.button("🗄️ Archive Folder", use_container_width=True):
        p = get_folder_path("Select Archive Folder")
        if p:
            st.session_state.archive_folder = p
            app_config['archive_folder'] = p
            save_config(app_config)
            st.rerun()
    st.markdown(f"<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;background:#1a1e26;border-radius:4px;padding:4px 8px;margin-bottom:6px;word-break:break-all;'>{st.session_state.archive_folder or 'ยังไม่ได้เลือก'}</div>", unsafe_allow_html=True)

    if st.button("🎯 Destination Folder", use_container_width=True):
        p = get_folder_path("Select Destination Folder")
        if p:
            st.session_state.dst_folder = p
            app_config['dst_folder'] = p
            save_config(app_config)
            st.rerun()
    st.markdown(f"<div style='font-family:IBM Plex Mono,monospace;font-size:var(--fs-xs);color:#555a6a;background:#1a1e26;border-radius:4px;padding:4px 8px;margin-bottom:6px;word-break:break-all;'>{st.session_state.dst_folder or 'ยังไม่ได้เลือก'}</div>", unsafe_allow_html=True)

    st.divider()
    read_btn = st.button("📥 Fetch Jobs", type="primary", use_container_width=True)

# ============================================================
# 🖥️ MAIN — HEADER
# ============================================================
st.markdown("""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <div style="font-size:var(--fs-hero);">⚡️</div>
  <div>
    <div style="font-family:'IBM Plex Sans Thai',sans-serif;font-size:var(--fs-hero);font-weight:700;color:#e8eaf0;line-height:1.1;">PyRUSH</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#555a6a;margin-top:2px;letter-spacing:.04em;">AUTO VIDEO CUTTER — FFMPEG ENGINE</div>
  </div>
</div>
<div style="height:1px;background:rgba(255,255,255,0.08);margin:16px 0 20px 0;"></div>
""", unsafe_allow_html=True)

# ── Watchdog toggle (บนสุด ชิดขวา) ──
if 'watchdog_on' not in st.session_state:
    st.session_state.watchdog_on = False

_, _wdc = st.columns([8, 1])
with _wdc:
    _wd_on = st.toggle("🤖 Watchdog", value=st.session_state.watchdog_on, key="wd_toggle")
    st.session_state.watchdog_on = _wd_on


_wd_sub_color = "#2dd4a8" if _wd_on else "#555a6a"
_wd_sub_text = "กำลังทำงาน — ตรวจไฟล์ใหม่ทุก 3 วินาที" if _wd_on else "ปิดอยู่ — เปิดเพื่อให้ระบบตัดต่ออัตโนมัติ"
st.markdown(
    f"<div style='text-align:right;font-family:IBM Plex Mono,monospace;"
    f"font-size:var(--fs-sm);color:{_wd_sub_color};margin-top:-12px;margin-bottom:12px;'>"
    f"{_wd_sub_text}</div>",
    unsafe_allow_html=True
)

# ── Stat cards ──
_tasks = st.session_state.get('all_tasks', [])
_total = len(_tasks)
_done_c  = sum(1 for t in _tasks if check_status(t['id'], t['name']) == 'done') if _tasks else 0
_wait_c  = sum(1 for t in _tasks if check_status(t['id'], t['name']) == 'waiting') if _tasks else 0
_err_c   = 0  # error = ไม่มีไฟล์และไม่ได้ทำงาน (waiting แต่ watchdog เคย process แล้ว)

st.markdown(
    f'<div class="lad-stat-row">'
    f'<div class="lad-stat"><span class="lad-stat-val" style="color:#e8eaf0;">{_total}</span><div class="lad-stat-lbl">📦 งานทั้งหมด</div></div>'
    f'<div class="lad-stat"><span class="lad-stat-val" style="color:#2dd4a8;">{_done_c}</span><div class="lad-stat-lbl">✅ เสร็จแล้ว</div></div>'
    f'<div class="lad-stat"><span class="lad-stat-val" style="color:#ff4d4d;">{_err_c}</span><div class="lad-stat-lbl">❌ Error</div></div>'
    f'<div class="lad-stat"><span class="lad-stat-val" style="color:#ffd166;">{_wait_c}</span><div class="lad-stat-lbl">⏳ รอไฟล์</div></div>'
    f'</div>',
    unsafe_allow_html=True
)

# ============================================================
# 📥 FETCH JOBS
# ============================================================
if read_btn and sheet_url:
    with st.spinner("📥 กำลังดึงข้อมูลและค้นหาไฟล์..."):
        try:
            service = get_sheets_service()
            drive_service = get_drive_service()
            rows = read_sheet_data(service, extract_id(sheet_url))
            all_tasks = []; r_u = set(); g_u = set()
            for row in rows:
                if len(row) < 3: continue
                vid, name, act = row[0].strip(), row[1].strip(), row[2].strip()
                all_tasks.append({"id": vid, "name": name, "action": act,
                    "start": row[3] if len(row)>3 else "", "end": row[4] if len(row)>4 else ""})
                if vid.lower().startswith(('rw','rc')) or vid.lower().endswith('rp1'): r_u.add(vid)
                else: g_u.add(vid)
            st.session_state.all_tasks = all_tasks
            src_f = st.session_state.get('src_folder')
            arc_f = st.session_state.get('archive_folder')
            st.session_state.found_files = {}
            g_miss=[]; g_found=[]; r_miss=[]; r_found=[]
            valid_exts = ('.mp4','.mov','.m4v','.avi')
            all_ids = sorted(list(g_u)) + sorted(list(r_u))
            local_found = {}; ids_need_drive = []
            for vid in all_ids:
                search_id = vid.lower().strip()
                if search_id.startswith(('rw','rc')): search_id = search_id[2:]
                found_local = False
                for folder in [src_f, arc_f]:
                    if folder and os.path.exists(folder):
                        for f in os.listdir(folder):
                            if f.lower().endswith(valid_exts) and search_id in f.lower():
                                local_found[vid] = ("Source" if folder==src_f else "Archive", os.path.join(folder, f))
                                found_local = True; break
                    if found_local: break
                if not found_local: ids_need_drive.append(vid)
            drive_found = batch_scan_drive(ids_need_drive, drive_service) if ids_need_drive else {}
            for vid in sorted(list(g_u)):
                if vid in local_found: loc,path=local_found[vid]; g_found.append((vid,loc)); st.session_state.found_files[vid]=(loc,path)
                elif vid in drive_found: g_found.append((vid,"Drive")); st.session_state.found_files[vid]=("Drive",drive_found[vid])
                else: g_miss.append(vid)
            for vid in sorted(list(r_u)):
                if vid in local_found: loc,path=local_found[vid]; r_found.append((vid,loc)); st.session_state.found_files[vid]=(loc,path)
                elif vid in drive_found: r_found.append((vid,"Drive")); st.session_state.found_files[vid]=("Drive",drive_found[vid])
                else: r_miss.append(vid)
            st.session_state.getty_missing=g_miss; st.session_state.getty_found=g_found
            st.session_state.reuters_missing=r_miss; st.session_state.reuters_found=r_found
            st.success("✅ โหลดข้อมูลเรียบร้อย!")
        except Exception as e: st.error(f"Error: {e}")

# ============================================================
# 🗂️ DOWNLOAD CODES + TASK TABLE
# ============================================================
st.markdown("""
<style>
.tbl-card{background:#13161b;border:1px solid rgba(255,255,255,0.08);border-top:2px solid #2dd4a8;border-radius:12px;overflow:hidden;}
.tbl-top{display:flex;justify-content:space-between;align-items:center;padding:13px 20px;border-bottom:1px solid rgba(255,255,255,0.08);}
.tbl-top-title{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);letter-spacing:.1em;color:#555a6a;text-transform:uppercase;}
.tbl-top-count{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);color:#555a6a;}
.lad-tbl{width:100%;border-collapse:collapse;}
.lad-tbl thead tr{border-bottom:1px solid rgba(255,255,255,0.08);}
.lad-tbl thead th{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-xs);letter-spacing:.06em;color:#555a6a;text-transform:uppercase;padding:10px 16px;text-align:left;font-weight:600;}
.lad-tbl thead th.th-r{text-align:right;}
.lad-tbl tbody tr{border-bottom:1px solid rgba(255,255,255,0.04);transition:background .15s;}
.lad-tbl tbody tr:last-child{border-bottom:none;}
.lad-tbl tbody tr:hover{background:rgba(255,255,255,0.03);}
.lad-tbl tbody tr.cutting{background:#161d2e;}
.lad-tbl td{padding:11px 16px;vertical-align:middle;}
.td-id{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#c0c4d0;width:160px;}
.td-name{font-size:var(--fs-md);font-weight:600;color:#e8eaf0;}
.td-act{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);color:#8b90a0;width:90px;}
.td-st{width:120px;text-align:right;}
.lad-b{font-family:'IBM Plex Mono',monospace;font-size:var(--fs-sm);font-weight:600;padding:3px 10px;border-radius:20px;white-space:nowrap;display:inline-block;}
.b-done{background:rgba(45,212,168,.12);color:#2dd4a8;border:1px solid rgba(45,212,168,.3);}
.b-cut {background:rgba(74,158,255,.15);color:#4a9eff;border:1px solid rgba(74,158,255,.35);}
.b-rdy {background:rgba(255,209,102,.12);color:#ffd166;border:1px solid rgba(255,209,102,.3);}
.b-wait{background:rgba(255,77,77,.08);color:#ff6b6b;border:1px solid rgba(255,77,77,.2);}
</style>
""", unsafe_allow_html=True)

if 'all_tasks' in st.session_state:
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Download codes ──
    m_r = st.session_state.get('reuters_missing', [])
    f_r = st.session_state.get('reuters_found', [])
    m_g = st.session_state.get('getty_missing', [])
    f_g = st.session_state.get('getty_found', [])

    col_r, col_g = st.columns(2, gap="medium")

    with col_r:
        miss_badge_r = f'<span class="lad-badge b-wait">{len(m_r)} ต้องโหลด</span>' if m_r else '<span class="lad-badge b-done">ครบแล้ว</span>'
        codes_html_r = '<br>'.join(m_r)
        body_r = (
            f'<div class="lad-code-box">{codes_html_r}</div>'
            if m_r else
            '<div style="background:rgba(45,212,168,.06);border:1px solid rgba(45,212,168,.2);'
            'border-radius:7px;padding:10px;text-align:center;margin-bottom:10px;">'
            '<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#2dd4a8;">'
            '✅ มีไฟล์ Reuters ครบหมดแล้ว</span></div>'
        )
        st.markdown(
            f'<div class="lad-codes-card lad-codes-r">'
            f'<div class="lad-codes-title">🟠 Reuters Connect {miss_badge_r}</div>'
            f'{body_r}</div>',
            unsafe_allow_html=True
        )
        if m_r:
            if st.button("🔗 เปิด Tab Reuters ทั้งหมด", use_container_width=True, key="open_reuters"):
                for rid in m_r:
                    force_open_tab(f"https://www.reutersconnect.com/all?search=all%3A{rid}")
        if f_r:
            found_html = ""
            for rid, loc in f_r:
                if loc == "Drive":
                    drive_info = st.session_state.found_files.get(rid, ("", {}))[1]
                    drive_info = drive_info if isinstance(drive_info, dict) else {}
                    link = drive_info.get("webViewLink", "#")
                    loc_badge = f'<a href="{link}" target="_blank" style="text-decoration:none;"><span class="lad-badge b-drive">☁️ Drive</span></a>'
                else:
                    loc_badge = '<span class="lad-badge b-local">📂 Local</span>'
                found_html += (
                    f'<div class="lad-found-row">'
                    f'<span style="color:#2dd4a8;font-size:var(--fs-xs);">✓</span>'
                    f'<span class="lad-found-id" style="color:#ff7a2f;">{rid}</span>'
                    f'<span style="margin-left:auto;">{loc_badge}</span></div>'
                )
            st.markdown(found_html, unsafe_allow_html=True)

    with col_g:
        miss_badge_g = f'<span class="lad-badge b-wait">{len(m_g)} ต้องโหลด</span>' if m_g else '<span class="lad-badge b-done">ครบแล้ว</span>'
        codes_html_g = '<br>'.join(m_g)
        body_g = (
            f'<div class="lad-code-box">{codes_html_g}</div>'
            if m_g else
            '<div style="background:rgba(45,212,168,.06);border:1px solid rgba(45,212,168,.2);'
            'border-radius:7px;padding:10px;text-align:center;margin-bottom:10px;">'
            '<span style="font-family:IBM Plex Mono,monospace;font-size:var(--fs-sm);color:#2dd4a8;">'
            '✅ มีไฟล์ Getty ครบหมดแล้ว</span></div>'
        )
        st.markdown(
            f'<div class="lad-codes-card lad-codes-g">'
            f'<div class="lad-codes-title">🔵 Getty Images {miss_badge_g}</div>'
            f'{body_g}</div>',
            unsafe_allow_html=True
        )
        if m_g:
            if st.button("🔗 เปิด Tab Getty ทั้งหมด", use_container_width=True, key="open_getty"):
                for gid in m_g:
                    force_open_tab(f"https://www.gettyimages.com/search/2/image?phrase={gid}")
        if f_g:
            found_html = ""
            for gid, loc in f_g:
                if loc == "Drive":
                    drive_info = st.session_state.found_files.get(gid, ("", {}))[1]
                    drive_info = drive_info if isinstance(drive_info, dict) else {}
                    link = drive_info.get("webViewLink", "#")
                    loc_badge = f'<a href="{link}" target="_blank" style="text-decoration:none;"><span class="lad-badge b-drive">☁️ Drive</span></a>'
                else:
                    loc_badge = '<span class="lad-badge b-local">📂 Local</span>'
                found_html += (
                    f'<div class="lad-found-row">'
                    f'<span style="color:#2dd4a8;font-size:var(--fs-xs);">✓</span>'
                    f'<span class="lad-found-id" style="color:#4a9eff;">{gid}</span>'
                    f'<span style="margin-left:auto;">{loc_badge}</span></div>'
                )
            st.markdown(found_html, unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Task table ──


    def _make_row(t):
        stat = check_status(t['id'], t['name'])
        name = str(t['name']).strip()
        if stat == "done":
            badge = '<span class="lad-b b-done">✅ Done</span>'
            cls = ""
        elif stat == "cutting":
            badge = '<span class="lad-b b-cut">🔥 Cutting</span>'
            cls = "cutting"
        elif stat == "ready":
            badge = '<span class="lad-b b-rdy">🟡 Ready</span>'
            cls = ""
        else:
            badge = '<span class="lad-b b-wait">🔴 Waiting</span>'
            cls = ""
        return (
            f'<tr class="{cls}">'
            f'<td class="td-id">{t["id"]}</td>'
            f'<td class="td-name">{name}</td>'
            f'<td class="td-act">{t["action"]}</td>'
            f'<td class="td-st">{badge}</td>'
            f'</tr>'
        )

    _thead = (
        '<thead><tr>'
        '<th>ID</th><th>ชื่องาน</th><th>Action</th><th class="th-r">Status</th>'
        '</tr></thead>'
    )

    all_t = st.session_state.all_tasks
    mid = (len(all_t) + 1) // 2
    left_rows  = ''.join(_make_row(t) for t in all_t[:mid])
    right_rows = ''.join(_make_row(t) for t in all_t[mid:])
    _n = len(all_t)

    _col_l, _col_r = st.columns(2, gap="medium")
    with _col_l:
        st.markdown(
            f'<div class="tbl-card">'
            f'<div class="tbl-top"><span class="tbl-top-title">รายการสถานะการตัด</span>'
            f'<span class="tbl-top-count">{mid}/{_n} งาน</span></div>'
            f'<table class="lad-tbl">{_thead}<tbody>{left_rows}</tbody></table>'
            f'</div>',
            unsafe_allow_html=True
        )
    with _col_r:
        st.markdown(
            f'<div class="tbl-card">'
            f'<div class="tbl-top"><span class="tbl-top-title">&nbsp;</span>'
            f'<span class="tbl-top-count">{_n - mid}/{_n} งาน</span></div>'
            f'<table class="lad-tbl">{_thead}<tbody>{right_rows}</tbody></table>'
            f'</div>',
            unsafe_allow_html=True
        )

# ============================================================
# 🐕 WATCHDOG AUTO-CUT
# ============================================================
watchdog_on = st.session_state.get('watchdog_on', False)

if watchdog_on:
    src_f = st.session_state.get('src_folder')
    arc_f = st.session_state.get('archive_folder')
    dst_f = st.session_state.get('dst_folder')
    sheet_id = extract_id(sheet_url) if sheet_url else None
    service = get_sheets_service()
    drive_service = get_drive_service()

    if src_f and dst_f and 'all_tasks' in st.session_state:
        for idx, task in enumerate(st.session_state.all_tasks):
            safe_task_name = sanitize_filename(task['name'])
            out_p = os.path.join(dst_f, f"{safe_task_name}.mp4")
            if not os.path.exists(out_p):
                loc, path_info = scan_file_location(task['id'], src_f, arc_f, drive_service)
                src_p = None
                if loc == "Drive":
                    if sheet_id: update_sheet_status_by_name(service, sheet_id, task['name'], "☁️ Downloading...")
                    src_p = download_from_drive(path_info['id'], path_info['name'], src_f, drive_service)
                elif loc in ["Source", "Archive"]:
                    src_p = path_info
                if src_p:
                    # rerun ครั้งแรก — แสดง cutting ก่อน FFmpeg เริ่ม
                    if st.session_state.processing_id != task['id']:
                        st.session_state.processing_id = task['id']
                        if sheet_id: update_sheet_status_by_name(service, sheet_id, task['name'], "⏳ Processing...")
                        st.rerun()

                    # rerun ครั้งสอง — ถึงตรงนี้แปลว่า processing_id ถูก set แล้ว ลงมือตัดได้เลย
                    act = str(task.get('action','')).lower()
                    success = False
                    if 'auto-5s' in act:
                        success = run_ffmpeg_process(src_p, out_p, start=6.0)
                    elif 'multi' in act:
                        raw_starts = [s.strip() for s in str(task['start']).split(',')]
                        raw_ends   = [e.strip() for e in str(task['end']).split(',')]
                        success = run_ffmpeg_multi_trim(src_p, out_p,
                            list(zip([parse_sheet_time(s) for s in raw_starts],
                                     [parse_sheet_time(e) for e in raw_ends])))
                    elif 'trim' in act:
                        success = run_ffmpeg_process(src_p, out_p,
                            start=parse_sheet_time(task['start']),
                            end=parse_sheet_time(task['end']))
                    elif 'none' in act:
                        success = run_ffmpeg_process(src_p, out_p, is_none=True)
                    st.session_state.processing_id = None
                    if sheet_id:
                        update_sheet_status_by_name(service, sheet_id, task['name'],
                            "✅ Done" if success else "❌ Error/Skipped")
                    if success: st.toast(f"✅ ตัดเสร็จ: {task['name']}")
                    # ตัดเสร็จแล้ว rerun ทันที ไม่ต้อง sleep
                    st.rerun()
    # ไม่มีงานที่ต้องตัด — poll ทุก 1 วินาที
    time.sleep(1)
    st.rerun()