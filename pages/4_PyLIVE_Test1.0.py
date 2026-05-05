"""
PyL.I.V.E. — Live Intelligence Video Extractor
V4.0

วาง file นี้ที่: pages/4_PyLIVE_Test1.0.py
"""

import sys, os, re, time, shutil, subprocess, tempfile, json, datetime
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
SAFETY_BUFFER_SEC = 2
PROBE_DURATION    = 90      # วิ — ยาวพอสำหรับ adaptive scan
OCR_CROP_RATIO    = {"left": 0.82, "top": 0.02, "right": 1.00, "bottom": 0.12}
SCAN_START        = 10      # เริ่ม scan ที่ 10s (ข้าม intro)
SCAN_END          = 65      # scan ถึง 60s
SCAN_STEP         = 5       # ขยับทีละ 5s

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
    release_timestamp: Optional[int] = None   # Unix timestamp (VOD only)

@dataclass
class CalibResult:
    stream_start_sec: int    # วินาทีนับจากเที่ยงคืน ของเวลาเริ่มต้น stream
    confidence:       float  # 0.0–1.0
    method_used:      str    # "metadata" | "ocr" | "manual"

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
    """หา ffmpeg exe สำหรับส่งให้ yt-dlp (ไม่ raise)"""
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
# 3.  MODULE 1 — TEXT PARSER
# ============================================================
def clock_to_sec(s: str) -> int:
    """HH.MM.SS (brief format) → วินาที"""
    p = s.split(".")
    return int(p[0])*3600 + int(p[1])*60 + int(p[2])

def hhmm_to_sec(s: str) -> int:
    """HH:MM:SS (OCR / manual format) → วินาที"""
    p = s.split(":")
    return int(p[0])*3600 + int(p[1])*60 + int(p[2])

def clock_to_sec_safe(clock_str: str, stream_start_sec: int) -> int:
    """
    แปลง TC string (HH.MM.SS) → วินาที
    รองรับ midnight wrap-around: ถ้า clock_sec น้อยกว่า stream_start เกิน 1 ชั่วโมง
    แสดงว่าข้ามเที่ยงคืน → +86400
    """
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

    segments = []
    for line in text.splitlines():
        m = re.match(
            r'TC.*?:\s*(\d{2}\.\d{2}\.\d{2})\s*(.*?)\s*-\s*(\d{2}\.\d{2}\.\d{2})\s*(.*)$',
            line.strip())
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
    """ดึง metadata จาก yt-dlp เพื่อวิเคราะห์ประเภท stream"""
    def _info(msg):
        if log: log(msg)

    opts = {
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'skip_download': True,
    }
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
        url=url,
        stream_type=stype,
        title=title,
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
    """OCR ที่ตำแหน่ง t วินาที — คืน 'HH:MM:SS' หรือ None"""
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
    """
    Adaptive scan: ลอง OCR ทีละ SCAN_STEP วินาที ตั้งแต่ SCAN_START
    คืน (T_found, clock_str) แรกที่ OCR สำเร็จ
    ถ้าไม่เจอเลยใน 10–60s → raise NoClock
    """
    def _info(msg):
        if log: log(msg)

    dur = get_duration(probe_clip)
    _info(f"  📏 Probe clip = {dur:.1f}s  |  Adaptive scan {SCAN_START}–{min(SCAN_END-1, int(dur))}s")

    for t in range(SCAN_START, SCAN_END, SCAN_STEP):
        if t >= dur - 1:
            _info(f"  ⚠️  T={t}s เกิน duration ของ probe clip ({dur:.0f}s)")
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
                   tmp_dir: str, api_key: str, log=None) -> CalibResult:
    """
    Calibrate 3 จุด: t_found, t_found+15s, t_found+30s
    stream_start = median(clock_at_T - T)
    """
    def _info(msg):
        if log: log(msg)

    dur = get_duration(probe_clip)

    # จุดแรกมีแล้วจาก find_clock_appearance
    wall_sec_0 = hhmm_to_sec(clock_found)
    est_0 = wall_sec_0 - int(t_found)
    estimates = [est_0]
    _info(f"  📐 T={t_found:.0f}s → {clock_found} → start estimate = "
          f"{est_0//3600:02d}:{(est_0%3600)//60:02d}:{est_0%60:02d}")

    for t in [t_found + 15, t_found + 30]:
        if t >= dur - 1:
            continue
        clock = _try_ocr_at(probe_clip, t, tmp_dir, api_key, "calib")
        if clock:
            wall_sec = hhmm_to_sec(clock)
            est = wall_sec - int(t)
            estimates.append(est)
            _info(f"  📐 T={t:.0f}s → {clock} → start estimate = "
                  f"{est//3600:02d}:{(est%3600)//60:02d}:{est%60:02d}")
        else:
            _info(f"  ⚠️  T={t:.0f}s — OCR ล้มเหลว — ข้าม")

    vals = sorted(estimates)
    stream_start = vals[len(vals) // 2]  # median
    spread = max(vals) - min(vals) if len(vals) > 1 else 0
    confidence = max(0.0, min(1.0, 1.0 - spread / 10.0))

    h, m, s = stream_start // 3600, (stream_start % 3600) // 60, stream_start % 60
    _info(f"  ✅ stream_start = {h:02d}:{m:02d}:{s:02d}  "
          f"(spread={spread}s, confidence={confidence:.0%})")

    return CalibResult(
        stream_start_sec=stream_start,
        confidence=confidence,
        method_used="ocr",
    )

def calibrate(stream_info: StreamInfo, tmp_dir: str, api_key: str,
              manual_ref: Optional[dict] = None, log=None) -> CalibResult:
    """
    Priority:
    1. manual_ref (ผู้ใช้กรอกเอง) → confidence 1.0
    2. Metadata release_timestamp → confidence 0.95
    3. OCR adaptive scan → confidence จาก spread
    """
    def _info(msg):
        if log: log(msg)

    # ── Priority 1: Manual ─────────────────────────────────────
    if manual_ref:
        try:
            clock_sec    = hhmm_to_sec(manual_ref["clock"])
            video_pos    = int(manual_ref["video_pos"])
            stream_start = clock_sec - video_pos
            h, m, s = stream_start // 3600, (stream_start % 3600) // 60, stream_start % 60
            _info(f"  ✋ Manual calibration → stream_start = {h:02d}:{m:02d}:{s:02d}")
            return CalibResult(stream_start_sec=stream_start, confidence=1.0, method_used="manual")
        except Exception as e:
            _info(f"  ⚠️  Manual ref error: {e} — ข้ามไป OCR")

    # ── Priority 2: Metadata ───────────────────────────────────
    if stream_info.release_timestamp:
        dt = datetime.datetime.fromtimestamp(stream_info.release_timestamp)
        stream_start = dt.hour * 3600 + dt.minute * 60 + dt.second
        _info(f"  📋 Metadata → stream_start = {dt.strftime('%H:%M:%S')}  (release_timestamp)")
        return CalibResult(stream_start_sec=stream_start, confidence=0.95, method_used="metadata")

    # ── Priority 3: OCR probe ──────────────────────────────────
    _info("  🔍 โหลด Probe Clip (90 วิ / 360p)...")
    probe = _download_probe_clip(stream_info.url, tmp_dir)
    if not probe:
        raise NoClock("โหลด Probe Clip ล้มเหลว")

    _info("  🔍 Adaptive Clock Scan...")
    t_found, clock_found = _find_clock_appearance(probe, tmp_dir, api_key, log)
    return _ocr_calibrate(probe, t_found, clock_found, tmp_dir, api_key, log)

# ============================================================
# 7.  MODULE 5 — DOWNLOADER
# ============================================================
def _download_probe_clip(url: str, out_dir: str) -> Optional[str]:
    """โหลด probe clip 90 วิ (360p) สำหรับ adaptive clock scan"""
    ffmpeg_exe = _get_ffmpeg_exe()
    out = os.path.join(out_dir, "probe_clip.mp4")
    opts = {
        'format': ('bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]'
                   '/bestvideo[height<=480]+bestaudio/worst'),
        'merge_output_format': 'mp4',
        'outtmpl': out.replace('.mp4', '.%(ext)s'),
        'download_ranges': yt_dlp.utils.download_range_func(None, [(0, PROBE_DURATION)]),
        'force_keyframes_at_cuts': True,
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'ffmpeg_location': ffmpeg_exe,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        for f in Path(out_dir).glob("probe_clip.*"):
            if get_duration(str(f)) >= 25:
                return str(f)
            os.remove(str(f))
            break
        # fallback format
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
        'format': ('bestvideo[ext=mp4][vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]'
                   '/bestvideo[ext=mp4][vcodec!^=av01][height<=1080]+bestaudio[ext=m4a]'
                   '/best[ext=mp4]/best'),
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
                            shutil.move(str(f), out)
                        return os.path.exists(out) and os.path.getsize(out) > 10*1024
                return os.path.exists(out) and os.path.getsize(out) > 10*1024
        return False
    except:
        return False

# ============================================================
# 8.  MODULE 6 — FFMPEG CONCAT
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
# 9.  PIPELINE ORCHESTRATOR
# ============================================================
def run_pipeline(brief: LiveBrief, out_dir: str, tmp_dir: str,
                 gemini_key: str, manual_ref: Optional[dict], log) -> dict:
    res = {"mp4": None, "calib": None, "error": None, "need_manual": False}
    os.makedirs(out_dir, exist_ok=True)

    # ── Step 1: Stream Intelligence ────────────────────────────
    log("📡 วิเคราะห์ stream...")
    try:
        stream_info = get_stream_info(brief.youtube_url, log)
    except Exception as e:
        res["error"] = f"วิเคราะห์ stream ล้มเหลว: {e}"
        return res

    # ── Step 2: Calibration ────────────────────────────────────
    log("🔍 Calibrate Timecode...")
    try:
        calib = calibrate(stream_info, tmp_dir, gemini_key, manual_ref, log)
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

    # ── Step 3: Compute timestamps ─────────────────────────────
    timestamps = compute_timestamps(brief.segments, calib)
    if not timestamps:
        res["error"] = "ไม่มี segment — ตรวจ TC format: HH.MM.SS label - HH.MM.SS"
        return res
    for i, ts in enumerate(timestamps, 1):
        log(f"  📐 SEG {i}: [{ts['video_start']:.0f}s → {ts['video_end']:.0f}s] "
            f"({ts['duration']:.0f}s)")

    # ── Step 4: Download segments ──────────────────────────────
    seg_paths = []
    for i, ts in enumerate(timestamps, 1):
        log(f"⬇️  Segment {i}/{len(timestamps)}: {ts['start_clock']} → {ts['end_clock']}")
        seg_out = os.path.join(tmp_dir, f"segment_{i:02d}.mp4")
        if download_segment(brief.youtube_url, ts["video_start"], ts["video_end"], seg_out):
            seg_paths.append(seg_out)
            log(f"  ✅ segment_{i:02d}.mp4 ({ts['duration']:.0f}s)")
        else:
            log(f"  ⚠️  segment_{i:02d} ล้มเหลว — ข้าม")
    if not seg_paths:
        res["error"] = "ไม่สามารถโหลด segment ได้เลย"
        return res

    # ── Step 5: Concat ─────────────────────────────────────────
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
# 10.  STREAMLIT UI
# ============================================================
st.set_page_config(page_title="PyL.I.V.E.", page_icon="🎬", layout="wide")
inject_global_css()

st.markdown("""<style>
:root{--bg0:#0d0f12;--bg1:#13161b;--bg2:#1a1e26;
  --border:rgba(255,255,255,0.08);
  --text-1:#e8eaf0;--text-2:#8b90a0;--text-3:#555a6a;
  --blue:#4a9eff;--teal:#2dd4a8;--orange:#ff7a2f;--red:#ff4d4d;--yellow:#ffd166;}
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
.calib-card{background:#13161b;border:1px solid rgba(255,255,255,.08);
  border-radius:8px;padding:10px 14px;margin-bottom:10px;}
.manual-warn{background:#1a1e26;border:1px solid rgba(255,122,47,.3);
  border-left:3px solid #ff7a2f;border-radius:10px;padding:14px 18px;margin-bottom:12px;}
.ff-ok{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#2dd4a8;
  padding:5px 10px;background:rgba(45,212,168,.08);border-radius:6px;
  border:1px solid rgba(45,212,168,.2);margin-bottom:4px;}
.ff-err{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#ff4d4d;
  padding:6px 10px;background:rgba(255,77,77,.08);border-radius:6px;
  border:1px solid rgba(255,77,77,.2);line-height:1.7;margin-bottom:4px;}
@keyframes spin{to{transform:rotate(360deg)}}
</style>""", unsafe_allow_html=True)

# ── session state ─────────────────────────────────────────────
_DEF = {
    "live_running":  False,
    "live_done":     False,
    "live_mp4":      None,
    "live_log":      [],
    "live_out_dir":  "",
    "live_calib":    None,
    "need_manual":   False,
    "_cfg_cache":    {},
}
for k, v in _DEF.items():
    if k not in st.session_state:
        st.session_state[k] = v

_cfg = load_config()
st.session_state["_cfg_cache"] = _cfg

# ── progress renderer ──────────────────────────────────────────
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

# ── header ─────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
  <div style="font-size:32px;">🎬</div>
  <div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:20px;font-weight:700;
      color:#e8eaf0;line-height:1.1;">PyL.I.V.E.</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#555a6a;
      margin-top:2px;letter-spacing:.06em;">LIVE INTELLIGENCE VIDEO EXTRACTOR — V4.0</div>
  </div>
  <div style="margin-left:auto;">
    <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;padding:3px 8px;
      background:#1a1e26;border-radius:4px;color:#ff7a2f;
      border:1px solid rgba(255,122,47,.25);">V4.0</span>
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
            '• macOS: <code>brew install ffmpeg</code><br>'
            '• หรือระบุ path ใน config → <code>ffmpeg_path</code></div>',
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
# MAIN COLUMNS
# ════════════════════════════════════════════════════════════
col_l, col_r = st.columns([1, 1], gap="large")

# ────────────────  LEFT — Input  ────────────────────────────
with col_l:
    st.markdown('<div class="sl-lbl">01 — วางข้อความ Brief</div>', unsafe_allow_html=True)
    brief_text = st.text_area(
        "Brief", label_visibility="collapsed", height=220,
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

    # ── Manual Calibration ─────────────────────────────────────
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    with st.expander(
        "✋ Manual Calibration (ระบุ reference point เอง)",
        expanded=st.session_state["need_manual"]
    ):
        st.markdown(
            '<div style="font-family:IBM Plex Sans Thai,sans-serif;font-size:12px;'
            'color:#8b90a0;margin-bottom:10px;">'
            'ใช้เมื่อ OCR ล้มเหลว หรือนาฬิกาไม่ปรากฏในวิดีโอ<br>'
            'กรอกเวลา 1 จุดที่รู้แน่ชัด เพื่อให้ระบบคำนวณ offset</div>',
            unsafe_allow_html=True)
        mc1, mc2 = st.columns(2)
        with mc1:
            man_clock = st.text_input(
                "เวลาบนหน้าจอ (HH:MM:SS)", placeholder="14:35:22", key="man_clock")
        with mc2:
            man_vpos = st.text_input(
                "ตำแหน่งในวิดีโอ (วินาที)", placeholder="125", key="man_vpos")

        manual_ref = None
        if man_clock and man_vpos:
            if re.match(r'^\d{2}:\d{2}:\d{2}$', man_clock.strip()) and man_vpos.strip().isdigit():
                manual_ref = {"clock": man_clock.strip(), "video_pos": int(man_vpos.strip())}
                st.markdown(
                    '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                    'color:#2dd4a8;margin-top:6px;">✅ Reference set — จะใช้ค่านี้แทน OCR</div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                    'color:#ff4d4d;margin-top:6px;">'
                    '⚠️ รูปแบบไม่ถูก — ต้องเป็น HH:MM:SS และตัวเลขจำนวนเต็ม</div>',
                    unsafe_allow_html=True)
        else:
            manual_ref = None

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    run_btn = st.button(
        "🚀  เริ่มประมวลผล", type="primary",
        disabled=(
            (not parsed)
            or (parsed is not None and not parsed.segments)
            or st.session_state["live_running"]
            or (not ff_path)
        ),
        use_container_width=True, key="run_btn")

# ────────────────  RIGHT — Results  ─────────────────────────
with col_r:
    st.markdown('<div class="sl-lbl">02 — ผลลัพธ์</div>', unsafe_allow_html=True)
    prog_box   = st.empty()
    result_box = st.empty()
    calib_box  = st.empty()
    log_box    = st.empty()

# ════════════════════════════════════════════════════════════
# PIPELINE
# ════════════════════════════════════════════════════════════
if run_btn and parsed:
    st.session_state.update({
        "live_running": True, "live_done": False,
        "live_mp4": None, "live_log": [],
        "live_calib": None, "need_manual": False,
    })
    tmp_dir = tempfile.mkdtemp(prefix="pylive_")

    def _log(msg):
        st.session_state["live_log"].append(f"[{time.strftime('%H:%M:%S')}]  {msg}")

    try:
        _prog(prog_box, "วิเคราะห์ stream + Calibrate...", "📡", pct=0.10)
        _log(f"🚀 เริ่ม Pipeline  |  {len(parsed.segments)} segment(s)")

        res = run_pipeline(
            brief=parsed,
            out_dir=st.session_state["live_out_dir"],
            tmp_dir=tmp_dir,
            gemini_key=_cfg.get("gemini_key1", ""),
            manual_ref=manual_ref,
            log=_log,
        )

        st.session_state["live_calib"]  = res.get("calib")
        st.session_state["need_manual"] = res.get("need_manual", False)

        if res["error"]:
            _log(f"❌ {res['error']}")
            _prog(prog_box, res["error"][:80], "❌", pct=0)
        else:
            st.session_state["live_mp4"] = res["mp4"]
            _prog(prog_box, "", done=True)
            _log("🎉 Pipeline เสร็จสมบูรณ์!")
            st.session_state["live_done"] = True

    except Exception as e:
        _log(f"❌ Error: {e}")
        _prog(prog_box, str(e)[:80], "❌", pct=0)
    finally:
        st.session_state["live_running"] = False
        shutil.rmtree(tmp_dir, ignore_errors=True)
    st.rerun()

# ════════════════════════════════════════════════════════════
# RENDER RESULTS
# ════════════════════════════════════════════════════════════

# Manual calibration warning
if st.session_state["need_manual"] and not st.session_state["live_done"]:
    result_box.markdown(
        '<div class="manual-warn">'
        '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#ff7a2f;'
        'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;">'
        '✋ ต้องการ Manual Calibration</div>'
        '<div style="font-family:IBM Plex Sans Thai,sans-serif;font-size:13px;color:#e8eaf0;">'
        'OCR ไม่สามารถอ่านนาฬิกาจากวิดีโอได้<br>'
        'กรุณากรอก reference point ในช่อง Manual Calibration ด้านซ้าย '
        'แล้วกด เริ่มประมวลผล อีกครั้ง</div>'
        '</div>', unsafe_allow_html=True)

# Calibration result card
calib = st.session_state.get("live_calib")
if calib:
    h = calib.stream_start_sec // 3600
    m = (calib.stream_start_sec % 3600) // 60
    s = calib.stream_start_sec % 60
    conf_color = (
        "#2dd4a8" if calib.confidence >= 0.8 else
        "#ffd166" if calib.confidence >= 0.5 else
        "#ff7a2f"
    )
    method_label = {
        "metadata": "📋 Metadata",
        "ocr":      "👁 OCR Probe",
        "manual":   "✋ Manual",
    }.get(calib.method_used, calib.method_used)
    calib_box.markdown(
        f'<div class="calib-card">'
        f'<div class="pl">Calibration Result</div>'
        f'<div style="display:flex;align-items:center;gap:16px;margin-top:6px;">'
        f'<div style="font-family:IBM Plex Mono,monospace;font-size:15px;color:#e8eaf0;">'
        f'⏱ stream start = {h:02d}:{m:02d}:{s:02d}</div>'
        f'<div style="font-family:IBM Plex Mono,monospace;font-size:11px;color:{conf_color};">'
        f'conf {calib.confidence:.0%}</div>'
        f'<div style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#555a6a;">'
        f'{method_label}</div>'
        f'</div></div>',
        unsafe_allow_html=True)

# Output file card
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
            f'{info.get("duration", 0):.1f}s · {info.get("size_mb", 0):.1f}MB · '
            f'codec={info.get("video_codec", "?")} · '
            f'audio={"✓" if info.get("has_audio") else "✗"}</div></div>',
            unsafe_allow_html=True)

# Log
if st.session_state["live_log"]:
    with log_box.container():
        st.markdown(
            '<div class="sl-lbl" style="margin-top:20px;">LOG</div>',
            unsafe_allow_html=True)
        lines = st.session_state["live_log"][-60:]
        st.markdown(
            '<div class="lg">' + "<br>".join(lines) + '</div>',
            unsafe_allow_html=True)

# Reset button
if st.session_state["live_done"]:
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if st.button("🔄 เริ่มใหม่", key="reset_btn"):
        for k, v in _DEF.items():
            st.session_state[k] = v
        st.rerun()
