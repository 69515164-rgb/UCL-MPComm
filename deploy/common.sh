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
PARALLEL_JOBS="${PARALLEL_JOBS:-20}"        # Max concurrent SSH operations across hosts
PARALLEL_LOG_DIR="${PARALLEL_LOG_DIR:-/tmp/mpcomm_parallel_$$}"

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
    log_step "Verifying SSH connectivity to all targets (parallel: $PARALLEL_JOBS)..."

    if $DRY_RUN; then
        for i in $(seq 0 $((NUM_TARGETS - 1))); do
            log_debug "  Would check: $(ssh_cmd "${TARGET_IPS[$i]}") 'echo ok'"
        done
        SSH_VERIFIED=true
        echo ""
        return 0
    fi

    # Run the verification in parallel across all targets.
    _verify_ssh_one() {
        local idx="$1"
        local ip="$2"
        if $(ssh_cmd "$ip") "echo ok" &>/dev/null; then
            return 0
        fi
        return 1
    }

    local failed_ips=()
    parallel_foreach_host _verify_ssh_one "verify_ssh" failed_ips

    if [ ${#failed_ips[@]} -gt 0 ]; then
        log_error "Some targets are unreachable:"
        for ip in "${failed_ips[@]}"; do
            log_error "  - $ip"
        done
        log_error "Aborting."
        exit 1
    fi
    SSH_VERIFIED=true
    log_info "All ${NUM_TARGETS} targets reachable."
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

# =============================================================================
# Parallel Execution Framework
# =============================================================================
#
# parallel_foreach_host <worker_fn> <task_label> <failed_ips_array_name> \
#                       [indices...]
#
# Runs <worker_fn> in the background for each target host (or a given subset
# of indices), limiting concurrency to $PARALLEL_JOBS. Each job's stdout+stderr
# is redirected to $PARALLEL_LOG_DIR/<task_label>_<ip>.log. Per-host progress
# is printed as [OK]/[FAIL] on completion. Failed IPs are appended to the
# caller-provided array variable whose name is given as the 3rd argument.
#
# <worker_fn> is called as:  worker_fn <index> <ip>
# It must return 0 on success, non-zero on failure. Its stdout/stderr is
# captured to the per-host log file. The worker can call log_*; those messages
# go to the log file (not the main console).
#
# Environment variables available to the worker (inherited):
#   All exported variables and shell functions in this file + sourcing script.
#
# Example:
#   _my_worker() { local i="$1" ip="$2"; $(ssh_cmd "$ip") "echo hi"; }
#   local failed=()
#   parallel_foreach_host _my_worker "my_task" failed
#
parallel_foreach_host() {
    local worker_fn="$1"
    local task_label="$2"
    local failed_arr_name="$3"
    shift 3

    # Determine which indices to iterate over
    local -a indices
    if [ $# -gt 0 ]; then
        indices=("$@")
    else
        local i
        for i in $(seq 0 $((NUM_TARGETS - 1))); do
            indices+=("$i")
        done
    fi

    local total=${#indices[@]}
    if [ "$total" -eq 0 ]; then
        return 0
    fi

    mkdir -p "$PARALLEL_LOG_DIR"

    # pids_by_idx[index] = pid ; ip_by_idx[index] = ip ; done_by_idx[idx] = marker file
    declare -A pids_by_idx
    declare -A ip_by_idx
    declare -A log_by_idx
    declare -A done_by_idx

    local running=0
    local success=0
    local fail=0
    local -a failed_local=()

    # Helper: wait for one job to finish (any), and update counters
    _reap_one() {
        local finished_idx=""
        local idx
        # Poll: look for the first "done" marker file written by a worker
        while true; do
            for idx in "${!pids_by_idx[@]}"; do
                if [ -f "${done_by_idx[$idx]}" ]; then
                    finished_idx="$idx"
                    break
                fi
            done
            if [ -n "$finished_idx" ]; then
                break
            fi
            sleep 0.1
        done

        local pid="${pids_by_idx[$finished_idx]}"
        local ip="${ip_by_idx[$finished_idx]}"
        local logf="${log_by_idx[$finished_idx]}"
        local donef="${done_by_idx[$finished_idx]}"
        local rc=0
        # Read the worker's return code from the done-marker, then reap the pid.
        rc=$(cat "$donef" 2>/dev/null || echo 1)
        rm -f "$donef" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true

        unset "pids_by_idx[$finished_idx]"
        unset "done_by_idx[$finished_idx]"
        running=$((running - 1))

        if [ "$rc" = "0" ]; then
            success=$((success + 1))
            log_info "  [$finished_idx] $ip - OK ($task_label)"
            if ! $VERBOSE; then
                rm -f "$logf" 2>/dev/null || true
            else
                log_debug "    log: $logf"
            fi
        else
            fail=$((fail + 1))
            failed_local+=("$ip")
            log_error "  [$finished_idx] $ip - FAIL ($task_label, rc=$rc)"
            log_error "    Log tail ($logf):"
            tail -20 "$logf" 2>/dev/null | sed 's/^/      /' >&2 || true
        fi
    }

    # Dispatch loop
    local idx ip logf donef
    for idx in "${indices[@]}"; do
        ip="${TARGET_IPS[$idx]}"
        logf="${PARALLEL_LOG_DIR}/${task_label}_${ip}.log"
        donef="${PARALLEL_LOG_DIR}/.done_${task_label}_${idx}_$$"
        rm -f "$donef" 2>/dev/null || true
        ip_by_idx[$idx]="$ip"
        log_by_idx[$idx]="$logf"
        done_by_idx[$idx]="$donef"

        # Throttle: block if we've hit the concurrency limit
        while [ "$running" -ge "$PARALLEL_JOBS" ]; do
            _reap_one
        done

        # Launch the worker in background; capture stdout/stderr to log file,
        # and always write the worker's return code to the done-marker file
        # (written atomically by mv to avoid the reaper reading a partial file).
        # NOTE: We disable `set -e` inside the subshell so an error in the
        # worker doesn't abort before the done-marker is written.
        (
            set +e
            local_rc=0
            "$worker_fn" "$idx" "$ip"
            local_rc=$?
            echo "$local_rc" > "${donef}.tmp" && mv -f "${donef}.tmp" "${donef}"
        ) >"$logf" 2>&1 &

        pids_by_idx[$idx]=$!
        running=$((running + 1))
    done

    # Drain remaining jobs
    while [ "$running" -gt 0 ]; do
        _reap_one
    done

    # Copy failed IPs into caller's array (name passed as $failed_arr_name)
    if [ ${#failed_local[@]} -gt 0 ]; then
        # Use printf+eval to safely populate named array
        local ip_esc
        for ip_esc in "${failed_local[@]}"; do
            eval "${failed_arr_name}+=(\"\$ip_esc\")"
        done
    fi

    log_info "  [$task_label] done: $success ok, $fail fail (of $total)"
    return 0
}

# =============================================================================
# parallel_foreach_ip <worker_fn> <task_label> <failed_ips_array_name> \
#                     <ip1> [ip2 ...]
#
# Same semantics as parallel_foreach_host, but operates on an arbitrary list of
# IPs (instead of TARGET_IPS[] indices). Each worker is invoked as:
#   worker_fn <slot_index> <ip>
# where slot_index is a 0-based position in the given IP list (useful as a
# sentinel file suffix to avoid collisions).
# =============================================================================
parallel_foreach_ip() {
    local worker_fn="$1"
    local task_label="$2"
    local failed_arr_name="$3"
    shift 3

    local -a ips=("$@")
    local total=${#ips[@]}
    if [ "$total" -eq 0 ]; then
        return 0
    fi

    mkdir -p "$PARALLEL_LOG_DIR"

    declare -A pids_by_idx
    declare -A ip_by_idx
    declare -A log_by_idx
    declare -A done_by_idx

    local running=0
    local success=0
    local fail=0
    local -a failed_local=()

    _reap_one_ip() {
        local finished_idx=""
        local idx
        while true; do
            for idx in "${!pids_by_idx[@]}"; do
                if [ -f "${done_by_idx[$idx]}" ]; then
                    finished_idx="$idx"
                    break
                fi
            done
            if [ -n "$finished_idx" ]; then
                break
            fi
            sleep 0.1
        done

        local pid="${pids_by_idx[$finished_idx]}"
        local ip="${ip_by_idx[$finished_idx]}"
        local logf="${log_by_idx[$finished_idx]}"
        local donef="${done_by_idx[$finished_idx]}"
        local rc=0
        rc=$(cat "$donef" 2>/dev/null || echo 1)
        rm -f "$donef" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true

        unset "pids_by_idx[$finished_idx]"
        unset "done_by_idx[$finished_idx]"
        running=$((running - 1))

        if [ "$rc" = "0" ]; then
            success=$((success + 1))
            log_info "  [$finished_idx] $ip - OK ($task_label)"
            if ! $VERBOSE; then
                rm -f "$logf" 2>/dev/null || true
            else
                log_debug "    log: $logf"
            fi
        else
            fail=$((fail + 1))
            failed_local+=("$ip")
            log_error "  [$finished_idx] $ip - FAIL ($task_label, rc=$rc)"
            log_error "    Log tail ($logf):"
            tail -20 "$logf" 2>/dev/null | sed 's/^/      /' >&2 || true
        fi
    }

    local slot ip logf donef
    for slot in $(seq 0 $((total - 1))); do
        ip="${ips[$slot]}"
        logf="${PARALLEL_LOG_DIR}/${task_label}_${ip}_${slot}.log"
        donef="${PARALLEL_LOG_DIR}/.done_${task_label}_${slot}_$$"
        rm -f "$donef" 2>/dev/null || true
        ip_by_idx[$slot]="$ip"
        log_by_idx[$slot]="$logf"
        done_by_idx[$slot]="$donef"

        while [ "$running" -ge "$PARALLEL_JOBS" ]; do
            _reap_one_ip
        done

        (
            set +e
            local_rc=0
            "$worker_fn" "$slot" "$ip"
            local_rc=$?
            echo "$local_rc" > "${donef}.tmp" && mv -f "${donef}.tmp" "${donef}"
        ) >"$logf" 2>&1 &

        pids_by_idx[$slot]=$!
        running=$((running + 1))
    done

    while [ "$running" -gt 0 ]; do
        _reap_one_ip
    done

    if [ ${#failed_local[@]} -gt 0 ]; then
        local ip_esc
        for ip_esc in "${failed_local[@]}"; do
            eval "${failed_arr_name}+=(\"\$ip_esc\")"
        done
    fi

    log_info "  [$task_label] done: $success ok, $fail fail (of $total)"
    return 0
}
