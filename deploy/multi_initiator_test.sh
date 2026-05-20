#!/bin/bash
# =============================================================================
# MPComm Multi-Initiator Test Script
#
# Runs MULTIPLE concurrent test jobs across a pool of machines. Each job has
# its own initiator and its own set of targets. A physical machine may appear
# as initiator in one job and as target in other jobs simultaneously; every
# host runs exactly one MPComm process bound to its single TCP port.
#
# Hosts (IP / TCP port / default NUMA) are described in hosts.txt. jobs.txt
# only references hosts by their ID, e.g.:
#
#   Job A: 1 -> [3, 4]
#   Job B: 3 -> [1, 2, 4]
#   Job C: 4 -> [1, 3]      (all jobs run concurrently)
#
# Prerequisites:
#   - deploy_all.sh has been run, OR --skip-deploy is specified along with a
#     working mpcomm + scatter_test installation on every referenced machine.
#   - SSH passwordless login configured between the orchestrator host and
#     every referenced machine (including the orchestrator itself if it is
#     used as an initiator/target).
#
# Usage:
#   bash multi_initiator_test.sh [--hosts hosts.txt] [--jobs jobs.txt] [options]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---- Multi-initiator defaults ----
HOSTS_FILE="${HOSTS_FILE:-${SCRIPT_DIR}/hosts.txt}"
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

Runs multiple concurrent test jobs across a pool of machines. Every host
involved in the jobs file runs exactly ONE 'scatter_test --mode both' process
that simultaneously acts as target (publishing one buffer per job whose
target list references it) and as initiator (running one benchmark round per
job whose initiator line names it). A host therefore opens a single TCP port
for all of its roles.

Options:
  --hosts FILE          Host inventory file (default: hosts.txt)
  --jobs FILE           Jobs configuration file (default: jobs.txt)
  --binary PATH         Path to scatter_test binary on remote hosts
                        (default: \$TESTS_INSTALL_DIR/build/scatter_test)
  --ssh-user USER       SSH username (default: root)
  --ssh-port PORT       SSH port (default: 36001)
  --tests-dir DIR       Test files install directory (default: /opt/mpcomm_tests)
  --skip-deploy         Skip mpcomm/test deployment check
  --startup-wait SECS   Timeout for targets to become ready (default: 30)
  --job-timeout SECS    Max seconds to wait for every job to finish
                        (0 = no limit; applies to the whole run)
  --parallel N          Max concurrent SSH operations (default: 20)
  --show-logs           Print each job's per-job log slice in the results
                        section (default: only show the bandwidth summary;
                        per-job slices are still saved to /tmp/mpcomm_job_*.log)
  --verbose             Enable verbose output
  --dry-run             Print planned actions without executing
  -h, --help            Show this help

Hosts file format (whitespace-separated columns):
  ID  IP  TCP_PORT  NUMA_NODES
Example:
  1   29.1.1.1  12345  0
  2   29.1.1.2  12345  0,1

Jobs file format (INI-style, see jobs.txt.example):
  [global]               # optional defaults for all jobs
  size = 1G
  test-type = scatter

  [jobA]
  initiator = 1
  target    = 3 4       # multiple targets on one line, space-separated

  [jobB]
  initiator = 3[1]      # bracketed NUMA override (defaults come from hosts.txt)
  target    = 1[0] 4    # per-target NUMA override; '4' uses its hosts.txt default
  size      = 512M
  test-type = gather
EOF
    exit 0
}

# ---- Parse Arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hosts)          HOSTS_FILE="$2"; shift 2 ;;
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

if [ ! -f "$HOSTS_FILE" ]; then
    log_error "Hosts file not found: $HOSTS_FILE"
    exit 1
fi

if [ ! -f "$JOBS_FILE" ]; then
    log_error "Jobs file not found: $JOBS_FILE"
    log_error "See ${SCRIPT_DIR}/jobs.txt.example for an example."
    exit 1
fi

if ! [[ "$PARALLEL_JOBS" =~ ^[0-9]+$ ]] || [ "$PARALLEL_JOBS" -lt 1 ]; then
    log_error "--parallel must be a positive integer (got: $PARALLEL_JOBS)"
    exit 1
fi

# Load host inventory first; jobs.txt references hosts by ID, so we need the
# HOST_ID_TO_IP / HOST_ID_TO_PORT / HOST_ID_TO_NUMAS maps populated before
# parse_jobs runs.
parse_hosts "$HOSTS_FILE"

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
        log_error "Each (ip, port) pair must be unique. Check $HOSTS_FILE for duplicate entries."
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
                # Exactly one token, either "ID" or "ID[NUMA]" (NUMA may
                # contain commas, e.g. 1[0,1]).
                local _ini_tokens
                read -r -a _ini_tokens <<< "$val"
                if [ "${#_ini_tokens[@]}" -eq 0 ]; then
                    log_error "Line $line_no: 'initiator' requires 'HOST_ID' or 'HOST_ID[NUMA]'"
                    exit 1
                fi
                if [ "${#_ini_tokens[@]}" -gt 1 ]; then
                    log_error "Line $line_no: 'initiator' accepts only one host (use 'ID[NUMA]' for NUMA override)"
                    exit 1
                fi
                local _ini_tok="${_ini_tokens[0]}"
                local hid numa_override
                if [[ "$_ini_tok" == *"["*"]" ]]; then
                    hid="${_ini_tok%%[*}"
                    numa_override="${_ini_tok#*[}"; numa_override="${numa_override%]}"
                    if [ -z "$numa_override" ]; then
                        log_error "Line $line_no: empty NUMA override in '$_ini_tok'"
                        exit 1
                    fi
                elif [[ "$_ini_tok" == *"["* || "$_ini_tok" == *"]"* ]]; then
                    log_error "Line $line_no: malformed initiator token '$_ini_tok' (expected 'ID' or 'ID[NUMA]')"
                    exit 1
                else
                    hid="$_ini_tok"
                    numa_override=""
                fi
                if [ -z "$hid" ]; then
                    log_error "Line $line_no: 'initiator' requires a host ID"
                    exit 1
                fi
                if [ -z "${HOST_ID_TO_IP[$hid]:-}" ]; then
                    log_error "Line $line_no: unknown host ID '$hid' (not defined in $HOSTS_FILE)"
                    exit 1
                fi
                cur_ini_ip="${HOST_ID_TO_IP[$hid]}"
                cur_ini_port="${HOST_ID_TO_PORT[$hid]}"
                cur_ini_numas="${numa_override:-${HOST_ID_TO_NUMAS[$hid]}}"
                ;;
            target)
                if [ "$section" = "global" ]; then
                    log_error "Line $line_no: 'target' not allowed in [global]"
                    exit 1
                fi
                # Accept one OR multiple targets on the same line. Each token
                # is either "ID" or "ID[NUMA]" (NUMA may itself contain commas,
                # e.g. 3[0,1]).
                local _tgt_tokens
                read -r -a _tgt_tokens <<< "$val"
                if [ "${#_tgt_tokens[@]}" -eq 0 ]; then
                    log_error "Line $line_no: 'target' requires at least one HOST_ID"
                    exit 1
                fi
                local _tok hid numa_override ip port numas
                for _tok in "${_tgt_tokens[@]}"; do
                    if [[ "$_tok" == *"["*"]" ]]; then
                        hid="${_tok%%[*}"
                        numa_override="${_tok#*[}"; numa_override="${numa_override%]}"
                        if [ -z "$numa_override" ]; then
                            log_error "Line $line_no: empty NUMA override in '$_tok'"
                            exit 1
                        fi
                    elif [[ "$_tok" == *"["* || "$_tok" == *"]"* ]]; then
                        log_error "Line $line_no: malformed target token '$_tok' (expected 'ID' or 'ID[NUMA]')"
                        exit 1
                    else
                        hid="$_tok"
                        numa_override=""
                    fi
                    if [ -z "${HOST_ID_TO_IP[$hid]:-}" ]; then
                        log_error "Line $line_no: unknown host ID '$hid' (not defined in $HOSTS_FILE)"
                        exit 1
                    fi
                    ip="${HOST_ID_TO_IP[$hid]}"
                    port="${HOST_ID_TO_PORT[$hid]}"
                    numas="${numa_override:-${HOST_ID_TO_NUMAS[$hid]}}"
                    if [ -n "$cur_tgt_specs" ]; then
                        cur_tgt_specs+="|"
                    fi
                    cur_tgt_specs+="${ip}:${port}:${numas}"
                done
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
echo "  Hosts file:    $HOSTS_FILE"
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
LAUNCHED_TARGETS=()       # "ip:port" pairs for each host's launched
                          # scatter_test --mode both process.
CLEANUP_DONE=false

cleanup() {
    if $CLEANUP_DONE; then
        return 0
    fi
    CLEANUP_DONE=true

    echo ""
    log_step "Cleaning up all launched 'both' processes..."

    # Precise kill for each host's 'both' launcher + scatter_test child.
    local pids=()
    for entry in "${LAUNCHED_TARGETS[@]}"; do
        [ -z "$entry" ] && continue
        local ip="${entry%%:*}"
        local port="${entry#*:}"
        (
            $(ssh_cmd "$ip") "pkill -f 'mpcomm_both_${port}\.sh' 2>/dev/null; \
                              pkill -f 'scatter_test --mode both --host-id ${ip}:${port}' 2>/dev/null; \
                              rm -f /tmp/mpcomm_go_${port} 2>/dev/null; \
                              true" 2>/dev/null || true
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
                              pkill -f 'mpcomm_both_.*\.sh' 2>/dev/null; \
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
        $(ssh_cmd "$ip") "pkill -f 'scatter_test' 2>/dev/null; pkill -f 'mpcomm_both_' 2>/dev/null; pkill -f 'mpcomm_ini_' 2>/dev/null" || true
        return 0
    }
    pkill_failed=()
    parallel_foreach_ip _mit_pkill "pkill_stale" pkill_failed "${ALL_HOSTS[@]}"
fi
sleep 1
log_info "Stale processes cleaned."
echo ""

# =============================================================================
# Build per-host plan for --mode both
#
# One process per host. We aggregate all jobs:
#   * For every (initiator_host -> target_host) pair in job X:
#       - target_host gains a --serve entry (channel_id=X, numa=target's numa)
#       - initiator_host gains a --target entry pointing at target_host with
#         the same channel_id and peer_numa=target's numa, tagged with the
#         job name so the binary can run each job's benchmark independently.
#   * Each host runs scatter_test exactly once with --mode both.
#
# Invariants (enforced below):
#   1. Every host has exactly one TCP port (a host cannot open MPComm on two
#      different ports from the same process). If a host appears as
#      initiator in one job with port P1 and as target in another job with
#      port P2, we require P1==P2.
#   2. channel_id is 1000 + job_index (1-based). It is unique within and
#      across hosts; only initiator+target endpoints of the same job share it.
# =============================================================================

declare -A HOST_PORT=()           # ip -> tcp port
declare -A HOST_NUMAS=()          # ip -> "0" or "0,1" (union of all roles)
declare -A HOST_SERVES=()         # ip -> "cid:size:numa|cid:size:numa|..."
declare -A HOST_TARGETS=()        # ip -> "cid:peer_job:peer_ip:peer_port:peer_numa|..."
declare -A HOST_JOBS=()           # ip -> "jobA|jobB|..." logical jobs whose
                                   #       initiator lives on this host
declare -a HOST_LIST=()           # de-duplicated list of hosts actually used
declare -A _seen_host_in_list=()

_require_port() {
    # ip / port / role-description (for error messages)
    local ip="$1" port="$2" role="$3"
    if [ -n "${HOST_PORT[$ip]:-}" ]; then
        if [ "${HOST_PORT[$ip]}" != "$port" ]; then
            log_error "Host $ip cannot use multiple ports in 'both' mode: "
            log_error "  already bound to port ${HOST_PORT[$ip]}, but $role wants port $port."
            log_error "  This indicates an inconsistency in $HOSTS_FILE (the same IP is listed with different ports)."
            exit 1
        fi
    else
        HOST_PORT[$ip]="$port"
    fi
    if [ -z "${_seen_host_in_list[$ip]:-}" ]; then
        HOST_LIST+=("$ip")
        _seen_host_in_list[$ip]=1
    fi
}

_merge_numas() {
    # Merge comma-separated numa spec into HOST_NUMAS[ip], deduplicating.
    local ip="$1" spec="$2"
    local existing="${HOST_NUMAS[$ip]:-}"
    local combined="$existing"
    if [ -z "$existing" ]; then
        combined="$spec"
    else
        combined="${existing},${spec}"
    fi
    # Dedup while preserving order of first appearance.
    local IFS=','
    local -A seen=()
    local out=""
    local tok
    for tok in $combined; do
        [ -z "$tok" ] && continue
        if [ -z "${seen[$tok]:-}" ]; then
            seen[$tok]=1
            if [ -z "$out" ]; then out="$tok"; else out="${out},${tok}"; fi
        fi
    done
    HOST_NUMAS[$ip]="$out"
}

_first_numa() {
    # Return the first numa node from a spec like "0,1".
    local spec="$1"
    echo "${spec%%,*}"
}

_append_pipe() {
    # $1 = variable name (assoc entry), $2 = key, $3 = value to append.
    # Usage: _append_pipe HOST_SERVES "$ip" "$new_entry"
    local -n _map="$1"
    local key="$2" val="$3"
    if [ -z "${_map[$key]:-}" ]; then
        _map[$key]="$val"
    else
        _map[$key]="${_map[$key]}|${val}"
    fi
}

# Walk jobs in declaration order and assign channel_id = 1000 + index (1-based).
job_idx=0
for name in "${JOB_NAMES[@]}"; do
    job_idx=$((job_idx + 1))
    cid=$((1000 + job_idx))

    ini_ip="${JOB_INI_IP[$name]}"
    ini_port="${JOB_INI_PORT[$name]}"
    ini_numas="${JOB_INI_NUMAS[$name]}"
    specs="${JOB_TGT_SPECS[$name]}"
    bufsz="$(get_param "$name" buffer-size)"
    bufsz="${bufsz:-2G}"

    _require_port "$ini_ip" "$ini_port" "job [$name] initiator"
    _merge_numas "$ini_ip" "$ini_numas"
    _append_pipe HOST_JOBS "$ini_ip" "$name"

    # Iterate targets of this job. Each target produces:
    #   - a --serve entry on the target host
    #   - a --target entry on the initiator host
    IFS='|' read -r -a _specs_arr <<< "$specs"
    for spec in "${_specs_arr[@]}"; do
        [ -z "$spec" ] && continue
        tip="${spec%%:*}"
        rest="${spec#*:}"
        tport="${rest%%:*}"
        tnumas="${rest#*:}"
        tfirst="$(_first_numa "$tnumas")"

        _require_port "$tip" "$tport" "job [$name] target"
        _merge_numas "$tip" "$tnumas"

        # Serve on the target host (one buffer per job-target pair).
        _append_pipe HOST_SERVES "$tip" "${cid}:${bufsz}:${tfirst}"

        # Target on the initiator host (benchmark direction: ini -> tgt).
        _append_pipe HOST_TARGETS "$ini_ip" \
            "${cid}:${name}:${tip}:${tport}:${tfirst}"
    done
done
unset job_idx

echo ""
log_step "Per-host 'both' process plan:"
for ip in "${HOST_LIST[@]}"; do
    port="${HOST_PORT[$ip]}"
    numas="${HOST_NUMAS[$ip]:-0}"
    serves="${HOST_SERVES[$ip]:-}"
    tgts="${HOST_TARGETS[$ip]:-}"
    jobs_on="${HOST_JOBS[$ip]:-}"
    serve_count=0
    tgt_count=0
    [ -n "$serves" ] && serve_count=$(awk -F'|' '{print NF}' <<< "$serves")
    [ -n "$tgts" ]   && tgt_count=$(awk -F'|' '{print NF}' <<< "$tgts")
    echo "  $ip : port=$port  numas=$numas  serves=$serve_count  targets=$tgt_count  jobs=[${jobs_on//|/,}]"
    if [ -n "$serves" ]; then
        IFS='|' read -r -a _a <<< "$serves"; for e in "${_a[@]}"; do echo "      --serve $e"; done
    fi
    if [ -n "$tgts" ]; then
        IFS='|' read -r -a _a <<< "$tgts"; for e in "${_a[@]}"; do echo "      --target $e"; done
    fi
done
echo ""

# =============================================================================
# Step 5: Start one scatter_test --mode both process per host
# =============================================================================
log_step "Step 5: Starting ${#HOST_LIST[@]} 'both' process(es) in parallel..."

ENV_EXPORTS="$(build_env_exports)"

# Build the command line for a given host.
#   cmd = numactl prefix + scatter_test --mode both --host-id ip:port
#           --tcp-port port --num-numas <spec>
#           [--serve cid:size:numa ...]
#           [--job NAME --target host_id:ip:port:cid:peer_numa ...]
#         followed by the per-job --size/--iterations/... overrides taken
#         from whichever job that --job block belongs to.
#
# Host IDs assigned to each target entry use the peer's IP only (since it is
# unique per host, thanks to _require_port). The remote process ID used as
# --host-id is "ip:port".
build_host_both_cmd() {
    local ip="$1"
    local remote_bin="$2"
    local port="${HOST_PORT[$ip]}"
    local numas="${HOST_NUMAS[$ip]:-0}"
    local bind_node="${numas%%,*}"
    local serves="${HOST_SERVES[$ip]:-}"
    local tgts="${HOST_TARGETS[$ip]:-}"

    local prefix=""
    if [ -n "$bind_node" ]; then
        prefix="\$(command -v numactl >/dev/null 2>&1 && echo \"numactl --cpunodebind=${bind_node} --membind=${bind_node}\" || { echo \"[WARN] numactl not found on \$(hostname); scatter_test will run without NUMA binding\" >&2; echo \"\"; })"
    fi

    local cmd="${prefix} ${remote_bin} --mode both"
    cmd+=" --host-id ${ip}:${port}"
    cmd+=" --tcp-port ${port}"
    cmd+=" --num-numas ${numas}"
    # Global barrier: scatter_test will block here after publishing buffers
    # until the driver writes the go-file (Step 6.5 below). This guarantees
    # that no initiator workload starts connecting before *every* peer has
    # finished publishing and reached the "Ready" marker.
    cmd+=" --wait-go-file /tmp/mpcomm_go_${port}"

    # All --serve entries (order does not matter).
    if [ -n "$serves" ]; then
        local s cid sz nn
        IFS='|' read -r -a _sv_arr <<< "$serves"
        for s in "${_sv_arr[@]}"; do
            [ -z "$s" ] && continue
            cmd+=" --serve ${s}"
        done
    fi

    # --target entries, grouped by --job. We print one --job header per job so
    # scatter_test splits the benchmark rounds correctly.
    if [ -n "$tgts" ]; then
        # Collect jobs in order of first appearance.
        local -a job_order=()
        declare -A _job_seen=()
        local t cid jname peer_ip peer_port peer_numa peer_hostid
        IFS='|' read -r -a _tg_arr <<< "$tgts"
        for t in "${_tg_arr[@]}"; do
            [ -z "$t" ] && continue
            jname="${t#*:}"; jname="${jname%%:*}"
            if [ -z "${_job_seen[$jname]:-}" ]; then
                job_order+=("$jname")
                _job_seen[$jname]=1
            fi
        done

        local j
        for j in "${job_order[@]}"; do
            cmd+=" --job ${j}"
            # Per-job overrides come next so they apply to the upcoming
            # --target entries. scatter_test does not re-parse --size inside
            # a --job block, so we repeat them at the top of each job block
            # too (last-wins semantics).
            local v
            v="$(get_param "$j" size)";        [ -n "$v" ] && cmd+=" --size $v"
            v="$(get_param "$j" iterations)";  [ -n "$v" ] && cmd+=" --iterations $v"
            v="$(get_param "$j" warmup)";      [ -n "$v" ] && cmd+=" --warmup $v"
            v="$(get_param "$j" batch-size)";  [ -n "$v" ] && cmd+=" --batch-size $v"
            v="$(get_param "$j" gpu)";         [ -n "$v" ] && cmd+=" --gpu $v"
            v="$(get_param "$j" both)";        [ "$v" = "true" ] && cmd+=" --both"
            v="$(get_param "$j" test-type)";   [ -n "$v" ] && cmd+=" --test-type $v"

            for t in "${_tg_arr[@]}"; do
                [ -z "$t" ] && continue
                cid="${t%%:*}"
                rest="${t#*:}"
                jname="${rest%%:*}"
                [ "$jname" = "$j" ] || continue
                rest="${rest#*:}"
                peer_ip="${rest%%:*}"
                rest="${rest#*:}"
                peer_port="${rest%%:*}"
                peer_numa="${rest#*:}"
                # host_id used by MPComm on the peer = "ip:port".
                peer_hostid="${peer_ip}:${peer_port}"
                cmd+=" --target ${peer_hostid}:${peer_ip}:${peer_port}:${cid}:${peer_numa}"
            done
        done
    fi

    echo "$cmd"
}

declare -a HOST_CMD=()
declare -a HOST_REMOTE_PID=()
for ip in "${HOST_LIST[@]}"; do
    bin="${HOST_BINARY[$ip]}"
    HOST_CMD+=("$(build_host_both_cmd "$ip" "$bin")")
    HOST_REMOTE_PID+=("")
done

# Print the full plan before launching
for i in $(seq 0 $((${#HOST_LIST[@]} - 1))); do
    log_info "  ${HOST_LIST[$i]} :: ${HOST_CMD[$i]}"
done

if $DRY_RUN; then
    log_warn "DRY RUN - skipping actual execution"
    exit 0
fi

_mit_start_both() {
    local slot="$1" ip="$2"
    local port="${HOST_PORT[$ip]}"
    local cmd="${HOST_CMD[$slot]}"
    local workdir="${HOST_WORKDIR[$ip]}"
    local tag="mpcomm_both_${port}"
    local launcher="/tmp/${tag}.sh"
    local pid_file="/tmp/${tag}.pid"
    local log_file="/tmp/${tag}.log"
    local exitcode_file="/tmp/${tag}.exitcode"
    local pid_sentinel="/tmp/mit_both_pid_$$_${slot}"

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

    echo "----- both-launcher content for ${ip} (${launcher}) -----"
    echo "${launcher_body}"
    echo "----- end launcher content -----"

    printf '%s\n' "${launcher_body}" \
        | $(ssh_cmd "$ip") "rm -f '${exitcode_file}' '${pid_file}' '${log_file}' '/tmp/mpcomm_go_${port}'; cat > '${launcher}' && chmod +x '${launcher}'"

    $(ssh_cmd "$ip") "nohup setsid '${launcher}' </dev/null >/dev/null 2>&1 & disown 2>/dev/null; exit 0"
    sleep 1

    local remote_pid
    remote_pid=$($(ssh_cmd "$ip") "cat ${pid_file} 2>/dev/null" || echo "")
    remote_pid=$(echo "$remote_pid" | tail -1 | tr -d '[:space:]')

    if [ -n "$remote_pid" ] && [ "$remote_pid" -gt 0 ] 2>/dev/null; then
        echo "$remote_pid" > "$pid_sentinel"
        echo "[$slot] $ip:$port - started (launcher PID: $remote_pid)"
        return 0
    fi
    echo "[$slot] $ip:$port - failed to start 'both' process"
    return 1
}

start_failed=()
parallel_foreach_ip _mit_start_both "start_both" start_failed "${HOST_LIST[@]}"

START_FAIL=false
for slot in $(seq 0 $((${#HOST_LIST[@]} - 1))); do
    ip="${HOST_LIST[$slot]}"
    port="${HOST_PORT[$ip]}"
    sentinel="/tmp/mit_both_pid_$$_${slot}"
    if [ -f "$sentinel" ]; then
        pid=$(cat "$sentinel")
        HOST_REMOTE_PID[$slot]="$pid"
        LAUNCHED_TARGETS+=("${ip}:${port}")
        rm -f "$sentinel"
        log_info "  [$slot] $ip:$port - 'both' process running (PID: $pid)"
    else
        log_error "  [$slot] $ip:$port - failed to start"
        START_FAIL=true
    fi
done
if $START_FAIL; then
    log_error "One or more 'both' processes failed to start. Aborting."
    exit 1
fi
echo ""

# =============================================================================
# Step 6: Wait for every host to finish publishing its serve buffers and
# reach the "Ready - waiting for connections" marker. (Hosts with no --serve
# still reach this marker; the binary prints it after startAcceptThread.)
# =============================================================================
log_step "Step 6: Waiting for all 'both' processes to be ready (timeout: ${STARTUP_WAIT}s)..."
ALL_READY=true
# Match both the new both-mode marker and the legacy target-mode marker.
BOTH_READY_REGEX='Ready - waiting for connections\|Waiting for connections'

if ! $DRY_RUN; then
    PHASE_A_ROUNDS=3
    PENDING=()
    for slot in $(seq 0 $((${#HOST_LIST[@]} - 1))); do
        PENDING+=("$slot")
    done

    _mit_ready_check() {
        local slot="$1" ip="$2"
        local port="${HOST_PORT[$ip]}"
        local pid="${HOST_REMOTE_PID[$slot]}"
        local log_file="/tmp/mpcomm_both_${port}.log"
        local ready_sentinel="/tmp/mit_ready_$$_${slot}"
        local dead_sentinel="/tmp/mit_dead_$$_${slot}"

        local status
        status=$($(ssh_cmd "$ip") "
            if ! kill -0 $pid 2>/dev/null; then
                echo DEAD
                tail -20 ${log_file} 2>/dev/null
                exit 0
            fi
            if grep -q '${BOTH_READY_REGEX}' ${log_file} 2>/dev/null; then
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
        log_info "  Round $round: checking ${#PENDING[@]} host(s)..."
        _ips=()
        for slot in "${PENDING[@]}"; do _ips+=("${HOST_LIST[$slot]}"); done
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
                log_info "    [$slot] ${HOST_LIST[$slot]} - ready"
                rm -f "$ready_sentinel"
            elif [ -f "$dead_sentinel" ]; then
                log_error "    [$slot] ${HOST_LIST[$slot]} - process DIED"
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
        log_info "  Phase B: polling ${#PENDING[@]} slow host(s) individually..."
        MAX_ELAPSED=$((STARTUP_WAIT - PHASE_A_ROUNDS))
        [ "$MAX_ELAPSED" -lt 5 ] && MAX_ELAPSED=5
        for slot in "${PENDING[@]}"; do
            ip="${HOST_LIST[$slot]}"
            port="${HOST_PORT[$ip]}"
            pid="${HOST_REMOTE_PID[$slot]}"
            LOG_FILE="/tmp/mpcomm_both_${port}.log"
            log_info "  [$slot] Waiting for $ip (max ${MAX_ELAPSED}s)..."
            ELAPSED=0
            READY=false
            while [ "$ELAPSED" -lt "$MAX_ELAPSED" ]; do
                if ! $(ssh_cmd "$ip") "kill -0 $pid 2>/dev/null"; then
                    log_error "  [$slot] $ip (PID $pid) - process died during startup"
                    $(ssh_cmd "$ip") "tail -20 ${LOG_FILE} 2>/dev/null" || true
                    ALL_READY=false
                    break
                fi
                if $(ssh_cmd "$ip") "grep -q '${BOTH_READY_REGEX}' ${LOG_FILE} 2>/dev/null"; then
                    READY=true
                    break
                fi
                sleep 1
                ELAPSED=$((ELAPSED + 1))
            done
            if $READY; then
                log_info "  [$slot] $ip - ready"
            elif $ALL_READY; then
                log_error "  [$slot] $ip - NOT ready after ${STARTUP_WAIT}s"
                $(ssh_cmd "$ip") "tail -20 ${LOG_FILE} 2>/dev/null" || true
                ALL_READY=false
            fi
        done
    fi
fi

if ! $ALL_READY && ! $DRY_RUN; then
    log_error "Some 'both' processes failed to become ready. Aborting."
    exit 1
fi
log_info "All ${#HOST_LIST[@]} host(s) ready. Initiator workloads will now run inside each 'both' process."
echo ""

# =============================================================================
# Step 6.5: Global barrier - now that every host has reached the "Ready"
# marker (i.e. has finished publishAll buffers and started its accept thread),
# touch the go-file on every host so that the scatter_test processes can
# leave their --wait-go-file barrier and start the initiator workload.
# =============================================================================
if ! $DRY_RUN; then
    log_step "Step 6.5: Releasing global barrier (touching go-file on all hosts)..."
    _mit_touch_go() {
        local slot="$1" ip="$2"
        local port="${HOST_PORT[$ip]}"
        $(ssh_cmd "$ip") "touch /tmp/mpcomm_go_${port}" >/dev/null 2>&1
    }
    go_failed=()
    parallel_foreach_ip _mit_touch_go "touch_go" go_failed "${HOST_LIST[@]}"
    if [ ${#go_failed[@]} -gt 0 ]; then
        log_warn "  Failed to touch go-file on ${#go_failed[@]} host(s); they may stall."
    fi
    log_info "Barrier released."
    echo ""
fi

# =============================================================================
# Step 7: Wait for every logical job to finish. A job is finished when its
# initiator host's log contains the line "[both] Job '<name>' complete." or
# "[both] Job '<name>' failed". The 'both' process keeps running afterwards
# (serving buffers), so we don't wait for process exit.
# =============================================================================
log_step "Step 7: Waiting for ${#JOB_NAMES[@]} job(s) to complete (heartbeat every 10s)..."

declare -A JOB_STATUS=()   # job_name -> OK | FAIL | TIMEOUT
PENDING_JOBS=("${JOB_NAMES[@]}")
START_TS=$(date +%s)
LAST_TICK=0

# Map each job to its initiator's host + remote log path.
declare -A JOB_LOGFILE=()
declare -A JOB_HOST=()
for name in "${JOB_NAMES[@]}"; do
    ini_ip="${JOB_INI_IP[$name]}"
    ini_port="${HOST_PORT[$ini_ip]}"
    JOB_HOST[$name]="$ini_ip"
    JOB_LOGFILE[$name]="/tmp/mpcomm_both_${ini_port}.log"
done

while [ ${#PENDING_JOBS[@]} -gt 0 ]; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TS))

    if [ $((ELAPSED - LAST_TICK)) -ge 10 ]; then
        LAST_TICK=$ELAPSED
        log_info "  [${ELAPSED}s] still running: ${PENDING_JOBS[*]}"
    fi

    if [ "$JOB_TIMEOUT" -gt 0 ] && [ "$ELAPSED" -gt "$JOB_TIMEOUT" ]; then
        log_error "Job timeout (${JOB_TIMEOUT}s) reached; marking remaining jobs as TIMEOUT."
        for j in "${PENDING_JOBS[@]}"; do JOB_STATUS[$j]="TIMEOUT"; done
        break
    fi

    NEW_PENDING=()
    for name in "${PENDING_JOBS[@]}"; do
        ip="${JOB_HOST[$name]}"
        logf="${JOB_LOGFILE[$name]}"
        # Find the pid of this host's 'both' launcher so we can detect death.
        host_slot=""
        for _s in $(seq 0 $((${#HOST_LIST[@]} - 1))); do
            if [ "${HOST_LIST[$_s]}" = "$ip" ]; then host_slot="$_s"; break; fi
        done
        host_pid="${HOST_REMOTE_PID[$host_slot]:-}"
        # Check for completion marker. Grep returns a non-empty line for OK,
        # another for FAIL. We escape the single quotes around the job name
        # in the search pattern by using double quotes on the remote side.
        status=$($(ssh_cmd "$ip") "
            if grep -q \"\\[both\\] Job '${name}' complete\\.\" ${logf} 2>/dev/null; then
                echo OK
            elif grep -q \"\\[both\\] Job '${name}' failed\" ${logf} 2>/dev/null; then
                echo FAIL
            elif [ -n '${host_pid}' ] && ! kill -0 ${host_pid:-1} 2>/dev/null; then
                echo DEAD
            else
                echo PENDING
            fi
        " 2>/dev/null | tail -1 | tr -d '[:space:]')

        case "$status" in
            OK)   JOB_STATUS[$name]="OK";   log_info "  [${name}] OK (after ${ELAPSED}s)" ;;
            FAIL) JOB_STATUS[$name]="FAIL"; log_error "  [${name}] FAIL (after ${ELAPSED}s)" ;;
            DEAD) JOB_STATUS[$name]="FAIL"; log_error "  [${name}] FAIL - 'both' process on $ip died before the job finished" ;;
            *)    NEW_PENDING+=("$name") ;;
        esac
    done
    PENDING_JOBS=("${NEW_PENDING[@]}")
    [ ${#PENDING_JOBS[@]} -gt 0 ] && sleep 2
done

echo ""

# =============================================================================
# Step 8: Fetch each host's 'both' log, then extract the per-job slice by
# matching the "[both] === Running job 'NAME' ===" / "[both] Job 'NAME'
# complete." bracket markers emitted by scatter_test.
# =============================================================================
log_step "Step 8: Fetching 'both' logs from every host..."
declare -A HOST_LOCAL_LOG=()
for ip in "${HOST_LIST[@]}"; do
    port="${HOST_PORT[$ip]}"
    local_log="/tmp/mpcomm_both_${ip}_${port}.log"
    if $(ssh_cmd "$ip") "cat /tmp/mpcomm_both_${port}.log" > "$local_log" 2>/dev/null; then
        HOST_LOCAL_LOG[$ip]="$local_log"
        log_info "  $ip - log saved to $local_log"
    else
        log_warn "  $ip - failed to fetch log"
        HOST_LOCAL_LOG[$ip]=""
    fi
done
echo ""

# Slice each host's log into per-job chunks, one file per job.
declare -A JOB_LOCAL_LOG=()
for name in "${JOB_NAMES[@]}"; do
    ip="${JOB_HOST[$name]}"
    src="${HOST_LOCAL_LOG[$ip]:-}"
    dst="/tmp/mpcomm_job_${name}.log"
    if [ -z "$src" ] || [ ! -f "$src" ]; then
        JOB_LOCAL_LOG[$name]=""
        continue
    fi
    # awk: print lines between the job's opening marker (inclusive) and the
    # closing marker (inclusive). scatter_test emits:
    #   opening : [both] === Running job 'NAME' with N target(s) ===
    #   closing : [both] Job 'NAME' complete.
    #             [both] Job 'NAME' failed ...
    # We match the opening line by prefix (up to and including "'NAME'") so
    # we do not depend on the " with N target(s) ===" suffix wording. If the
    # closing marker is missing (e.g. the process died mid-benchmark), we
    # still emit everything from the opening marker to EOF.
    awk -v jn="$name" '
        BEGIN {
            inside = 0
            open_tag  = "[both] === Running job \x27" jn "\x27"
            close_ok  = "[both] Job \x27" jn "\x27 complete."
            close_bad = "[both] Job \x27" jn "\x27 failed"
        }
        {
            if (!inside && index($0, open_tag) > 0) {
                inside = 1
            }
            if (inside) {
                print
            }
            if (inside && (index($0, close_ok) > 0 || index($0, close_bad) > 0)) {
                inside = 0
            }
        }
    ' "$src" > "$dst" 2>/dev/null || true
    if [ -s "$dst" ]; then
        JOB_LOCAL_LOG[$name]="$dst"
    else
        JOB_LOCAL_LOG[$name]=""
    fi
done

# =============================================================================
# Step 9: Print per-job results
# =============================================================================
echo "============================================================"
echo "  Results"
echo "============================================================"
ALL_OK=true
for name in "${JOB_NAMES[@]}"; do
    st="${JOB_STATUS[$name]:-UNKNOWN}"
    echo ""
    echo "------------------------------------------------------------"
    if [ "$st" = "OK" ]; then
        echo "  [${name}] SUCCESS (${JOB_HOST[$name]})"
    else
        echo "  [${name}] FAILED/$(echo "$st" | tr '[:upper:]' '[:lower:]') (${JOB_HOST[$name]})"
        ALL_OK=false
    fi
    echo "------------------------------------------------------------"
    logf="${JOB_LOCAL_LOG[$name]:-}"
    if $SHOW_LOGS; then
        if [ -n "$logf" ] && [ -f "$logf" ]; then
            cat "$logf"
        else
            echo "(log unavailable)"
        fi
    else
        if [ -n "$logf" ] && [ -f "$logf" ]; then
            echo "  (per-job log: $logf  --  rerun with --show-logs to print inline)"
        else
            echo "  (log unavailable)"
        fi
    fi
done

# =============================================================================
# Step 10: Stop every 'both' process (they are still running, serving buffers)
# =============================================================================
echo ""
log_step "Step 10: Stopping all 'both' processes..."
_stop_pids=()
for slot in $(seq 0 $((${#HOST_LIST[@]} - 1))); do
    ip="${HOST_LIST[$slot]}"
    port="${HOST_PORT[$ip]}"
    (
        $(ssh_cmd "$ip") "pkill -f 'mpcomm_both_${port}\\.sh' 2>/dev/null; \
                          pkill -f 'scatter_test --mode both --host-id ${ip}:${port}' 2>/dev/null; \
                          true" 2>/dev/null || true
    ) &
    _stop_pids+=($!)
done
for p in "${_stop_pids[@]}"; do wait "$p" 2>/dev/null || true; done
log_info "Stop signal sent."
echo ""

# =============================================================================
# Final bandwidth summary: same extractor as before, but now labels come from
# "--- <TestType> DRAM@<job> Summary" / "--- <TestType> HBM@<job> Summary"
# lines emitted by scatter_test in both mode. We parse the "@<job>" suffix to
# attribute each row to its originating job. Standalone (no @job) labels from
# initiator-mode logs are still supported for backward compatibility.
# =============================================================================
echo "============================================================"
echo "  Bandwidth Summary"
echo "============================================================"
SUM_FMT_HEADER="  %-14s %-14s %14s %14s %14s\n"
SUM_FMT_NUM="  %-14s %-14s %14.2f %14.2f %14.2f\n"
SUM_FMT_TEXT="  %-14s %-14s %14s %14s %14s\n"

printf "$SUM_FMT_HEADER" \
    "Job" "Test" "AvgBW(GB/s)" "BestBW(GB/s)" "WorstBW(GB/s)"
printf "$SUM_FMT_HEADER" \
    "--------------" "--------------" "--------------" "--------------" "--------------"

for name in "${JOB_NAMES[@]}"; do
    st="${JOB_STATUS[$name]:-UNKNOWN}"
    logf="${JOB_LOCAL_LOG[$name]:-}"

    if [ "$st" != "OK" ]; then
        printf "$SUM_FMT_TEXT" \
            "$name" "-" "$st" "$st" "$st"
        continue
    fi
    if [ -z "$logf" ] || [ ! -f "$logf" ]; then
        printf "$SUM_FMT_TEXT" \
            "$name" "-" "(no log)" "(no log)" "(no log)"
        continue
    fi

    awk -v jobname="$name" '
        function extract_num(line, p,    rest) {
            rest = substr(line, p)
            if (match(rest, /[0-9]+\.[0-9]+|[0-9]+/)) {
                return substr(rest, RSTART, RLENGTH)
            }
            return ""
        }
        function extract_gbs(line, p,    q) {
            q = index(substr(line, p), "Gbps")
            if (q <= 0) return ""
            return extract_num(line, p + q - 1 + length("Gbps"))
        }

        # "--- Scatter DRAM@jobA Summary (..." or "--- Scatter DRAM Summary ("
        /^---[[:space:]]+[A-Za-z]+[[:space:]]+[A-Za-z0-9@_()[:space:]]+Summary/ {
            # $2 = test type, $3..$(NF-1) assembled back to mem label.
            test_type = $2
            mem = $3
            # Strip "@jobname" suffix if present.
            at = index(mem, "@")
            if (at > 0) mem = substr(mem, 1, at - 1)
            label = test_type "/" mem
            avg = ""; best = ""; worst = ""
            next
        }
        /Aggregate Avg:/ {
            p = index($0, "(")
            if (p > 0) avg = extract_gbs($0, p + 1)
        }
        /Best BW:/ {
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
