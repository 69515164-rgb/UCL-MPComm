#!/bin/bash
# =============================================================================
# MPComm Multi-Node Common Utilities
#
# Shared functions and configuration for deploy_all.sh and multi_node_test.sh.
# Source this file from other scripts: source "$(dirname "$0")/common.sh"
# =============================================================================

# ---- Default Configuration ----
# These can be overridden by the sourcing script before calling parse_hosts()
HOSTS_FILE="${HOSTS_FILE:-${SCRIPT_DIR:-.}/hosts.txt}"
BINARY_PATH="${BINARY_PATH:-./build/scatter_test}"
DEPLOY_URL="${DEPLOY_URL:-https://mirrors.tencent.com/repository/generic/mpcomm/utils/deploy_mpcomm.sh}"
DEPLOY_TESTS_URL="${DEPLOY_TESTS_URL:-https://mirrors.tencent.com/repository/generic/mpcomm/utils/deploy_tests.sh}"
TESTS_INSTALL_DIR="${TESTS_INSTALL_DIR:-/opt/mpcomm_tests}"
SSH_USER="${SSH_USER:-root}"
SSH_PORT="${SSH_PORT:-36001}"
SSH_OPTS="${SSH_OPTS:--o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes -o LogLevel=ERROR}"
VERBOSE="${VERBOSE:-false}"
DRY_RUN="${DRY_RUN:-false}"

# ---- Color Output ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $*"; }
log_debug() { if $VERBOSE; then echo -e "${CYAN}[DEBUG]${NC} $*"; fi; }

# ---- Build SSH Command Prefix ----
ssh_cmd() {
    local host="$1"
    local cmd="ssh ${SSH_OPTS} -p ${SSH_PORT}"
    if [ -n "$SSH_USER" ]; then
        cmd+=" ${SSH_USER}@${host}"
    else
        cmd+=" ${host}"
    fi
    echo "$cmd"
}

# ---- Read Hosts File ----
# Populates: INITIATOR_IP, INITIATOR_PORT, INITIATOR_NUMAS,
#             TARGET_IPS[], TARGET_PORTS[], TARGET_NUMA_LIST[], NUM_TARGETS
parse_hosts() {
    local hosts_file="${1:-$HOSTS_FILE}"

    if [ ! -f "$hosts_file" ]; then
        log_error "Hosts file not found: $hosts_file"
        exit 1
    fi

    INITIATOR_IP=""
    INITIATOR_PORT=""
    INITIATOR_NUMAS=""
    declare -g -a TARGET_IPS=()
    declare -g -a TARGET_PORTS=()
    declare -g -a TARGET_NUMA_LIST=()

    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip comments and empty lines
        line=$(echo "$line" | sed 's/#.*//' | xargs)
        [ -z "$line" ] && continue

        # Parse: IP  PORT  NUMAS
        read -r ip port numas <<< "$line"
        port="${port:-12345}"
        numas="${numas:-0}"

        if [ -z "$INITIATOR_IP" ]; then
            INITIATOR_IP="$ip"
            INITIATOR_PORT="$port"
            INITIATOR_NUMAS="$numas"
        else
            TARGET_IPS+=("$ip")
            TARGET_PORTS+=("$port")
            TARGET_NUMA_LIST+=("$numas")
        fi
    done < "$hosts_file"

    NUM_TARGETS=${#TARGET_IPS[@]}

    if [ "$NUM_TARGETS" -eq 0 ]; then
        log_error "No target hosts found in $hosts_file (need at least 2 lines: 1 initiator + 1 target)"
        exit 1
    fi
}

# ---- Verify SSH Connectivity ----
# Sets SSH_VERIFIED=true on success
verify_ssh() {
    log_step "Verifying SSH connectivity to all targets..."

    ALL_REACHABLE=true
    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        ip="${TARGET_IPS[$i]}"
        if $DRY_RUN; then
            log_debug "  Would check: $(ssh_cmd "$ip") 'echo ok'"
            continue
        fi
        if $(ssh_cmd "$ip") "echo ok" &>/dev/null; then
            log_info "  [$i] $ip - OK"
        else
            log_error "  [$i] $ip - FAILED"
            ALL_REACHABLE=false
        fi
    done

    if ! $ALL_REACHABLE && ! $DRY_RUN; then
        log_error "Some targets are unreachable. Aborting."
        exit 1
    fi
    SSH_VERIFIED=true
    log_info "All targets reachable."
    echo ""
}

# ---- Deploy tests on a remote machine via deploy_tests.sh ----
# Usage: remote_deploy_tests <ip> [label]
# Returns 0 on success, 1 on failure
# Sets BUILT_BINARY_PATH and BUILT_TESTS_DIR on success
remote_deploy_tests() {
    local ip="$1"
    local label="${2:-$ip}"
    local install_dir="$TESTS_INSTALL_DIR"

    log_info "  $label - deploying tests via deploy_tests.sh..."
    local deploy_output deploy_ok=false
    deploy_output=$($(ssh_cmd "$ip") "wget -qO- '${DEPLOY_TESTS_URL}' | bash -s -- --install-dir=${install_dir}" 2>&1) && deploy_ok=true

    if $deploy_ok && $(ssh_cmd "$ip") "test -x '${install_dir}/build/scatter_test'" &>/dev/null; then
        BUILT_BINARY_PATH="${install_dir}/build/scatter_test"
        BUILT_TESTS_DIR="$install_dir"
        log_info "  $label - deployed successfully: $BUILT_BINARY_PATH"
        return 0
    else
        log_error "  $label - deploy_tests FAILED"
        if [ -n "${deploy_output:-}" ]; then
            log_error "  Output (last 20 lines):"
            echo "$deploy_output" | tail -20
        fi
        return 1
    fi
}

# ---- Deploy tests locally via deploy_tests.sh ----
# Returns 0 on success, 1 on failure
# Sets BUILT_BINARY_PATH and BUILT_TESTS_DIR on success
local_deploy_tests() {
    local install_dir="$TESTS_INSTALL_DIR"

    log_info "Deploying tests locally via deploy_tests.sh..."
    local deploy_output deploy_ok=false
    deploy_output=$(wget -qO- "${DEPLOY_TESTS_URL}" | bash -s -- --install-dir="${install_dir}" 2>&1) && deploy_ok=true

    if $deploy_ok && [ -x "${install_dir}/build/scatter_test" ]; then
        BUILT_BINARY_PATH="${install_dir}/build/scatter_test"
        BUILT_TESTS_DIR="$install_dir"
        log_info "Local tests deployed successfully: $BUILT_BINARY_PATH"
        return 0
    else
        log_error "Local deploy_tests failed."
        if [ -n "${deploy_output:-}" ]; then
            log_error "  Output (last 20 lines):"
            echo "$deploy_output" | tail -20
        fi
        return 1
    fi
}
