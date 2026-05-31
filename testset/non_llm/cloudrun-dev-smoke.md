# Cloud Run DEV Non-LLM Smoke Testset

Target: `dev-53023-loadpap-suite`

LLM calls: `0`

## Required Checks

1. Cloud Run Streamlit health endpoint returns `ok`.
2. Root route returns HTTP 200 and HTML.
3. Main Streamlit shell renders at desktop, tablet, and mobile widths without console errors that stop page execution.
4. These Streamlit page routes are reachable without a server error:
   - Main
   - PyLOAD
   - PyRUSH
   - PyLOG
   - PyLIVE
   - PyCUT
5. Sensitive local files remain excluded from deployed source:
   - `credentials.json`
   - `token.pickle`
   - `token_*.pickle`
   - `vmaster_config.json`
6. Do not perform OAuth login, Google Drive/Docs/Sheets actions, file uploads, local folder picker actions, external downloads, or Gemini calls during unattended smoke.
