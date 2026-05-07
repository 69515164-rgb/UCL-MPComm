#!/usr/bin/env bash
# Run the minimal demo as INITIATOR. Override env vars as needed.
set -euo pipefail
DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

LOCAL_IP=${LOCAL_IP:-127.0.0.1}
TARGET_HOST_ID=${TARGET_HOST_ID:-127.0.0.1:12345}
TARGET_IP=${TARGET_IP:-127.0.0.1}
TARGET_PORT=${TARGET_PORT:-12345}
ROLE_IMPL=${ROLE_IMPL:-cpp}   # cpp | py

ARGS=(initiator "${LOCAL_IP}:0" "${TARGET_HOST_ID}" "${TARGET_IP}" "${TARGET_PORT}")

if [[ "${ROLE_IMPL}" == "py" ]]; then
    exec python3 "${DIR}/hello_mpcomm.py" "${ARGS[@]}"
else
    exec "${DIR}/build/hello_mpcomm" "${ARGS[@]}"
fi
