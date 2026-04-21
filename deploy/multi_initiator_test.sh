#!/bin/bash
# =============================================================================
# MPComm Multi-Initiator Test Script
#
# Runs MULTIPLE concurrent test jobs across a pool of machines. Each job has
# its own initiator and its own set of targets. A physical machine may appear
# as initiator in one job and as target in other jobs simultaneously (the user
# is responsible for assigning non-conflicting TCP ports).
#
# This script does NOT replace multi_node_test.sh. Use it when you need to
# stress-test asymmetric / mixed-traffic scenarios, e.g.:
#
#   Job A: machine-1 -> [machine-3, machine-4]
#   Job B: machine-3 -> [machine-1, machine-2, machine-4]
#   Job C: machine-4 -> [machine-1, machine-3]      (all jobs run concurrently)
#
# Prerequisites:
#   - deploy_all.sh has been run, OR --skip-deploy is specified along with a
#     working mpcomm + scatter_test installation on every referenced machine.
#   - SSH passwordless login configured between the orchestrator host and
#     every referenced machine (including the orchestrator itself if it is
#     used as an initiator/target).
#
# Usage:
#   bash multi_initiator_test.sh --jobs jobs.txt [options]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---- Multi-initiator defaults ----
JOBS_FILE="${JOBS_FILE:-${SCRIPT_DIR}/jobs.txt}"
SKIP_DEPLOY=false
STARTUP_WAIT=30
JOB_TIMEOUT=0   # 0 = wait indefinitely
READY_MARKER="Waiting for connections..."
SHOW_LOGS=false   # if true, print each job's full log before the summary

# ---- MPComm Environment Variables (same as multi_node_test.sh) ----
MPCOMM_NIC_FILTER="${MPCOMM_NIC_FILTER:-mlx5_bond_1,mlx5_bond_2,mlx5_bond_3,mlx5_bond_4,mlx5_bond_5,mlx5_bond_6,mlx5_bond_7,mlx5_bond_8}"
MPCOMM_QPS_PER_CONNECTION="${MPCOMM_QPS_PER_CONNECTION:-4}"
MPCOMM_POLL_INTERVAL="${MPCOMM_POLL_INTERVAL:-16}"
MPCOMM_MAX_SEND_WR="${MPCOMM_MAX_SEND_WR:-128}"
MPCOMM_PXN_ENABLE="${MPCOMM_PXN_ENABLE:-0}"
MPCOMM_PXN_NVLINK_ALPHA="${MPCOMM_PXN_NVLINK_ALPHA:-5}"
MPCOMM_LOG_LEVEL="${MPCOMM_LOG_LEVEL:-}"
if [ "${MPCOMM_PXN_ENABLE}" -eq 1 ]; then
    MPCOMM_MAX_RDMA_TRANSFER_SIZE="${MPCOMM_MAX_RDMA_TRANSFER_SIZE:-2097152}"
    MPCOMM_MAX_OUTSTANDING_PER_QP="${MPCOMM_MAX_OUTSTANDING_PER_QP:-1}"
else
    MPCOMM_MAX_RDMA_TRANSFER_SIZE="${MPCOMM_MAX_RDMA_TRANSFER_SIZE:-65536}"
    MPCOMM_MAX_OUTSTANDING_PER_QP="${MPCOMM_MAX_OUTSTANDING_PER_QP:-16}"
fi

build_env_exports() {
    local exports=""
    exports+="export MPCOMM_NIC_FILTER='${MPCOMM_NIC_FILTER}';"
    exports+="export MPCOMM_QPS_PER_CONNECTION=${MPCOMM_QPS_PER_CONNECTION};"
    exports+="export MPCOMM_POLL_INTERVAL=${MPCOMM_POLL_INTERVAL};"
    exports+="export MPCOMM_MAX_SEND_WR=${MPCOMM_MAX_SEND_WR};"
    exports+="export MPCOMM_PXN_ENABLE=${MPCOMM_PXN_ENABLE};"
    exports+="export MPCOMM_PXN_NVLINK_ALPHA=${MPCOMM_PXN_NVLINK_ALPHA};"
    exports+="export MPCOMM_MAX_RDMA_TRANSFER_SIZE=${MPCOMM_MAX_RDMA_TRANSFER_SIZE};"
    exports+="export MPCOMM_MAX_OUTSTANDING_PER_QP=${MPCOMM_MAX_OUTSTANDING_PER_QP};"
    if [ -n "${MPCOMM_LOG_LEVEL}" ]; then
        exports+="export MPCOMM_LOG_LEVEL=${MPCOMM_LOG_LEVEL};"
    fi
    echo "$exports"
}

# ---- Usage ----
usage() {
    cat <<EOF
Usage: $(basename "$0") --jobs FILE [options]

Runs multiple concurrent test jobs, each with its own initiator and targets.
Every initiator is launched via SSH on its assigned machine; all initiators
start running only after ALL targets (across all jobs) are ready.

Options:
  --jobs FILE           Jobs configuration file (default: jobs.txt)
  --binary PATH         Path to scatter_test binary on remote hosts
                        (default: \$TESTS_INSTALL_DIR/build/scatter_test)
  --ssh-user USER       SSH username (default: root)
  --ssh-port PORT       SSH port (default: 36001)
  --tests-dir DIR       Test files install directory (default: /opt/mpcomm_tests)
  --skip-deploy         Skip mpcomm/test deployment check
  --startup-wait SECS   Timeout for targets to become ready (default: 30)
  --job-timeout SECS    Max seconds to wait for each initiator (0 = no limit)
  --parallel N          Max concurrent SSH operations (default: 20)
  --show-logs           Print each initiator's full log in the results
                        section (default: only show the bandwidth summary;
                        full logs are still saved to /tmp/mpcomm_job_*.log)
  --verbose             Enable verbose output
  --dry-run             Print planned actions without executing
  -h, --help            Show this help

Jobs file format (INI-style, see jobs.txt.example):
  [global]               # optional defaults for all jobs
  size = 1G
  test-type = scatter

  [jobA]
  initiator = 29.1.1.1 12345 0
  target    = 29.1.1.3 22345 0
  target    = 29.1.1.4 22345 0

  [jobB]
  initiator = 29.1.1.3 12346 1
  target    = 29.1.1.1 22346 1
  size      = 512M
  test-type = gather
EOF
    exit 0
}

# ---- Parse Arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --jobs)           JOBS_FILE="$2"; shift 2 ;;
        --binary)         BINARY_PATH="$2"; shift 2 ;;
        --ssh-user)       SSH_USER="$2"; shift 2 ;;
        --ssh-port)       SSH_PORT="$2"; shift 2 ;;
        --tests-dir)      TESTS_INSTALL_DIR="$2"; shift 2 ;;
        --skip-deploy)    SKIP_DEPLOY=true; shift ;;
        --startup-wait)   STARTUP_WAIT="$2"; shift 2 ;;
        --job-timeout)    JOB_TIMEOUT="$2"; shift 2 ;;
        --parallel)       PARALLEL_JOBS="$2"; shift 2 ;;
        --show-logs)      SHOW_LOGS=true; shift ;;
        --verbose)        VERBOSE=true; shift ;;
        --dry-run)        DRY_RUN=true; shift ;;
        -h|--help)        usage ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

if [ ! -f "$JOBS_FILE" ]; then
    log_error "Jobs file not found: $JOBS_FILE"
    log_error "See ${SCRIPT_DIR}/jobs.txt.example for an example."
    exit 1
fi

if ! [[ "$PARALLEL_JOBS" =~ ^[0-9]+$ ]] || [ "$PARALLEL_JOBS" -lt 1 ]; then
    log_error "--parallel must be a positive integer (got: $PARALLEL_JOBS)"
    exit 1
fi

# =============================================================================
# Jobs file parser
# =============================================================================
# After parse_jobs, the following arrays/maps are populated:
#   JOB_NAMES[]           : ordered list of job names
#   JOB_INI_IP[name]      : initiator IP
#   JOB_INI_PORT[name]    : initiator TCP port
#   JOB_INI_NUMAS[name]   : initiator NUMA spec
#   JOB_TGT_SPECS[name]   : targets encoded as "ip1:port1:numas1|ip2:port2:numas2|..."
#   JOB_PARAMS[name]      : per-job parameter overrides, encoded as
#                           "key1=val1\nkey2=val2\n..." (\n-separated)
#   GLOBAL_PARAMS         : global defaults, same encoding as JOB_PARAMS
#   ALL_HOSTS[]           : de-duplicated list of every IP referenced
#   ALL_TGT_KEYS[]        : de-duplicated list of "ip:port:numas" for every
#                           target instance (one remote process per entry)
# =============================================================================
declare -a JOB_NAMES=()
declare -A JOB_INI_IP=()
declare -A JOB_INI_PORT=()
declare -A JOB_INI_NUMAS=()
declare -A JOB_TGT_SPECS=()
declare -A JOB_PARAMS=()
GLOBAL_PARAMS=""
declare -a ALL_HOSTS=()
declare -A _seen_hosts=()
declare -a ALL_TGT_KEYS=()
declare -A _seen_tgt_keys=()

_add_host() {
    local ip="$1"
    if [ -z "${_seen_hosts[$ip]:-}" ]; then
        ALL_HOSTS+=("$ip")
        _seen_hosts[$ip]=1
    fi
}

_add_tgt_key() {
    local key="$1"   # ip:port:numas
    local ipport="${key%:*}"
    if [ -n "${_seen_tgt_keys[$ipport]:-}" ]; then
        log_error "Duplicate target (ip:port) across jobs: $ipport"
        log_error "Each (ip, port) pair must be unique. Fix ports in $JOBS_FILE."
        exit 1
    fi
    _seen_tgt_keys[$ipport]=1
    ALL_TGT_KEYS+=("$key")
}

parse_jobs() {
    local file="$1"
    local section=""
    local cur_ini_ip="" cur_ini_port="" cur_ini_numas=""
    local cur_tgt_specs=""
    local cur_params=""
    local line_no=0

    _flush_job() {
        [ -z "$section" ] && return 0
        case "$section" in
            global)
                GLOBAL_PARAMS="$cur_params"
                ;;
            *)
                if [ -z "$cur_ini_ip" ]; then
                    log_error "Job [$section] missing 'initiator' line"
                    exit 1
                fi
                if [ -z "$cur_tgt_specs" ]; then
                    log_error "Job [$section] missing 'target' line(s)"
                    exit 1
                fi
                JOB_NAMES+=("$section")
                JOB_INI_IP[$section]="$cur_ini_ip"
                JOB_INI_PORT[$section]="$cur_ini_port"
                JOB_INI_NUMAS[$section]="$cur_ini_numas"
                JOB_TGT_SPECS[$section]="$cur_tgt_specs"
                JOB_PARAMS[$section]="$cur_params"
                _add_host "$cur_ini_ip"
                local -a _specs_arr=()
                IFS='|' read -r -a _specs_arr <<< "$cur_tgt_specs"
                local spec tip tport tnumas rest
                for spec in "${_specs_arr[@]}"; do
                    [ -z "$spec" ] && continue
                    tip="${spec%%:*}"
                    rest="${spec#*:}"
                    tport="${rest%%:*}"
                    tnumas="${rest#*:}"
                    _add_host "$tip"
                    _add_tgt_key "${tip}:${tport}:${tnumas}"
                done
                ;;
        esac
    }

    while IFS= read -r raw || [[ -n "$raw" ]]; do
        line_no=$((line_no + 1))
        # Strip trailing CR (handles CRLF line endings from Windows editors).
        raw="${raw%$'\r'}"
        local line
        line="$(echo "$raw" | sed 's/#.*//')"
        # Trim leading/trailing whitespace (portable)
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [ -z "$line" ] && continue

        # Section header?
        if [[ "$line" =~ ^\[(.+)\]$ ]]; then
            _flush_job
            section="${BASH_REMATCH[1]}"
            section="${section#"${section%%[![:space:]]*}"}"
            section="${section%"${section##*[![:space:]]}"}"
            cur_ini_ip=""; cur_ini_port=""; cur_ini_numas=""
            cur_tgt_specs=""; cur_params=""
            if [ "$section" != "global" ] && [ -n "${JOB_INI_IP[$section]:-}" ]; then
                log_error "Duplicate job section [$section] at line $line_no"
                exit 1
            fi
            continue
        fi

        if [ -z "$section" ]; then
            log_error "Line $line_no: content outside any [section]: $line"
            exit 1
        fi

        # key = value
        if [[ "$line" != *"="* ]]; then
            log_error "Line $line_no: expected 'key = value', got: $line"
            exit 1
        fi
        local key val
        key="${line%%=*}"
        val="${line#*=}"
        key="${key#"${key%%[![:space:]]*}"}"; key="${key%"${key##*[![:space:]]}"}"
        val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"

        case "$key" in
            initiator)
                if [ "$section" = "global" ]; then
                    log_error "Line $line_no: 'initiator' not allowed in [global]"
                    exit 1
                fi
                if [ -n "$cur_ini_ip" ]; then
                    log_error "Line $line_no: job [$section] has more than one initiator"
                    exit 1
                fi
                local ip port numas
                read -r ip port numas <<< "$val"
                if [ -z "$ip" ] || [ -z "$port" ]; then
                    log_error "Line $line_no: 'initiator' requires 'IP PORT [NUMAS]'"
                    exit 1
                fi
                numas="${numas:-0}"
                cur_ini_ip="$ip"; cur_ini_port="$port"; cur_ini_numas="$numas"
                ;;
            target)
                if [ "$section" = "global" ]; then
                    log_error "Line $line_no: 'target' not allowed in [global]"
                    exit 1
                fi
                local ip port numas
                read -r ip port numas <<< "$val"
                if [ -z "$ip" ] || [ -z "$port" ]; then
                    log_error "Line $line_no: 'target' requires 'IP PORT [NUMAS]'"
                    exit 1
                fi
                numas="${numas:-0}"
                if [ -n "$cur_tgt_specs" ]; then
                    cur_tgt_specs+="|"
                fi
                cur_tgt_specs+="${ip}:${port}:${numas}"
                ;;
            size|iterations|warmup|batch-size|gpu|both|test-type|buffer-size)
                # Defense in depth: strip any stray CR from the value before
                # storing, so even if the raw-level CR strip is bypassed we
                # don't end up with "1G\r" being passed to scatter_test.
                val="${val%$'\r'}"
                # per-job or global parameter override
                if [ -n "$cur_params" ]; then
                    cur_params+=$'\n'
                fi
                cur_params+="${key}=${val}"
                ;;
            *)
                log_error "Line $line_no: unknown key '$key'"
                exit 1
                ;;
        esac
    done < "$file"

    _flush_job

    if [ ${#JOB_NAMES[@]} -eq 0 ]; then
        log_error "No jobs defined in $file"
        exit 1
    fi
}

# Look up a parameter value for a job, falling back to GLOBAL_PARAMS.
# Usage: get_param <job_name> <key> ; prints value or empty.
get_param() {
    local name="$1" key="$2"
    local params="${JOB_PARAMS[$name]:-}"
    local line val
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        if [ "${line%%=*}" = "$key" ]; then
            val="${line#*=}"
            val="${val%$'\r'}"
            echo "$val"
            return 0
        fi
    done <<< "$params"
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        if [ "${line%%=*}" = "$key" ]; then
            val="${line#*=}"
            val="${val%$'\r'}"
            echo "$val"
            return 0
        fi
    done <<< "$GLOBAL_PARAMS"
    echo ""
}

parse_jobs "$JOBS_FILE"

# =============================================================================
# Print plan
# =============================================================================
echo ""
echo "============================================================"
echo "  MPComm Multi-Initiator Test"
echo "============================================================"
echo "  Jobs file:     $JOBS_FILE"
echo "  Jobs:          ${#JOB_NAMES[@]}"
for name in "${JOB_NAMES[@]}"; do
    ini_ip="${JOB_INI_IP[$name]}"
    ini_port="${JOB_INI_PORT[$name]}"
    ini_numas="${JOB_INI_NUMAS[$name]}"
    specs="${JOB_TGT_SPECS[$name]}"
    tgt_count=$(awk -F'|' '{print NF}' <<< "$specs")
    echo "    [${name}] initiator=${ini_ip}:${ini_port} (NUMA ${ini_numas}) -> ${tgt_count} target(s)"
    IFS='|' read -r -a _arr <<< "$specs"
    for s in "${_arr[@]}"; do
        echo "          target ${s//:/ }"
    done
    ttype="$(get_param "$name" test-type)"
    size="$(get_param "$name" size)"
    iters="$(get_param "$name" iterations)"
    gpu="$(get_param "$name" gpu)"
    [ -n "$ttype" ] && echo "          test-type=$ttype"
    [ -n "$size" ]  && echo "          size=$size"
    [ -n "$iters" ] && echo "          iterations=$iters"
    [ -n "$gpu" ]   && echo "          gpu=$gpu"
done
echo "  Unique hosts:  ${#ALL_HOSTS[@]} (${ALL_HOSTS[*]})"
echo "  Target procs:  ${#ALL_TGT_KEYS[@]}"
echo "  Parallel:      $PARALLEL_JOBS concurrent SSH jobs"
echo "  Startup wait:  ${STARTUP_WAIT}s"
echo "  PXN:           ${MPCOMM_PXN_ENABLE}"
echo "============================================================"
echo ""

if $DRY_RUN; then
    log_warn "DRY RUN mode - commands will be printed but not executed"
    echo ""
fi

# =============================================================================
# Cleanup trap: kill every launched target on exit
# =============================================================================
LAUNCHED_TARGETS=()       # "ip:port" pairs that were successfully launched
LAUNCHED_INITIATORS=()    # "ip:port" pairs for initiators we started via SSH
CLEANUP_DONE=false

cleanup() {
    if $CLEANUP_DONE; then
        return 0
    fi
    CLEANUP_DONE=true

    echo ""
    log_step "Cleaning up all launched target/initiator processes..."

    # Kill initiators (should normally have exited already). We tag each
    # initiator launcher with the string "mpcomm_ini_<job>_<port>" (its file
    # name), and the scatter_test child inherits that tag in its process
    # tree, so we pkill the launcher script by name. We also do a broad sweep
    # by tagged launcher path.
    local pids=()
    for entry in "${LAUNCHED_INITIATORS[@]}"; do
        [ -z "$entry" ] && continue
        local ip="${entry%%:*}"
        local port="${entry#*:}"
        (
            $(ssh_cmd "$ip") "pkill -f 'mpcomm_ini_.*_${port}\.sh' 2>/dev/null; true" 2>/dev/null || true
        ) &
        pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p" 2>/dev/null || true; done

    # Kill targets
    pids=()
    for entry in "${LAUNCHED_TARGETS[@]}"; do
        [ -z "$entry" ] && continue
        local ip="${entry%%:*}"
        local port="${entry#*:}"
        (
            $(ssh_cmd "$ip") "pkill -f 'scatter_test --mode target --host-id ${ip}:${port}' 2>/dev/null" 2>/dev/null || true
        ) &
        pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p" 2>/dev/null || true; done

    # Broad sweep to be safe: kill any remaining scatter_test and launcher
    # processes on every host we touched.
    pids=()
    for ip in "${ALL_HOSTS[@]}"; do
        (
            $(ssh_cmd "$ip") "pkill -f 'scatter_test' 2>/dev/null; \
                              pkill -f 'mpcomm_ini_.*\.sh' 2>/dev/null; \
                              pkill -f 'mpcomm_launch_' 2>/dev/null; true" 2>/dev/null || true
        ) &
        pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p" 2>/dev/null || true; done

    if [ -d "${PARALLEL_LOG_DIR:-}" ] && ! $VERBOSE; then
        rm -rf "$PARALLEL_LOG_DIR" 2>/dev/null || true
    fi

    log_info "Cleanup done."
}
trap cleanup EXIT INT TERM

# =============================================================================
# Step 1: SSH connectivity
# =============================================================================
log_step "Step 1: Verifying SSH connectivity to ${#ALL_HOSTS[@]} unique host(s)..."
if ! $DRY_RUN; then
    _mit_verify_ssh() {
        local slot="$1" ip="$2"
        if $(ssh_cmd "$ip") "echo ok" &>/dev/null; then
            return 0
        fi
        return 1
    }
    verify_failed=()
    parallel_foreach_ip _mit_verify_ssh "verify_ssh" verify_failed "${ALL_HOSTS[@]}"
    if [ ${#verify_failed[@]} -gt 0 ]; then
        log_error "Some hosts are unreachable: ${verify_failed[*]}"
        exit 1
    fi
else
    for ip in "${ALL_HOSTS[@]}"; do log_debug "  Would verify SSH to $ip"; done
fi
log_info "All hosts reachable."
echo ""

# =============================================================================
# Step 2: Check mpcomm installation on every host (fail fast if --skip-deploy
# and missing; otherwise this is informational — users should run deploy_all.sh
# first for a proper deploy).
# =============================================================================
log_step "Step 2: Checking mpcomm installation on all hosts..."
declare -A HOST_MPCOMM_OK=()
MISSING_HOSTS=()
if ! $DRY_RUN; then
    _mit_check_mpcomm() {
        local slot="$1" ip="$2"
        local sentinel="/tmp/mit_mpcomm_ok_$$_${slot}"
        if $(ssh_cmd "$ip") "python3 -c 'import mpcomm' 2>/dev/null" &>/dev/null; then
            local ver
            ver=$($(ssh_cmd "$ip") "python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null" || echo "unknown")
            echo "$ver" > "$sentinel"
            return 0
        fi
        return 0
    }
    check_failed=()
    parallel_foreach_ip _mit_check_mpcomm "check_mpcomm" check_failed "${ALL_HOSTS[@]}"
    for slot in $(seq 0 $((${#ALL_HOSTS[@]} - 1))); do
        ip="${ALL_HOSTS[$slot]}"
        sentinel="/tmp/mit_mpcomm_ok_$$_${slot}"
        if [ -f "$sentinel" ]; then
            ver=$(cat "$sentinel")
            log_info "  $ip - mpcomm installed (version: $ver)"
            HOST_MPCOMM_OK[$ip]=1
            rm -f "$sentinel"
        else
            log_warn "  $ip - mpcomm NOT installed"
            MISSING_HOSTS+=("$ip")
        fi
    done
fi
if [ ${#MISSING_HOSTS[@]} -gt 0 ]; then
    log_error "mpcomm missing on ${#MISSING_HOSTS[@]} host(s): ${MISSING_HOSTS[*]}"
    log_error "Please run deploy_all.sh first to install mpcomm + scatter_test."
    exit 1
fi
echo ""

# =============================================================================
# Step 3: Locate scatter_test binary on every host
# =============================================================================
log_step "Step 3: Locating scatter_test binary on all hosts..."
declare -A HOST_BINARY=()
declare -A HOST_WORKDIR=()
if ! $DRY_RUN; then
    _mit_locate_bin() {
        local slot="$1" ip="$2"
        local sentinel="/tmp/mit_bin_$$_${slot}"
        if $(ssh_cmd "$ip") "test -x '${TESTS_INSTALL_DIR}/build/scatter_test'" &>/dev/null; then
            echo "${TESTS_INSTALL_DIR}/build/scatter_test|${TESTS_INSTALL_DIR}" > "$sentinel"
            return 0
        fi
        return 1
    }
    locate_failed=()
    parallel_foreach_ip _mit_locate_bin "locate_binary" locate_failed "${ALL_HOSTS[@]}"
    for slot in $(seq 0 $((${#ALL_HOSTS[@]} - 1))); do
        ip="${ALL_HOSTS[$slot]}"
        sentinel="/tmp/mit_bin_$$_${slot}"
        if [ -f "$sentinel" ]; then
            IFS='|' read -r _bin _wd < "$sentinel"
            HOST_BINARY[$ip]="$_bin"
            HOST_WORKDIR[$ip]="$_wd"
            log_info "  $ip - binary: $_bin"
            rm -f "$sentinel"
        else
            log_error "  $ip - scatter_test binary not found under ${TESTS_INSTALL_DIR}"
            log_error "  Run deploy_all.sh first."
            exit 1
        fi
    done
fi
echo ""

# =============================================================================
# Step 4: Kill any stale scatter_test processes on every host
# =============================================================================
log_step "Step 4: Cleaning up stale scatter_test processes..."
if ! $DRY_RUN; then
    _mit_pkill() {
        local slot="$1" ip="$2"
        $(ssh_cmd "$ip") "pkill -f 'scatter_test' 2>/dev/null; pkill -f 'mpcomm_ini_' 2>/dev/null" || true
        return 0
    }
    pkill_failed=()
    parallel_foreach_ip _mit_pkill "pkill_stale" pkill_failed "${ALL_HOSTS[@]}"
fi
sleep 1
log_info "Stale processes cleaned."
echo ""

# =============================================================================
# Step 5: Start every target process in parallel
#
# ALL_TGT_KEYS[] entries are "ip:port:numas". For each entry we launch a
# scatter_test --mode target process. Buffer size is resolved per-JOB (the job
# whose target list contains this spec), falling back to 2G if unset.
# =============================================================================
log_step "Step 5: Starting ${#ALL_TGT_KEYS[@]} target process(es) in parallel..."

ENV_EXPORTS="$(build_env_exports)"

# Resolve buffer size per target key by finding which job declares it.
# Returns the first job's buffer-size (defaulting to 2G). This is fine because
# a (ip,port) pair is unique across the whole file.
resolve_target_buffer_size() {
    local want_key="$1"   # ip:port:numas
    local want_ipport="${want_key%:*}"
    local name specs s s_ipport
    for name in "${JOB_NAMES[@]}"; do
        specs="${JOB_TGT_SPECS[$name]}"
        IFS='|' read -r -a _arr <<< "$specs"
        for s in "${_arr[@]}"; do
            s_ipport="${s%:*}"
            if [ "$s_ipport" = "$want_ipport" ]; then
                local bs
                bs="$(get_param "$name" buffer-size)"
                echo "${bs:-2G}"
                return 0
            fi
        done
    done
    echo "2G"
}

declare -a TGT_BUFSIZES=()
for key in "${ALL_TGT_KEYS[@]}"; do
    TGT_BUFSIZES+=("$(resolve_target_buffer_size "$key")")
done

# Prepare arrays indexed by slot (= index into ALL_TGT_KEYS)
declare -a TGT_IP=()
declare -a TGT_PORT=()
declare -a TGT_NUMAS=()
for key in "${ALL_TGT_KEYS[@]}"; do
    ip="${key%%:*}"
    rest="${key#*:}"
    port="${rest%%:*}"
    numas="${rest#*:}"
    TGT_IP+=("$ip")
    TGT_PORT+=("$port")
    TGT_NUMAS+=("$numas")
done

# Sentinel arrays for parallel launch
declare -a TGT_PID=()
for _ in "${ALL_TGT_KEYS[@]}"; do TGT_PID+=(""); done

if ! $DRY_RUN; then
    _mit_start_target() {
        local slot="$1" ip="$2"
        local port="${TGT_PORT[$slot]}"
        local numas="${TGT_NUMAS[$slot]}"
        local bufsz="${TGT_BUFSIZES[$slot]}"
        local remote_bin="${HOST_BINARY[$ip]}"
        local remote_dir="${HOST_WORKDIR[$ip]}"
        local pid_file="/tmp/mpcomm_target_${port}.pid"
        local log_file="/tmp/mpcomm_target_${port}.log"
        local launcher="/tmp/mpcomm_launch_${port}.sh"
        local pid_sentinel="/tmp/mit_tgt_pid_$$_${slot}"

        # Build the target launcher body locally; ship it via stdin.
        local launcher_body
        launcher_body="$(cat <<EOF
#!/bin/bash
${ENV_EXPORTS}
cd '${remote_dir}'
stdbuf -oL ${remote_bin} --mode target --host-id ${ip}:${port} --tcp-port ${port} --buffer-size ${bufsz} --num-numas ${numas} > '${log_file}' 2>&1 &
echo \$! > '${pid_file}'
EOF
)"

        printf '%s\n' "${launcher_body}" \
            | $(ssh_cmd "$ip") "rm -f '${pid_file}'; cat > '${launcher}' && chmod +x '${launcher}'"

        $(ssh_cmd "$ip") "setsid ${launcher} </dev/null >/dev/null 2>&1 &"
        sleep 1

        local remote_pid
        remote_pid=$($(ssh_cmd "$ip") "cat ${pid_file} 2>/dev/null" || echo "")
        remote_pid=$(echo "$remote_pid" | tail -1 | tr -d '[:space:]')

        if [ -n "$remote_pid" ] && [ "$remote_pid" -gt 0 ] 2>/dev/null; then
            echo "$remote_pid" > "$pid_sentinel"
            echo "[$slot] $ip:$port - started (PID: $remote_pid)"
            return 0
        fi
        echo "[$slot] $ip:$port - failed to start target"
        return 1
    }

    start_failed=()
    parallel_foreach_ip _mit_start_target "start_target" start_failed "${TGT_IP[@]}"

    START_FAIL=false
    for slot in $(seq 0 $((${#ALL_TGT_KEYS[@]} - 1))); do
        ip="${TGT_IP[$slot]}"
        port="${TGT_PORT[$slot]}"
        sentinel="/tmp/mit_tgt_pid_$$_${slot}"
        if [ -f "$sentinel" ]; then
            pid=$(cat "$sentinel")
            TGT_PID[$slot]="$pid"
            LAUNCHED_TARGETS+=("${ip}:${port}")
            rm -f "$sentinel"
            log_info "  [$slot] $ip:$port - started (PID: $pid)"
        else
            log_error "  [$slot] $ip:$port - failed to start target"
            START_FAIL=true
        fi
    done
    if $START_FAIL; then
        log_error "One or more targets failed to start. Aborting."
        exit 1
    fi
fi
echo ""

# =============================================================================
# Step 6: Wait for every target to be ready
# =============================================================================
log_step "Step 6: Waiting for all targets to be ready (timeout: ${STARTUP_WAIT}s)..."
ALL_READY=true
if ! $DRY_RUN; then
    PHASE_A_ROUNDS=3
    PENDING=()
    for slot in $(seq 0 $((${#ALL_TGT_KEYS[@]} - 1))); do
        PENDING+=("$slot")
    done

    _mit_ready_check() {
        local slot="$1" ip="$2"
        local port="${TGT_PORT[$slot]}"
        local pid="${TGT_PID[$slot]}"
        local log_file="/tmp/mpcomm_target_${port}.log"
        local ready_sentinel="/tmp/mit_ready_$$_${slot}"
        local dead_sentinel="/tmp/mit_dead_$$_${slot}"

        local status
        status=$($(ssh_cmd "$ip") "
            if ! kill -0 $pid 2>/dev/null; then
                echo DEAD
                tail -20 ${log_file} 2>/dev/null
                exit 0
            fi
            if grep -q '${READY_MARKER}' ${log_file} 2>/dev/null; then
                echo READY
                exit 0
            fi
            echo PENDING
        " 2>&1)

        local first_line
        first_line=$(echo "$status" | head -1)
        case "$first_line" in
            READY) : > "$ready_sentinel" ;;
            DEAD)  echo "$status" > "$dead_sentinel" ;;
        esac
        return 0
    }

    for round in $(seq 1 "$PHASE_A_ROUNDS"); do
        [ ${#PENDING[@]} -eq 0 ] && break
        log_info "  Round $round: checking ${#PENDING[@]} target(s)..."
        # Build IP list restricted to pending slots
        _ips=()
        for slot in "${PENDING[@]}"; do _ips+=("${TGT_IP[$slot]}"); done
        # But the worker needs the slot index; parallel_foreach_ip passes the
        # position in the supplied IP list as slot_index. So we need to map
        # that back — easiest fix: run one worker at a time with its real slot.
        # Implementation: temporarily replace TGT_PORT/TGT_PID lookups via a
        # slot->real_slot map built before dispatch.
        declare -a _real_slot=()
        for slot in "${PENDING[@]}"; do _real_slot+=("$slot"); done

        _mit_ready_check_proxy() {
            local pos="$1" ip="$2"
            local real="${_real_slot[$pos]}"
            _mit_ready_check "$real" "$ip"
        }

        rc_failed=()
        parallel_foreach_ip _mit_ready_check_proxy "ready_r${round}" rc_failed "${_ips[@]}"

        NEW_PENDING=()
        for slot in "${PENDING[@]}"; do
            ready_sentinel="/tmp/mit_ready_$$_${slot}"
            dead_sentinel="/tmp/mit_dead_$$_${slot}"
            if [ -f "$ready_sentinel" ]; then
                log_info "    [$slot] ${TGT_IP[$slot]}:${TGT_PORT[$slot]} - ready"
                rm -f "$ready_sentinel"
            elif [ -f "$dead_sentinel" ]; then
                log_error "    [$slot] ${TGT_IP[$slot]}:${TGT_PORT[$slot]} - process DIED"
                sed 's/^/      /' "$dead_sentinel" >&2
                rm -f "$dead_sentinel"
                ALL_READY=false
            else
                NEW_PENDING+=("$slot")
            fi
        done
        PENDING=("${NEW_PENDING[@]}")
        [ ${#PENDING[@]} -gt 0 ] && sleep 1
    done

    if [ ${#PENDING[@]} -gt 0 ] && $ALL_READY; then
        log_info "  Phase B: polling ${#PENDING[@]} slow target(s) individually..."
        MAX_ELAPSED=$((STARTUP_WAIT - PHASE_A_ROUNDS))
        [ "$MAX_ELAPSED" -lt 5 ] && MAX_ELAPSED=5
        for slot in "${PENDING[@]}"; do
            ip="${TGT_IP[$slot]}"
            port="${TGT_PORT[$slot]}"
            pid="${TGT_PID[$slot]}"
            LOG_FILE="/tmp/mpcomm_target_${port}.log"
            log_info "  [$slot] Waiting for $ip:$port (max ${MAX_ELAPSED}s)..."
            ELAPSED=0
            READY=false
            while [ "$ELAPSED" -lt "$MAX_ELAPSED" ]; do
                if ! $(ssh_cmd "$ip") "kill -0 $pid 2>/dev/null"; then
                    log_error "  [$slot] $ip (PID $pid) - process died during startup"
                    $(ssh_cmd "$ip") "tail -20 ${LOG_FILE} 2>/dev/null" || true
                    ALL_READY=false
                    break
                fi
                if $(ssh_cmd "$ip") "grep -q '${READY_MARKER}' ${LOG_FILE} 2>/dev/null"; then
                    READY=true
                    break
                fi
                sleep 1
                ELAPSED=$((ELAPSED + 1))
            done
            if $READY; then
                log_info "  [$slot] $ip:$port - ready"
            elif $ALL_READY; then
                log_error "  [$slot] $ip:$port - NOT ready after ${STARTUP_WAIT}s"
                $(ssh_cmd "$ip") "tail -20 ${LOG_FILE} 2>/dev/null" || true
                ALL_READY=false
            fi
        done
    fi
fi

if ! $ALL_READY && ! $DRY_RUN; then
    log_error "Some targets failed to become ready. Aborting."
    exit 1
fi
log_info "All ${#ALL_TGT_KEYS[@]} targets ready."
echo ""

# =============================================================================
# Step 7: Launch every initiator in parallel (via SSH, including the host that
# may be the orchestrator machine itself, for symmetry).
# =============================================================================
log_step "Step 7: Launching ${#JOB_NAMES[@]} initiator(s) in parallel (via SSH)..."

build_initiator_cmd() {
    local name="$1"
    local remote_bin="$2"
    local specs="${JOB_TGT_SPECS[$name]}"
    local cmd="${remote_bin}"
    local i=0
    IFS='|' read -r -a arr <<< "$specs"
    for s in "${arr[@]}"; do
        local tip="${s%%:*}"
        local rest="${s#*:}"
        local tport="${rest%%:*}"
        cmd+=" --target t${i}:${tip}:${tport}"
        i=$((i + 1))
    done
    local v
    v="$(get_param "$name" size)";        [ -n "$v" ] && cmd+=" --size $v"
    v="$(get_param "$name" iterations)";  [ -n "$v" ] && cmd+=" --iterations $v"
    v="$(get_param "$name" warmup)";      [ -n "$v" ] && cmd+=" --warmup $v"
    v="$(get_param "$name" batch-size)";  [ -n "$v" ] && cmd+=" --batch-size $v"
    v="$(get_param "$name" gpu)";         [ -n "$v" ] && cmd+=" --gpu $v"
    v="$(get_param "$name" both)";        [ "$v" = "true" ] && cmd+=" --both"
    v="$(get_param "$name" test-type)";   [ -n "$v" ] && cmd+=" --test-type $v"
    cmd+=" --num-numas ${JOB_INI_NUMAS[$name]}"
    echo "$cmd"
}

# Arrays indexed by job slot
declare -a JOB_IP=()
declare -a JOB_PORT=()
declare -a JOB_CMD=()
for name in "${JOB_NAMES[@]}"; do
    ip="${JOB_INI_IP[$name]}"
    port="${JOB_INI_PORT[$name]}"
    bin="${HOST_BINARY[$ip]}"
    JOB_IP+=("$ip")
    JOB_PORT+=("$port")
    JOB_CMD+=("$(build_initiator_cmd "$name" "$bin")")
done

# Print the full plan before launching
for i in $(seq 0 $((${#JOB_NAMES[@]} - 1))); do
    name="${JOB_NAMES[$i]}"
    log_info "  [${name}] ${JOB_IP[$i]} :: ${JOB_CMD[$i]}"
done

if $DRY_RUN; then
    log_warn "DRY RUN - skipping actual execution"
    exit 0
fi

# For each job, write an initiator launcher script on its host, launch via
# setsid (fully detached), and record the PID. stdout/stderr is captured to
# /tmp/mpcomm_ini_<job>.log on the remote host; we'll pull it back later.
declare -a JOB_REMOTE_PID=()
for _ in "${JOB_NAMES[@]}"; do JOB_REMOTE_PID+=(""); done

_mit_start_initiator() {
    local pos="$1" ip="$2"
    local name="${JOB_NAMES[$pos]}"
    local port="${JOB_PORT[$pos]}"
    local cmd="${JOB_CMD[$pos]}"
    local workdir="${HOST_WORKDIR[$ip]}"
    local tag="mpcomm_ini_${name}_${port}"
    local launcher="/tmp/${tag}.sh"
    local pid_file="/tmp/${tag}.pid"
    local log_file="/tmp/${tag}.log"
    local exitcode_file="/tmp/${tag}.exitcode"
    local pid_sentinel="/tmp/mit_ini_pid_$$_${pos}"

    # Build the launcher script body locally as a single string. Using a
    # single-variable interpolation here (not nested heredocs) guarantees
    # that values like "1G" / "512M" are never re-parsed by any shell layer.
    # The launcher writes its own PID to pid_file; it lives until the
    # scatter_test child exits, so kill -0 reliably reflects liveness.
    local launcher_body
    launcher_body="$(cat <<EOF
#!/bin/bash
echo \$\$ > '${pid_file}'
${ENV_EXPORTS}
cd '${workdir}'
stdbuf -oL ${cmd} > '${log_file}' 2>&1
rc=\$?
echo \$rc > '${exitcode_file}'
EOF
)"

    # Print the exact launcher body for easy diagnosis.
    echo "----- launcher content for [${name}] on ${ip} (${launcher}) -----"
    echo "${launcher_body}"
    echo "----- end launcher content -----"

    # Step 1: Ship the launcher body via stdin and make it executable.
    printf '%s\n' "${launcher_body}" \
        | $(ssh_cmd "$ip") "rm -f '${exitcode_file}' '${pid_file}' '${log_file}'; cat > '${launcher}' && chmod +x '${launcher}'"

    # Step 2: Launch it detached. The launcher itself writes its PID inside.
    $(ssh_cmd "$ip") "nohup setsid '${launcher}' </dev/null >/dev/null 2>&1 & disown 2>/dev/null; exit 0"

    # Wait briefly for the launcher to write its PID file.
    sleep 1

    local remote_pid
    remote_pid=$($(ssh_cmd "$ip") "cat ${pid_file} 2>/dev/null" || echo "")
    remote_pid=$(echo "$remote_pid" | tail -1 | tr -d '[:space:]')

    if [ -n "$remote_pid" ] && [ "$remote_pid" -gt 0 ] 2>/dev/null; then
        echo "$remote_pid" > "$pid_sentinel"
        echo "[${name}] $ip - initiator started (launcher PID: $remote_pid)"
        return 0
    fi
    echo "[${name}] $ip - failed to start initiator"
    return 1
}

ini_failed=()
parallel_foreach_ip _mit_start_initiator "start_initiator" ini_failed "${JOB_IP[@]}"

START_FAIL=false
for i in $(seq 0 $((${#JOB_NAMES[@]} - 1))); do
    name="${JOB_NAMES[$i]}"
    ip="${JOB_IP[$i]}"
    port="${JOB_PORT[$i]}"
    sentinel="/tmp/mit_ini_pid_$$_${i}"
    if [ -f "$sentinel" ]; then
        pid=$(cat "$sentinel")
        JOB_REMOTE_PID[$i]="$pid"
        LAUNCHED_INITIATORS+=("${ip}:${port}")
        rm -f "$sentinel"
        log_info "  [${name}] $ip - initiator running (PID: $pid)"
    else
        log_error "  [${name}] $ip - initiator failed to start"
        START_FAIL=true
    fi
done
if $START_FAIL; then
    log_error "One or more initiators failed to start. Aborting."
    exit 1
fi
echo ""

# =============================================================================
# Step 8: Wait for every initiator to finish, then fetch its log
# =============================================================================
log_step "Step 8: Waiting for ${#JOB_NAMES[@]} initiator(s) to complete..."

# Pending list of job indices
PENDING_JOBS=()
for i in $(seq 0 $((${#JOB_NAMES[@]} - 1))); do PENDING_JOBS+=("$i"); done

declare -A JOB_EXIT_CODE=()
START_TS=$(date +%s)
LAST_TICK=0

while [ ${#PENDING_JOBS[@]} -gt 0 ]; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TS))

    # Print heartbeat every 10s
    if [ $((ELAPSED - LAST_TICK)) -ge 10 ]; then
        LAST_TICK=$ELAPSED
        running_names=()
        for i in "${PENDING_JOBS[@]}"; do running_names+=("${JOB_NAMES[$i]}"); done
        log_info "  [${ELAPSED}s] still running: ${running_names[*]}"
    fi

    # Timeout check
    if [ "$JOB_TIMEOUT" -gt 0 ] && [ "$ELAPSED" -gt "$JOB_TIMEOUT" ]; then
        log_error "Job timeout (${JOB_TIMEOUT}s) reached; killing remaining initiators."
        for i in "${PENDING_JOBS[@]}"; do
            JOB_EXIT_CODE[$i]=124
        done
        break
    fi

    NEW_PENDING=()
    for i in "${PENDING_JOBS[@]}"; do
        name="${JOB_NAMES[$i]}"
        ip="${JOB_IP[$i]}"
        pid="${JOB_REMOTE_PID[$i]}"
        port="${JOB_PORT[$i]}"
        tag="mpcomm_ini_${name}_${port}"
        exitcode_file="/tmp/${tag}.exitcode"

        # Is the remote PID still alive?
        alive=$($(ssh_cmd "$ip") "kill -0 $pid 2>/dev/null && echo Y || echo N" 2>/dev/null || echo "N")
        alive=$(echo "$alive" | tail -1 | tr -d '[:space:]')
        if [ "$alive" = "Y" ]; then
            NEW_PENDING+=("$i")
            continue
        fi
        # Process exited; read the exit code file written by the launcher.
        exitcode_file="/tmp/${tag}.exitcode"
        rc=$($(ssh_cmd "$ip") "cat ${exitcode_file} 2>/dev/null" || echo "")
        rc=$(echo "$rc" | tail -1 | tr -d '[:space:]')
        if [ -z "$rc" ]; then
            rc="?"
        fi
        JOB_EXIT_CODE[$i]="$rc"
        log_info "  [${name}] finished after ${ELAPSED}s (rc=$rc)"
    done
    PENDING_JOBS=("${NEW_PENDING[@]}")
    [ ${#PENDING_JOBS[@]} -gt 0 ] && sleep 2
done

echo ""
log_step "Step 9: Fetching logs from every initiator..."
declare -A JOB_LOCAL_LOG=()
for i in $(seq 0 $((${#JOB_NAMES[@]} - 1))); do
    name="${JOB_NAMES[$i]}"
    ip="${JOB_IP[$i]}"
    port="${JOB_PORT[$i]}"
    tag="mpcomm_ini_${name}_${port}"
    local_log="/tmp/mpcomm_job_${name}.log"
    if $(ssh_cmd "$ip") "cat /tmp/${tag}.log" > "$local_log" 2>/dev/null; then
        JOB_LOCAL_LOG[$name]="$local_log"
        log_info "  [${name}] log saved to $local_log"
    else
        log_warn "  [${name}] failed to fetch log"
        JOB_LOCAL_LOG[$name]=""
    fi
done
echo ""

# =============================================================================
# Step 10: Print per-job results, one after another
# =============================================================================
echo "============================================================"
echo "  Results"
echo "============================================================"
ALL_OK=true
for i in $(seq 0 $((${#JOB_NAMES[@]} - 1))); do
    name="${JOB_NAMES[$i]}"
    rc="${JOB_EXIT_CODE[$i]:-?}"
    echo ""
    echo "------------------------------------------------------------"
    if [ "$rc" = "0" ]; then
        echo "  [${name}] SUCCESS (${JOB_IP[$i]})"
    else
        echo "  [${name}] FAILED (rc=$rc, ${JOB_IP[$i]})"
        ALL_OK=false
    fi
    echo "------------------------------------------------------------"
    logf="${JOB_LOCAL_LOG[$name]}"
    if $SHOW_LOGS; then
        if [ -n "$logf" ] && [ -f "$logf" ]; then
            cat "$logf"
        else
            echo "(log unavailable)"
        fi
    else
        if [ -n "$logf" ] && [ -f "$logf" ]; then
            echo "  (full log: $logf  --  rerun with --show-logs to print inline)"
        else
            echo "  (log unavailable)"
        fi
    fi
done

# =============================================================================
# Final bandwidth summary: compact per-job bandwidth table.
# Extracted directly from each job's fetched log by matching the three
# well-known anchor lines that scatter_test prints at the end of every run:
#   --- <TestType> <Mem> Summary (...)
#     Aggregate Avg: <wall> ms (<avg_gbps> Gbps, <avg_gbs> GB/s)
#     Best BW:  <best_gbps> Gbps (...)  |  Worst BW: <worst_gbps> Gbps (...)
# A single job may contain multiple test types (scatter, gather, broadcast)
# and both DRAM / HBM sections, so we list every summary block we find.
# =============================================================================
echo ""
echo "============================================================"
echo "  Bandwidth Summary"
echo "============================================================"
# Column widths: tuned so that typical job names (<=14 chars) and test labels
# like "Scatter/DRAM", "Broadcast/HBM" (<=14 chars) fit cleanly, and numeric
# columns are wide enough for values up to 9999.99 GB/s with 2 decimals.
SUM_FMT_HEADER="  %-14s %-14s %14s %14s %14s\n"
SUM_FMT_NUM="  %-14s %-14s %14.2f %14.2f %14.2f\n"
SUM_FMT_TEXT="  %-14s %-14s %14s %14s %14s\n"

printf "$SUM_FMT_HEADER" \
    "Job" "Test" "AvgBW(GB/s)" "BestBW(GB/s)" "WorstBW(GB/s)"
printf "$SUM_FMT_HEADER" \
    "--------------" "--------------" "--------------" "--------------" "--------------"

for i in $(seq 0 $((${#JOB_NAMES[@]} - 1))); do
    name="${JOB_NAMES[$i]}"
    rc="${JOB_EXIT_CODE[$i]:-?}"
    logf="${JOB_LOCAL_LOG[$name]}"

    if [ "$rc" != "0" ]; then
        printf "$SUM_FMT_TEXT" \
            "$name" "-" "FAILED" "FAILED" "FAILED"
        continue
    fi
    if [ -z "$logf" ] || [ ! -f "$logf" ]; then
        printf "$SUM_FMT_TEXT" \
            "$name" "-" "(no log)" "(no log)" "(no log)"
        continue
    fi

    # Parse summary blocks with awk (POSIX-compatible).
    # State machine: when we see a "--- <Type> <Mem> Summary" line we remember
    # the label; then for the next "Aggregate Avg" / "Best BW" lines we extract
    # the GB/s numeric fields (the value in parentheses after the Gbps number)
    # and emit one tab-separated row per block.
    awk -v jobname="$name" '
        # Extract the first floating-point number in the substring that starts
        # at position p of the current line. Returns "" if none found.
        function extract_num(line, p,    rest, r) {
            rest = substr(line, p)
            if (match(rest, /[0-9]+\.[0-9]+|[0-9]+/)) {
                return substr(rest, RSTART, RLENGTH)
            }
            return ""
        }
        # Find the GB/s number that appears right after the "Gbps" token whose
        # start position is at/after p in the current line. Returns "" if the
        # token is not found.
        function extract_gbs(line, p,    q) {
            q = index(substr(line, p), "Gbps")
            if (q <= 0) return ""
            # q is relative to substr(line,p); convert back to absolute pos.
            return extract_num(line, p + q - 1 + length("Gbps"))
        }

        /^---[[:space:]]+[A-Za-z]+[[:space:]]+[A-Za-z]+[[:space:]]+Summary/ {
            # Example: "--- Scatter DRAM Summary (2 targets, ...)"
            # Field 2 = test type, field 3 = memory type.
            label = $2 "/" $3
            avg = ""; best = ""; worst = ""
            next
        }
        /Aggregate Avg:/ {
            # "  Aggregate Avg: 0.018 ms (298.99 Gbps, 37.37 GB/s)"
            # Skip past the first "(" and grab the GB/s value following Gbps.
            p = index($0, "(")
            if (p > 0) avg = extract_gbs($0, p + 1)
        }
        /Best BW:/ {
            # "  Best BW:  396.28 Gbps (49.53 GB/s)  |  Worst BW: 194.60 Gbps (24.33 GB/s)"
            pb = index($0, "Best BW:")
            pw = index($0, "Worst BW:")
            if (pb > 0) best  = extract_gbs($0, pb + length("Best BW:"))
            if (pw > 0) worst = extract_gbs($0, pw + length("Worst BW:"))
            if (label != "" && avg != "" && best != "" && worst != "") {
                printf "%s\t%s\t%s\t%s\t%s\n", jobname, label, avg, best, worst
                label = ""; avg = ""; best = ""; worst = ""
            }
        }
    ' "$logf" | while IFS=$'\t' read -r jname tlabel avg best worst; do
        # Use the numeric format so values are always right-aligned with two
        # decimals; if awk somehow produced a non-numeric string, fall back
        # to the text format so the row still prints cleanly.
        if [[ "$avg" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
            printf "$SUM_FMT_NUM" "$jname" "$tlabel" "$avg" "$best" "$worst"
        else
            printf "$SUM_FMT_TEXT" "$jname" "$tlabel" "$avg" "$best" "$worst"
        fi
    done || true
done

echo ""
echo "============================================================"
if $ALL_OK; then
    log_info "All ${#JOB_NAMES[@]} jobs completed successfully."
    exit 0
else
    log_error "Some jobs failed. See individual logs above."
    exit 1
fi
