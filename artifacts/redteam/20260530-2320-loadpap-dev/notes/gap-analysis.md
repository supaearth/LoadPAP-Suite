# Red-Team Coverage Gap Analysis

## Covered Now
- Cloud Run liveness and root HTML smoke.
- Streamlit page route reachability for Main, PyLOAD, PyRUSH, PyLOG, PyLIVE, PyCUT.
- Non-authenticated, non-mutating UI load checks across responsive viewports.

## Missing / Deferred By Safety
- Google OAuth login flows, because they require user account interaction.
- File upload/download and local folder picker workflows, because unattended Cloud Run cannot access the user Mac filesystem and browser upload actions require explicit file selection.
- LLM/Gemini output quality checks, because no user-approved API keys should be used in unattended red-team.
- End-to-end Drive/Docs/Sheets calls, because credentials are intentionally excluded from Cloud Run source and Git.
