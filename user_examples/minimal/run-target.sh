#!/usr/bin/env bash
# Run the minimal demo as TARGET. Override env vars as needed.
set -euo pipefail
DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

TARGET_IP=${TARGET_IP:-127.0.0.1}
TCP_PORT=${TCP_PORT:-12345}
ROLE_IMPL=${ROLE_IMPL:-cpp}   # cpp | py

if [[ "${ROLE_IMPL}" == "py" ]]; then
    exec python3 "${DIR}/hello_mpcomm.py" target "${TARGET_IP}:${TCP_PORT}" "${TCP_PORT}"
else
    exec "${DIR}/build/hello_mpcomm" target "${TARGET_IP}:${TCP_PORT}" "${TCP_PORT}"
fi
