"""
PyL.I.V.E. — Live Intelligence Video Extractor
V3.0

วาง file นี้ที่: pages/4_PyLIVE_V3.0.py
"""

import sys, os, re, time, shutil, subprocess, tempfile, json
import streamlit as st
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yt_dlp
from PIL import Image

# ── Path setup ──────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils import load_config, inject_global_css

# ============================================================
# 0.  CONSTANTS
# ============================================================
SAFETY_BUFFER_SEC     = 2
PROBE_DURATION        = 30
OCR_CROP_RATIO        = {"left": 0.82, "top": 0.02, "right": 1.00, "bottom": 0.12}

# ============================================================
# 1.  HELPERS — binary paths (ไม่ raise ตอน module load)
# ============================================================
def _find_bin(name: str) -> Optional[str]:
    """คืน path หรือ None — ไม่ raise exception"""
    candidates = [
        os.path.join(_ROOT, name),          # ← วางไว้ใน root โปรเจกต์ (เหมือน PyLAD)
        shutil.which(name),
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
        f"/usr/local/sbin/{name}",
        f"/snap/bin/{name}",
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None

def _ff() -> str:
    """คืน path ffmpeg — ใช้ config override ก่อนถ้ามี, raise ถ้าหาไม่เจอ"""
    cfg_path = st.session_state.get("_cfg_cache", {}).get("ffmpeg_path", "")
    if cfg_path and os.path.isfile(cfg_path):
        return cfg_path
    p = _find_bin("ffmpeg")
    if p:
        return p
    raise RuntimeError(
        "ไม่พบ ffmpeg\n"
        "• macOS: brew install ffmpeg\n"
        "• Linux: sudo apt install ffmpeg\n"
        "• หรือระบุ path ใน vmaster_config.json → ffmpeg_path"
    )

def _ffp() -> str:
    """คืน path ffprobe — raise ถ้าหาไม่เจอ"""
    cfg_path = st.session_state.get("_cfg_cache", {}).get("ffprobe_path", "")
    if cfg_path and os.path.isfile(cfg_path):
        return cfg_path
    p = _find_bin("ffprobe")
    if p:
        return p
    raise RuntimeError("ไม่พบ ffprobe — ติดตั้ง ffmpeg (รวม ffprobe)")

def probe_video(path: str) -> dict:
    try:
        r = subprocess.run(
            [_ffp(), "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True)
        if r.returncode != 0:
            return {}
        d = json.loads(r.stdout)
        streams = d.get("streams", [])
        return {
            "has_video":   any(s["codec_type"] == "video" for s in streams),
            "has_audio":   any(s["codec_type"] == "audio" for s in streams),
            "video_codec": next((s.get("codec_name", "") for s in streams
                                 if s["codec_type"] == "video"), ""),
            "duration":    float(d.get("format", {}).get("duration", 0)),
            "size_mb":     os.path.getsize(path) / (1024*1024) if os.path.exists(path) else 0,
        }
    except:
        return {}

def get_duration(path: str) -> float:
    try:
        r = subprocess.run(
            [_ffp(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True)
        return float(r.stdout.strip())
    except:
        return 0.0

# ============================================================
# 2.  MODULE 1 — TEXT PARSER
# ============================================================
@dataclass
class ClipSegment:
    start_clock: str
    start_label: str
    end_clock:   str
    end_label:   str

@dataclass
class LiveBrief:
    youtube_url: str
    cover_text:  str    # อาจมีหลายบรรทัด (\n)
    caption:     str
    segments:    list[ClipSegment] = field(default_factory=list)

def clock_to_sec(s: str) -> int:
    p = s.split(".")
    return int(p[0])*3600 + int(p[1])*60 + int(p[2])

def hhmm_to_sec(s: str) -> int:
    p = s.split(":")
    return int(p[0])*3600 + int(p[1])*60 + int(p[2])

def parse_brief(text: str) -> Optional[LiveBrief]:
    url_m = re.search(
        r'https?://(?:www\.)?(?:youtube\.com/(?:live/|watch\?v=)|youtu\.be/)[\w\-?=&]+', text)
    if not url_m:
        return None

    # cover รองรับหลายบรรทัด (จน keyword ถัดไปหรือบรรทัดว่าง)
    cover_m = re.search(
        r'ปก\s*:\s*(.+?)(?=\n[ \t]*(?:แคปชั่น|TC|ลิงค์)|\n[ \t]*\n|\Z)',
        text, re.DOTALL)
    caption_m = re.search(
        r'แคปชั่น\s*:\s*(.+?)(?=\n\s*\n|\nTC|\nลิงค์|$)', text, re.DOTALL)
    tc_m = re.search(
        r'TC.*?:\s*\n?(.*?)(?=\n\s*\n|\nลิงค์|$)', text, re.DOTALL)

    segments = []
    for line in text.splitlines():
        log_line = line.strip()
        m = re.match(
            r'TC.*?:\s*(\d{2}\.\d{2}\.\d{2})\s*(.*?)\s*-\s*(\d{2}\.\d{2}\.\d{2})\s*(.*)$',
            log_line)
        if m:
            start_label = m.group(2).strip() or "clip"
            end_label   = m.group(4).strip() or start_label
            segments.append(ClipSegment(m.group(1), start_label, m.group(3), end_label))
    cover_text = ""
    if cover_m:
        cover_text = "\n".join(
            l.strip() for l in cover_m.group(1).strip().splitlines() if l.strip())

    return LiveBrief(
        youtube_url=url_m.group(0),
        cover_text=cover_text,
        caption=caption_m.group(1).strip() if caption_m else "",
        segments=segments,
    )

def compute_timestamps(segments: list[ClipSegment], stream_start: int) -> list[dict]:
    out = []
    for seg in segments:
        rs  = clock_to_sec(seg.start_clock) - stream_start
        re_ = clock_to_sec(seg.end_clock)   - stream_start
        vs  = max(0, rs - SAFETY_BUFFER_SEC)
        ve  = re_ + SAFETY_BUFFER_SEC
        out.append({
            "start_clock": seg.start_clock, "end_clock": seg.end_clock,
            "start_label": seg.start_label, "end_label": seg.end_label,
            "video_start": vs, "video_end": ve, "duration": ve - vs,
        })
    return out

# ============================================================
# 3.  MODULE 2 — OCR OFFSET + SEGMENT DOWNLOADER
# ============================================================
def _extract_frame(video: str, at: float, out: str) -> bool:
    return subprocess.run(
        [_ff(), "-y", "-ss", f"{at:.3f}", "-i", video,
         "-frames:v", "1", "-q:v", "2", out],
        capture_output=True).returncode == 0

def _crop_clock_region(frame: str, out: str) -> bool:
    try:
        img = Image.open(frame)
        w, h = img.size
        crop = img.crop((int(w*OCR_CROP_RATIO["left"]), int(h*OCR_CROP_RATIO["top"]),
                         int(w*OCR_CROP_RATIO["right"]), int(h*OCR_CROP_RATIO["bottom"])))
        crop = crop.resize((crop.width*3, crop.height*3), Image.LANCZOS)
        crop.save(out)
        return True
    except:
        return False

def _ocr_tesseract(img_path: str) -> Optional[str]:
    try:
        import pytesseract
        cfg = "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789:"
        t = pytesseract.image_to_string(Image.open(img_path), config=cfg).strip()
        cleaned = re.sub(r'[^0-9]', ':', t)
        m = re.search(r'\d{2}:\d{2}:\d{2}', cleaned)
        return m.group(0) if m else None
    except:
        return None

def _ocr_gemini(img_path: str, api_key: str) -> Optional[str]:
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        with open(img_path, "rb") as f:
            img_bytes = f.read()
        resp = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                types.Part.from_text(text=(
                    "This is a cropped image from the top-right corner of a Thai live stream. "
                    "There is a real-time wall clock showing current time of day (e.g. 15:53:34). "
                    "Read that clock and reply ONLY with the time in HH:MM:SS format. No other text."
                )),
            ],
        )
        m = re.search(r'\d{2}:\d{2}:\d{2}', resp.text.strip())
        return m.group(0) if m else None
    except:
        return None

def ocr_stream_clock(video: str, tmp_dir: str,
                     api_key: str = "", at: float = 5.0) -> Optional[str]:
    """Single-point OCR — ยังคงไว้เพื่อ backward compat"""
    frame = os.path.join(tmp_dir, "probe_frame.jpg")
    crop  = os.path.join(tmp_dir, "probe_crop.png")
    if not _extract_frame(video, at, frame): return None
    if not _crop_clock_region(frame, crop): return None
    result = _ocr_tesseract(crop)
    if result: return result
    if api_key: return _ocr_gemini(crop, api_key)
    return None

def calibrate_stream_start(probe_clip: str, tmp_dir: str, api_key: str,
                            probe_points: list = None, log=None) -> Optional[int]:
    """
    OCR นาฬิกาที่หลาย probe_points แล้ว cross-validate หา stream_start ที่แม่นยำ

    ปัญหาที่แก้:
    - force_keyframes ทำให้ frame ตรง second จริง → est = wall_sec - at ถูกต้อง
    - ใช้ median กรอง outlier จาก OCR ผิด
    - ตรวจสอบ consistency ก่อน accept: ทุกจุดต้องได้ wall_clock ต่างกัน (ไม่ซ้ำกัน)
      ถ้าซ้ำกันหมด = probe clip สั้นกว่าที่คิด หรือ frame ไม่ต่างกัน

    คืน stream_start (วินาที) หรือ None
    """
    if probe_points is None:
        probe_points = [5.0, 20.0, 40.0]   # ห่างกันมากขึ้น เพื่อให้ wall_clock ต่างกันชัด

    def _info(msg):
        if log: log(msg)

    estimates = []
    wall_clocks = []

    dur = get_duration(probe_clip)
    _info(f"  📏 Probe clip duration = {dur:.1f}s")

    # กรอง probe_points ที่อยู่นอก duration จริง
    valid_points = [p for p in probe_points if p < dur - 1]
    if len(valid_points) < 1:
        _info(f"  ❌ Probe clip สั้นเกินไป ({dur:.1f}s) — ต้องการอย่างน้อย {probe_points[0]+1}s")
        return None

    for at in valid_points:
        frame = os.path.join(tmp_dir, f"calib_{int(at)}s.jpg")
        crop  = os.path.join(tmp_dir, f"calib_{int(at)}s_crop.png")

        if not _extract_frame(probe_clip, at, frame):
            _info(f"  ⚠️  extract frame ล้มเหลวที่ {at}s — ข้าม")
            continue
        if not _crop_clock_region(frame, crop):
            _info(f"  ⚠️  crop ล้มเหลวที่ {at}s — ข้าม")
            continue

        clock_str = _ocr_tesseract(crop) or (api_key and _ocr_gemini(crop, api_key)) or None
        if not clock_str:
            _info(f"  ⚠️  OCR ล้มเหลวที่ {at}s — ข้าม")
            continue

        wall_sec = hhmm_to_sec(clock_str)
        est = wall_sec - int(at)
        estimates.append((at, clock_str, est))
        wall_clocks.append(wall_sec)
        _info(f"  🕐 @ {at}s → clock={clock_str} → stream_start estimate={est}s")

    if not estimates:
        return None

    # ⚠️ ตรวจว่า wall_clock ทุกจุดเหมือนกันหมด = frame ไม่ได้ต่างกัน (probe clip มีปัญหา)
    if len(set(wall_clocks)) == 1 and len(estimates) > 1:
        _info(f"  ⚠️  Wall clock เหมือนกันทุกจุด ({estimates[0][1]}) — probe clip อาจสั้นเกินไปหรือ keyframe ซ้ำ")
        _info(f"  ↳ ใช้จุดเดียว: @ {estimates[0][0]}s → stream_start={estimates[0][2]}s")
        return int(estimates[0][2])

    vals = sorted([e[2] for e in estimates])
    median_start = vals[len(vals) // 2]

    spread = max(vals) - min(vals)
    if spread > 5:
        _info(f"  ⚠️  OCR drift = {spread}s — ใช้ median={median_start}s")
    else:
        _info(f"  ✅ stream_start = {median_start}s  "
              f"({median_start//3600:02d}:{(median_start%3600)//60:02d}:{median_start%60:02d})")

    return int(median_start)

def _get_ffmpeg_exe() -> Optional[str]:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir  = os.path.dirname(current_dir)
    for candidate in [
        os.path.join(current_dir, "ffmpeg"),
        os.path.join(parent_dir,  "ffmpeg"),
        shutil.which("ffmpeg"),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]:
        if candidate and os.path.exists(candidate):
            return candidate
    return None

def download_probe_clip(url: str, out_dir: str) -> Optional[str]:
    """
    โหลด probe clip 60 วิ ความละเอียดต่ำ (360p) เพื่อ OCR นาฬิกา
    - ใช้ force_keyframes_at_cuts=True เพื่อให้ได้ frame ตรง second ที่ต้องการ
    - โหลด 60 วิ (แทน 30) เพื่อให้มี headroom สำหรับ calibrate หลายจุด
    """
    ffmpeg_exe = _get_ffmpeg_exe()
    out = os.path.join(out_dir, "probe_clip.mp4")
    opts = {
        'format': 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/worst',
        'merge_output_format': 'mp4',
        'outtmpl': out.replace('.mp4', '.%(ext)s'),
        'download_ranges': yt_dlp.utils.download_range_func(None, [(0, 60)]),
        'force_keyframes_at_cuts': True,   # ✅ ตัดตรง second จริง ไม่ drift ตาม keyframe
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'ffmpeg_location': ffmpeg_exe,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        # ตรวจสอบ duration จริง — ต้องได้อย่างน้อย 25 วิ
        for f in Path(out_dir).glob("probe_clip.*"):
            dur = get_duration(str(f))
            if dur >= 25:
                return str(f)
            # ถ้าสั้นเกินไป ลอง download อีกครั้งด้วย format fallback
            os.remove(str(f))
            break
        # fallback: format ยืดหยุ่นขึ้น
        opts['format'] = 'best[height<=480]/best'
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        for f in Path(out_dir).glob("probe_clip.*"):
            return str(f)
        return None
    except:
        return None

def download_segment(url: str, vs: float, ve: float, out: str) -> bool:
    ffmpeg_exe = _get_ffmpeg_exe()
    opts = {
        'format': 'bestvideo[ext=mp4][vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4][vcodec!^=av01][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'outtmpl': out.replace('.mp4', '.%(ext)s'),
        'download_ranges': yt_dlp.utils.download_range_func(None, [(vs, ve)]),
        'force_keyframes_at_cuts': False,
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'ffmpeg_location': ffmpeg_exe,
        'retries': 3, 'socket_timeout': 60,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            if ydl.download([url]) == 0:
                for f in Path(out).parent.glob(f"{Path(out).stem}.*"):
                    if f.suffix.lower() in ('.mp4', '.mkv', '.webm'):
                        if str(f) != out:
                            shutil.move(str(f), out)   # ✅ shutil.move ข้ามปัญหา cross-device rename
                        return os.path.exists(out) and os.path.getsize(out) > 10*1024
                return os.path.exists(out) and os.path.getsize(out) > 10*1024
        return False
    except:
        return False

# ============================================================
# 4.  MODULE 3 — FFMPEG CONCAT
# ============================================================
def concat_segments(seg_paths: list[str], output: str, tmp_dir: str) -> bool:
    valid = [p for p in seg_paths
             if os.path.exists(p) and os.path.getsize(p) > 10*1024]
    if not valid:
        return False
    if len(valid) == 1:
        shutil.copy2(valid[0], output)
        return os.path.exists(output)

    list_f = os.path.join(tmp_dir, "concat_list.txt")
    temp_o = output.replace(".mp4", "_ctmp.mp4")
    with open(list_f, "w", encoding="utf-8") as f:
        for p in valid:
            f.write(f"file '{p}'\n")

    r = subprocess.run(
        [_ff(), "-y", "-f", "concat", "-safe", "0", "-i", list_f,
         "-c", "copy", "-movflags", "+faststart", temp_o],
        capture_output=True)
    if r.returncode == 0 and os.path.exists(temp_o) and os.path.getsize(temp_o) > 10*1024:
        os.rename(temp_o, output)
        return True

    if os.path.exists(temp_o):
        os.remove(temp_o)
    n = len(valid)
    inputs = []
    for p in valid:
        inputs += ["-i", p]
    flt = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    r2 = subprocess.run(
        [_ff(), "-y", *inputs, "-filter_complex", flt,
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "18", "-preset", "fast",
         "-c:a", "aac", "-movflags", "+faststart", output],
        capture_output=True)
    return r2.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 10*1024

# ============================================================
# 5.  PIPELINE ORCHESTRATOR
# ============================================================
def run_pipeline(brief: LiveBrief, out_dir: str, tmp_dir: str,
                 gemini_key: str, log) -> dict:
    res = {"mp4": None, "thumbs": [], "error": None}
    os.makedirs(out_dir, exist_ok=True)

    log("📡 โหลด Probe Clip (60 วิ — 360p)...")
    log(f"DEBUG ffmpeg = {_get_ffmpeg_exe()}")
    probe = download_probe_clip(brief.youtube_url, tmp_dir)
    if not probe:
        res["error"] = "โหลด Probe Clip ล้มเหลว"
        return res

    log("🔍 Calibrate Timecode (OCR 3 จุด)...")
    stream_start = calibrate_stream_start(
        probe_clip=probe,
        tmp_dir=tmp_dir,
        api_key=gemini_key,
        probe_points=[5.0, 20.0, 40.0],
        log=log,
    )
    if stream_start is None:
        res["error"] = "Calibrate ล้มเหลว — OCR ไม่สำเร็จ ตรวจสอบ pytesseract หรือ Gemini key"
        return res

    timestamps = compute_timestamps(brief.segments, stream_start)
    if not timestamps:
        res["error"] = "ไม่มี segment — ตรวจสอบ TC format: ต้องเป็น HH.MM.SS label - HH.MM.SS"
        return res
    for i, ts in enumerate(timestamps, 1):
        log(f"  📐 SEG {i}: video [{ts['video_start']:.0f}s → {ts['video_end']:.0f}s] ({ts['duration']:.0f}s)")

    seg_paths = []
    for i, ts in enumerate(timestamps, 1):
        log(f"⬇️  Segment {i}/{len(timestamps)}: {ts['start_clock']} → {ts['end_clock']}")
        seg_out = os.path.join(tmp_dir, f"segment_{i:02d}.mp4")
        if download_segment(brief.youtube_url, ts["video_start"], ts["video_end"], seg_out):
            seg_paths.append(seg_out)
            log(f"  ✅ segment_{i:02d}.mp4  ({ts['duration']:.0f}s)")
        else:
            log(f"  ⚠️  segment_{i:02d} ล้มเหลว — ข้าม")
    if not seg_paths:
        res["error"] = "ไม่สามารถโหลด segment ได้เลย"
        return res

    log("⚡ FFmpeg Concat...")
    safe_cover = re.sub(r'[\\/*?:"<>|\'\n\r]', '', brief.cover_text)[:40].strip()
    ts_stamp   = time.strftime("%Y%m%d_%H%M")
    out_mp4    = os.path.join(out_dir, f"PyLIVE_{safe_cover}_{ts_stamp}.mp4")
    if not concat_segments(seg_paths, out_mp4, tmp_dir):
        res["error"] = "FFmpeg Concat ล้มเหลว"
        return res
    res["mp4"] = out_mp4
    info = probe_video(out_mp4)
    log(f"✅ {os.path.basename(out_mp4)}  {info.get('duration',0):.1f}s  {info.get('size_mb',0):.1f}MB")
    return res

# ============================================================
# 7.  STREAMLIT UI
# ============================================================
st.set_page_config(page_title="PyL.I.V.E.", page_icon="🎬", layout="wide")
inject_global_css()

# ── CSS — design tokens เดิม ────────────────────────────────
st.markdown("""<style>
:root{--bg0:#0d0f12;--bg1:#13161b;--bg2:#1a1e26;
  --border:rgba(255,255,255,0.08);
  --text-1:#e8eaf0;--text-2:#8b90a0;--text-3:#555a6a;
  --blue:#4a9eff;--teal:#2dd4a8;--orange:#ff7a2f;--red:#ff4d4d;}
textarea{font-family:'IBM Plex Mono',monospace!important;font-size:13px!important;
  background:#1a1e26!important;color:#e8eaf0!important;
  border:1px solid rgba(255,255,255,.1)!important;border-radius:8px!important;}
.pc{background:#13161b;border:1px solid rgba(255,255,255,.08);
  border-left:3px solid #4a9eff;border-radius:10px;padding:14px 18px;margin-bottom:8px;}
.pl{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#555a6a;
  text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px;}
.pv{font-family:'IBM Plex Sans Thai',sans-serif;font-size:14px;color:#e8eaf0;line-height:1.6;}
.sr{background:#1a1e26;border:1px solid rgba(255,255,255,.08);border-radius:8px;
  padding:10px 14px;margin-bottom:6px;display:flex;align-items:flex-start;gap:12px;}
.sn{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;color:#4a9eff;
  background:rgba(74,158,255,.12);border:1px solid rgba(74,158,255,.25);
  border-radius:5px;padding:3px 8px;flex-shrink:0;margin-top:2px;}
.sc{font-family:'IBM Plex Mono',monospace;font-size:13px;color:#2dd4a8;}
.sl{font-family:'IBM Plex Sans Thai',sans-serif;font-size:12px;color:#8b90a0;margin-top:2px;}
.oc{background:#13161b;border:1px solid rgba(45,212,168,.25);
  border-left:3px solid #2dd4a8;border-radius:10px;padding:16px 20px;margin-bottom:14px;}
.lg{background:#0d0f12;border:1px solid rgba(255,255,255,.06);border-radius:8px;
  padding:12px 14px;font-family:'IBM Plex Mono',monospace;font-size:11px;
  color:#8b90a0;line-height:1.8;max-height:260px;overflow-y:auto;}
.sl-lbl{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.12em;
  color:#555a6a;text-transform:uppercase;margin-bottom:12px;padding-bottom:8px;
  border-bottom:1px solid rgba(255,255,255,.08);}
.prev-wrap{border:1px solid rgba(255,255,255,.08);border-radius:10px;overflow:hidden;
  background:#0d0f12;}
.ff-ok{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#2dd4a8;
  padding:5px 10px;background:rgba(45,212,168,.08);border-radius:6px;
  border:1px solid rgba(45,212,168,.2);margin-bottom:4px;}
.ff-err{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#ff4d4d;
  padding:6px 10px;background:rgba(255,77,77,.08);border-radius:6px;
  border:1px solid rgba(255,77,77,.2);line-height:1.7;margin-bottom:4px;}
@keyframes spin{to{transform:rotate(360deg)}}
</style>""", unsafe_allow_html=True)

# ── session state ───────────────────────────────────────────
_DEF = {
    "live_running":    False,
    "live_done":       False,
    "live_mp4":        None,
    "live_log":        [],
    "live_out_dir":    "",
    "_cfg_cache":      {},
}
for k, v in _DEF.items():
    if k not in st.session_state:
        st.session_state[k] = v

_cfg = load_config()
st.session_state["_cfg_cache"] = _cfg   # ให้ _ff()/_ffp() อ่านได้ใน runtime

# ── browse helpers ──────────────────────────────────────────
def _browse_folder(sk: str):
    """เลือกโฟลเดอร์ผ่าน osascript — เหมือน select_folder_mac ใน utils"""
    try:
        result = subprocess.run(
            ["osascript", "-e", 'return POSIX path of (choose folder with prompt "เลือก Folder")'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            folder = result.stdout.strip()
            if folder:
                st.session_state[sk] = folder
                st.rerun()
    except Exception as e:
        st.toast(f"เปิด dialog ไม่ได้: {e} — พิมพ์ path ตรงๆ ได้เลย", icon="⚠️")

# ── progress renderer ────────────────────────────────────────
def _prog(c, msg, icon="⚙️", pct=0.0, done=False):
    if done:
        c.markdown(
            '<div style="background:#13161b;border:1px solid rgba(45,212,168,.3);'
            'border-left:3px solid #2dd4a8;border-radius:10px;padding:14px 18px;">'
            '<div style="font-family:IBM Plex Sans Thai,sans-serif;font-size:14px;'
            'color:#2dd4a8;margin-bottom:8px;">✅ เสร็จสิ้นทั้งหมด!</div>'
            '<div style="background:rgba(45,212,168,.2);border-radius:4px;height:6px;"></div>'
            '</div>', unsafe_allow_html=True)
    else:
        pw = int(min(pct, .99)*100)
        c.markdown(
            f'<div style="background:#13161b;border:1px solid rgba(255,255,255,.08);'
            f'border-left:3px solid #4a9eff;border-radius:10px;padding:14px 18px;">'
            f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">'
            f'<div style="width:16px;height:16px;border:2px solid #4a9eff;'
            f'border-top-color:transparent;border-radius:50%;'
            f'animation:spin .8s linear infinite;flex-shrink:0;"></div>'
            f'<span style="font-family:IBM Plex Sans Thai,sans-serif;font-size:14px;'
            f'color:#e8eaf0;">{icon} {msg}</span>'
            f'<span style="font-family:IBM Plex Mono,monospace;font-size:12px;'
            f'color:#4a9eff;margin-left:auto;">{pw}%</span></div>'
            f'<div style="background:#1a1e26;border-radius:4px;height:6px;overflow:hidden;">'
            f'<div style="background:linear-gradient(90deg,#4a9eff,#2dd4a8);height:6px;'
            f'width:{pw}%;border-radius:4px;transition:width .3s;"></div></div></div>'
            f'<style>@keyframes spin{{to{{transform:rotate(360deg)}}}}</style>',
            unsafe_allow_html=True)

# ── header ───────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <div style="font-size:32px;">🎬</div>
  <div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:20px;font-weight:700;
      color:#e8eaf0;line-height:1.1;">PyL.I.V.E.</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#555a6a;
      margin-top:2px;letter-spacing:.06em;">LIVE INTELLIGENCE VIDEO EXTRACTOR — V3.0</div>
  </div>
  <div style="margin-left:auto;display:flex;gap:8px;">
    <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;padding:3px 8px;
      background:#1a1e26;border-radius:4px;color:#ff7a2f;
      border:1px solid rgba(255,122,47,.25);">V3.0</span>
  </div>
</div>
<div style="height:1px;background:rgba(255,255,255,.08);margin:16px 0 22px 0;"></div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# SIDEBAR — Settings
# ════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
        'letter-spacing:.1em;color:#555a6a;text-transform:uppercase;'
        'border-bottom:1px solid rgba(255,255,255,.08);'
        'padding-bottom:8px;margin-bottom:14px;">⚙️ ตั้งค่า</div>',
        unsafe_allow_html=True)

    # ffmpeg status (safe — _find_bin ไม่ raise)
    _cfg_ff = st.session_state.get("_cfg_cache", {}).get("ffmpeg_path", "")
    ff_path = (_cfg_ff if _cfg_ff and os.path.isfile(_cfg_ff) else None) or _find_bin("ffmpeg")
    if ff_path:
        st.markdown(f'<div class="ff-ok">✅ ffmpeg พร้อมใช้งาน</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="ff-err">❌ ไม่พบ ffmpeg<br>'
            '• macOS: <code>brew install ffmpeg</code><br>'
            '• Linux: <code>sudo apt install ffmpeg</code><br>'
            '• หรือระบุ path ใน config → <code>ffmpeg_path</code></div>',
            unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Output Folder ──
    st.markdown('<div class="pl">📁 Output Folder</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([4, 1])
    with c1:
        od = st.text_input("od", label_visibility="collapsed",
            value=st.session_state["live_out_dir"] or
                  _cfg.get("dest_folder", os.path.expanduser("~/Downloads/PyLIVE")))
        st.session_state["live_out_dir"] = od
    with c2:
        if st.button("📂", key="br_od", help="เลือก Folder"):
            result = subprocess.run(
                ["osascript", "-e", 'return POSIX path of (choose folder with prompt "เลือก Folder")'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                folder = result.stdout.strip()
                if folder:
                    st.session_state["live_out_dir"] = folder
                    st.rerun()

# ════════════════════════════════════════════════════════════
# MAIN — single column
# ════════════════════════════════════════════════════════════
col_l, col_r = st.columns([1, 1], gap="large")

# ════════════  LEFT — Brief input  ══════════════════════════
with col_l:
    st.markdown('<div class="sl-lbl">01 — วางข้อความ Brief</div>',
                unsafe_allow_html=True)
    brief_text = st.text_area(
        "Brief", label_visibility="collapsed", height=240,
        placeholder=(
            "//\n"
            "ปก : ชื่อเรื่อง\n"
            "แคปชั่น : ...\n\n"
            "TC (เวลามุมขวาของจอ) :\n"
            "21.08.12 วันที่ 1 ม.ค. - 21.10.24 เท่านั้นเอง\n\n"
            "ลิงค์ถ่ายทอดสด : https://www.youtube.com/live/..."
        ), key="brief_ta",
    )

    parsed: Optional[LiveBrief] = None
    if brief_text.strip():
        parsed = parse_brief(brief_text)
        if parsed:
            st.markdown(
                '<div style="font-family:IBM Plex Mono,monospace;font-size:10px;'
                'color:#2dd4a8;text-transform:uppercase;letter-spacing:.1em;'
                'margin:12px 0 10px;">✅ Parse สำเร็จ</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="pc"><div class="pl">YouTube URL</div>'
                f'<div class="pv" style="font-family:IBM Plex Mono,monospace;'
                f'font-size:12px;color:#4a9eff;">{parsed.youtube_url}</div></div>',
                unsafe_allow_html=True)
            segs_html = "".join(
                f'<div class="sr"><span class="sn">SEG {i}</span>'
                f'<div><div class="sc">{s.start_clock} → {s.end_clock}</div>'
                f'<div class="sl">"{s.start_label}" … "{s.end_label}"</div>'
                f'</div></div>'
                for i, s in enumerate(parsed.segments, 1))
            if segs_html:
                st.markdown(
                    f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;'
                    f'color:#555a6a;text-transform:uppercase;letter-spacing:.1em;'
                    f'margin:12px 0 8px;">{len(parsed.segments)} SEGMENT(S)</div>' + segs_html,
                    unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="font-family:IBM Plex Mono,monospace;font-size:12px;'
                'color:#ff4d4d;margin-top:8px;">⚠️ ไม่พบลิงก์ YouTube</div>',
                unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    run_btn = st.button(
        "🚀  เริ่มประมวลผล", type="primary",
        disabled=(not parsed) or (parsed is not None and not parsed.segments) or st.session_state["live_running"] or (not ff_path),
        use_container_width=True, key="run_btn")

# ════════════  RIGHT — Results  ═════════════════════════════
with col_r:
    st.markdown('<div class="sl-lbl">02 — ผลลัพธ์</div>',
                unsafe_allow_html=True)
    prog_box   = st.empty()
    result_box = st.empty()
    log_box    = st.empty()

# ════════════  PIPELINE  ════════════════════════════════════
if run_btn and parsed:
    st.session_state.update({
        "live_running": True, "live_done": False,
        "live_mp4": None, "live_log": [],
    })
    tmp_dir = tempfile.mkdtemp(prefix="pylive_")

    def _log(msg):
        st.session_state["live_log"].append(f"[{time.strftime('%H:%M:%S')}]  {msg}")

    try:
        _prog(prog_box, "กำลัง OCR + โหลด Segments...", "📡", pct=0.10)
        _log(f"🚀 เริ่ม Pipeline  |  {len(parsed.segments)} segments")
        res = run_pipeline(
            brief=parsed,
            out_dir=st.session_state["live_out_dir"],
            tmp_dir=tmp_dir,
            gemini_key=_cfg.get("gemini_key1", ""),
            log=_log)
        if res["error"]:
            _log(f"❌ {res['error']}")
            _prog(prog_box, f"❌ {res['error']}", "❌", pct=0)
        else:
            st.session_state["live_mp4"] = res["mp4"]
            _prog(prog_box, "", done=True)
            _log("🎉 Pipeline เสร็จสมบูรณ์!")
            st.session_state["live_done"] = True
    except Exception as e:
        _log(f"❌ Error: {e}")
        _prog(prog_box, f"❌ {str(e)[:80]}", "❌", pct=0)
    finally:
        st.session_state["live_running"] = False
        shutil.rmtree(tmp_dir, ignore_errors=True)
    st.rerun()

# ════════════  RENDER RESULTS  ══════════════════════════════
if st.session_state["live_done"]:
    mp4 = st.session_state["live_mp4"]
    if mp4 and os.path.exists(mp4):
        info = probe_video(mp4)
        result_box.markdown(
            f'<div class="oc"><div class="pl">OUTPUT FILE</div>'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:13px;'
            f'color:#2dd4a8;">📹 {os.path.basename(mp4)}</div>'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
            f'color:#555a6a;margin-top:4px;">'
            f'{info.get("duration",0):.1f}s · {info.get("size_mb",0):.1f}MB · '
            f'codec={info.get("video_codec","?")} · '
            f'audio={"✓" if info.get("has_audio") else "✗"}</div></div>',
            unsafe_allow_html=True)

if st.session_state["live_log"]:
    with log_box.container():
        st.markdown('<div class="sl-lbl" style="margin-top:20px;">LOG</div>',
                    unsafe_allow_html=True)
        lines = st.session_state["live_log"][-60:]
        st.markdown('<div class="lg">' + "<br>".join(lines) + '</div>',
                    unsafe_allow_html=True)

if st.session_state["live_done"]:
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if st.button("🔄 เริ่มใหม่", key="reset_btn"):
        for k, v in _DEF.items():
            st.session_state[k] = v
        st.rerun()