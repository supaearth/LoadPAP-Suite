# LoadPAP Suite

LoadPAP Suite is a local macOS production toolset for daily broadcast video workflows. Its language centers on scripts, footage, cut lists, stock-footage handling, logging, and short-form clipping.

## Language

**LoadPAP Suite**:
The complete local Streamlit application containing the production tools below.
_Avoid_: LoadPAP Suit, LoadPAP Family when referring to this repository specifically.

**PyLOAD**:
The tool that reads a Google Doc script, extracts footage references, checks local/Drive archives, and downloads available footage into organized folders.
_Avoid_: Downloader when the specific tool name matters.

**PyRUSH**:
The tool that reads a Google Sheet cut list and cuts or copies source media into finished output files.
_Avoid_: Cutter when the specific tool name matters.

**PyLOG**:
The tool that scans a folder of video files, generates AI-assisted footage descriptions, and appends review rows to a Google Sheet.
_Avoid_: Logger when the specific tool name matters.

**PyLIVE**:
The in-development tool for extracting clips from YouTube Live/VOD sources or local REC files by matching broadcast clock or document timecodes.
_Avoid_: Treating Live-noDVR as supported without an explicit implementation note.

**PyCUT**:
The tool that reads a structured Google Doc, builds SRT subtitles, downloads or waits for footage, and cuts footage by timecode.
_Avoid_: Treating PyCUT as experimental-only; it is present in the main UI.

**Script Document**:
A Google Doc used as the source of truth for a production task. Depending on the tool, it may contain footage URLs, stock IDs, local REC source links, subtitles, or insert-footage rows.
_Avoid_: Brief when the document is the full structured source.

**Brief**:
The short text block or parsed structure containing clip title, caption, source URL, and timecode instructions for PyLIVE.
_Avoid_: Script Document when the whole Google Doc/table is meant.

**Footage**:
Any source media item needed by a production task, including video, image, social URL, Drive file, Getty ID, or Reuters ID.
_Avoid_: Asset when discussing newsroom source material.

**Stock Footage**:
Footage that cannot be fully downloaded by the app because it must be fetched manually from a stock provider such as Getty or Reuters.
_Avoid_: Drive footage, social footage.

**Local Archive**:
A local folder containing previously downloaded or reused footage that should be searched before spending stock credits or downloading again.
_Avoid_: Destination Folder.

**Source Folder**:
The folder PyRUSH watches or scans for input media that is ready to be cut.
_Avoid_: Destination Folder, Local Archive.

**Destination Folder**:
The folder where a tool writes output files for the current job.
_Avoid_: Source Folder, Watch Folder.

**Watch Folder**:
A folder watched for manually downloaded stock footage so PyRUSH or PyCUT can continue once a matching file appears.
_Avoid_: Local Archive when the folder is being actively watched for new files.

**Cut List**:
A Google Sheet table used by PyRUSH to define source IDs, output names, actions, and timecodes.
_Avoid_: Script Document.

**Timecode**:
A human-entered time reference. In PyRUSH and PyCUT, dot notation means `MM.SS` or `HH.MM.SS`; in PyLIVE YouTube mode, broadcast-clock notation means `HH.MM.SS`.
_Avoid_: Decimal seconds for dot notation unless a function explicitly says seconds.

**SOT**:
Sound-on-tape rows where subtitles should align to spoken audio timing rather than simple reading speed.
_Avoid_: VO for rows that need speech timing.

**Insert Footage**:
Supplemental footage from a dedicated insert column that should be collected separately and should not shift the main SRT timeline.
_Avoid_: Main footage row.

**Active Google Account**:
The Google OAuth account selected in the Main page and used for Docs, Drive, and Sheets calls unless a tool explicitly handles multiple accounts.
_Avoid_: Assuming all stored accounts are searched.

**Manual Calibration**:
A user-provided reference point mapping an on-screen clock value to a position in a live/DVR clip.
_Avoid_: OCR calibration when the user enters the reference manually.

## Example Dialogue

Producer: "This Script Document has Getty IDs and a Drive link. Can PyLOAD pull everything?"

Developer: "PyLOAD can pull Drive and social footage automatically, search the Local Archive first, and list Stock Footage that still needs manual download."

Producer: "The PyCUT row has SOT and an Insert Footage link."

Developer: "The SOT row affects subtitle timing for the main Cut Footages. The Insert Footage is collected separately and must not shift the SRT timeline."

Producer: "For PyLIVE, this YouTube brief uses `21.08.12`."

Developer: "In YouTube Live mode that is broadcast clock `HH.MM.SS`. In PyRUSH or PyCUT, `15.43` means `MM.SS`, not decimal seconds."
