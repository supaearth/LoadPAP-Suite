# LoadPAP Suite — Project Context for Claude Code

## โปรเจคคืออะไร

**LoadPAP Suite** (Load Process Automation Pipeline) — ชุดเครื่องมือ Python/Streamlit สำหรับ automation workflow การผลิตวิดีโอ broadcast ประจำวัน ใช้งานจริงในทีมโปรดักชัน distribute ให้ Mac users ผ่าน GitHub

---

## โครงสร้างไฟล์

```
LoadPAP-Suit/
├── 0_Main.py              # Streamlit entry point + Gemini API key settings
├── 1_PyLOAD__betaV2_2.py  # PyS.A.R.N. — ดาวน์โหลดฟุตเทจจาก Google Doc script
├── 2_PyRUSH__BetaV2_2.py  # PyL.A.D. — ตัดวิดีโออัตโนมัติจาก Google Sheet cut list
├── 3_PyLOG_BetaV2_2.py    # PyJ.I.T. — log/วิเคราะห์ฟุตเทจด้วย Gemini Vision
├── 4_PyLIVE_Test1_0.py    # PyLIVE — คลิปจาก YouTube Live Stream (กำลังพัฒนา)
├── utils.py               # Shared utilities — Google OAuth, Drive/Docs/Sheets API, config
├── setup.py               # One-time setup script สำหรับ user ใหม่
├── requirements.txt       # Python dependencies
├── vmaster_config.json    # User config (ไม่อยู่ใน git)
├── credentials.json       # Google OAuth credentials (ไม่อยู่ใน git)
└── token.pickle           # Google OAuth token (ไม่อยู่ใน git)
```

---

## เครื่องมือแต่ละตัว

### PyLOAD (1_PyLOAD)
- อ่าน Google Doc script → extract URLs/IDs → auto-download footage
- stock sources (Getty ฯลฯ) require manual download แต่ collect IDs อัตโนมัติ
- search Drive archive ก่อน download เพื่อป้องกัน duplicate (ประหยัด Getty credits)
- embed credits ใน filename + organize ลงโฟลเดอร์

### PyRUSH (2_PyRUSH)
- pull cut list จาก Google Sheet
- Watchdog loop รอไฟล์ → FFmpeg cut ทันที
- rename output ตาม convention

### PyLOG (3_PyLOG)
- วิเคราะห์ footage ผ่าน Gemini Vision → เขียนผลลง Google Sheet
- keyword search + reporting
- one-file-per-rerun architecture: process 1 video → st.rerun() → real-time log update
- Pause/Resume ผ่าน `jit_status` session state

### PyLIVE (4_PyLIVE) — ยังพัฒนาอยู่
- คลิปวิดีโอจาก YouTube Live Stream
- ใช้ Gemini OCR อ่าน clock timestamp จากหน้าจอ
- decision tree: VOD / Live+DVR / Live-noDVR

---

## utils.py — Shared Core

ทุก page import จากที่นี่:

```python
from utils import get_g_services, extract_id, load_config, save_config, 
                  sanitize_filename, inject_global_css, batch_search_drive
```

**สำคัญ:**
- `ROOT_DIR` = โฟลเดอร์หลักของโปรเจค
- `load_config()` / `save_config()` → `vmaster_config.json`
- `get_g_creds()` → Google OAuth 2.0 (token cache in memory)
- `batch_search_drive()` → query Drive 20 IDs per request (quota efficient)
- `inject_global_css()` → เรียกหลัง `st.set_page_config()` ทุกหน้า

---

## Known Bugs (ยังไม่ได้แก้)

1. **PyRUSH** locally redefines `extract_id()` และ `get_folder_path()` — override utils.py imports
2. **PyLOAD** retry block เรียก `download_worker()` ด้วย 4 args แทน 5 (missing `dirs['images']`)

---

## Gemini API

ใช้ `google-genai` SDK (ไม่ใช่ deprecated `google-generativeai`):

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=key)
response = client.models.generate_content(
    model="gemini-2.0-flash-lite",
    contents=[types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"), prompt]
)
```

**Model priority สำหรับ PyLOG:**
1. `gemini-2.5-flash-preview` (primary)
2. `gemini-2.0-flash-lite`
3. `gemini-1.5-flash-8b`

**Error handling:**
- 503 → retry same key ก่อน (delay)
- 429/quota → rotate ไป key ถัดไปทันที

---

## Google APIs

- OAuth 2.0 scopes: `documents.readonly`, `drive.readonly`, `spreadsheets`
- `credentials.json` → รับจากผู้ดูแล (ไม่อยู่ใน repo)
- `token.pickle` → สร้างอัตโนมัติตอน login ครั้งแรก

---

## UI Design System

**Fonts:** IBM Plex Sans Thai (body) + IBM Plex Mono (code/labels)

**Color palette:**
```
Background:  #0d0f12 / #13161b / #1a1e26 / #222733
Text:        #e8eaf0 / #8b90a0 / #555a6a
Blue:        #4a9eff
Teal:        #2dd4a8
Orange:      #ff7a2f
Red:         #ff4d4d
Yellow:      #ffd166
```

**Font sizes:** 15px general / 14–15px buttons / h1=32px / h2=26px / h3=22px

**CSS quirks:**
- Material Icons/Symbols break under wildcard CSS — target specific selectors, exclude `.material-icons` `.material-symbols-rounded`
- `st.button` ไม่ support right-align — ใช้ `st.columns([8.5, 1])`

---

## Config keys ใน vmaster_config.json

```json
{
  "gemini_key1": "",
  "gemini_key2": "",
  "archive_url": "",
  "local_archive": "",
  "dest_folder": "",
  "p_type": "Special",
  "last_yt_dlp_update": ""
}
```

---

## Code Style & Patterns

- **Output preference:** patch-style snippets (เฉพาะส่วนที่เปลี่ยน) ไม่ rewrite ทั้งไฟล์ ยกเว้นจำเป็น
- `yt-dlp` upgrade → ทำครั้งเดียวต่อวันผ่าน session_state date check (ไม่ทำทุก rerun)
- PyLOG ใช้ one-file-per-rerun: process 1 ไฟล์ → `st.rerun()` → real-time update
- Watchdog loop ใน PyRUSH ต้องมี guard condition ป้องกัน infinite `st.rerun()` memory growth

---

## Deployment

- macOS only (ทีมใช้ Mac ทั้งหมด)
- Python 3.12 (ไม่รองรับ 3.13+)
- macOS 12 ขึ้นไป (opencv wheel requirement)
- FFmpeg ต้องติดตั้งแยก (ไม่ได้ bundle)
- `setup.py` → สร้าง venv + ติดตั้ง packages + สร้าง `START.command`
- `START.command` → git pull + pip check + เปิด Streamlit + Chrome

---

## Dependencies ที่ต้อง pin

```
opencv-python==4.8.1.78   # macOS 11 compatible
pyarrow==16.1.0            # หลีกเลี่ยง cmake build
```
