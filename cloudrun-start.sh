#!/bin/sh
set -eu

python -m streamlit run 0_Main.py \
  --server.port=8501 \
  --server.address=127.0.0.1 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false &

streamlit_pid="$!"

for _ in $(seq 1 90); do
  if ! kill -0 "$streamlit_pid" 2>/dev/null; then
    echo "Streamlit exited before nginx startup" >&2
    wait "$streamlit_pid"
    exit 1
  fi

  if python - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health", timeout=1).read()
PY
  then
    exec nginx -g 'daemon off;'
  fi

  sleep 1
done

echo "Timed out waiting for Streamlit health on 127.0.0.1:8501" >&2
exit 1
