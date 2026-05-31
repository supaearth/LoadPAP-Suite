# LoadPAP Suite Function Inventory — 2026-05-30

This inventory was regenerated from the current worktree during the `/grill-with-docs` audit. Python syntax verification passed with:

```bash
python3 -m py_compile 0_Main.py Setup.py start.py utils.py pages/*.py
```

Python AST inventory found **192** Python functions/methods. The Getty userscript was also included because it is executable code in this repo.

## Python Files

### `0_Main.py`

- 0 Python functions. This file is Streamlit top-level UI code.

### `Setup.py`

- `32` `ok`
- `33` `warn`
- `34` `err`
- `35` `info`
- `36` `header`
- `65` `check_git`
- `81` `check_python`
- `93` `check_credentials`
- `107` `create_config`
- `124` `setup_venv`
- `157` `create_start_command`
- `283` `print_summary`

### `utils.py`

- `46` `get_token_file`
- `53` `get_active_account_index`
- `58` `set_active_account`
- `67` `get_g_creds`
- `110` `_open_chrome_delayed`
- `130` `add_account`
- `146` `_open_chrome`
- `162` `remove_account`
- `181` `get_all_accounts_info`
- `219` `get_all_drive_services`
- `234` `_get_service`
- `246` `get_docs_service`
- `249` `get_drive_service`
- `252` `get_sheets_service`
- `255` `get_g_services`
- `260` `get_logged_in_email`
- `281` `logout_google`
- `301` `extract_id`
- `313` `sanitize_filename`
- `321` `select_folder_mac`
- `336` `load_config`
- `346` `save_config`
- `359` `inject_global_css`

### `start.py`

- 0 Python functions. This file is top-level launcher code.

### `pages/1_PyLOAD_V3.0.py`

- `31` `init_session_state`
- `71` `make_open_ci_button`
- `140` `display_social_link`
- `158` `build_local_index`
- `172` `find_local_file`
- `181` `find_in_index`
- `190` `batch_search_drive`
- `206` `search_chunk`
- `238` `search_file_in_drive`
- `245` `extract_handle_from_url`
- `265` `_download_drive_file`
- `289` `_run_parallel_drive_downloads`
- `300` `_resolve`
- `419` `get_source_tag`
- `431` `get_ai_caption`
- `454` `download_worker`
- `560` `__init__`
- `561` `debug`
- `562` `warning`
- `563` `error`
- `649` `save_run_history`
- `695` `update_doc`
- `696` `update_ptype`
- `697` `update_ep`
- `771` `_prog`
- `852` `classify_url`
- `983` `_search_local_all`
- `1036` `get_dest`
- `1152` `_s`
- `1185` `_found_html`
- `1301` `get_pending`
- `1375` `_img_src`

### `pages/2_PyRUSH_V3.0.py`

- `37` `_get_ffmpeg`
- `52` `parse_sheet_time`
- `69` `update_sheet_status_by_name`
- `92` `read_sheet_data`
- `97` `read_sheet_data_with_links`
- `117` `force_open_tab`
- `121` `get_bad_segments`
- `122` `_detect`
- `146` `run_ffmpeg_process`
- `190` `run_ffmpeg_multi_trim`
- `195` `_trim_part`
- `244` `batch_scan_drive`
- `266` `scan_file_location`
- `290` `download_from_drive`
- `320` `_output_exists`
- `329` `check_status`
- `744` `_make_row`

### `pages/3_PyLOG_V3.0.py`

- `21` `analyze_video_with_gemini`

### `pages/4_PyLIVE_Test1.0.py`

- `97` `_find_bin`
- `112` `_ff`
- `124` `_ffp`
- `133` `_get_ffmpeg_exe`
- `160` `probe_video`
- `181` `get_duration`
- `194` `clock_to_sec`
- `198` `hhmm_to_sec`
- `202` `clock_to_sec_safe`
- `209` `parse_brief`
- `256` `compute_timestamps`
- `273` `get_stream_info`
- `274` `_info`
- `314` `_extract_frame`
- `320` `_crop_clock_region`
- `334` `_ocr_tesseract`
- `344` `_ocr_gemini`
- `371` `_try_ocr_at`
- `384` `_find_clock_appearance`
- `386` `_info`
- `405` `_ocr_calibrate`
- `413` `_info`
- `442` `calibrate`
- `445` `_info`
- `490` `_download_probe_clip`
- `508` `_get_stream_url_and_dvr`
- `521` `_grab_live_tail`
- `535` `quick_clock_check`
- `542` `_info`
- `571` `download_segment`
- `589` `concat_segments`
- `629` `run_pipeline`
- `709` `_read_doc_text`
- `771` `_extract_all_urls_from_para`
- `794` `_tc_to_sec_local`
- `806` `_tc_format`
- `809` `_sec_to_display`
- `813` `parse_doc_brief`
- `888` `_search_drive_by_name`
- `890` `_info`
- `913` `_get_drive_file_info`
- `923` `_download_drive_file`
- `929` `_info`
- `958` `_ffmpeg_cut`
- `973` `_cleanup_cache`
- `987` `_get_cached_video`
- `995` `_cache_path_for`
- `1001` `run_local_pipeline`
- `1145` `_prog`
- `1413` `_yt_log`
- `1638` `_rec_log`
- `1660` `_dl_progress`

### `pages/5_PyCUT_BetaV1.0.py`

- `42` `_get_ffmpeg`
- `77` `_init`
- `129` `_gemini_client`
- `139` `_gemini_keys`
- `160` `parse_tc`
- `185` `detect_footage_type`
- `207` `_cell_text`
- `221` `_is_footage_url`
- `269` `_cell_footage_list`
- `322` `_cell_bullets`
- `347` `_split_at_thai_clauses`
- `351` `_mark`
- `360` `_chunk_by_words`
- `402` `_process_sot_lines`
- `425` `_word_sent_split`
- `461` `_merge_short_blocks`
- `482` `_split_sot_sentences`
- `516` `parse_pycut_doc`
- `683` `_srt_ts`
- `691` `_calc_duration`
- `696` `_split_line`
- `741` `build_srt`
- `815` `get_source_tag`
- `827` `download_social`
- `835` `_progress_hook`
- `880` `download_image_url`
- `923` `_download_single_file`
- `946` `_find_cached_file`
- `962` `download_drive_file`
- `963` `_log`
- `1021` `_unique_cut_path`
- `1032` `cut_video`
- `1033` `_log`
- `1086` `_extract_audio_clip`
- `1108` `_get_audio_duration`
- `1123` `_extract_json_array`
- `1149` `_align_via_gemini_words`
- `1225` `_align_via_gemini_text`
- `1310` `_analyze_sot_timing_whisper`
- `1332` `_char_proportional`
- `1338` `pos_to_time`
- `1444` `_analyze_sot_timing`
- `1521` `_do_cut_and_sot`
- `1582` `_prewd_scan`
- `1604` `_extract_stock_code`
- `1631` `make_open_ci_button`
- `1669` `watchdog_loop`
- `1822` `_whisper_sot_words`
- `1884` `_batch_sot_gemini`
- `1977` `_batch_sot_fallback`
- `1992` `_p2t`
- `2012` `run_pycut`
- `2021` `_set_status`
- `2045` `_save_srt`
- `2669` `_render_stock_col`

## Userscript Functions

`จ่าไว - Ja.W.A.I. V28-28.0.user.js` contains these executable helpers and handlers:

- `clearHighlights`
- `forceFocusReset`
- `setNativeValue`
- `findNoteField`
- `selectResolution`
- `toggleMode`
- `saveData`
- `getID`
- `runLoad`
- Inline drag, toggle, click, and hotkey handlers for `onmousedown`, `onmousemove`, `onmouseup`, `onclick`, and `keydown`.
