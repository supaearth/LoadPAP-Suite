"""
PyL.I.V.E. — Live Intelligence Video Extractor
V4.1

วาง file นี้ที่: pages/4_PyLIVE_Test1.0.py
"""

import sys, os, re, time, shutil, subprocess, tempfile, json, datetime, io
import streamlit as st
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yt_dlp
from PIL import Image
from googleapiclient.http import MediaIoBaseDownload

# ── Path setup ───────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils import (load_config, inject_global_css,
                   get_docs_service, get_drive_service, extract_id)

# ============================================================
# 0.  CONSTANTS
# ============================================================
SAFETY_BUFFER_SEC = 2
PROBE_DURATION    = 15   # โหลดแค่ 15 วิต่อ probe (พอ scan 2-3 frame)
OCR_CROP_RATIO    = {"left": 0.82, "top": 0.02, "right": 1.00, "bottom": 0.12}
SCAN_START        = 2
SCAN_END          = 14
SCAN_STEP         = 5

# ============================================================
# 1.  DATACLASSES
# ============================================================
class StreamType:
    VOD        = "VOD"
    LIVE_DVR   = "LiveDVR"
    LIVE_NODVR = "LiveNoDVR"

@dataclass
class StreamInfo:
    url:               str
    stream_type:       str
    title:             str = ""
    release_timestamp: Optional[int] = None

@dataclass
class CalibResult:
    stream_start_sec: int
    confidence:       float
    method_used:      str

@dataclass
class ClipSegment:
    start_clock: str
    start_label: str
    end_clock:   str
    end_label:   str

@dataclass
class LiveBrief:
    youtube_url: str
    cover_text:  str
    caption:     str
    segments:    list[ClipSegment] = field(default_factory=list)

# ── Local (REC) dataclasses ──────────────────────────────────
@dataclass
class RecSegment:
    start_tc:    str   # raw เช่น "15.43"
    start_sec:   int
    start_label: str
    end_tc:      str
    end_sec:     int
    end_label:   str
    tc_format:   str   # "MM.SS" | "HH.MM.SS"

@dataclass
class RecBrief:
    raw_source:  str            # raw string จาก doc (URL หรือชื่อไฟล์)
    file_id:     Optional[str]  # Drive file ID (ถ้าเป็น URL)
    filename:    Optional[str]  # ชื่อไฟล์ (ถ้าไม่ใช่ URL)
    cover_text:  str
    caption:     str
    doc_title:   str = ""       # ชื่อ Google Doc
    segments:    list[RecSegment] = field(default_factory=list)

class NoClock(Exception):
    pass

# ============================================================
# 2.  HELPERS — binary paths
# ============================================================
def _find_bin(name: str) -> Optional[str]:
    candidates = [
        os.path.join(_ROOT, name),
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
    cfg_path = st.session_state.get("_cfg_cache", {}).get("ffmpeg_path", "")
    if cfg_path and os.path.isfile(cfg_path):
        return cfg_path
    p = _find_bin("ffmpeg")
    if p:
        return p
    raise RuntimeError(
        "ไม่พบ ffmpeg\n• macOS: brew install ffmpeg\n"
        "• หรือระบุ path ใน vmaster_config.json → ffmpeg_path"
    )

def _ffp() -> str:
    cfg_path = st.session_state.get("_cfg_cache", {}).get("ffprobe_path", "")
    if cfg_path and os.path.isfile(cfg_path):
        return cfg_path
    p = _find_bin("ffprobe")
    if p:
        return p
    raise RuntimeError("ไม่พบ ffprobe — ติดตั้ง ffmpeg (รวม ffprobe)")

def _get_ffmpeg_exe() -> Optional[str]:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir  = os.path.dirname(current_dir)
    for candidate in [
        os.path.join(parent_dir, "ffmpeg"),
        os.path.join(current_dir, "ffmpeg"),
        shutil.which("ffmpeg"),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]:
        if candidate and os.path.exists(candidate):
            return candidate
    return None

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
# 3.  MODULE 1 — YOUTUBE BRIEF PARSER
# ============================================================
def clock_to_sec(s: str) -> int:
    p = s.split(".")
    return int(p[0])*3600 + int(p[1])*60 + int(p[2])

def hhmm_to_sec(s: str) -> int:
    p = s.split(":")
    return int(p[0])*3600 + int(p[1])*60 + int(p[2])

def clock_to_sec_safe(clock_str: str, stream_start_sec: int) -> int:
    sec = clock_to_sec(clock_str)
    start_of_day = stream_start_sec % 86400
    if sec < start_of_day - 3600:
        sec += 86400
    return sec

def parse_brief(text: str) -> Optional[LiveBrief]:
    url_m = re.search(
        r'https?://(?:www\.)?(?:youtube\.com/(?:live/|watch\?v=)|youtu\.be/)[\w\-?=&]+', text)
    if not url_m:
        return None
    cover_m = re.search(
        r'ปก\s*:\s*(.+?)(?=\n[ \t]*(?:แคปชั่น|TC|ลิงค์)|\n[ \t]*\n|\Z)',
        text, re.DOTALL)
    caption_m = re.search(
        r'แคปชั่น\s*:\s*(.+?)(?=\n\s*\n|\nTC|\nลิงค์|$)', text, re.DOTALL)

    # TC pattern: HH.MM.SS (1-2 digit hour) label - HH.MM.SS label
    _TC_RE = re.compile(
        r'(\d{1,2}\.\d{2}\.\d{2})'   # start TC
        r'\s*(.*?)'                    # start label (optional)
        r'\s*-\s*'
        r'(\d{1,2}\.\d{2}\.\d{2})'   # end TC
        r'\s*(.*)$'                    # end label (optional)
    )
    segments = []
    for line in text.splitlines():
        stripped = line.strip()
        # รองรับ 2 format:
        # 1. "TC ...: HH.MM.SS label - HH.MM.SS label"  (TC: นำหน้า)
        # 2. "HH.MM.SS label - HH.MM.SS label"           (timecode ล้วน)
        search_in = stripped
        if re.match(r'TC.*?:', stripped, re.IGNORECASE):
            # ตัด prefix "TC...:" ออกก่อนแล้วค่อย match
            search_in = re.sub(r'^TC.*?:\s*', '', stripped, flags=re.IGNORECASE)
        m = _TC_RE.match(search_in)
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

def compute_timestamps(segments: list[ClipSegment], calib: CalibResult) -> list[dict]:
    out = []
    for seg in segments:
        rs  = clock_to_sec_safe(seg.start_clock, calib.stream_start_sec) - calib.stream_start_sec
        re_ = clock_to_sec_safe(seg.end_clock,   calib.stream_start_sec) - calib.stream_start_sec
        vs  = max(0, rs - SAFETY_BUFFER_SEC)
        ve  = re_ + SAFETY_BUFFER_SEC
        out.append({
            "start_clock": seg.start_clock, "end_clock": seg.end_clock,
            "start_label": seg.start_label, "end_label": seg.end_label,
            "video_start": vs, "video_end": ve, "duration": ve - vs,
        })
    return out

# ============================================================
# 4.  MODULE 2 — STREAM INTELLIGENCE
# ============================================================
def get_stream_info(url: str, log=None) -> StreamInfo:
    def _info(msg):
        if log: log(msg)
    opts = {'quiet': True, 'no_warnings': True, 'noplaylist': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        _info(f"  ⚠️  ดึง metadata ล้มเหลว: {e}")
        return StreamInfo(url=url, stream_type=StreamType.VOD)

    live_status = info.get('live_status', 'not_live')
    title       = info.get('title', '')
    _info(f"  📺 {title[:60]}")
    _info(f"  📡 live_status: {live_status}")

    rel_ts = info.get('release_timestamp') or info.get('timestamp')
    if rel_ts:
        dt = datetime.datetime.fromtimestamp(int(rel_ts))
        _info(f"  🕐 release_timestamp: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        _info(f"  🕐 release_timestamp: ไม่มี")

    if live_status == 'is_live':
        stype = StreamType.LIVE_DVR
        _info("  ✅ Stream type: Live (assume DVR available)")
    elif live_status in ('was_live', 'post_live'):
        stype = StreamType.VOD
        _info("  ✅ Stream type: VOD (was live)")
    else:
        stype = StreamType.VOD
        _info("  ✅ Stream type: VOD")

    return StreamInfo(
        url=url, stream_type=stype, title=title,
        release_timestamp=int(rel_ts) if rel_ts else None,
    )

# ============================================================
# 5.  MODULE 3 — OCR ENGINE
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
        crop = img.crop((
            int(w * OCR_CROP_RATIO["left"]),  int(h * OCR_CROP_RATIO["top"]),
            int(w * OCR_CROP_RATIO["right"]), int(h * OCR_CROP_RATIO["bottom"]),
        ))
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
        crop.save(out)
        return True
    except:
        return False

def _ocr_tesseract(img_path: str) -> Optional[str]:
    try:
        import pytesseract
        cfg = "--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789:"
        t = pytesseract.image_to_string(Image.open(img_path), config=cfg).strip()
        m = re.search(r'\d{2}:\d{2}:\d{2}', t)
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
            model="gemini-2.0-flash-lite",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                types.Part.from_text(text=(
                    "This is a cropped image from the top-right corner of a Thai TV live stream. "
                    "There may be a real-time wall clock showing time in HH:MM:SS format. "
                    "If you can see a clock, reply ONLY with the time as HH:MM:SS. "
                    "If there is no clock visible, reply exactly: NONE"
                )),
            ],
        )
        txt = resp.text.strip()
        if "NONE" in txt.upper():
            return None
        m = re.search(r'\d{2}:\d{2}:\d{2}', txt)
        return m.group(0) if m else None
    except:
        return None

def _try_ocr_at(probe_clip: str, t: float, tmp_dir: str,
                api_key: str, prefix: str = "scan") -> Optional[str]:
    frame = os.path.join(tmp_dir, f"{prefix}_{int(t)}s.jpg")
    crop  = os.path.join(tmp_dir, f"{prefix}_{int(t)}s_crop.png")
    if not _extract_frame(probe_clip, t, frame):
        return None
    if not _crop_clock_region(frame, crop):
        return None
    return _ocr_tesseract(crop) or (api_key and _ocr_gemini(crop, api_key)) or None

# ============================================================
# 6.  MODULE 4 — CALIBRATOR
# ============================================================
def _find_clock_appearance(probe_clip: str, tmp_dir: str,
                            api_key: str, log=None) -> tuple[float, str]:
    def _info(msg):
        if log: log(msg)
    dur = get_duration(probe_clip)
    _info(f"  📏 Probe clip = {dur:.1f}s  |  Adaptive scan {SCAN_START}–{min(SCAN_END-1, int(dur))}s")
    for t in range(SCAN_START, SCAN_END, SCAN_STEP):
        if t >= dur - 1:
            _info(f"  ⚠️  T={t}s เกิน duration ({dur:.0f}s)")
            break
        clock = _try_ocr_at(probe_clip, float(t), tmp_dir, api_key, "scan")
        if clock:
            _info(f"  🕐 พบนาฬิกาที่ T={t}s → {clock}")
            return (float(t), clock)
        else:
            _info(f"  ⬜ T={t}s — ไม่พบนาฬิกา")
    raise NoClock(
        f"ไม่พบนาฬิกาในช่วง {SCAN_START}–{min(SCAN_END-1, int(dur))}s\n"
        "กรุณากรอก Manual Calibration ด้านซ้าย"
    )

def _ocr_calibrate(probe_clip: str, t_found: float, clock_found: str,
                   tmp_dir: str, api_key: str, log=None,
                   video_offset: int = 0) -> CalibResult:
    """
    คำนวณ stream_start จาก OCR
    video_offset: จำนวนวินาทีที่ probe clip เริ่มจาก (ถ้าไม่ได้ดึงจากต้นไฟล์)
    stream_start = clock_at_T - (video_offset + T)
    """
    def _info(msg):
        if log: log(msg)
    dur = get_duration(probe_clip)
    wall_sec_0 = hhmm_to_sec(clock_found)
    est_0 = wall_sec_0 - (video_offset + int(t_found))
    estimates = [est_0]
    _info(f"  📐 T={video_offset+t_found:.0f}s (abs) → {clock_found} → start estimate = "
          f"{est_0//3600:02d}:{(est_0%3600)//60:02d}:{est_0%60:02d}")
    for t in [t_found + 5, t_found + 10]:
        if t >= dur - 1:
            continue
        clock = _try_ocr_at(probe_clip, t, tmp_dir, api_key, "calib")
        if clock:
            wall_sec = hhmm_to_sec(clock)
            est = wall_sec - (video_offset + int(t))
            estimates.append(est)
            _info(f"  📐 T={video_offset+t:.0f}s (abs) → {clock} → start estimate = "
                  f"{est//3600:02d}:{(est%3600)//60:02d}:{est%60:02d}")
        else:
            _info(f"  ⚠️  T={t:.0f}s — OCR ล้มเหลว — ข้าม")
    vals = sorted(estimates)
    stream_start = vals[len(vals) // 2]
    spread = max(vals) - min(vals) if len(vals) > 1 else 0
    confidence = max(0.0, min(1.0, 1.0 - spread / 10.0))
    h, m, s = stream_start // 3600, (stream_start % 3600) // 60, stream_start % 60
    _info(f"  ✅ stream_start = {h:02d}:{m:02d}:{s:02d}  "
          f"(spread={spread}s, confidence={confidence:.0%})")
    return CalibResult(stream_start_sec=stream_start, confidence=confidence, method_used="ocr")

def calibrate(stream_info: StreamInfo, tmp_dir: str, api_key: str,
              manual_ref: Optional[dict] = None, log=None,
              stream_url: str = "", dvr_dur: int = 0) -> CalibResult:
    def _info(msg):
        if log: log(msg)

    if manual_ref:
        clock_sec    = hhmm_to_sec(manual_ref["clock"])
        video_pos    = int(manual_ref["video_pos"])
        stream_start = clock_sec - video_pos
        h, m, s = stream_start // 3600, (stream_start % 3600) // 60, stream_start % 60
        _info(f"  ✋ Manual calibration → stream_start = {h:02d}:{m:02d}:{s:02d}")
        return CalibResult(stream_start_sec=stream_start, confidence=1.0, method_used="manual")

    # ดึง stream URL ก่อน probe (ถ้ายังไม่มี)
    if not stream_url:
        _info("  🔗 ดึง stream URL...")
        stream_url, dvr_dur = _get_stream_url_and_dvr(stream_info.url)
        if not stream_url:
            raise NoClock("ดึง stream URL ล้มเหลว — ตรวจสอบการเชื่อมต่อ")
    if dvr_dur:
        _info(f"  📏 DVR ≈ {dvr_dur//60} นาที")

    # scan ทีละ 10 นาที จนเจอนาฬิกา (รองรับ pre-live ยาว)
    for skip_min in [0, 10, 20, 30, 45, 60]:
        skip_sec = skip_min * 60
        if dvr_dur and skip_sec >= dvr_dur:
            _info(f"  ⬜ {skip_min} นาที เกิน DVR — หยุด")
            break
        _info(f"  🔍 Probe @ {skip_min} นาที...")
        probe = _download_probe_clip(stream_url, tmp_dir, start_sec=skip_sec)
        if not probe:
            _info(f"  ⚠️  โหลดล้มเหลว @ {skip_min} นาที — ข้าม")
            continue
        try:
            t_found, clock_found = _find_clock_appearance(probe, tmp_dir, api_key, log)
            t_absolute = skip_sec + t_found
            _info(f"  ✅ พบนาฬิกา @ {skip_min} นาที + {t_found:.0f}s (absolute {t_absolute:.0f}s)")
            return _ocr_calibrate(probe, t_found, clock_found, tmp_dir, api_key, log,
                                  video_offset=skip_sec)
        except NoClock:
            _info(f"  ⬜ ไม่พบนาฬิกาใน {skip_min} นาที — ลองถัดไป")
            continue
    raise NoClock("ไม่พบนาฬิกาในช่วง 0–60 นาที\nกรุณากด '📸 เช็คนาฬิกาตอนนี้' หรือกรอก Manual Calibration")

# ============================================================
# 7.  MODULE 5 — YOUTUBE DOWNLOADER
# ============================================================
def _download_probe_clip(stream_url: str, out_dir: str, start_sec: int = 0) -> Optional[str]:
    """ดึง PROBE_DURATION วิ จาก DVR position start_sec ด้วย FFmpeg seek"""
    ffmpeg_exe = _get_ffmpeg_exe()
    if not ffmpeg_exe or not stream_url:
        return None
    tag = f"probe_{start_sec}"
    out = os.path.join(out_dir, f"{tag}.mp4")
    r = subprocess.run(
        [ffmpeg_exe, "-y",
         "-ss", str(start_sec),
         "-i", stream_url,
         "-t", str(PROBE_DURATION),
         "-c", "copy", "-movflags", "+faststart", out],
        capture_output=True, timeout=90)
    if r.returncode == 0 and os.path.exists(out) and get_duration(out) >= 3:
        return out
    return None

def _get_stream_url_and_dvr(url: str) -> tuple[Optional[str], int]:
    """คืน (stream_url, dvr_duration_sec) จาก yt-dlp — ใช้สำหรับ FFmpeg seek"""
    try:
        opts = {'quiet': True, 'no_warnings': True, 'skip_download': True,
                'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]/best'}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        stream_url = info.get('url') or (info.get('requested_formats') or [{}])[0].get('url', '')
        dvr_dur = int(info.get('duration') or 0)
        return (stream_url or None, dvr_dur)
    except:
        return (None, 0)

def _grab_live_tail(stream_url: str, out_dir: str) -> Optional[str]:
    """ดึงวิดีโอ ~15 วิจาก live head (ใช้ FFmpeg -t ตัดจาก stream โดยตรง)"""
    ffmpeg_exe = _get_ffmpeg_exe()
    if not ffmpeg_exe or not stream_url:
        return None
    out = os.path.join(out_dir, "live_tail.mp4")
    r = subprocess.run(
        [ffmpeg_exe, "-y", "-i", stream_url, "-t", "15",
         "-c", "copy", "-movflags", "+faststart", out],
        capture_output=True, timeout=60)
    if r.returncode == 0 and os.path.exists(out) and get_duration(out) >= 3:
        return out
    return None

def quick_clock_check(url: str, tmp_dir: str, api_key: str,
                      log=None, dvr_dur: int = 0) -> Optional[tuple[str, int]]:
    """
    ดึง ~15 วิล่าสุดของ live stream → OCR นาฬิกา
    คืน (clock_HH:MM:SS, dvr_pos_sec) หรือ None ถ้าล้มเหลว
    dvr_pos_sec = DVR position จริงของ frame ที่ OCR ได้ (นับจาก DVR start)
    """
    def _info(msg):
        if log: log(msg)
    _info("  🔗 ดึง stream URL...")
    stream_url, fetched_dvr = _get_stream_url_and_dvr(url)
    if not stream_url:
        _info("  ❌ ดึง stream URL ล้มเหลว")
        return None
    D = dvr_dur or fetched_dvr
    _info(f"  📏 DVR ≈ {D//60} นาที")
    _info("  📥 ดึงวิดีโอ ~15 วิล่าสุด...")
    clip = _grab_live_tail(stream_url, tmp_dir)
    if not clip:
        _info("  ❌ ดึงวิดีโอล้มเหลว — อาจไม่รองรับ DVR")
        return None
    tail_dur = get_duration(clip)
    _info(f"  📏 ได้ {tail_dur:.1f}s")
    # scan จากท้ายคลิปย้อนกลับมา (นาฬิกาควรเห็นชัดตอนท้าย)
    for t in [tail_dur - 2, tail_dur - 5, tail_dur - 8, 5, 2]:
        if t < 0:
            continue
        clock = _try_ocr_at(clip, t, tmp_dir, api_key, "tail")
        if clock:
            # แปลง t (position ใน tail clip) → DVR position จริง
            dvr_pos = int(D - tail_dur + t) if D > 0 else int(t)
            _info(f"  🕐 พบนาฬิกา T={t:.0f}s → {clock}  (DVR pos ≈ {dvr_pos}s)")
            return (clock, dvr_pos)
    _info("  ❌ ไม่พบนาฬิกาในคลิป")
    return None

def download_segment(stream_url: str, vs: float, ve: float, out: str) -> bool:
    """ดึง segment จาก stream_url ด้วย FFmpeg seek (vs, ve = DVR positions)"""
    ffmpeg_exe = _get_ffmpeg_exe()
    if not ffmpeg_exe or not stream_url:
        return False
    duration = ve - vs
    r = subprocess.run(
        [ffmpeg_exe, "-y",
         "-ss", f"{vs:.3f}",
         "-i", stream_url,
         "-t", f"{duration:.3f}",
         "-c", "copy", "-movflags", "+faststart", out],
        capture_output=True, timeout=300)
    return r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 10*1024

# ============================================================
# 8.  MODULE 6 — FFMPEG CONCAT (shared)
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
# 9.  MODULE 7 — YOUTUBE PIPELINE
# ============================================================
def run_pipeline(brief: LiveBrief, out_dir: str, tmp_dir: str,
                 gemini_key: str, manual_ref: Optional[dict], log) -> dict:
    res = {"mp4": None, "calib": None, "error": None, "need_manual": False,
           "dvr_dur": 0, "stream_url": ""}
    os.makedirs(out_dir, exist_ok=True)

    log("📡 วิเคราะห์ stream...")
    try:
        stream_info = get_stream_info(brief.youtube_url, log)
    except Exception as e:
        res["error"] = f"วิเคราะห์ stream ล้มเหลว: {e}"
        return res

    log("🔗 ดึง stream URL...")
    stream_url, dvr_dur = _get_stream_url_and_dvr(brief.youtube_url)
    if not stream_url:
        res["error"] = "ดึง stream URL ล้มเหลว — ตรวจสอบการเชื่อมต่อ"
        return res
    res["dvr_dur"]    = dvr_dur
    res["stream_url"] = stream_url
    log(f"  📏 DVR ≈ {dvr_dur//60} นาที")

    log("🔍 Calibrate Timecode...")
    try:
        calib = calibrate(stream_info, tmp_dir, gemini_key, manual_ref, log,
                          stream_url=stream_url, dvr_dur=dvr_dur)
        res["calib"] = calib
    except NoClock as e:
        log(f"  ⚠️  {e}")
        res["error"] = str(e)
        res["need_manual"] = True
        return res
    except Exception as e:
        res["error"] = f"Calibration ล้มเหลว: {e}"
        res["need_manual"] = True
        return res

    ss = calib.stream_start_sec
    log(f"  🕐 stream_start = {ss//3600:02d}:{(ss%3600)//60:02d}:{ss%60:02d}  "
        f"(method: {calib.method_used})")

    timestamps = compute_timestamps(brief.segments, calib)
    if not timestamps:
        res["error"] = "ไม่มี segment — ตรวจ TC format: HH.MM.SS label - HH.MM.SS"
        return res
    for i, ts in enumerate(timestamps, 1):
        vs, ve = ts['video_start'], ts['video_end']
        vm, vs2 = int(vs)//60, int(vs)%60
        log(f"  📐 SEG {i}: TC {ts['start_clock']} → {ts['end_clock']}  "
            f"= DVR {vm:02d}:{vs2:02d} ({vs:.0f}s → {ve:.0f}s)")

    seg_paths = []
    for i, ts in enumerate(timestamps, 1):
        log(f"⬇️  Segment {i}/{len(timestamps)}: {ts['start_clock']} → {ts['end_clock']}")
        seg_out = os.path.join(tmp_dir, f"segment_{i:02d}.mp4")
        if download_segment(stream_url, ts["video_start"], ts["video_end"], seg_out):
            seg_paths.append(seg_out)
            log(f"  ✅ segment_{i:02d}.mp4 ({ts['duration']:.0f}s)")
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
    log(f"✅ {os.path.basename(out_mp4)}  "
        f"{info.get('duration', 0):.1f}s  {info.get('size_mb', 0):.1f}MB")
    return res

# ============================================================
# 10. MODULE 8 — DOC READER + LOCAL BRIEF PARSER
# ============================================================
def _read_doc_text(doc_id: str) -> tuple[str, Optional[str], str]:
    """
    อ่าน Google Doc คืน (plain_text, drive_url, doc_title)
    - plain_text: text ปกติ (display text ไม่มี URL)
    - drive_url: URL แรกที่เจอจาก hyperlink ในย่อหน้าถัดจาก 'ลิงก์คลิปต้นทาง'
    - doc_title: ชื่อ Google Doc

    เหตุที่แยก: hyperlink ใน Google Doc เก็บ URL ใน textStyle.link.url
    ไม่ได้อยู่ใน content text เลยต้อง scan structure โดยตรง
    """
    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id).execute()
    doc_title = doc.get("title", "")
    body_content = doc.get("body", {}).get("content", [])

    paragraphs = []  # [(plain_text, [urls_in_para])]
    for element in body_content:
        para = element.get("paragraph")
        if not para:
            continue
        para_text = ""
        for run_elem in para.get("elements", []):
            para_text += run_elem.get("textRun", {}).get("content", "")
        # ดึง URL จากทุก element ใน paragraph (hyperlink + rich chip)
        para_urls = []
        for run_elem in para.get("elements", []):
            # hyperlink
            url = (run_elem.get("textRun", {})
                           .get("textStyle", {})
                           .get("link", {})
                           .get("url", ""))
            if url:
                para_urls.append(url)
            # Drive file chip / smart chip
            rich_url = (run_elem.get("richLink", {})
                                .get("richLinkProperties", {})
                                .get("uri", ""))
            if rich_url:
                para_urls.append(rich_url)
        paragraphs.append((para_text, para_urls))

    # รวม plain text ทั้งหมด
    plain_text = "".join(p[0] for p in paragraphs)

    # หา Drive URL: scan ย่อหน้าที่มี "ลิงก์คลิปต้นทาง" และย่อหน้าถัดไป
    # รองรับทั้ง hyperlink (textStyle.link) และ Drive file chip (richLink)
    drive_url = None
    for i, (para_text, para_urls) in enumerate(paragraphs):
        if "ลิงก์คลิปต้นทาง" in para_text:
            # ดูบรรทัดเดียวกันก่อน แล้วดูถัดไป 3 ย่อหน้า
            for j in range(i, min(i + 4, len(paragraphs))):
                for url in paragraphs[j][1]:
                    if url.startswith("http"):
                        drive_url = url
                        break
                if drive_url:
                    break
            break

    return plain_text, drive_url, doc_title


def _extract_all_urls_from_para(para: dict) -> list[str]:
    """
    Extract URL จาก paragraph element ทุกรูปแบบ:
    1. textRun.textStyle.link.url  — hyperlink ธรรมดา
    2. richLink.richLinkProperties.uri — Drive file chip / smart chip
    """
    urls = []
    for elem in para.get("elements", []):
        # 1. hyperlink
        url = (elem.get("textRun", {})
                   .get("textStyle", {})
                   .get("link", {})
                   .get("url", ""))
        if url:
            urls.append(url)
        # 2. Drive file chip / smart chip
        rich_url = (elem.get("richLink", {})
                        .get("richLinkProperties", {})
                        .get("uri", ""))
        if rich_url:
            urls.append(rich_url)
    return urls

def _tc_to_sec_local(tc_str: str) -> int:
    """
    Auto-detect: MM.SS (1 dot) หรือ HH.MM.SS (2 dots)
    ตัวอย่าง: "15.43" → 943s, "01.15.43" → 4543s
    """
    parts = tc_str.strip().split(".")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0

def _tc_format(tc_str: str) -> str:
    return "HH.MM.SS" if tc_str.count(".") == 2 else "MM.SS"

def _sec_to_display(sec: int) -> str:
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

def parse_doc_brief(text: str, drive_url: Optional[str] = None, doc_title: str = "") -> Optional[RecBrief]:
    """
    Parse Google Doc script text → RecBrief
    drive_url: URL จาก hyperlink ที่ _read_doc_text scan มาโดยตรง
    doc_title: ชื่อ Google Doc (ใช้ตั้งชื่อไฟล์ output)
    """
    # ── cover ──────────────────────────────────────────────
    cover_m = re.search(
        r'ปก\s*:\s*(.+?)(?=\n[ \t]*(?:Caption|แคปชั่น|Tc|TC|ลิงก์)|\n[ \t]*\n|\Z)',
        text, re.DOTALL | re.IGNORECASE)
    cover_text = ""
    if cover_m:
        cover_text = "\n".join(
            l.strip() for l in cover_m.group(1).strip().splitlines() if l.strip())

    # ── caption ────────────────────────────────────────────
    caption_m = re.search(
        r'(?:Caption|แคปชั่น)\s*:\s*(.+?)(?=\n\s*\n|\nTc|\nTC|\nลิงก์|$)',
        text, re.DOTALL | re.IGNORECASE)
    caption = caption_m.group(1).strip() if caption_m else ""

    # ── video source ───────────────────────────────────────
    raw_source, file_id, filename = "", None, None
    if drive_url:
        # ได้ URL จาก hyperlink structure โดยตรง — เชื่อถือได้สุด
        raw_source = drive_url
        file_id    = extract_id(drive_url)
    else:
        # fallback: หา URL เปล่าๆ ในข้อความ (กรณีไม่ใช่ hyperlink)
        src_m = re.search(r'ลิงก์คลิปต้นทาง\s*[:\s]+\s*(https?://[^\s\n]+)', text)
        if src_m:
            raw_source = src_m.group(1).strip()
            file_id    = extract_id(raw_source)

    if not raw_source:
        return None

    # ── TC segments ────────────────────────────────────────
    # Pattern: optional_prefix TC_start (label) - TC_end (label)
    # TC = (\d{1,2}\.\d{2}) หรือ (\d{1,2}\.\d{2}\.\d{2})
    TC_PAT = re.compile(
        r'(\d{1,2}\.\d{2}(?:\.\d{2})?)'    # group 1: start TC
        r'\s*(?:\(([^)]*)\))?'              # group 2: start label (optional)
        r'\s*-\s*'
        r'(\d{1,2}\.\d{2}(?:\.\d{2})?)'    # group 3: end TC
        r'\s*(?:\(([^)]*)\))?'              # group 4: end label (optional)
    )
    segments = []
    for line in text.splitlines():
        m = TC_PAT.search(line)
        if m:
            s_tc, s_lbl, e_tc, e_lbl = m.group(1), m.group(2), m.group(3), m.group(4)
            s_sec = _tc_to_sec_local(s_tc)
            e_sec = _tc_to_sec_local(e_tc)
            segments.append(RecSegment(
                start_tc=s_tc, start_sec=s_sec,
                start_label=(s_lbl or "clip").strip(),
                end_tc=e_tc,   end_sec=e_sec,
                end_label=(e_lbl or "").strip(),
                tc_format=_tc_format(s_tc),
            ))

    return RecBrief(
        raw_source=raw_source,
        file_id=file_id,
        filename=filename,
        cover_text=cover_text,
        caption=caption,
        segments=segments,
        doc_title=doc_title,
    )

# ============================================================
# 11. MODULE 9 — DRIVE DOWNLOADER + LOCAL PIPELINE
# ============================================================
def _search_drive_by_name(filename: str, log=None) -> Optional[str]:
    """ค้นหาไฟล์ใน Drive ด้วยชื่อ — คืน file ID แรกที่เจอ"""
    def _info(msg):
        if log: log(msg)
    try:
        service = get_drive_service()
        safe_name = filename.replace("'", "\\'")
        results = service.files().list(
            q=f"name='{safe_name}' and trashed=false",
            fields="files(id, name, size, mimeType)",
            pageSize=5,
            orderBy="modifiedTime desc",
        ).execute()
        files = results.get("files", [])
        if files:
            f = files[0]
            size_mb = int(f.get("size", 0)) / (1024*1024)
            _info(f"  🔎 พบไฟล์: {f['name']}  ({size_mb:.1f} MB)")
            return f["id"]
        _info(f"  ❌ ไม่พบไฟล์ '{filename}' ใน Drive")
        return None
    except Exception as e:
        _info(f"  ❌ Drive search error: {e}")
        return None

def _get_drive_file_info(file_id: str) -> dict:
    """ดึง metadata ของไฟล์จาก Drive"""
    try:
        service = get_drive_service()
        f = service.files().get(
            fileId=file_id, fields="id,name,size,mimeType").execute()
        return f
    except:
        return {}

def _download_drive_file(file_id: str, out_path: str,
                         log=None, progress_cb=None) -> bool:
    """
    Download ไฟล์จาก Drive แบบ chunked
    progress_cb(float 0.0–1.0): callback อัปเดต progress bar
    """
    def _info(msg):
        if log: log(msg)
    try:
        service    = get_drive_service()
        request    = service.files().get_media(fileId=file_id)
        last_pct   = -1
        with open(out_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=20*1024*1024)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if progress_cb:
                        progress_cb(status.progress())
                    if pct >= last_pct + 10:
                        _info(f"  ⬇️  Download {pct}%")
                        last_pct = pct
        ok = os.path.exists(out_path) and os.path.getsize(out_path) > 1024
        if ok:
            size_mb = os.path.getsize(out_path) / (1024*1024)
            _info(f"  ✅ Download เสร็จ — {size_mb:.1f} MB")
            if progress_cb:
                progress_cb(1.0)
        return ok
    except Exception as e:
        _info(f"  ❌ Download error: {e}")
        return False

def _ffmpeg_cut(src: str, start_sec: int, end_sec: int, out: str) -> bool:
    """ตัดวิดีโอโดยตรงด้วย FFmpeg — ไม่ต้อง re-encode"""
    r = subprocess.run(
        [_ff(), "-y",
         "-ss", str(start_sec),
         "-to", str(end_sec),
         "-i", src,
         "-c", "copy",
         "-avoid_negative_ts", "1",
         out],
        capture_output=True)
    return r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 10*1024

_VIDEO_CACHE_DIR = os.path.join(_ROOT, "pylive_cache")

def _cleanup_cache(days: int = 3) -> None:
    """ลบไฟล์ cache ที่เก่ากว่า `days` วัน"""
    if not os.path.isdir(_VIDEO_CACHE_DIR):
        return
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y%m%d")
    for fname in os.listdir(_VIDEO_CACHE_DIR):
        # ชื่อไฟล์รูปแบบ YYYYMMDD_<file_id><ext>
        if len(fname) >= 8 and fname[:8].isdigit() and fname[:8] < cutoff_str:
            try:
                os.remove(os.path.join(_VIDEO_CACHE_DIR, fname))
            except OSError:
                pass

def _get_cached_video(file_id: str, ext: str) -> Optional[str]:
    """คืน path ของไฟล์ที่ cache ไว้วันนี้ หรือ None ถ้ายังไม่มี"""
    today = datetime.date.today().strftime("%Y%m%d")
    cache_path = os.path.join(_VIDEO_CACHE_DIR, f"{today}_{file_id}{ext}")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1024:
        return cache_path
    return None

def _cache_path_for(file_id: str, ext: str) -> str:
    """คืน path ที่จะเก็บ cache ของไฟล์"""
    os.makedirs(_VIDEO_CACHE_DIR, exist_ok=True)
    today = datetime.date.today().strftime("%Y%m%d")
    return os.path.join(_VIDEO_CACHE_DIR, f"{today}_{file_id}{ext}")

def run_local_pipeline(brief: RecBrief, out_dir: str, tmp_dir: str,
                       log, progress_cb=None) -> dict:
    res = {"mp4": None, "error": None}
    os.makedirs(out_dir, exist_ok=True)

    # ── Step 1: Resolve video file ─────────────────────────────
    file_id = brief.file_id
    if not file_id:
        res["error"] = (
            "ไม่พบ Drive link ใน Doc\n"
            "กรุณาใส่ลิ้ง Google Drive หลังคำว่า 'ลิงก์คลิปต้นทาง:'"
        )
        return res

    # ── Step 2: Download (with cache) ─────────────────────────
    info = _get_drive_file_info(file_id)
    ext  = Path(info.get("name", "video.mp4")).suffix or ".mp4"
    fname = info.get("name", file_id)

    cached = _get_cached_video(file_id, ext)
    if cached:
        log(f"💾 ใช้ไฟล์ cache วันนี้: {os.path.basename(cached)}")
        src_path = cached
    else:
        src_path = _cache_path_for(file_id, ext)
        log(f"⬇️  กำลัง download: {fname}")
        if not _download_drive_file(file_id, src_path, log, progress_cb):
            res["error"] = "Download ไฟล์จาก Drive ล้มเหลว"
            return res
        log(f"💾 บันทึก cache: {os.path.basename(src_path)}")

    # ── Step 3: FFmpeg cut ─────────────────────────────────────
    seg_paths = []
    for i, seg in enumerate(brief.segments, 1):
        log(f"✂️  SEG {i}/{len(brief.segments)}: "
            f"{seg.start_tc} → {seg.end_tc}  "
            f"({_sec_to_display(seg.start_sec)} → {_sec_to_display(seg.end_sec)})")
        seg_out = os.path.join(tmp_dir, f"seg_{i:02d}.mp4")
        if _ffmpeg_cut(src_path, seg.start_sec, seg.end_sec, seg_out):
            dur = seg.end_sec - seg.start_sec
            seg_paths.append(seg_out)
            log(f"  ✅ seg_{i:02d}.mp4 ({dur}s)")
        else:
            log(f"  ⚠️  SEG {i} ล้มเหลว — ข้าม")
    if not seg_paths:
        res["error"] = "ไม่สามารถตัดได้สักคลิป — ตรวจสอบ TC และไฟล์วิดีโอ"
        return res

    # ── Step 4: Concat ─────────────────────────────────────────
    log("⚡ FFmpeg Concat...")
    name_src   = brief.doc_title or brief.cover_text
    safe_cover = re.sub(r'[\\/*?:"<>|\'\n\r]', '', name_src)[:50].strip()
    ts_stamp   = time.strftime("%Y%m%d_%H%M")
    out_mp4    = os.path.join(out_dir, f"PyLIVE_{safe_cover}_{ts_stamp}.mp4")
    if not concat_segments(seg_paths, out_mp4, tmp_dir):
        res["error"] = "FFmpeg Concat ล้มเหลว"
        return res
    res["mp4"] = out_mp4
    vi = probe_video(out_mp4)
    log(f"✅ {os.path.basename(out_mp4)}  "
        f"{vi.get('duration', 0):.1f}s  {vi.get('size_mb', 0):.1f}MB")
    return res

# ============================================================
# 12. STREAMLIT UI
# ============================================================
st.set_page_config(page_title="PyL.I.V.E.", page_icon="🎬", layout="wide")
inject_global_css()
_cleanup_cache(days=3)

st.markdown("""<style>
:root{--bg0:#0d0f12;--bg1:#13161b;--bg2:#1a1e26;
  --border:rgba(255,255,255,0.08);
  --text-1:#e8eaf0;--text-2:#8b90a0;--text-3:#555a6a;
  --blue:#4a9eff;--teal:#2dd4a8;--orange:#ff7a2f;--red:#ff4d4d;--yellow:#ffd166;}
textarea,input[type=text]{font-family:'IBM Plex Mono',monospace!important;font-size:13px!important;
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
.calib-card{background:#13161b;border:1px solid rgba(255,255,255,.08);
  border-radius:8px;padding:10px 14px;margin-bottom:10px;}
.manual-warn{background:#1a1e26;border:1px solid rgba(255,122,47,.3);
  border-left:3px solid #ff7a2f;border-radius:10px;padding:14px 18px;margin-bottom:12px;}
.src-card{background:#13161b;border:1px solid rgba(255,255,255,.08);
  border-left:3px solid #ff7a2f;border-radius:10px;padding:12px 16px;margin-bottom:8px;}
.ff-ok{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#2dd4a8;
  padding:5px 10px;background:rgba(45,212,168,.08);border-radius:6px;
  border:1px solid rgba(45,212,168,.2);margin-bottom:4px;}
.ff-err{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#ff4d4d;
  padding:6px 10px;background:rgba(255,77,77,.08);border-radius:6px;
  border:1px solid rgba(255,77,77,.2);line-height:1.7;margin-bottom:4px;}
@keyframes spin{to{transform:rotate(360deg)}}
</style>""", unsafe_allow_html=True)

# ── session state ─────────────────────────────────────────────
_YT_DEF = {
    "live_running":      False,
    "live_done":         False,
    "live_mp4":          None,
    "live_log":          [],
    "live_calib":        None,
    "need_manual":       False,
    "clock_checking":    False,
    "clock_check_result": None,  # (clock_str, dvr_pos_sec) หรือ "error"
    "yt_dvr_dur":        0,      # DVR window length (วินาที) จาก yt-dlp
    "yt_stream_url":     "",     # stream URL จาก yt-dlp (ใช้ซ้ำใน clock check)
}
_REC_DEF = {
    "rec_running":   False,
    "rec_done":      False,
    "rec_mp4":       None,
    "rec_log":       [],
    "rec_brief":     None,   # RecBrief parsed จาก doc
    "rec_doc_url":   "",
}
_SHARED = {"live_out_dir": "", "_cfg_cache": {}}

for k, v in {**_YT_DEF, **_REC_DEF, **_SHARED}.items():
    if k not in st.session_state:
        st.session_state[k] = v

_cfg = load_config()
st.session_state["_cfg_cache"] = _cfg

# ── shared helpers ────────────────────────────────────────────
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
        pw = int(min(pct, .99) * 100)
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

# ── header ────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <div style="font-size:32px;">🎬</div>
  <div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:20px;font-weight:700;
      color:#e8eaf0;line-height:1.1;">PyL.I.V.E.</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#555a6a;
      margin-top:2px;letter-spacing:.06em;">LIVE INTELLIGENCE VIDEO EXTRACTOR — V4.1</div>
  </div>
  <div style="margin-left:auto;">
    <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;padding:3px 8px;
      background:#1a1e26;border-radius:4px;color:#ff7a2f;
      border:1px solid rgba(255,122,47,.25);">V4.1</span>
  </div>
</div>
<div style="height:1px;background:rgba(255,255,255,.08);margin:16px 0 22px 0;"></div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
        'letter-spacing:.1em;color:#555a6a;text-transform:uppercase;'
        'border-bottom:1px solid rgba(255,255,255,.08);'
        'padding-bottom:8px;margin-bottom:14px;">⚙️ ตั้งค่า</div>',
        unsafe_allow_html=True)

    _cfg_ff = st.session_state.get("_cfg_cache", {}).get("ffmpeg_path", "")
    ff_path = (_cfg_ff if _cfg_ff and os.path.isfile(_cfg_ff) else None) or _find_bin("ffmpeg")
    if ff_path:
        st.markdown('<div class="ff-ok">✅ ffmpeg พร้อมใช้งาน</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="ff-err">❌ ไม่พบ ffmpeg<br>'
            '• macOS: <code>brew install ffmpeg</code></div>',
            unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="pl">📁 Output Folder</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([4, 1])
    with c1:
        od = st.text_input("od", label_visibility="collapsed",
            value=st.session_state["live_out_dir"] or
                  _cfg.get("dest_folder", os.path.expanduser("~/Downloads/PyLIVE")))
        st.session_state["live_out_dir"] = od
    with c2:
        if st.button("📂", key="br_od"):
            result = subprocess.run(
                ["osascript", "-e",
                 'return POSIX path of (choose folder with prompt "เลือก Folder")'],
                capture_output=True, text=True)
            if result.returncode == 0:
                folder = result.stdout.strip()
                if folder:
                    st.session_state["live_out_dir"] = folder
                    st.rerun()

# ════════════════════════════════════════════════════════════
# TABS
# ════════════════════════════════════════════════════════════
tab_yt, tab_rec = st.tabs(["📡  YouTube Live", "📁  Local (REC)"])

# ════════════════════════════════════════════════════════════
# TAB 1 — YOUTUBE LIVE
# ════════════════════════════════════════════════════════════
with tab_yt:
    col_l, col_r = st.columns([1, 1], gap="large")

    with col_l:
        st.markdown('<div class="sl-lbl">01 — วางข้อความ Brief</div>', unsafe_allow_html=True)
        brief_text = st.text_area(
            "Brief", label_visibility="collapsed", height=220,
            placeholder=(
                "ปก : ชื่อเรื่อง\n"
                "แคปชัน : ...\n\n"
                "https://www.youtube.com/watch?v=...\n\n"
                "TC: 21.08.12 label - 21.10.24 label\n"
                "TC: 21.15.00 - 21.16.30\n\n"
                "หรือ timecode ล้วน:\n"
                "21.08.12 - 21.10.24"
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

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        with st.expander(
            "✋ Manual Calibration (ระบุ reference point เอง)",
            expanded=st.session_state["need_manual"]
        ):
            st.markdown(
                '<div style="font-family:IBM Plex Sans Thai,sans-serif;font-size:12px;'
                'color:#8b90a0;margin-bottom:10px;">'
                'ใช้เมื่อ OCR ล้มเหลว หรือต้องการระบุเวลาอ้างอิงเอง</div>',
                unsafe_allow_html=True)

            # ── ปุ่มเช็คนาฬิกาอัตโนมัติ ────────────────────────
            _url_for_check = parsed.youtube_url if parsed else ""
            check_btn = st.button(
                "📸  เช็คนาฬิกาตอนนี้",
                disabled=(not _url_for_check) or st.session_state["clock_checking"],
                use_container_width=True, key="clock_check_btn")

            _ck_result = st.session_state.get("clock_check_result")
            if _ck_result and _ck_result != "error":
                _ck_clock, _ck_vpos = _ck_result
                h3, rem = _ck_vpos // 3600, _ck_vpos % 3600
                mm3, ss3 = rem // 60, rem % 60
                _vpos_display = (f"{h3:02d}.{mm3:02d}.{ss3:02d}" if h3 > 0
                                 else f"{mm3:02d}.{ss3:02d}")
                st.markdown(
                    f'<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                    f'color:#2dd4a8;margin:6px 0 10px;">✅ พบนาฬิกา {_ck_clock} '
                    f'@ DVR {_vpos_display} — กรอกด้านล่างอัตโนมัติแล้ว</div>',
                    unsafe_allow_html=True)
            elif _ck_result == "error":
                st.markdown(
                    '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                    'color:#ff4d4d;margin:6px 0 10px;">❌ ไม่พบนาฬิกา — กรอกเองด้านล่าง</div>',
                    unsafe_allow_html=True)

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

            # auto-fill value ถ้าเพิ่งเช็คมา
            _default_clock = ""
            _default_vpos  = ""
            if _ck_result and _ck_result != "error":
                _ck_clock, _ck_vpos = _ck_result
                _default_clock = _ck_clock
                h3, rem = _ck_vpos // 3600, _ck_vpos % 3600
                mm3, ss3 = rem // 60, rem % 60
                _default_vpos = (f"{h3:02d}.{mm3:02d}.{ss3:02d}" if h3 > 0
                                 else f"{mm3:02d}.{ss3:02d}")

            mc1, mc2 = st.columns(2)
            with mc1:
                man_clock = st.text_input(
                    "เวลาบนหน้าจอ (HH:MM:SS)", placeholder="14:35:22",
                    value=_default_clock, key="man_clock")
            with mc2:
                man_vpos = st.text_input(
                    "ตำแหน่งในวิดีโอ (MM.SS หรือ HH.MM.SS)", placeholder="20.02",
                    value=_default_vpos, key="man_vpos")
            manual_ref = None
            if man_clock and man_vpos:
                vpos_m = re.match(r'^(\d{1,2})\.(\d{2})(?:\.(\d{2}))?$', man_vpos.strip())
                if re.match(r'^\d{2}:\d{2}:\d{2}$', man_clock.strip()) and vpos_m:
                    if vpos_m.group(3) is not None:
                        vpos_sec = int(vpos_m.group(1))*3600 + int(vpos_m.group(2))*60 + int(vpos_m.group(3))
                    else:
                        vpos_sec = int(vpos_m.group(1))*60 + int(vpos_m.group(2))
                    manual_ref = {"clock": man_clock.strip(), "video_pos": vpos_sec}
                    st.markdown(
                        '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                        'color:#2dd4a8;margin-top:6px;">✅ Reference set</div>',
                        unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                        'color:#ff4d4d;margin-top:6px;">⚠️ รูปแบบไม่ถูก — HH:MM:SS และ MM.SS / HH.MM.SS</div>',
                        unsafe_allow_html=True)
            else:
                manual_ref = None

        # ── clock check handler ────────────────────────────────
        if check_btn and _url_for_check:
            st.session_state["clock_checking"] = True
            st.session_state["clock_check_result"] = None
            _chk_tmp = tempfile.mkdtemp(prefix="pylive_chk_")
            _chk_log = []
            # ดึง dvr_dur จาก session state (ถ้า run_pipeline เคยดึงไว้แล้ว)
            _dvr = st.session_state.get("yt_dvr_dur", 0)
            result = quick_clock_check(
                _url_for_check, _chk_tmp,
                _cfg.get("gemini_key1", ""),
                log=_chk_log.append,
                dvr_dur=_dvr)
            st.session_state["clock_check_result"] = result if result else "error"
            st.session_state["clock_checking"] = False
            st.rerun()

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        yt_run_btn = st.button(
            "🚀  เริ่มประมวลผล", type="primary",
            disabled=(
                (not parsed)
                or (parsed is not None and not parsed.segments)
                or st.session_state["live_running"]
                or (not ff_path)
            ),
            use_container_width=True, key="yt_run_btn")

    with col_r:
        st.markdown('<div class="sl-lbl">02 — ผลลัพธ์</div>', unsafe_allow_html=True)
        yt_prog_box   = st.empty()
        yt_result_box = st.empty()
        yt_calib_box  = st.empty()
        yt_log_box    = st.empty()

    # ── YouTube pipeline ──────────────────────────────────────
    if yt_run_btn and parsed:
        st.session_state.update({
            "live_running": True, "live_done": False,
            "live_mp4": None, "live_log": [],
            "live_calib": None, "need_manual": False,
        })
        tmp_dir = tempfile.mkdtemp(prefix="pylive_yt_")

        def _yt_log(msg):
            st.session_state["live_log"].append(f"[{time.strftime('%H:%M:%S')}]  {msg}")
            lines = st.session_state["live_log"][-60:]
            with yt_log_box.container():
                st.markdown('<div class="sl-lbl" style="margin-top:20px;">LOG</div>',
                            unsafe_allow_html=True)
                st.markdown('<div class="lg">' + "<br>".join(lines) + '</div>',
                            unsafe_allow_html=True)

        try:
            _prog(yt_prog_box, "วิเคราะห์ stream + Calibrate...", "📡", pct=0.10)
            _yt_log(f"🚀 เริ่ม Pipeline  |  {len(parsed.segments)} segment(s)")
            res = run_pipeline(
                brief=parsed,
                out_dir=st.session_state["live_out_dir"],
                tmp_dir=tmp_dir,
                gemini_key=_cfg.get("gemini_key1", ""),
                manual_ref=manual_ref,
                log=_yt_log,
            )
            st.session_state["live_calib"]    = res.get("calib")
            st.session_state["need_manual"]   = res.get("need_manual", False)
            if res.get("dvr_dur"):
                st.session_state["yt_dvr_dur"] = res["dvr_dur"]
            if res["error"]:
                _yt_log(f"❌ {res['error']}")
                _prog(yt_prog_box, res["error"][:80], "❌", pct=0)
            else:
                st.session_state["live_mp4"] = res["mp4"]
                _prog(yt_prog_box, "", done=True)
                _yt_log("🎉 Pipeline เสร็จสมบูรณ์!")
                st.session_state["live_done"] = True
        except Exception as e:
            _yt_log(f"❌ Error: {e}")
            _prog(yt_prog_box, str(e)[:80], "❌", pct=0)
        finally:
            st.session_state["live_running"] = False
            shutil.rmtree(tmp_dir, ignore_errors=True)
        st.rerun()

    # ── render YouTube results ─────────────────────────────────
    if st.session_state["need_manual"] and not st.session_state["live_done"]:
        yt_result_box.markdown(
            '<div class="manual-warn">'
            '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#ff7a2f;'
            'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;">'
            '✋ ต้องการ Manual Calibration</div>'
            '<div style="font-family:IBM Plex Sans Thai,sans-serif;font-size:13px;color:#e8eaf0;">'
            'OCR ไม่สามารถอ่านนาฬิกาจากวิดีโอได้<br>'
            'กรุณากรอก reference point ในช่อง Manual Calibration แล้วกดเริ่มอีกครั้ง</div>'
            '</div>', unsafe_allow_html=True)

    calib = st.session_state.get("live_calib")
    if calib:
        h = calib.stream_start_sec // 3600
        m = (calib.stream_start_sec % 3600) // 60
        s = calib.stream_start_sec % 60
        conf_color = "#2dd4a8" if calib.confidence >= 0.8 else "#ffd166" if calib.confidence >= 0.5 else "#ff7a2f"
        method_label = {"metadata": "📋 Metadata", "ocr": "👁 OCR Probe", "manual": "✋ Manual"}.get(calib.method_used, calib.method_used)
        yt_calib_box.markdown(
            f'<div class="calib-card"><div class="pl">Calibration Result</div>'
            f'<div style="display:flex;align-items:center;gap:16px;margin-top:6px;">'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:15px;color:#e8eaf0;">'
            f'⏱ stream start = {h:02d}:{m:02d}:{s:02d}</div>'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:11px;color:{conf_color};">'
            f'conf {calib.confidence:.0%}</div>'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#555a6a;">'
            f'{method_label}</div></div></div>', unsafe_allow_html=True)

    if st.session_state["live_done"]:
        mp4 = st.session_state["live_mp4"]
        if mp4 and os.path.exists(mp4):
            info = probe_video(mp4)
            yt_result_box.markdown(
                f'<div class="oc"><div class="pl">OUTPUT FILE</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:13px;'
                f'color:#2dd4a8;">📹 {os.path.basename(mp4)}</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                f'color:#555a6a;margin-top:4px;">'
                f'{info.get("duration", 0):.1f}s · {info.get("size_mb", 0):.1f}MB · '
                f'codec={info.get("video_codec", "?")} · '
                f'audio={"✓" if info.get("has_audio") else "✗"}</div></div>',
                unsafe_allow_html=True)

    if st.session_state["live_log"]:
        with yt_log_box.container():
            st.markdown('<div class="sl-lbl" style="margin-top:20px;">LOG</div>', unsafe_allow_html=True)
            lines = st.session_state["live_log"][-60:]
            st.markdown('<div class="lg">' + "<br>".join(lines) + '</div>', unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if st.button("🔄 เริ่มใหม่", key="yt_reset_btn"):
        for k, v in _YT_DEF.items():
            st.session_state[k] = v
        st.rerun()

# ════════════════════════════════════════════════════════════
# TAB 2 — LOCAL (REC)
# ════════════════════════════════════════════════════════════
with tab_rec:
    col_l2, col_r2 = st.columns([1, 1], gap="large")

    with col_l2:
        st.markdown('<div class="sl-lbl">01 — Google Doc Script URL</div>', unsafe_allow_html=True)

        doc_url_input = st.text_input(
            "doc_url", label_visibility="collapsed",
            placeholder="https://docs.google.com/document/d/...",
            value=st.session_state["rec_doc_url"],
            key="doc_url_input",
        )
        st.session_state["rec_doc_url"] = doc_url_input

        load_col, _ = st.columns([2, 3])
        with load_col:
            load_btn = st.button(
                "🔍  โหลด Doc", key="load_doc_btn",
                disabled=not doc_url_input.strip() or st.session_state["rec_running"],
                use_container_width=True)

        # ── Load Doc ────────────────────────────────────────────
        if load_btn and doc_url_input.strip():
            with st.spinner("กำลังอ่าน Google Doc..."):
                try:
                    doc_id  = extract_id(doc_url_input.strip())
                    if not doc_id:
                        st.error("❌ ไม่สามารถ extract ID จาก URL ได้")
                    else:
                        doc_text, drive_url, doc_title = _read_doc_text(doc_id)
                        brief    = parse_doc_brief(doc_text, drive_url, doc_title)
                        if brief:
                            st.session_state["rec_brief"] = brief
                            st.session_state["rec_done"]  = False
                            st.session_state["rec_mp4"]   = None
                            st.session_state["rec_log"]   = []
                        else:
                            st.error("❌ Parse ไม่ได้ — ตรวจสอบว่า Doc มี 'ลิงก์คลิปต้นทาง' และ 'Tc'")
                            # debug: แสดง raw text 500 ตัวแรก
                            with st.expander("🐛 Debug — raw doc text"):
                                st.code(repr(doc_text[:1000]))
                except Exception as e:
                    st.error(f"❌ อ่าน Doc ล้มเหลว: {e}")

        # ── Preview parsed brief ────────────────────────────────
        rec_brief: Optional[RecBrief] = st.session_state.get("rec_brief")
        if rec_brief:
            st.markdown(
                '<div style="font-family:IBM Plex Mono,monospace;font-size:10px;'
                'color:#2dd4a8;text-transform:uppercase;letter-spacing:.1em;'
                'margin:14px 0 10px;">✅ อ่าน Doc สำเร็จ</div>', unsafe_allow_html=True)

            # source card
            src_type = "Drive URL ✅" if rec_brief.file_id else "⚠️ ไม่พบ Drive link — กรุณาใส่ลิ้ง"
            st.markdown(
                f'<div class="src-card">'
                f'<div class="pl">ไฟล์วิดีโอ</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:13px;'
                f'color:#ff7a2f;">{rec_brief.raw_source}</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;'
                f'color:#555a6a;margin-top:3px;">{src_type}</div>'
                f'</div>', unsafe_allow_html=True)
            # debug: แสดง file_id ที่ได้
            with st.expander("🐛 Debug — parsed values"):
                st.code(
                    f"raw_source : {repr(rec_brief.raw_source)}\n"
                    f"file_id    : {repr(rec_brief.file_id)}\n"
                    f"filename   : {repr(rec_brief.filename)}\n"
                    f"segments   : {len(rec_brief.segments)}"
                )

            # cover / caption
            if rec_brief.cover_text:
                st.markdown(
                    f'<div class="pc"><div class="pl">ปก</div>'
                    f'<div class="pv">{rec_brief.cover_text}</div></div>',
                    unsafe_allow_html=True)

            # segments
            if rec_brief.segments:
                segs_html = "".join(
                    f'<div class="sr"><span class="sn">SEG {i}</span>'
                    f'<div>'
                    f'<div class="sc">{_sec_to_display(s.start_sec)} → {_sec_to_display(s.end_sec)}'
                    f'  <span style="color:#555a6a;font-size:11px;">({s.end_sec - s.start_sec}s · {s.tc_format})</span></div>'
                    f'<div class="sl">{s.start_tc} "{s.start_label}" — {s.end_tc} "{s.end_label}"</div>'
                    f'</div></div>'
                    for i, s in enumerate(rec_brief.segments, 1))
                st.markdown(
                    f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;'
                    f'color:#555a6a;text-transform:uppercase;letter-spacing:.1em;'
                    f'margin:12px 0 8px;">{len(rec_brief.segments)} SEGMENT(S)</div>' + segs_html,
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    '<div style="font-family:IBM Plex Mono,monospace;font-size:12px;'
                    'color:#ff7a2f;margin-top:8px;">⚠️ ไม่พบ TC segments — ตรวจสอบ format ใน Doc</div>',
                    unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        rec_run_btn = st.button(
            "🚀  ดาวน์โหลด + ตัด", type="primary",
            disabled=(
                (not rec_brief)
                or (rec_brief is not None and not rec_brief.segments)
                or st.session_state["rec_running"]
                or (not ff_path)
            ),
            use_container_width=True, key="rec_run_btn")

    with col_r2:
        st.markdown('<div class="sl-lbl">02 — ผลลัพธ์</div>', unsafe_allow_html=True)
        rec_prog_box      = st.empty()
        rec_dl_label_box  = st.empty()
        rec_dl_bar_box    = st.empty()
        rec_result_box    = st.empty()
        rec_log_box       = st.empty()

    # ── Local pipeline ────────────────────────────────────────
    if rec_run_btn and rec_brief:
        st.session_state.update({
            "rec_running": True, "rec_done": False,
            "rec_mp4": None, "rec_log": [],
        })
        tmp_dir2 = tempfile.mkdtemp(prefix="pylive_rec_")

        def _rec_log(msg):
            st.session_state["rec_log"].append(f"[{time.strftime('%H:%M:%S')}]  {msg}")
            lines = st.session_state["rec_log"][-60:]
            with rec_log_box.container():
                st.markdown('<div class="sl-lbl" style="margin-top:20px;">LOG</div>',
                            unsafe_allow_html=True)
                st.markdown('<div class="lg">' + "<br>".join(lines) + '</div>',
                            unsafe_allow_html=True)

        try:
            _prog(rec_prog_box, "กำลัง download + ตัดวิดีโอ...", "⬇️", pct=0.10)
            _rec_log(f"🚀 เริ่ม Pipeline  |  {len(rec_brief.segments)} segment(s)")
            _rec_log(f"📄 ไฟล์ต้นทาง: {rec_brief.raw_source}")

            # progress bar สำหรับ download
            rec_dl_label_box.markdown(
                '<div style="font-family:IBM Plex Mono,monospace;font-size:10px;'
                'color:#555a6a;text-transform:uppercase;letter-spacing:.08em;'
                'margin-bottom:4px;">⬇️ Download Progress</div>',
                unsafe_allow_html=True)
            dl_bar = rec_dl_bar_box.progress(0)

            def _dl_progress(ratio: float):
                dl_bar.progress(min(ratio, 1.0))

            res = run_local_pipeline(
                brief=rec_brief,
                out_dir=st.session_state["live_out_dir"],
                tmp_dir=tmp_dir2,
                log=_rec_log,
                progress_cb=_dl_progress,
            )
            if res["error"]:
                _rec_log(f"❌ {res['error']}")
                _prog(rec_prog_box, res["error"][:80], "❌", pct=0)
                rec_dl_label_box.empty()
                rec_dl_bar_box.empty()
            else:
                st.session_state["rec_mp4"] = res["mp4"]
                _prog(rec_prog_box, "", done=True)
                rec_dl_label_box.empty()
                rec_dl_bar_box.empty()
                _rec_log("🎉 Pipeline เสร็จสมบูรณ์!")
                st.session_state["rec_done"] = True
        except Exception as e:
            _rec_log(f"❌ Error: {e}")
            _prog(rec_prog_box, str(e)[:80], "❌", pct=0)
            rec_dl_label_box.empty()
            rec_dl_bar_box.empty()
        finally:
            st.session_state["rec_running"] = False
            shutil.rmtree(tmp_dir2, ignore_errors=True)
        st.rerun()

    # ── render Local results ───────────────────────────────────
    if st.session_state["rec_done"]:
        mp4 = st.session_state["rec_mp4"]
        if mp4 and os.path.exists(mp4):
            info = probe_video(mp4)
            rec_result_box.markdown(
                f'<div class="oc"><div class="pl">OUTPUT FILE</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:13px;'
                f'color:#2dd4a8;">📹 {os.path.basename(mp4)}</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                f'color:#555a6a;margin-top:4px;">'
                f'{info.get("duration", 0):.1f}s · {info.get("size_mb", 0):.1f}MB · '
                f'codec={info.get("video_codec", "?")} · '
                f'audio={"✓" if info.get("has_audio") else "✗"}</div></div>',
                unsafe_allow_html=True)

    if st.session_state["rec_log"]:
        with rec_log_box.container():
            st.markdown('<div class="sl-lbl" style="margin-top:20px;">LOG</div>', unsafe_allow_html=True)
            lines = st.session_state["rec_log"][-60:]
            st.markdown('<div class="lg">' + "<br>".join(lines) + '</div>', unsafe_allow_html=True)

    if st.session_state["rec_done"]:
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        if st.button("🔄 เริ่มใหม่", key="rec_reset_btn"):
            for k, v in _REC_DEF.items():
                st.session_state[k] = v
            st.rerun()
