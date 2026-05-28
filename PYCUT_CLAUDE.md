# PYCUT_CLAUDE.md

Context file สำหรับ Claude Code — อ่านไฟล์นี้ก่อนแตะ PyCUT ทุกครั้ง

---

## ภาพรวม

**PyCUT** คือ tool ใน LoadPAP Suite สำหรับทีมวิดีโอ
รับ Google Doc สคริปต์ → สร้าง `.srt` subtitle + โหลดและตัดฟุตเทจตาม Timecode อัตโนมัติ
ออกแบบสำหรับคลิปแนวตั้ง (vertical) รองรับทั้ง VO และ SOT

**ไฟล์หลัก:** `pages/5_PyCUT_BetaV1.0.py`

---

## Dependencies ที่ติดตั้งเพิ่ม

```
mlx-whisper>=0.3.0   # Apple Silicon only — MLX Whisper
stable-ts[mlx]       # stable-ts for mlx backend
```

ทั้งคู่อยู่ใน `requirements.txt` แล้ว — `pip install -r requirements.txt` ครั้งเดียว
**หมายเหตุ:** `mlx-whisper` ทำงานได้เฉพาะ Mac Apple Silicon (M1/M2/M3)
บน Intel Mac จะ fallback ไปใช้ `faster-whisper` (ต้องติดตั้งแยก) หรือ char-proportional

---

## Google Doc Table Structure

### Info Table (ตารางแรก — ข้อมูลทั่วไป)

| Key | ค่า |
|-----|-----|
| Title: | ชื่อคลิป |
| Brief / Format: | แนวตั้ง/แนวนอน + มี/ไม่มีซับ |

parse: `"นอน" / "horizontal"` → horizontal, ค่าอื่น → vertical
`"subtitle" / "ซับ"` → has_subtitle = True

### Script Table (ตารางหลัก)

| Index | Header | หมายเหตุ |
|-------|--------|----------|
| 0 | Footages | URL/code ฟุตเทจ — อาจมีหลาย paragraph = หลาย footage |
| 1 | TC_in | format MM.SS |
| 2 | TC_out | format MM.SS |
| 3 | Insert | footage ที่ต้องการ insert — ไม่ตัด TC |
| 4 | Super/Barname | — |
| 5 (last) | SUB/เนื้อหา | bullets (1 paragraph = 1 subtitle block) |

detect script table: header row มีคำ "footages" หรือ "sub"
detect insert column: header cell ที่มีคำ "insert" → เก็บเป็น `insert_col_idx`

---

## Doc Parser (`parse_pycut_doc`)

### Return schema

```python
{
    "format": "vertical" | "horizontal",
    "has_subtitle": bool,
    "title": str,
    "rows": [
        {
            "index": int,              # global sub_idx (นับทั้ง main + insert)
            "footage_raw": str,
            "footage_display": str,    # display name จาก richLink title หรือ hyperlink text
            "footage_type": str,       # "drive"|"social"|"getty"|"reuters"|"image"|"other"|"none"
            "file_id": str | None,     # Drive file_id
            "tc_in": float | None,     # วินาที
            "tc_out": float | None,
            "bullets": [str, ...],     # subtitle text (ซอยแล้ว ≤ _SOT_MAX_CHARS=40)
            "sot": bool,               # True ถ้ามี "ปล่อยเสียง"
            "is_insert": bool,
            "inherited_footage": bool,
        },
        ...
    ]
}
```

### `_cell_footage_list(cell)` → `list[(value, display)]`

1 paragraph = 1 footage:
- **richLink** (Google Smart Chip) → uri + title
- **textRun + hyperlink** → url + display text
- **plain text** → URL ดิบ / Getty code / Reuters code / "ปล่อยเสียง"
- กรอง homepage/เครดิตออกด้วย `_is_footage_url()` per-domain

### `_is_footage_url(url)` — per-domain path validation

| Domain | เงื่อนไข |
|--------|----------|
| drive.google.com | `/file/`, `/folders/`, `/open?`, `id=` |
| facebook.com / fb.watch | `/videos/`, `/watch/`, `/reel/`, `/posts/`, `/story/` |
| instagram.com | `/p/`, `/reel/`, `/tv/` |
| tiktok.com | `/video/` |
| x.com / twitter.com | `/status/` |
| youtube.com | `watch?`, `/shorts/`, `/live/`, `/embed/`, `list=` |
| youtu.be | path ยาวกว่า 4 chars |
| gettyimages.* / reutersconnect.com | ผ่านทั้งหมด |

---

## Subtitle Processing

### `_split_sot_sentences(text)` — ลำดับการแบ่ง

1. `\n` split
2. `_word_sent_split()` — `word_tokenize` + particle (`ครับ/ค่ะ/นะครับ`) + conjunction (`ซึ่ง/แต่/เพราะ`) — min 15 chars ก่อนตัด
3. `_split_at_thai_clauses()` — regex clause boundary (`_THAI_CLAUSE_RE`)
4. English punctuation (`.!?`)
5. `_chunk_by_words()` — word-boundary chunk ถ้ายังยาว > 40 chars

### `_merge_short_blocks(parts)` — ป้องกัน orphan blocks

```python
_MIN_BLOCK_CHARS = 10
```
block ที่สั้นกว่า 10 chars → merge เข้า block ก่อนหน้า
ป้องกัน "กว่านี้", "นั้น" ลอยโดดๆ

---

## SRT Generator (`build_srt`)

- **VO rows** (sot=False): reading speed ~16 chars/sec, min 1.0 วิ
- **SOT rows** (sot=True + TC): ใช้ Whisper → Gemini timestamps (ดูหัวข้อ SOT Timing)
- Gap ระหว่าง block: `GAP_SEC = 3/25 = 0.120s`
- Line break (แนวตั้ง): `MAX_CHARS_VERTICAL = 26` — หา word boundary ใกล้กึ่งกลาง (PyThaiNLP)
- Output: CRLF (`\r\n`) ตาม SRT spec

---

## SOT Timing Pipeline

### ขั้นตอนหลัก (เรียงตาม priority)

```
1. MLX Whisper (word_timestamps=True)
      ↓ words [{w, s, e}] + seg_events
2a. Gemini word-align (_align_via_gemini_words)
      ↓ map Thai sub → word index range
2b. Gemini segment-align (_align_via_gemini_text) [fallback ถ้าไม่มี word text]
      ↓ map Thai sub → segment timestamps
3.  char-proportional fallback (ข้ามช่วงเงียบ)
4.  file_dur fallback (ถ้าไม่มี Whisper)
```

### `_whisper_sot_words(audio_path)` → `(words_w, speech_ev, clean_segs)`

- `words_w`: `[{w, s, e}]` — สำหรับ Gemini word-align
- `speech_ev`: `[(s, e)]` — สำหรับ char-proportional fallback
- `clean_segs`: `[{s, e, t}]` — segment-level สำหรับ Gemini segment-align

### `_align_via_gemini_words(words, sentences)` — word-level

```
Prompt: words JSON [{w,s,e}] + Thai subs
Response: [{"idx":1,"wstart":0,"wend":4}, ...]
```
map Thai sub → word index range → timestamp จากตัวคำจริง

### `_align_via_gemini_text(segs, sentences)` — segment-level

```
Prompt: segments JSON [{s,e,t}] + Thai subs
Response: [{"idx":1,"start":0.0,"end":3.5}, ...]
```
ใช้เป็น fallback เมื่อไม่มี word timestamps

### Batch pattern (ประหยัด RPM)

```python
# Phase 1: Whisper per row (ต้องใช้ local file)
_do_cut_and_sot(...) → row["_sot_whisper"] = {words, events, segs}

# Phase 2: Gemini batch (1 call ต่อ run → แต่ยังแยก call ต่อ row ด้วย _batch_sot_gemini)
_sot_pending = [rows ที่มี _sot_whisper]
_batch_sot_gemini(_sot_pending, log)

# Phase 3: build SRT
_save_srt()
```

### `_extract_json_array(text)` — bracket-depth parser

ป้องกัน non-greedy regex `\[.*?\]` หยุดที่ `]` แรกใน nested array
track depth → คืน outermost array เสมอ

### Gemini Models

**SOT Audio Timing** (`_SOT_MODELS`):
```python
("gemini-2.5-flash",      "v1beta")
("gemini-2.5-flash-lite", "v1beta")
("gemini-2.0-flash-lite", "v1beta")
("gemini-1.5-flash-latest","v1")       # legacy fallback
```

**Text Alignment** (`_TEXT_ALIGN_MODELS`):
```python
("gemini-3.1-flash-lite", "v1beta")   # primary — text-only, RPD สูง
("gemini-2.5-flash-lite", "v1beta")
("gemini-2.0-flash-lite", "v1beta")
("gemini-2.5-flash",      "v1beta")
```

**Key rotation:**
- 503 → retry same key
- 429/RESOURCE_EXHAUSTED → rotate key (`_gemini_key_idx[0]`)
- `http_options` ต้องใส่แค่ `{"api_version": api_ver}` — ห้ามใส่ `timeout` (SDK แปลงเป็น 1s gRPC deadline)

---

## Download Engine

### Drive (`download_drive_file`)
- `MediaIoBaseDownload` → บันทึกใน `Raw Footages/Drive/`
- รองรับ Drive Folder: list ไฟล์ข้างใน — ถ้ามีหลายไฟล์ → `folder_conflict` warning
- **Cache check**: `_find_cached_file(folder, drive_name)` — เปรียบเทียบ stem (lowercase + sanitize)

### Social (`download_social`)
- yt-dlp, format: `bestvideo[ext=mp4][vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]`
- fallback: non-av01 mp4 / best mp4
- บันทึก `%(title).40s_{source_tag}.ext` ใน `Raw Footages/Social/` หรือ `Others/`

### Image (`download_image_url`)
- `requests.get` → บันทึกใน `Raw Footages/Images/`

### Stock (Getty/Reuters) — 2 phases

**Phase 1 (Pre-run): `_prewd_scan()`**
- สแกน Watch Folder ทันทีทุก 2 วิ (autorefresh)
- คืน `{search_code: filename | None}`
- แสดงใน UI ก่อน Run — toggle 🐕 Watchdog ขวาสุด
- พอครบทุก code → "✅ ครบแล้ว — พร้อม Run PyCUT"

**Phase 2 (Post-run): `watchdog_loop()`**
- thread loop สแกนทุก 2 วิ → match code → copy Raw → cut → update status_ref
- `stock_pending = {code: [{row_key, cut_idx, tc_in, tc_out, ...}]}`

**`_extract_stock_code(raw, type)`:**
- Reuters: strip `RW/RC` prefix → ดึง numeric part → `re.search(r'RW|RC([0-9]{6,})')`
- Getty: ดึง code ท้าย URL / ใช้ตัวเลข 7-12 หลักตรงๆ
- **display_code** (RWxxxxxxxx) ใช้ใน URL เพิ่ม Tab, **search_code** (numeric) ใช้ match ชื่อไฟล์

---

## Footage Pipeline (`run_pycut`)

### Folder Structure

```
Output Folder/
├── Raw Footages/
│   ├── Drive/
│   ├── Social/
│   ├── Others/
│   ├── Getty/
│   ├── Reuters/
│   └── Images/
├── Cut Footages/         ← main footage ที่ตัด TC (prefix 01_ 02_...)
├── Insert Footages/      ← insert footage (ไม่ตัด TC, ไม่มีเลข)
└── {title}.srt
```

### Main Footage Numbering

`main_idx` — counter เฉพาะ row ที่ `footage_type != "none"` และ `is_insert == False`
prefix ชื่อไฟล์: `{main_idx:02d}_{original_stem}.mp4`

### TC Cut (`cut_video`)

- ขั้น 1: re-encode `libx264 crf=18 preset=ultrafast aac`
- ขั้น 2 fallback: `-c copy`
- Pad (checkbox): `+1.0s` ก่อน tc_in และหลัง tc_out
- Unique output: `_unique_cut_path()` → `_01`, `_02` ถ้าซ้ำ

### `do_srt` guard

ถ้าไม่ติ๊ก "สร้าง SRT" → `do_srt=False` → ข้าม Whisper และ Gemini ทั้งหมด
ส่งต่อไปทุก function ที่ทำ SOT timing: `_do_cut_and_sot`, `watchdog_loop`, `_save_srt`

---

## UI Structure

### Pre-run (หลัง อ่าน Doc)

1. Stat cards — ทั้งหมด / ✅ / ⏳ Stock / ❌
2. Preview Table — footage + TC + SUB + status icon
3. Insert Footages section (ถ้ามี)
4. **📦 Stock Footage section** (ถ้ามี Getty/Reuters):
   - Toggle 🐕 Watchdog ขวาสุด (`st.columns([8,1])`) — สแกนทุก 2 วิ
   - 2 column cards (Getty / Reuters): header card + `st.code()` โค้ดที่ยังไม่เจอ + `make_open_ci_button()`
   - พอเจอไฟล์ → แสดง ✅ ชื่อไฟล์สีเขียว + code หายออกจาก st.code()
   - Badge: "X ต้องโหลด" (แดง) / "✅ ครบแล้ว" (เขียว)
5. ▶️ Run PyCUT

### Post-run (ผลลัพธ์ section)

- Progress bar — cap 90% ขณะ `pycut_running=True`, 100% เมื่อ done
- Status text สีตาม prefix (✅=เขียว, 🐕=เหลือง, อื่น=เทา)
- Folder conflict warning (ถ้ามี)
- In-run watchdog control (ถ้ามี stock pending): status + 🐕 Watch / ⏹ Stop
- Debug Log
- SRT Editor (editable text_area + ⬇️ Download + ↺ Reset)

### Sidebar

1. Doc URL + ปุ่ม "📖 อ่าน Doc"
2. Settings: สร้าง SRT / แนวตั้ง / โหลดฟุต / ตัดตาม TC / เผื่อหัวท้าย 1 วิ
3. Output Folder + Stock Watch Folder
4. ▶️ Run PyCUT / ⏹ Stop (พร้อมสถานะ)

### Autorefresh

```python
if st.session_state["pycut_running"] or st.session_state.get("pycut_prewd_on"):
    st_autorefresh(interval=2000, key="pycut_refresh")
```

---

## Session State Keys

```python
"pycut_doc_url": str
"pycut_parsed": dict
"pycut_settings": {make_srt, is_vertical, download_footage, cut_by_tc, pad_cut}
"pycut_output_folder": str
"pycut_stock_watch_folder": str
"pycut_row_status": dict        # key=str(row["index"]), value=status string
"pycut_srt_content": str        # generated SRT
"pycut_srt_editor": str         # editable version
"pycut_running": bool
"pycut_result_holder": dict     # shared dict กับ thread: srt_content,error,done,status_text,log,...
"pycut_prewd_on": bool          # pre-run watchdog toggle
"pycut_prewd_found": dict       # {search_code: filename|None} จาก _prewd_scan()
```

---

## Known Patterns / ข้อควรระวัง

| เรื่อง | วิธีที่ถูกต้อง |
|--------|----------------|
| FFmpeg binary | `_get_ffmpeg()` — detect arch ก่อน (`ffmpeg_arm64` / `ffmpeg`) |
| Thread + Streamlit | ห้ามแตะ `st.session_state` ใน thread — ใช้ `result_holder` dict แทน |
| autorefresh | `st_autorefresh(interval=2000)` ทั้งเมื่อ running และ prewd_on |
| status_ref key | ใช้ `str(row["index"])` เป็น key เสมอ |
| main_idx vs row["index"] | `main_idx` ใช้ prefix ชื่อไฟล์เท่านั้น — `row["index"]` ใช้ lookup status_ref |
| Insert rows | ข้าม main loop — ประมวลผลใน insert block แยกหลัง `_save_srt()` |
| Cache check | เปรียบเทียบ filename stem เท่านั้น — ไม่ดู path เต็ม |
| SRT newline | ใช้ CRLF (`\r\n`) ตาม spec |
| Gemini http_options | ใส่แค่ `{"api_version": api_ver}` — ห้ามใส่ `timeout` (SDK แปลงเป็น 1s gRPC deadline) |
| Reuters URL | ใช้ `display_code` (RWxxxxxxxx) — ไม่ใช่ `search_code` (ตัวเลขอย่างเดียว) |
| _extract_json_array | ใช้ bracket-depth tracker แทน regex `\[.*?\]` ทุกกรณี |
| do_srt=False | ข้ามทุกอย่าง: Whisper, Gemini, _save_srt — ไม่แค่ build_srt |
| prewd_scan | สแกนซ้ำทุก rerun ขณะ prewd_on=True — result เก็บใน `pycut_prewd_found` |
| progress bar cap | `min(done/total, 0.9)` ขณะ running → 100% เมื่อ running=False |

---

*PYCUT_CLAUDE.md — อัปเดต 28 พ.ค. 2569*
