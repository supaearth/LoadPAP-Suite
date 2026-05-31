# macOS Local Streamlit Distribution

LoadPAP Suite is distributed as a macOS local Streamlit app launched through a generated `START.command`, with repo-bundled FFmpeg binaries preferred before system fallbacks. This is intentional because the production team uses Macs and needs a low-friction local workflow with Google OAuth, local folders, and file-system access rather than a Cloud Run style deployment.
