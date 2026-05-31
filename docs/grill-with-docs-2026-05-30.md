# LoadPAP Suite `/grill-with-docs` Audit — 2026-05-30

User bounds:

- Maximum questions: 100.
- This pass records 86 questions.
- User pre-approved the recommended answer for every question, so each item is marked as auto-selected.
- Pause limit: 3 hours. This pass did not intentionally continue beyond that limit.
- Repo-local policy: do not push this repository unless the user explicitly asks.

Evidence regenerated from current worktree:

- `python3 -m py_compile 0_Main.py Setup.py start.py utils.py pages/*.py` passed.
- Python AST inventory found 192 Python functions/methods. See `docs/function-inventory-2026-05-30.md`.
- The Getty userscript was included because it is executable repo code.
- No live Google, Gemini, Drive, YouTube, or Getty calls were made during this audit.

## Auto-Selected Questions And Decisions

### Repository, Docs, And Setup

**Q001 — Actual file layout vs project docs**
- Evidence: `CLAUDE.md:19-31`, `AGENTS.md:19-31`, actual files under `pages/*_V3.0.py`.
- Question: Should docs keep the old beta filenames or reflect the current Streamlit `pages/` layout?
- Auto-selected answer: Reflect the current `pages/` layout and treat old beta names as stale documentation.

**Q002 — Project folder spelling**
- Evidence: `CLAUDE.md:20`, `AGENTS.md:20` say `LoadPAP-Suit/`, repo root is `LoadPAP-Suite`.
- Question: Is `LoadPAP-Suit` an intentional product spelling or a typo?
- Auto-selected answer: Treat it as a typo; canonical folder/repo name is `LoadPAP-Suite`.

**Q003 — Tool list drift**
- Evidence: `README.md:8-14` lists PyLOAD, PyRUSH, PyLOG, PyLIVE; `0_Main.py:293-365` exposes PyCUT instead of PyLIVE on the main cards while PyLIVE still exists as a page.
- Question: Which tools are officially in the suite today?
- Auto-selected answer: Canonical tool list is PyLOAD, PyRUSH, PyLOG, PyLIVE, and PyCUT; PyLIVE is still in-development, PyCUT is active enough to document.

**Q004 — Python version policy**
- Evidence: `CLAUDE.md:172` says Python 3.12 only; `README.md:26` and `Setup.py:85` allow 3.10+; `create app.sh:5` prefers 3.14 and 3.13 first.
- Question: Which Python versions should new users be told to use?
- Auto-selected answer: Standardize on Python 3.12 for supported installs; do not prefer 3.13 or 3.14 until dependency wheels are proven.

**Q005 — Dependency pin mismatch**
- Evidence: `CLAUDE.md:183-184` requires `opencv-python==4.8.1.78` and `pyarrow==16.1.0`; `requirements.txt:18` uses `opencv-python>=4.9.0` and has no `pyarrow`.
- Question: Are the pins mandatory or stale?
- Auto-selected answer: Treat the docs as the intended policy and align requirements in a follow-up, unless a current macOS 12/Python 3.12 install proof shows newer pins are safe.

**Q006 — README clone remote**
- Evidence: `README.md:40` and `README.md:46` point to `github.com/supaearth/LoadPAP-Suite`; `git remote -v` also points to `supaearth/LoadPAP-Suite`.
- Question: Should the README remote be changed to `piyalitt`?
- Auto-selected answer: No. Keep `supaearth/LoadPAP-Suite` as the canonical upstream unless the user explicitly changes repo ownership.

**Q007 — Auto-pull vs no auto-push**
- Evidence: `CLAUDE.md:9-13` and `AGENTS.md:9-13` forbid auto-push; `Setup.py:181-203` generates `START.command` that auto-fetches and fast-forward merges on launch.
- Question: Does no auto-push also mean no auto-pull?
- Auto-selected answer: No. Keep end-user auto-pull as a distribution feature, but document it separately from the agent no-push policy.

**Q008 — `Setup.py` vs `setup.py` casing**
- Evidence: actual file is `Setup.py`; `README.md:62-69` and docs mention `setup.py`.
- Question: Should install docs use the actual case?
- Auto-selected answer: Yes. Use `Setup.py` consistently or add a lowercase compatibility wrapper.

**Q009 — Legacy `start.py` launcher**
- Evidence: `start.py:1-12` runs `python3 -m streamlit` directly and opens Chrome, bypassing venv and credential checks; `Setup.py:157-278` generates the richer `START.command`.
- Question: Is `start.py` still a supported launch path?
- Auto-selected answer: Treat `START.command` as supported and mark `start.py` as legacy or remove it after checking `.app` usage.

**Q010 — `create app.sh` launcher**
- Evidence: `create app.sh:5` prefers unsupported Python versions and writes a `.app`; README does not mention this install path.
- Question: Is `.app` generation supported for production users?
- Auto-selected answer: Not currently. Deprecate or rewrite it to call the venv-backed `START.command`.

**Q011 — Bundled FFmpeg policy**
- Evidence: repo includes `ffmpeg` and `ffmpeg_x86_64`; `0_Main.py:490-492` says FFmpeg bundled; `CLAUDE.md:174` says FFmpeg must be installed separately.
- Question: Is FFmpeg bundled or external?
- Auto-selected answer: Canonical policy is bundled binary first, system FFmpeg fallback second, with external install only for missing/unsupported binaries.

**Q012 — Stale known bugs**
- Evidence: `CLAUDE.md:80-83` and `AGENTS.md:80-83` list PyRUSH local override and PyLOAD 4-arg retry bugs; current PyRUSH imports utilities at `pages/2_PyRUSH_V3.0.py:22-31`, and PyLOAD passes 5 args at `pages/1_PyLOAD_V3.0.py:1095`.
- Question: Are these still known bugs?
- Auto-selected answer: No. Reclassify as resolved/stale notes and remove from active known-bug lists.

**Q013 — Vendor/model naming in UI**
- Evidence: global instruction says do not show vendor names in UI; this repo UI intentionally shows Gemini API setup at `0_Main.py:541-555` and PyLOG/PyCUT labels.
- Question: Should this internal tool hide Gemini/Google names?
- Auto-selected answer: No. This repo is an operator tool where credential setup depends on explicit provider names; document it as a repo-specific exception.

**Q014 — `footage_history.json` tracked data**
- Evidence: `footage_history.json` is tracked and present in `rg --files`; `.gitignore` does not ignore it.
- Question: Is run history sample data or local user history?
- Auto-selected answer: Treat runtime history as local user data; ignore future `footage_history.json` updates unless it is deliberate seed/sample data.

**Q015 — Binary storage in Git**
- Evidence: `ffmpeg` and `ffmpeg_x86_64` are tracked large executable files.
- Question: Should FFmpeg binaries remain in Git?
- Auto-selected answer: Keep for now because macOS end-user setup depends on zero-install behavior; revisit only with a release-asset or installer replacement.

### Shared Core And Config

**Q016 — Config load failures**
- Evidence: `utils.py:336-344` returns `{}` on JSON read/parse errors.
- Question: Should corrupt config fail silently?
- Auto-selected answer: No. Preserve app usability but surface a visible warning and backup corrupt JSON before using defaults.

**Q017 — Config save failures**
- Evidence: `utils.py:346-352` swallows save errors.
- Question: Should settings saves fail silently?
- Auto-selected answer: No. Return success/failure or raise so pages can show a clear Thai error.

**Q018 — Config key canon**
- Evidence: `vmaster_config.template.json` includes `archive_folder/src_folder/dst_folder`; `Setup.py:52-60` includes `p_type/last_yt_dlp_update`; PyCUT stores `pycut_output_folder/pycut_stock_watch_folder`; PyLIVE reads `ffmpeg_path/ffprobe_path`.
- Question: What is the canonical config schema?
- Auto-selected answer: Use a documented superset schema and keep the template aligned with all current runtime keys.

**Q019 — OAuth token pickle**
- Evidence: `utils.py:81-95`, `utils.py:119-156` read/write `token*.pickle`; `.gitignore:7-10` ignores credentials and tokens.
- Question: Is pickle acceptable for token cache?
- Auto-selected answer: Accept for a local-only macOS desktop tool, but document the trust boundary and never sync token files.

**Q020 — Fixed OAuth ports**
- Evidence: `utils.py:108-119` uses port 8765 for account 0; `utils.py:144-155` uses `8765 + idx`.
- Question: Should OAuth handle port collisions?
- Auto-selected answer: Yes. Add collision handling or retry ports because Streamlit/local services can occupy fixed ports.

**Q021 — Account removal fallback**
- Evidence: `utils.py:170-174` sets active account to 0 after removing the active account.
- Question: What if token 0 does not exist?
- Auto-selected answer: Switch to the first remaining valid account; otherwise clear active account and show login required.

**Q022 — Folder picker prompt escaping**
- Evidence: `utils.py:321-330` interpolates `prompt_text` directly into AppleScript.
- Question: Should prompt text be escaped?
- Auto-selected answer: Yes. Escape quotes/backslashes before building AppleScript.

**Q023 — ID extraction permissiveness**
- Evidence: `utils.py:301-311` returns raw stripped input when no Google URL pattern matches.
- Question: Should every caller accept arbitrary text as an ID?
- Auto-selected answer: No. Keep generic `extract_id`, but add stricter wrappers for Google Doc, Drive file, and Drive folder contexts.

**Q024 — Unsafe HTML rendering**
- Evidence: many `st.markdown(..., unsafe_allow_html=True)` blocks inject filenames, doc text, URLs, or model output, e.g. `0_Main.py:206-240`, `pages/3_PyLOG_V3.0.py:364-370`, `pages/5_PyCUT_BetaV1.0.py:2545-2558`.
- Question: Should dynamic values be escaped before HTML rendering?
- Auto-selected answer: Yes. Escape all dynamic user/file/doc/model strings before injecting into unsafe HTML.

**Q025 — `inject_global_css` import location**
- Evidence: `utils.py:357-359` imports Streamlit near the bottom, after non-UI helpers.
- Question: Should non-UI utility imports stay independent from Streamlit?
- Auto-selected answer: Prefer moving Streamlit import inside `inject_global_css` or a UI-only module so non-UI helpers stay lighter.

### PyLOAD

**Q026 — JavaScript escaping in open-tab buttons**
- Evidence: `pages/1_PyLOAD_V3.0.py:75-80` and `97-120` interpolate URLs/project names into JS strings manually.
- Question: Should this use JSON escaping?
- Auto-selected answer: Yes. Use `json.dumps` for every JS string/array.

**Q027 — Broken inline CSS**
- Evidence: `pages/1_PyLOAD_V3.0.py:148` contains `text-decoration: none; #e8eaf0;`.
- Question: Is the missing `color:` intentional?
- Auto-selected answer: No. Change to `color:#e8eaf0;`.

**Q028 — Drive query escaping**
- Evidence: `pages/1_PyLOAD_V3.0.py:208-213` and `238-241` interpolate search codes into Drive query strings.
- Question: Should codes be escaped for Drive query syntax?
- Auto-selected answer: Yes. Escape single quotes and reject empty/invalid codes before query construction.

**Q029 — Drive search cache scope**
- Evidence: `pages/1_PyLOAD_V3.0.py:198-201` cache key is based only on codes, not active account/service set.
- Question: Should Drive search cache include account context?
- Auto-selected answer: Yes. Include active account/service identity to avoid stale cross-account results.

**Q030 — Drive folder pagination**
- Evidence: `pages/1_PyLOAD_V3.0.py:350-357` lists folder children once with no page token loop.
- Question: Should folder download support folders with more than one page of files?
- Auto-selected answer: Yes. Add pagination, even if most folders are small.

**Q031 — Folder recursion**
- Evidence: PyLOAD folder handling at `pages/1_PyLOAD_V3.0.py:350-364` is one level only.
- Question: Should Drive folders be recursive?
- Auto-selected answer: No for now. Document one-level behavior to avoid unexpectedly pulling entire folder trees.

**Q032 — SVG image handling**
- Evidence: `pages/1_PyLOAD_V3.0.py:470-510` classifies `.svg` as image, then validates via PIL, which generally cannot open SVG.
- Question: Should SVG be treated like raster images?
- Auto-selected answer: No. Either direct-save SVG without PIL captioning or exclude SVG from image validation.

**Q033 — Temp filename collision**
- Evidence: `pages/1_PyLOAD_V3.0.py:480` uses millisecond timestamp temp names in concurrent workers.
- Question: Is timestamp uniqueness enough under threads?
- Auto-selected answer: No. Use `tempfile` or UUID-based names.

**Q034 — `gallery-dl` dependency**
- Evidence: `pages/1_PyLOAD_V3.0.py:533-539` shells out to `gallery-dl`; `requirements.txt` does not include it.
- Question: Is `gallery-dl` required?
- Auto-selected answer: If this path is supported, add it to setup checks; otherwise remove the branch or show manual-download guidance.

**Q035 — Runtime `yt-dlp` upgrade**
- Evidence: `pages/1_PyLOAD_V3.0.py:962-967` calls `pip3 install --upgrade yt-dlp --break-system-packages`.
- Question: Should Streamlit runtime mutate the system Python?
- Auto-selected answer: No. Use the app venv or `sys.executable -m pip`, and gate once per day through config/session state.

**Q036 — Failed category drift**
- Evidence: `pages/1_PyLOAD_V3.0.py:34` initializes failed keys including getty/reuters; `pages/1_PyLOAD_V3.0.py:1011` resets only drive/social/others.
- Question: Which failed categories are canonical?
- Auto-selected answer: Canonicalize failed categories across init/reset/dashboard.

**Q037 — Stock archive duplicate semantics**
- Evidence: `pages/1_PyLOAD_V3.0.py:996-1005` marks local and Drive archive hits as duplicates.
- Question: Is a Drive archive hit a duplicate or an auto-download source?
- Auto-selected answer: Treat it as duplicate-for-credit accounting and auto-download source operationally; label the dashboard clearly.

**Q038 — AI caption language**
- Evidence: `pages/1_PyLOAD_V3.0.py:443` asks for English filename captions.
- Question: Should image captions be Thai-only?
- Auto-selected answer: No. Filename captions should remain short ASCII/English for file compatibility, while user-facing summaries remain Thai.

### PyRUSH

**Q039 — Timecode dot format**
- Evidence: `pages/2_PyRUSH_V3.0.py:52-67` treats `1.2` as `01:20`, not 1.2 seconds.
- Question: Is dot notation decimal seconds or `MM.SS`?
- Auto-selected answer: Dot notation is `MM.SS` or `HH.MM.SS`; document this and validate ambiguous inputs.

**Q040 — Black/white frame removal**
- Evidence: `pages/2_PyRUSH_V3.0.py:121-144`, `174-188`, `221-237` automatically remove detected black/white sections.
- Question: Should frame removal always run?
- Auto-selected answer: Make it an explicit option or at least log exactly what was removed, because fade/flash frames can be editorially meaningful.

**Q041 — FFmpeg concat list escaping**
- Evidence: `pages/2_PyRUSH_V3.0.py:216-220` writes concat file paths directly.
- Question: What if a path contains apostrophes or special chars?
- Auto-selected answer: Escape concat list paths or use a safer concat strategy.

**Q042 — Drive search pagination and escaping**
- Evidence: `pages/2_PyRUSH_V3.0.py:248-256` builds Drive query strings without escaping or pagination.
- Question: Should PyRUSH Drive search match PyLOAD hardening?
- Auto-selected answer: Yes. Share a hardened Drive query helper.

**Q043 — Local scan depth**
- Evidence: `pages/2_PyRUSH_V3.0.py:270-283` only scans top-level source/archive folders.
- Question: Should PyRUSH scan recursively like PyLOAD local archive indexing?
- Auto-selected answer: Keep top-level scanning unless user confirms nested archive workflows; recursive scans can be expensive.

**Q044 — Status lookup cost**
- Evidence: `pages/2_PyRUSH_V3.0.py:329-346` may rescan folders on every render.
- Question: Should status use cached scan results?
- Auto-selected answer: Yes. Use `found_files`/cached index for render, and refresh only on explicit scan/watchdog ticks.

**Q045 — Watchdog rerun loop**
- Evidence: `pages/2_PyRUSH_V3.0.py:903-905` unconditionally sleeps and reruns while watchdog is on.
- Question: Is this the intended guard against Streamlit memory growth?
- Auto-selected answer: No. Replace with `st_autorefresh` or a stateful poll guard so idle loops do not grow rerun pressure.

**Q046 — Sheet status matching**
- Evidence: `pages/2_PyRUSH_V3.0.py:69-89` updates status by substring match in columns A/B.
- Question: What happens when task names repeat?
- Auto-selected answer: Track the original row index from the Sheet and update that exact row.

**Q047 — Failed task key**
- Evidence: `pages/2_PyRUSH_V3.0.py:818-820`, `887-889` key failures by `task['id']`.
- Question: Should duplicate IDs fail together?
- Auto-selected answer: No. Key failures by stable row identity, not only footage ID.

**Q048 — Action vocabulary**
- Evidence: `pages/2_PyRUSH_V3.0.py:863-886` branches on substrings `none`, `auto-5s`, `multi`, `trim`.
- Question: Is the action column free text or a controlled vocabulary?
- Auto-selected answer: Treat it as a controlled vocabulary and validate unknown actions visibly before watchdog starts.

### PyLOG

**Q049 — Top-level Streamlit orchestration**
- Evidence: `pages/3_PyLOG_V3.0.py` has only `analyze_video_with_gemini`; most orchestration is top-level code.
- Question: Should PyLOG remain top-level script style?
- Auto-selected answer: Accept for now, but extract queue/state/sheet writing if adding tests or more error recovery.

**Q050 — Temp image collision and cleanup**
- Evidence: `pages/3_PyLOG_V3.0.py:25-28` uses second-level timestamp temp filenames in the current working directory.
- Question: Is this safe for multiple sessions?
- Auto-selected answer: No. Use `tempfile.TemporaryDirectory` or include PID/UUID.

**Q051 — VideoCapture cleanup**
- Evidence: `pages/3_PyLOG_V3.0.py:43-83` releases `cap` only on the successful path.
- Question: Should capture release happen on exceptions?
- Auto-selected answer: Yes. Use `finally` to release OpenCV resources.

**Q052 — Model priority drift**
- Evidence: docs list `gemini-2.5-flash-preview`, `gemini-2.0-flash-lite`, `gemini-1.5-flash-8b`; code uses `gemini-3.1-flash-lite-preview`, `gemini-2.5-flash-lite` at `pages/3_PyLOG_V3.0.py:139`.
- Question: Which PyLOG model list is canonical?
- Auto-selected answer: Code is current behavior; update docs and then decide separately whether deprecated fallback models must be removed.

**Q053 — Hardcoded Google Sheet**
- Evidence: `pages/3_PyLOG_V3.0.py:268-269` hardcodes a default worksheet URL.
- Question: Is this a production default or developer convenience?
- Auto-selected answer: Move to config/template and make the UI remember the last used Sheet.

**Q054 — Pause/resume terminology**
- Evidence: docs mention `jit_status`; code uses `is_running`, `is_paused`, `current_idx` at `pages/3_PyLOG_V3.0.py:221-231`.
- Question: Which state model should docs describe?
- Auto-selected answer: Document the current `is_running/is_paused/current_idx` model.

**Q055 — Quota rotation semantics**
- Evidence: `pages/3_PyLOG_V3.0.py:433-437` rotates keys only after the returned summary contains quota text.
- Question: Should quota be represented as structured status instead of string matching?
- Auto-selected answer: Yes. Return structured error codes from `analyze_video_with_gemini`.

### PyLIVE

**Q056 — Live-noDVR support**
- Evidence: `StreamType.LIVE_NODVR` exists at `pages/4_PyLIVE_Test1.0.py:38-41`, but `get_stream_info` assumes live streams are DVR at `296-299`.
- Question: Does PyLIVE support Live-noDVR?
- Auto-selected answer: Not yet. Mark Live-noDVR as unsupported or implement the decision branch.

**Q057 — Metadata calibration label**
- Evidence: UI maps `metadata` method at `pages/4_PyLIVE_Test1.0.py:1471`, but calibration returns only `manual` or `ocr`.
- Question: Is metadata calibration planned or stale UI?
- Auto-selected answer: Remove the stale label unless metadata calibration is implemented.

**Q058 — YouTube brief time format**
- Evidence: `parse_brief` accepts `HH.MM.SS` at `pages/4_PyLIVE_Test1.0.py:220-242`; Local REC accepts `MM.SS` and `HH.MM.SS`.
- Question: Should YouTube Live accept `MM.SS`?
- Auto-selected answer: Keep YouTube Live as wall-clock `HH.MM.SS`; document this difference because live clips reference broadcast clock time.

**Q059 — Midnight rollover**
- Evidence: `clock_to_sec_safe` at `pages/4_PyLIVE_Test1.0.py:202-207` only adjusts when segment clock is earlier than stream start by more than one hour.
- Question: Is this enough for cross-midnight broadcasts?
- Auto-selected answer: Add tests and explicit rollover handling before relying on overnight live streams.

**Q060 — DVR duration source**
- Evidence: `_get_stream_url_and_dvr` uses `info.get('duration')` at `pages/4_PyLIVE_Test1.0.py:508-519`.
- Question: Is `duration` always DVR window length for live streams?
- Auto-selected answer: Treat as heuristic; log raw yt-dlp fields and validate against live stream metadata.

**Q061 — Latest live tail semantics**
- Evidence: `_grab_live_tail` claims latest live head at `pages/4_PyLIVE_Test1.0.py:521-533`.
- Question: Does FFmpeg always capture the latest edge for all YouTube HLS URLs?
- Auto-selected answer: Do not assume. Add diagnostic logs showing actual clock/DVR position and fallback to manual calibration.

**Q062 — Concat without audio**
- Evidence: `concat_segments` fallback builds `[i:v][i:a]` for every input at `pages/4_PyLIVE_Test1.0.py:613-623`.
- Question: What if a segment has no audio?
- Auto-selected answer: Probe streams and build audio/no-audio filter graphs dynamically.

**Q063 — Google Doc source label**
- Evidence: `_read_doc_text` looks for Thai `ลิงก์คลิปต้นทาง` at `pages/4_PyLIVE_Test1.0.py:753-766`.
- Question: Should English source labels be supported?
- Auto-selected answer: Thai-only is acceptable by default, but add documented aliases only if users submit English docs.

**Q064 — Debug expanders in user UI**
- Evidence: raw doc and parsed value debug expanders at `pages/4_PyLIVE_Test1.0.py:1550-1552`, `1574-1581`.
- Question: Should debug data always be visible?
- Auto-selected answer: Hide behind a debug toggle to avoid confusing production users.

**Q065 — Cache cleanup**
- Evidence: `.gitignore:36-37` ignores `pylive_cache/`; `_cleanup_cache(days=3)` runs at `pages/4_PyLIVE_Test1.0.py:973-985`, `1067-1069`.
- Question: Is 3 days the intended retention?
- Auto-selected answer: Keep 3 days as a practical default and expose it as config only if users ask.

**Q066 — Local REC source by filename**
- Evidence: `RecBrief.filename` exists at `pages/4_PyLIVE_Test1.0.py:84-85`, but `run_local_pipeline` errors if no Drive link at `1006-1013`.
- Question: Can Local REC cut local filename sources?
- Auto-selected answer: Not currently. Remove filename fields or implement local-file resolution.

### PyCUT

**Q067 — Unused model constant**
- Evidence: `pages/5_PyCUT_BetaV1.0.py:58` defines `GEMINI_MODEL`; `rg` shows no runtime use.
- Question: Is this constant still meaningful?
- Auto-selected answer: Remove it or replace with the canonical model lists used by alignment code.

**Q068 — Legacy model fallbacks**
- Evidence: `_SOT_MODELS` includes `gemini-2.0-flash-lite` and `gemini-1.5-flash-latest` at `pages/5_PyCUT_BetaV1.0.py:147-151`; text alignment also includes `gemini-2.0-flash-lite` at `1141-1145`.
- Question: Should legacy fallbacks remain?
- Auto-selected answer: Keep as current compatibility debt for this audit, but create a follow-up to move all repo model lists to the supported 2.5+ policy.

**Q069 — Gemini client consistency**
- Evidence: `_gemini_client` chooses only one key at `pages/5_PyCUT_BetaV1.0.py:129-137`; alignment helpers rotate keys.
- Question: Should all PyCUT model calls use the same key-rotation policy?
- Auto-selected answer: Yes. Use a shared key/model runner.

**Q070 — PyCUT table detection**
- Evidence: `parse_pycut_doc` decides script table by header text containing `footages` or `sub` at `pages/5_PyCUT_BetaV1.0.py:530-540`.
- Question: Is fuzzy table detection stable enough?
- Auto-selected answer: Add header schema validation and clear Thai errors when required columns are missing.

**Q071 — Subtitle default**
- Evidence: result defaults `has_subtitle=True` at `pages/5_PyCUT_BetaV1.0.py:525`, but info table can set it false unless `subtitle` or `ซับ` appears at `555-557`.
- Question: Is missing subtitle text supposed to disable SRT?
- Auto-selected answer: Default to SRT on unless the document explicitly says no subtitle.

**Q072 — SOT marker variants**
- Evidence: `parse_pycut_doc` detects SOT only when footage cell starts with `ปล่อยเสียง` at `pages/5_PyCUT_BetaV1.0.py:594-596`.
- Question: Should `SOT`, `sound on tape`, or other labels work?
- Auto-selected answer: Thai-only default is okay, but support `SOT` as a common newsroom alias.

**Q073 — PyCUT timecode dot format**
- Evidence: `parse_tc` at `pages/5_PyCUT_BetaV1.0.py:160-180` has the same `MM.SS` behavior as PyRUSH.
- Question: Is `1.2` one minute twenty seconds?
- Auto-selected answer: Yes. Validate and display parsed seconds so users catch ambiguity.

**Q074 — Unused `client` parameter**
- Evidence: `_split_line(text, is_vertical, client)` and `build_srt(..., client)` pass a client that `_split_line` does not use.
- Question: Is AI line splitting still planned?
- Auto-selected answer: No current evidence. Remove the unused parameter unless AI splitting is reintroduced.

**Q075 — Image download validation**
- Evidence: `download_image_url` at `pages/5_PyCUT_BetaV1.0.py:880-912` checks nonzero size but not image content.
- Question: Should PyCUT validate downloaded images like PyLOAD?
- Auto-selected answer: Yes. Validate MIME/content or PIL-open raster formats.

**Q076 — Drive downloader cleanup**
- Evidence: `_download_single_file` at `pages/5_PyCUT_BetaV1.0.py:923-943` opens `io.FileIO` without a `finally` close.
- Question: Can partial files remain on chunk failure?
- Auto-selected answer: Yes. Add `try/finally`, close handles, and delete partial output on failure.

**Q077 — Folder conflict return type**
- Evidence: `download_drive_file` type hint says `str | None`, but returns a conflict dict at `pages/5_PyCUT_BetaV1.0.py:991-994`.
- Question: Should callers rely on a dict return?
- Auto-selected answer: Make the return type explicit with a small result object or typed dict.

**Q078 — Invalid TC duration**
- Evidence: `cut_video` at `pages/5_PyCUT_BetaV1.0.py:1041-1053` omits `-t` when `tc_out <= tc_in`, which can create long clips.
- Question: Should invalid ranges cut from start to EOF?
- Auto-selected answer: No. Validate `tc_out > tc_in` before invoking FFmpeg.

**Q079 — Old Gemini audio timing function**
- Evidence: `_analyze_sot_timing` at `pages/5_PyCUT_BetaV1.0.py:1444-1515` is not called by current `rg` results.
- Question: Is it dead code?
- Auto-selected answer: Treat as dead legacy code unless tests or docs prove a caller; remove after a focused cleanup.

**Q080 — Background thread state**
- Evidence: PyCUT starts background threads at `pages/5_PyCUT_BetaV1.0.py:2416-2427`, `2809-2822`, `2856-2868` and mutates shared dicts.
- Question: Is plain dict mutation sufficient across Streamlit reruns?
- Auto-selected answer: Works pragmatically today, but use a lock or queue if adding more concurrent work.

**Q081 — Watchdog completion semantics**
- Evidence: `watchdog_loop` runs until all pending stock codes are found or stopped at `pages/5_PyCUT_BetaV1.0.py:1692-1817`.
- Question: Should watchdog wait forever?
- Auto-selected answer: Keep manual stop, but add elapsed time and pending-code visibility so users know it is intentionally waiting.

**Q082 — Insert footage and SRT**
- Evidence: insert rows are filtered for watchdog SRT build at `pages/5_PyCUT_BetaV1.0.py:1803`, but `_save_srt` uses all rows at `2049`.
- Question: Should insert rows ever affect SRT timing?
- Auto-selected answer: No. Always filter insert rows out of SRT generation for consistency.

### Getty Userscript

**Q083 — Program type vocabulary**
- Evidence: userscript includes `Decoding the World` at `จ่าไว - Ja.W.A.I. V28-28.0.user.js:52`; app lists use `The World Dialogue` in PyLOAD/PyLOG and typo `Dialouge` in Main.
- Question: What is the canonical program list?
- Auto-selected answer: Use one shared program list: Global Focus, Key Messages, News Digest, The World Dialogue, Special, plus Decoding the World only if it is still active.

**Q084 — Hardcoded Getty board period**
- Evidence: userscript routes to `world jan-jun 2026` or `feature jan-jun 2026` at `จ่าไว - Ja.W.A.I. V28-28.0.user.js:241`.
- Question: Should this remain hardcoded after June 2026?
- Auto-selected answer: No. Make board period configurable or derive it from current date before July 1, 2026.

**Q085 — Getty DOM fragility**
- Evidence: userscript selectors rely on labels, text, and save/download button text at `จ่าไว - Ja.W.A.I. V28-28.0.user.js:119-172`, `244-253`.
- Question: Should failures be silent?
- Auto-selected answer: No. Add visible failure state when required controls are not found.

**Q086 — `setNativeValue` robustness**
- Evidence: `setNativeValue` assumes value descriptors exist at `จ่าไว - Ja.W.A.I. V28-28.0.user.js:109-116`.
- Question: Should descriptor absence be handled?
- Auto-selected answer: Yes. Guard descriptor access and fall back to direct `element.value = value`.

## Decisions Captured Outside This Audit

- `CONTEXT.md` records the canonical domain vocabulary used by this repo.
- `docs/adr/0001-repo-local-no-auto-push.md` records the repo-local no-push rule.
- `docs/adr/0002-macos-local-streamlit-distribution.md` records the macOS local Streamlit/START.command distribution choice.
- `docs/adr/0003-current-ai-model-fallback-debt.md` records current model fallback behavior as compatibility debt.

## Highest-Priority Follow-Ups

1. Update `CLAUDE.md`, `AGENTS.md`, and `README.md` to remove stale filenames, stale known bugs, and version/dependency conflicts.
2. Harden shared config loading/saving and unsafe HTML escaping.
3. Replace runtime system `pip3 --break-system-packages` upgrades with venv-aware update logic.
4. Fix PyRUSH/PyLOAD Drive query escaping and pagination.
5. Decide and implement the repo model policy so code and docs no longer conflict.
6. Hide debug expanders behind debug mode for production users.
7. Add focused tests for parsers/timecode conversion: PyRUSH `parse_sheet_time`, PyLIVE brief parsers, PyCUT `parse_tc`/`parse_pycut_doc`.
