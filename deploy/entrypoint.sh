#!/bin/sh
# Hand the data volume to the app user, then run the server without root.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown tripwire "$DATA_DIR" 2>/dev/null || echo "warning: could not chown $DATA_DIR" >&2
  exec setpriv --reuid=tripwire --regid=tripwire --init-groups \
    uvicorn api.serve:build --factory --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn api.serve:build --factory --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
