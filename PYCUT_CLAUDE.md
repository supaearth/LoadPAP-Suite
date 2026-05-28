# PYCUT_CLAUDE.md

Context file สำหรับ Claude Code — อ่านไฟล์นี้ก่อนแตะ PyCUT ทุกครั้ง

---

## ภาพรวม

**PyCUT** คือ tool ใน LoadPAP Suite สำหรับทีมวิดีโอ
รับ Google Doc สคริปต์ → สร้าง `.srt` subtitle + โหลดและตัดฟุตเทจตาม Timecode อัตโนมัติ
ออกแบบสำหรับคลิปแนวตั้ง (vertical) รองรับทั้ง VO และ SOT

**ไฟล์หลัก:** `pages/5_PyCUT_BetaV1.0.py`

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
            "footage_type": str,       # "drive" | "social" | "getty" | "reuters" | "image" | "other" | "none"
            "file_id": str | None,     # Drive file_id
            "tc_in": float | None,     # วินาที
            "tc_out": float | None,
            "bullets": [str, ...],     # subtitle text (ซอยแล้ว ≤ _SOT_MAX_CHARS)
            "sot": bool,               # True ถ้ามี "ปล่อยเสียง"
            "is_insert": bool,         # True ถ้ามาจาก Insert column
            "inherited_footage": bool, # True ถ้า inherit จาก row ก่อนหน้า
        },
        ...
    ]
}
```

### `_cell_footage_list(cell)` → `list[(value, display)]`

ดึงเฉพาะ footage จริงจาก cell — 1 paragraph = 1 footage:
- **richLink** (Google Smart Chip) → uri + title
- **textRun + hyperlink** → url + display text
- **plain text** → URL ดิบ / Getty code / Reuters code / "ปล่อยเสียง"
- กรอง homepage/เครดิตออกด้วย `_is_footage_url()`

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

ป้องกัน auto-link ที่ Google Docs สร้างเอง เช่น `facebook.com/m`

### Row parsing rules

- **Skip empty rows**: ไม่มี footage + TC + bullets + insert footage → ข้าม
- **Inherit footage**: row ที่มี TC แต่ไม่มี footage → ใช้ footage จาก `last_footage`
- **SOT marker**: "ปล่อยเสียง" ใน footage cell → `sot=True`, กรองออกจาก footage list
- **Insert column**: `_cell_footage_list(cells[insert_col_idx])` → สร้าง row แยกพร้อม `is_insert=True`, `tc_in=None`, `tc_out=None`
- **Bullet splitting**: ซอยทุก bullet ≤ `_SOT_MAX_CHARS` (40) ด้วย `_split_sot_sentences()`

---

## SRT Generator (`build_srt`)

- **VO rows** (sot=False): reading speed ~16 chars/sec, min 1.0 วิ
- **SOT rows** (sot=True + TC): แบ่ง clip duration เท่ากัน หรือใช้ Gemini/Whisper timestamps
- Gap ระหว่าง block: `GAP_SEC = 3/25 = 0.120s`
- Line break (แนวตั้ง): ถ้า len > 18 chars → หา word boundary ใกล้กึ่งกลาง (PyThaiNLP, ไม่ใช้ Gemini)
- Output: CRLF (`\r\n`) ตาม SRT spec

### SOT Timing

ลำดับ priority:
1. **Whisper** (`faster-whisper` medium) — Thai speech ใช้ segment timestamps โดยตรง, non-Thai ใช้ proportional alignment
2. **Gemini Audio** — ส่ง mp3 clip → JSON array `[{idx, start, end}]`
3. **Fallback** — แบ่ง clip duration เท่ากัน

### Subtitle Splitting (`_split_sot_sentences`)

1. `\n` split
2. `word_tokenize` + particle (`ครับ/ค่ะ/นะครับ`) และ conjunction (`ซึ่ง/แต่/เพราะ`) split — min 15 chars ก่อนตัด
3. Thai clause regex (`_THAI_CLAUSE_RE`)
4. English punctuation (`.!?`)
5. Word-boundary chunk fallback

---

## Download Engine

### Drive (`download_drive_file`)
- `MediaIoBaseDownload` — บันทึกเป็นชื่อไฟล์ต้นฉบับใน `Raw Footages/Drive/`
- รองรับ Drive Folder: list ไฟล์ภายใน, ถ้ามีหลายไฟล์ → `folder_conflict` warning
- **Cache check**: `_find_cached_file(folder, drive_name)` — เปรียบเทียบ stem (lowercase + sanitize) ไม่ดู extension

### Social (`download_social`)
- yt-dlp, format: `bestvideo[ext=mp4][vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]`
- บันทึกเป็น `%(title).40s_{source_tag}.ext` ใน `Raw Footages/Social/` หรือ `Others/`

### Image (`download_image_url`)
- `requests.get` → บันทึกใน `Raw Footages/Images/`

### Stock (Getty/Reuters)
- ไม่โหลดอัตโนมัติ — รอ user วางไฟล์ใน Watch Folder
- `_extract_stock_code()`: Reuters strip `RW/RC` prefix → ดึง numeric part; Getty ดึง code ท้าย URL
- Watchdog scan ทุก 2 วิ, match ด้วย `code in fname.lower()`
- Stock raw copy ไปยัง `Raw Footages/Getty/` หรือ `Reuters/`

---

## Footage Pipeline (`run_pycut`)

### Folder Structure Output

```
Output Folder/
├── Raw Footages/
│   ├── Drive/
│   ├── Social/
│   ├── Others/
│   ├── Getty/
│   ├── Reuters/
│   └── Images/
├── Cut Footages/         ← main footage ที่ตัด TC แล้ว (มีเลข 01_ 02_...)
├── Insert Footages/      ← insert footage (ไม่ตัด TC, ไม่มีเลข)
└── {title}.srt
```

### Main Footage Numbering

`main_idx` — counter เฉพาะ row ที่ `footage_type != "none"` และ `is_insert == False`
ใช้เป็น prefix ชื่อไฟล์: `{main_idx:02d}_{original_stem}.mp4`
→ Cut Footages เรียง 01, 02, 03... ต่อเนื่อง ไม่มีช่อง

### Insert Rows

- ประมวลผลแยกหลัง main loop + `_save_srt()`
- โหลดไปยัง `Insert Footages/` ด้วย logic เดียวกับ main (Drive/social/image/stock)
- **ไม่ตัด TC**, **ไม่มีเลข prefix** — ใช้ชื่อไฟล์ต้นฉบับ
- Stock insert ใน watchdog: `cut_dir = info["insert_out_dir"]` (ไม่ใช่ Cut Footages)

### TC Cut (`cut_video`)

- ขั้น 1: re-encode (`libx264 crf=18 preset=ultrafast`)
- ขั้น 2 fallback: `-c copy`
- Pad (checkbox): `+1.0s` ก่อน tc_in และหลัง tc_out
- Unique output: `_unique_cut_path()` → ต่อท้าย `_01`, `_02` ถ้าชื่อซ้ำ

### FFmpeg Binary

```python
def _get_ffmpeg():
    arch = platform.machine()  # "arm64" หรือ "x86_64"
    candidates = [
        os.path.join(ROOT_DIR, f"ffmpeg_{arch}"),
        os.path.join(ROOT_DIR, "ffmpeg"),
        shutil.which("ffmpeg"),
    ]
```

---

## UI Structure

### Sidebar
1. Google Doc URL input + ปุ่ม "📖 อ่าน Doc"
2. Settings checkboxes: สร้าง SRT / แนวตั้ง / โหลดฟุต / ตัดตาม TC / เผื่อหัวท้าย 1 วิ
3. Output Folder + Stock Watch Folder (บันทึกใน `vmaster_config.json`)
4. Run / Stop button

### Main Area

**Stat cards** (นับเฉพาะ main rows):
- ทั้งหมด / ✅ เสร็จ / ⏳ รอ Stock / ❌ Error

**Preview — ตาราง footage** (เฉพาะ main rows):
- `#` column: `_ui_seq` counter (เฉพาะ rows ที่มี footage) — ตรงกับ prefix ไฟล์
- แสดง footage display name (จาก richLink title) แทน ID/URL
- Status icon: ⬜ pending / ✅ done / ⬇️ downloading / ⏳ waiting_stock / ❌ error

**📌 Insert Footages** (section แยก):
- แสดง footage + status icon
- ไม่มีเลข column

**Progress bar + status text**:
- แสดง text แทน debug log: "⬇️ #01 — กำลังโหลด (Drive)..." / "✂️ #02 — ตัด 1.0s → 32.0s"

**SRT Preview**:
- `st.text_area` แก้ไขได้ (key: `pycut_srt_editor`)
- ปุ่ม "⬇️ Download .srt" — โหลด version ที่แก้ไข
- ปุ่ม "↺ Reset" — reload จาก generated version

---

## Session State Keys

```python
"pycut_doc_url": str
"pycut_parsed": dict           # output จาก parse_pycut_doc()
"pycut_settings": {
    "make_srt": bool,
    "is_vertical": bool,
    "download_footage": bool,
    "cut_by_tc": bool,
    "pad_cut": bool,
}
"pycut_output_folder": str
"pycut_stock_watch_folder": str
"pycut_row_status": dict       # key = str(row["index"]), value = status string
"pycut_srt_content": str       # generated SRT
"pycut_srt_editor": str        # editable version ใน text_area
"pycut_running": bool
"pycut_result_holder": dict    # shared dict กับ thread: srt_content, error, done, status_text
```

---

## Gemini / Whisper

```python
_SOT_MODELS = [
    ("gemini-2.5-flash",      "v1beta"),
    ("gemini-2.5-flash-lite", "v1beta"),
    ("gemini-2.0-flash-lite", "v1beta"),
    ("gemini-1.5-flash-latest", "v1"),
]
```

- 503 → retry same key
- 429/RESOURCE_EXHAUSTED → rotate key
- Whisper: `faster-whisper` medium, device=cpu, compute_type=int8

---

## Known Patterns / ข้อควรระวัง

| เรื่อง | วิธีที่ถูกต้อง |
|--------|----------------|
| FFmpeg binary | `_get_ffmpeg()` — detect arch ก่อน |
| Thread + Streamlit | ห้ามแตะ `st.session_state` ใน thread — ใช้ `result_holder` dict แทน |
| autorefresh | `st_autorefresh(interval=2000)` เฉพาะตอน `pycut_running == True` |
| status_ref key | ใช้ `str(row["index"])` เป็น key เสมอ |
| main_idx vs row["index"] | `main_idx` ใช้ prefix ชื่อไฟล์เท่านั้น — `row["index"]` ใช้ lookup status_ref |
| Insert rows | ข้าม main loop ทั้งหมด — ประมวลผลใน insert block แยกหลัง `_save_srt()` |
| Cache check | เปรียบเทียบ filename stem เท่านั้น — ไม่ดู path เต็ม |
| SRT newline | ใช้ CRLF (`\r\n`) ตาม spec |

---

*PYCUT_CLAUDE.md — อัปเดต 27 พ.ค. 2569*
