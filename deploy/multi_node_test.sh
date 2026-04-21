#!/bin/bash
# =============================================================================
# MPComm Multi-Node Test Script
#
# Orchestrates scatter/gather/broadcast performance tests across multiple
# machines via SSH. Starts target processes on remote hosts, runs the
# initiator locally, and cleans up when done.
#
# Prerequisites:
#   - Run deploy_all.sh first (or ensure mpcomm + scatter_test are ready)
#   - SSH passwordless login configured between all machines
#
# Usage:
#   bash multi_node_test.sh [options]
#
# Examples:
#   # Basic: use hosts.txt, default settings
#   bash multi_node_test.sh
#
#   # Custom hosts file, 1GB scatter test with GPU
#   bash multi_node_test.sh --hosts my_hosts.txt --size 1G --gpu 2 --test-type scatter
#
#   # Large-scale: 15 targets, gather test, 100 iterations
#   bash multi_node_test.sh --hosts hosts.txt --test-type gather --iterations 100
#
#   # Run all test types with both DRAM and HBM
#   bash multi_node_test.sh --test-type scatter,gather,broadcast --gpu 0 --both
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---- Test-specific defaults ----
SKIP_DEPLOY=false              # --skip-deploy to skip auto-deployment
BUFFER_SIZE="2G"                # Target buffer size
SIZE=""                         # Initiator per-target size (empty = use binary default)
ITERATIONS=""                   # empty = use binary default
WARMUP=""
BATCH_SIZE=""
GPU_DEVICE=""                   # empty = DRAM only
RUN_BOTH=""                     # --both flag
TEST_TYPE=""                    # empty = all (scatter,gather,broadcast)
NUM_NUMAS=""                    # Initiator NUMA nodes override
TARGET_NUMAS=""                 # Target NUMA nodes override (per-host default from hosts.txt)
REMOTE_WORK_DIR=""              # empty = same as local SCRIPT_DIR
STARTUP_WAIT=30                 # Timeout (seconds) for targets to become ready

# ---- MPComm Environment Variables ----
# These will be exported on both local and remote machines.
# Override via environment or edit defaults here.
MPCOMM_NIC_FILTER="${MPCOMM_NIC_FILTER:-mlx5_bond_1,mlx5_bond_2,mlx5_bond_3,mlx5_bond_4,mlx5_bond_5,mlx5_bond_6,mlx5_bond_7,mlx5_bond_8}"
MPCOMM_QPS_PER_CONNECTION="${MPCOMM_QPS_PER_CONNECTION:-4}"
MPCOMM_POLL_INTERVAL="${MPCOMM_POLL_INTERVAL:-16}"
MPCOMM_MAX_SEND_WR="${MPCOMM_MAX_SEND_WR:-128}"
MPCOMM_PXN_ENABLE="${MPCOMM_PXN_ENABLE:-0}"
MPCOMM_PXN_NVLINK_ALPHA="${MPCOMM_PXN_NVLINK_ALPHA:-5}"
MPCOMM_LOG_LEVEL="${MPCOMM_LOG_LEVEL:-}"

# Derived from PXN setting
if [ "${MPCOMM_PXN_ENABLE}" -eq 1 ]; then
    MPCOMM_MAX_RDMA_TRANSFER_SIZE="${MPCOMM_MAX_RDMA_TRANSFER_SIZE:-2097152}"
    MPCOMM_MAX_OUTSTANDING_PER_QP="${MPCOMM_MAX_OUTSTANDING_PER_QP:-1}"
else
    MPCOMM_MAX_RDMA_TRANSFER_SIZE="${MPCOMM_MAX_RDMA_TRANSFER_SIZE:-65536}"
    MPCOMM_MAX_OUTSTANDING_PER_QP="${MPCOMM_MAX_OUTSTANDING_PER_QP:-16}"
fi

# ---- Build Environment Export String ----
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
Usage: $(basename "$0") [options]

Multi-node MPComm test orchestrator. Starts targets via SSH, runs initiator locally.
Run deploy_all.sh first to ensure mpcomm and scatter_test are ready on all machines.

Options:
  --hosts FILE          Host list file (default: hosts.txt)
  --binary PATH         Path to scatter_test binary (default: ./build/scatter_test)
  --buffer-size SIZE    Target buffer size, e.g. 2G (default: 2G)
  --size SIZE           Initiator per-target data size in bytes (default: binary default)
  --iterations N        Number of timed iterations (default: binary default)
  --warmup N            Number of warmup iterations (default: binary default)
  --batch-size N        Async requests per batch (default: binary default)
  --gpu DEVICE          GPU device ID for HBM test (default: DRAM only)
  --both                Run both DRAM and HBM tests
  --test-type TYPES     Comma-separated: scatter,gather,broadcast (default: all)
  --num-numas NODES     Initiator NUMA nodes, e.g. "0,1" (default: from hosts.txt)
  --target-numas NODES  Override target NUMA nodes for all targets
  --ssh-user USER       SSH username (default: root)
  --ssh-port PORT       SSH port (default: 36001)
  --remote-dir DIR      Working directory on remote machines (default: same as local)
  --deploy-url URL      Custom deploy script URL (for auto-deploy)
  --deploy-tests-url URL Custom test deploy script URL
  --tests-dir DIR        Test files install directory (default: /opt/mpcomm_tests)
  --version VER         mpcomm version to deploy (default: resolved from VERSION file on mirror)
  --skip-deploy         Skip auto-deployment, fail if mpcomm not installed
--startup-wait SECS   Timeout for targets to become ready (default: 30)
  --parallel N          Max concurrent SSH operations (default: 20)
  --verbose             Enable verbose output
  --dry-run             Print commands without executing
  -h, --help            Show this help

Environment Variables (override via export before running):
  MPCOMM_NIC_FILTER, MPCOMM_QPS_PER_CONNECTION, MPCOMM_POLL_INTERVAL,
  MPCOMM_MAX_SEND_WR, MPCOMM_PXN_ENABLE, MPCOMM_PXN_NVLINK_ALPHA,
  MPCOMM_MAX_RDMA_TRANSFER_SIZE, MPCOMM_MAX_OUTSTANDING_PER_QP,
  MPCOMM_LOG_LEVEL

Examples:
  # 15-target scatter test
  $(basename "$0") --hosts hosts.txt --test-type scatter --size 1000000000

  # Gather test with GPU on 8 targets
  $(basename "$0") --hosts hosts_8.txt --test-type gather --gpu 0 --iterations 50

  # Full benchmark: all ops, DRAM+HBM, dual NUMA
  $(basename "$0") --test-type scatter,gather,broadcast --gpu 0 --both --num-numas 0,1
EOF
    exit 0
}

# ---- Parse Arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hosts)          HOSTS_FILE="$2"; shift 2 ;;
        --binary)         BINARY_PATH="$2"; shift 2 ;;
        --buffer-size)    BUFFER_SIZE="$2"; shift 2 ;;
        --size)           SIZE="$2"; shift 2 ;;
        --iterations)     ITERATIONS="$2"; shift 2 ;;
        --warmup)         WARMUP="$2"; shift 2 ;;
        --batch-size)     BATCH_SIZE="$2"; shift 2 ;;
        --gpu)            GPU_DEVICE="$2"; shift 2 ;;
        --both)           RUN_BOTH="--both"; shift ;;
        --test-type)      TEST_TYPE="$2"; shift 2 ;;
        --num-numas)      NUM_NUMAS="$2"; shift 2 ;;
        --target-numas)   TARGET_NUMAS="$2"; shift 2 ;;
        --ssh-user)       SSH_USER="$2"; shift 2 ;;
        --ssh-port)       SSH_PORT="$2"; shift 2 ;;
        --remote-dir)     REMOTE_WORK_DIR="$2"; shift 2 ;;
        --deploy-url)     DEPLOY_URL="$2"; shift 2 ;;
        --deploy-tests-url) DEPLOY_TESTS_URL="$2"; shift 2 ;;
        --tests-dir)      TESTS_INSTALL_DIR="$2"; shift 2 ;;
        --version)        MPCOMM_VERSION="$2"; shift 2 ;;
        --version=*)      MPCOMM_VERSION="${1#*=}"; shift ;;
        --skip-deploy)    SKIP_DEPLOY=true; shift ;;
        --startup-wait)   STARTUP_WAIT="$2"; shift 2 ;;
        --parallel)       PARALLEL_JOBS="$2"; shift 2 ;;
        --verbose)        VERBOSE=true; shift ;;
        --dry-run)        DRY_RUN=true; shift ;;
        -h|--help)        usage ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# ---- Main ----
parse_hosts "$HOSTS_FILE"

if ! [[ "$PARALLEL_JOBS" =~ ^[0-9]+$ ]] || [ "$PARALLEL_JOBS" -lt 1 ]; then
    log_error "--parallel must be a positive integer (got: $PARALLEL_JOBS)"
    exit 1
fi

# Resolve the target version once so every node deploys the same version.
if ! $DRY_RUN && ! $SKIP_DEPLOY; then
    resolve_mpcomm_version || exit 1
fi

# ---- Cleanup Function ----
REMOTE_PIDS=()
CLEANUP_DONE=false
SSH_VERIFIED=false

cleanup() {
    if $CLEANUP_DONE; then
        return 0
    fi
    CLEANUP_DONE=true

    echo ""
    log_step "Cleaning up remote target processes..."

    # Kill tracked PIDs in parallel
    if [ ${#REMOTE_PIDS[@]} -gt 0 ]; then
        local pids=()
        for entry in "${REMOTE_PIDS[@]}"; do
            [ -z "$entry" ] && continue
            local cip="${entry%%:*}"
            local cpid="${entry#*:}"
            log_info "  Killing PID $cpid on $cip"
            ( $(ssh_cmd "$cip") "kill $cpid 2>/dev/null; kill -9 $cpid 2>/dev/null" 2>/dev/null || true ) &
            pids+=($!)
        done
        for p in "${pids[@]}"; do wait "$p" 2>/dev/null || true; done
    fi

    # Broad pkill in parallel
    if $SSH_VERIFIED; then
        local pids=()
        for cip in "${TARGET_IPS[@]}"; do
            ( $(ssh_cmd "$cip") "pkill -f 'scatter_test --mode target' 2>/dev/null" 2>/dev/null || true ) &
            pids+=($!)
        done
        for p in "${pids[@]}"; do wait "$p" 2>/dev/null || true; done
    fi

    # Clean up parallel log dir if we created one and the user didn't ask for verbose
    if [ -d "${PARALLEL_LOG_DIR:-}" ] && ! $VERBOSE; then
        rm -rf "$PARALLEL_LOG_DIR" 2>/dev/null || true
    fi

    log_info "Cleanup done."
}

trap cleanup EXIT INT TERM

# ---- Print Configuration ----
echo ""
echo "============================================================"
echo "  MPComm Multi-Node Test"
echo "============================================================"
echo "  Hosts file:    $HOSTS_FILE"
echo "  Binary:        $BINARY_PATH"
echo "  Initiator:     $INITIATOR_IP (port: $INITIATOR_PORT, NUMA: $INITIATOR_NUMAS)"
echo "  Targets:       $NUM_TARGETS machine(s)"
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    echo "    [$i] ${TARGET_IPS[$i]}:${TARGET_PORTS[$i]} (NUMA: ${TARGET_NUMA_LIST[$i]})"
done
echo "  Test type:     ${TEST_TYPE:-all (scatter,gather,broadcast)}"
echo "  Buffer size:   ${BUFFER_SIZE} (target)"
[ -n "$SIZE" ]       && echo "  Data size:     ${SIZE} (per target)"
[ -n "$ITERATIONS" ] && echo "  Iterations:    ${ITERATIONS}"
[ -n "$BATCH_SIZE" ] && echo "  Batch size:    ${BATCH_SIZE}"
[ -n "$GPU_DEVICE" ] && echo "  GPU device:    ${GPU_DEVICE}"
[ -n "$RUN_BOTH" ]   && echo "  DRAM + HBM:    yes"
echo "  PXN:           ${MPCOMM_PXN_ENABLE}"
echo "  Parallel:      $PARALLEL_JOBS concurrent SSH jobs"
echo "============================================================"
echo ""

if $DRY_RUN; then
    log_warn "DRY RUN mode - commands will be printed but not executed"
    echo ""
fi

# ---- Step 1: Verify SSH Connectivity ----
log_step "Step 1: Verifying SSH connectivity to all targets..."
verify_ssh

# ---- Step 2: Check mpcomm & auto-deploy if needed ----
log_step "Step 2: Checking mpcomm installation on all machines..."

DEPLOY_NEEDED_IPS=()

# Check local (initiator) machine
if ! $DRY_RUN; then
    if python3 -c 'import mpcomm' 2>/dev/null; then
        LOCAL_VER=$(python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null || echo "unknown")
        log_info "  [local] $INITIATOR_IP - mpcomm installed (version: $LOCAL_VER)"
    else
        log_warn "  [local] $INITIATOR_IP - mpcomm NOT installed"
        DEPLOY_NEEDED_IPS+=("LOCAL")
    fi
else
    log_debug "  Would check mpcomm on local machine"
fi

# Check remote (target) machines in parallel
if ! $DRY_RUN; then
    _mt_check_mpcomm() {
        local idx="$1"
        local ip="$2"
        local sentinel="/tmp/mt_mpcomm_ok_$$_${idx}"
        if $(ssh_cmd "$ip") "python3 -c 'import mpcomm' 2>/dev/null" &>/dev/null; then
            local ver
            ver=$($(ssh_cmd "$ip") "python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null" || echo "unknown")
            echo "$ver" > "$sentinel"
            echo "INSTALLED version=$ver on $ip"
            return 0
        fi
        echo "NOT_INSTALLED on $ip"
        return 0
    }
    CHECK_FAILED=()
    parallel_foreach_host _mt_check_mpcomm "check_mpcomm" CHECK_FAILED

    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        ip="${TARGET_IPS[$i]}"
        sentinel="/tmp/mt_mpcomm_ok_$$_${i}"
        if [ -f "$sentinel" ]; then
            REMOTE_VER=$(cat "$sentinel")
            log_info "  [$i] $ip - mpcomm installed (version: $REMOTE_VER)"
            rm -f "$sentinel"
        else
            log_warn "  [$i] $ip - mpcomm NOT installed"
            DEPLOY_NEEDED_IPS+=("$ip")
        fi
    done
else
    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        log_debug "  Would check mpcomm on ${TARGET_IPS[$i]}"
    done
fi

if [ ${#DEPLOY_NEEDED_IPS[@]} -gt 0 ]; then
    if $SKIP_DEPLOY; then
        log_error "mpcomm not installed on ${#DEPLOY_NEEDED_IPS[@]} machine(s) and --skip-deploy is set."
log_error "Run deploy_all.sh first, or remove --skip-deploy to auto-deploy."
        exit 1
    fi

    log_step "Auto-deploying mpcomm on ${#DEPLOY_NEEDED_IPS[@]} machine(s) in parallel..."
    DEPLOY_FAIL=false

    # Deploy on local machine synchronously (if needed)
    for ip in "${DEPLOY_NEEDED_IPS[@]}"; do
        if [ "$ip" = "LOCAL" ]; then
            log_info "  Deploying mpcomm on local machine ($INITIATOR_IP) (this may take a few minutes)..."
            if $DRY_RUN; then
                log_debug "  Would run: wget -qO- '${DEPLOY_URL}' | bash -s -- --version=${MPCOMM_VERSION:-<latest>}"
                break
            fi
            DEPLOY_OUTPUT=$(wget -qO- "${DEPLOY_URL}" | bash -s -- --version="${MPCOMM_VERSION}" 2>&1) || {
                log_error "  local ($INITIATOR_IP) - deployment FAILED"
                log_error "  Output (last 20 lines):"
                echo "$DEPLOY_OUTPUT" | tail -20
                DEPLOY_FAIL=true
                break
            }
            if python3 -c 'import mpcomm' 2>/dev/null; then
                LOCAL_VER=$(python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null || echo "unknown")
                log_info "  local ($INITIATOR_IP) - mpcomm deployed successfully (version: $LOCAL_VER)"
            else
                log_error "  local ($INITIATOR_IP) - deployment completed but mpcomm import still fails"
                DEPLOY_FAIL=true
            fi
            break
        fi
    done

    # Deploy on remote targets in parallel
    REMOTE_DEPLOY_INDICES=()
    for ip in "${DEPLOY_NEEDED_IPS[@]}"; do
        [ "$ip" = "LOCAL" ] && continue
        for i in $(seq 0 $((NUM_TARGETS - 1))); do
            if [ "${TARGET_IPS[$i]}" = "$ip" ]; then
                REMOTE_DEPLOY_INDICES+=("$i")
                break
            fi
        done
    done

    if [ ${#REMOTE_DEPLOY_INDICES[@]} -gt 0 ] && ! $DRY_RUN; then
        log_info "  Deploying mpcomm on ${#REMOTE_DEPLOY_INDICES[@]} remote machine(s) (parallel: $PARALLEL_JOBS)..."
        _mt_deploy_mpcomm() {
            local idx="$1"
            local ip="$2"
            echo "=== Deploying mpcomm on $ip ==="
            if ! $(ssh_cmd "$ip") "wget -qO- '${DEPLOY_URL}' | bash -s -- --version=${MPCOMM_VERSION}" 2>&1; then
                echo "DEPLOY SCRIPT FAILED on $ip"
                return 1
            fi
            if ! $(ssh_cmd "$ip") "python3 -c 'import mpcomm' 2>/dev/null"; then
                echo "POST-DEPLOY IMPORT CHECK FAILED on $ip"
                return 1
            fi
            local ver
            ver=$($(ssh_cmd "$ip") "python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null" || echo "unknown")
            echo "Deployed successfully on $ip (version: $ver)"
            return 0
        }
        REMOTE_DEPLOY_FAILED=()
        parallel_foreach_host _mt_deploy_mpcomm "deploy_mpcomm" REMOTE_DEPLOY_FAILED "${REMOTE_DEPLOY_INDICES[@]}"
        if [ ${#REMOTE_DEPLOY_FAILED[@]} -gt 0 ]; then
            DEPLOY_FAIL=true
        fi
    elif $DRY_RUN; then
        for idx in "${REMOTE_DEPLOY_INDICES[@]}"; do
            log_debug "  Would run: $(ssh_cmd "${TARGET_IPS[$idx]}") 'wget -qO- \"${DEPLOY_URL}\" | bash -s -- --version=${MPCOMM_VERSION}'"
        done
    fi

    if $DEPLOY_FAIL; then
        log_error "Deployment failed on some machines. Aborting."
        exit 1
    fi
    log_info "All deployments successful."
else
    log_info "mpcomm already installed on all machines."
fi
echo ""

# ---- Step 3: Locate scatter_test binary on all targets ----
log_step "Step 3: Locating scatter_test binary on all targets (parallel: $PARALLEL_JOBS)..."

declare -a REMOTE_BINARY_PATHS=()
declare -a REMOTE_WORK_DIRS=()

ALL_BINARY_OK=true

if $DRY_RUN; then
    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        log_debug "  Would resolve binary path on ${TARGET_IPS[$i]}"
        REMOTE_BINARY_PATHS+=("${TESTS_INSTALL_DIR}/build/scatter_test")
        REMOTE_WORK_DIRS+=("${TESTS_INSTALL_DIR}")
    done
else
    # Phase 1: locate binary on each target in parallel.
    # Each worker writes "<binary_path>|<work_dir>" into a sentinel file on
    # success (binary present), or creates a "missing" marker otherwise.
    _mt_locate_binary() {
        local idx="$1"
        local ip="$2"
        local sentinel="/tmp/mt_bin_loc_$$_${idx}"

        if $(ssh_cmd "$ip") "test -x '${TESTS_INSTALL_DIR}/build/scatter_test'" &>/dev/null; then
            echo "${TESTS_INSTALL_DIR}/build/scatter_test|${TESTS_INSTALL_DIR}" > "$sentinel"
            echo "FOUND on $ip: ${TESTS_INSTALL_DIR}/build/scatter_test"
            return 0
        fi
        if [ -n "${REMOTE_WORK_DIR:-}" ] && \
           $(ssh_cmd "$ip") "test -x '${REMOTE_WORK_DIR}/${BINARY_PATH}'" &>/dev/null; then
            echo "${REMOTE_WORK_DIR}/${BINARY_PATH}|${REMOTE_WORK_DIR}" > "$sentinel"
            echo "FOUND (fallback) on $ip: ${REMOTE_WORK_DIR}/${BINARY_PATH}"
            return 0
        fi
        echo "NOT FOUND on $ip"
        # Not a failure; we will deploy in phase 2.
        return 0
    }
    LOCATE_FAILED=()
    parallel_foreach_host _mt_locate_binary "locate_binary" LOCATE_FAILED

    # Collect phase-1 results; figure out which indices need deploy
    BIN_DEPLOY_INDICES=()
    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        ip="${TARGET_IPS[$i]}"
        sentinel="/tmp/mt_bin_loc_$$_${i}"
        if [ -f "$sentinel" ]; then
            IFS='|' read -r _bin _wd < "$sentinel"
            REMOTE_BINARY_PATHS+=("$_bin")
            REMOTE_WORK_DIRS+=("$_wd")
            log_info "  [$i] $ip - binary found: $_bin"
            rm -f "$sentinel"
        else
            log_warn "  [$i] $ip - binary not found, will deploy tests"
            # Placeholder; will fill in after phase-2 deploy
            REMOTE_BINARY_PATHS+=("")
            REMOTE_WORK_DIRS+=("")
            BIN_DEPLOY_INDICES+=("$i")
        fi
    done

    # Phase 2: deploy tests on targets that need it, in parallel.
    if [ ${#BIN_DEPLOY_INDICES[@]} -gt 0 ]; then
        log_info "  Deploying tests on ${#BIN_DEPLOY_INDICES[@]} machine(s) (parallel: $PARALLEL_JOBS)..."
        _mt_deploy_tests() {
            local idx="$1"
            local ip="$2"
            local sentinel="/tmp/mt_bin_deploy_$$_${idx}"
            echo "=== Deploying tests on $ip ==="
            if ! $(ssh_cmd "$ip") "wget -qO- '${DEPLOY_TESTS_URL}' | bash -s -- --install-dir=${TESTS_INSTALL_DIR} --version=${MPCOMM_VERSION}" 2>&1; then
                echo "deploy_tests.sh FAILED on $ip"
                return 1
            fi
            if ! $(ssh_cmd "$ip") "test -x '${TESTS_INSTALL_DIR}/build/scatter_test'" &>/dev/null; then
                echo "Binary missing after deploy on $ip"
                return 1
            fi
            echo "${TESTS_INSTALL_DIR}/build/scatter_test|${TESTS_INSTALL_DIR}" > "$sentinel"
            echo "Deployed successfully on $ip"
            return 0
        }
        BIN_DEPLOY_FAILED=()
        parallel_foreach_host _mt_deploy_tests "deploy_tests" BIN_DEPLOY_FAILED "${BIN_DEPLOY_INDICES[@]}"

        for idx in "${BIN_DEPLOY_INDICES[@]}"; do
            sentinel="/tmp/mt_bin_deploy_$$_${idx}"
            if [ -f "$sentinel" ]; then
                IFS='|' read -r _bin _wd < "$sentinel"
                REMOTE_BINARY_PATHS[$idx]="$_bin"
                REMOTE_WORK_DIRS[$idx]="$_wd"
                rm -f "$sentinel"
            else
                ALL_BINARY_OK=false
            fi
        done
    fi
fi

if ! $ALL_BINARY_OK && ! $DRY_RUN; then
    log_error "Binary missing/build failed on some targets. Aborting."
    exit 1
fi
log_info "Binary verified on all targets."
echo ""

# ---- Step 4: Kill Any Existing Target Processes ----
log_step "Step 4: Cleaning up any existing target processes (parallel: $PARALLEL_JOBS)..."

if $DRY_RUN; then
    for ip in "${TARGET_IPS[@]}"; do
        log_debug "  Would kill existing scatter_test on $ip"
    done
else
    _mt_pkill_existing() {
        local idx="$1"
        local ip="$2"
        $(ssh_cmd "$ip") "pkill -f 'scatter_test --mode target' 2>/dev/null" || true
        return 0
    }
    PKILL_FAILED=()
    parallel_foreach_host _mt_pkill_existing "pkill_existing" PKILL_FAILED
fi
sleep 1
log_info "Existing processes cleaned."
echo ""

# ---- Step 5: Start Target Processes on All Remote Machines ----
log_step "Step 5: Starting target processes on ${NUM_TARGETS} remote machines (parallel: $PARALLEL_JOBS)..."

ENV_EXPORTS=$(build_env_exports)

# Pre-compute per-target arguments and print the launch plan.
declare -a TARGET_NUMAS_EFFECTIVE=()
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    ip="${TARGET_IPS[$i]}"
    port="${TARGET_PORTS[$i]}"
    numas="${TARGET_NUMA_LIST[$i]}"
    if [ -n "$TARGET_NUMAS" ]; then
        numas="$TARGET_NUMAS"
    fi
    TARGET_NUMAS_EFFECTIVE+=("$numas")
    log_info "  [$i] Will start target on $ip:$port (NUMA: $numas)"
done

# Initialize REMOTE_PIDS to the correct length so parallel workers can write
# back via sentinel files without races on array growth.
REMOTE_PIDS=()
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    REMOTE_PIDS+=("")
done

if ! $DRY_RUN; then
    _mt_start_target() {
        local idx="$1"
        local ip="$2"
        local port="${TARGET_PORTS[$idx]}"
        local numas="${TARGET_NUMAS_EFFECTIVE[$idx]}"
        local remote_bin="${REMOTE_BINARY_PATHS[$idx]:-${BINARY_PATH}}"
        local remote_dir="${REMOTE_WORK_DIRS[$idx]:-${REMOTE_WORK_DIR:-$SCRIPT_DIR}}"
        local pid_file="/tmp/mpcomm_target_${port}.pid"
        local log_file="/tmp/mpcomm_target_${port}.log"
        local launcher="/tmp/mpcomm_launch_${port}.sh"
        local pid_sentinel="/tmp/mt_start_pid_$$_${idx}"

        # Step A: Write the launcher script on the remote machine
        $(ssh_cmd "$ip") bash -s <<LAUNCH_HEREDOC
cat > ${launcher} << 'INNER_EOF'
#!/bin/bash
${ENV_EXPORTS}
cd '${remote_dir}'
stdbuf -oL ${remote_bin} --mode target --host-id ${ip}:${port} --tcp-port ${port} --buffer-size ${BUFFER_SIZE} --num-numas ${numas} > ${log_file} 2>&1 &
echo \$! > ${pid_file}
INNER_EOF
chmod +x ${launcher}
LAUNCH_HEREDOC

        # Step B: Execute the launcher script in a fully detached session
        $(ssh_cmd "$ip") "setsid ${launcher} </dev/null >/dev/null 2>&1 &"
        sleep 1

        # Step C: Read back the PID
        local remote_pid
        remote_pid=$($(ssh_cmd "$ip") "cat ${pid_file} 2>/dev/null" || echo "")
        remote_pid=$(echo "$remote_pid" | tail -1 | tr -d '[:space:]')

        if [ -n "$remote_pid" ] && [ "$remote_pid" -gt 0 ] 2>/dev/null; then
            echo "$remote_pid" > "$pid_sentinel"
            echo "[$idx] $ip - started (PID: $remote_pid)"
            return 0
        fi
        echo "[$idx] $ip - failed to start target"
        return 1
    }
    START_FAILED=()
    parallel_foreach_host _mt_start_target "start_target" START_FAILED

    # Collect PIDs
    START_FAIL=false
    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        ip="${TARGET_IPS[$i]}"
        port="${TARGET_PORTS[$i]}"
        sentinel="/tmp/mt_start_pid_$$_${i}"
        if [ -f "$sentinel" ]; then
            pid=$(cat "$sentinel")
            REMOTE_PIDS[$i]="${ip}:${pid}"
            rm -f "$sentinel"
            log_info "  [$i] $ip:$port - started (PID: $pid)"
        else
            log_error "  [$i] $ip:$port - failed to start target"
            START_FAIL=true
        fi
    done
    if $START_FAIL; then
        exit 1
    fi
fi

echo ""

# ---- Step 6: Wait for All Targets to Be Ready ----
log_step "Step 6: Waiting for all targets to be ready (hybrid: parallel check + sequential tail)..."

READY_MARKER="Waiting for connections..."
READY_TIMEOUT=${STARTUP_WAIT:-30}
# Ensure at least 10s timeout for readiness polling
if [ "$READY_TIMEOUT" -lt 10 ]; then
    READY_TIMEOUT=10
fi

ALL_READY=true

if ! $DRY_RUN; then
    # ---- Phase A: quick parallel checks ----
    # Run up to PHASE_A_ROUNDS fast parallel sweeps (1 second between rounds).
    # Most targets become ready within 1-3 seconds, so this avoids the quadratic
    # blow-up of opening a fresh SSH connection every second per host.
    PHASE_A_ROUNDS=3
    declare -A PHASE_A_READY=()
    declare -A PHASE_A_DEAD=()
    PHASE_A_PENDING=()
    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        PHASE_A_PENDING+=("$i")
    done

    _mt_check_ready() {
        local idx="$1"
        local ip="$2"
        local port="${TARGET_PORTS[$idx]}"
        local entry="${REMOTE_PIDS[$idx]}"
        local pid="${entry#*:}"
        local log_file="/tmp/mpcomm_target_${port}.log"
        local ready_sentinel="/tmp/mt_ready_$$_${idx}"
        local dead_sentinel="/tmp/mt_dead_$$_${idx}"

        # Check process liveness + ready marker in a single ssh round trip.
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
            READY)
                : > "$ready_sentinel"
                echo "[$idx] $ip:$port - ready"
                return 0
                ;;
            DEAD)
                echo "$status" > "$dead_sentinel"
                echo "[$idx] $ip:$port - PROCESS DIED"
                return 0  # handled by caller
                ;;
            *)
                echo "[$idx] $ip:$port - still pending"
                return 0
                ;;
        esac
    }

    for round in $(seq 1 "$PHASE_A_ROUNDS"); do
        [ ${#PHASE_A_PENDING[@]} -eq 0 ] && break
        log_info "  Phase A round $round: checking ${#PHASE_A_PENDING[@]} target(s) in parallel..."
        local_failed=()
        parallel_foreach_host _mt_check_ready "ready_check_r${round}" local_failed "${PHASE_A_PENDING[@]}"

        # Collect results
        NEW_PENDING=()
        for idx in "${PHASE_A_PENDING[@]}"; do
            ready_sentinel="/tmp/mt_ready_$$_${idx}"
            dead_sentinel="/tmp/mt_dead_$$_${idx}"
            if [ -f "$ready_sentinel" ]; then
                PHASE_A_READY[$idx]=1
                rm -f "$ready_sentinel"
                log_info "    [$idx] ${TARGET_IPS[$idx]}:${TARGET_PORTS[$idx]} - ready"
            elif [ -f "$dead_sentinel" ]; then
                PHASE_A_DEAD[$idx]=1
                log_error "    [$idx] ${TARGET_IPS[$idx]} - process died!"
                log_error "    Log tail:"
                sed 's/^/      /' "$dead_sentinel" >&2
                rm -f "$dead_sentinel"
                ALL_READY=false
            else
                NEW_PENDING+=("$idx")
            fi
        done
        PHASE_A_PENDING=("${NEW_PENDING[@]}")
        [ ${#PHASE_A_PENDING[@]} -gt 0 ] && sleep 1
    done

    # ---- Phase B: sequential tail for the few stragglers ----
    if [ ${#PHASE_A_PENDING[@]} -gt 0 ] && $ALL_READY; then
        log_info "  Phase B: ${#PHASE_A_PENDING[@]} slow target(s) still pending, polling individually..."
        for idx in "${PHASE_A_PENDING[@]}"; do
            ip="${TARGET_IPS[$idx]}"
            port="${TARGET_PORTS[$idx]}"
            entry="${REMOTE_PIDS[$idx]}"
            pid="${entry#*:}"
            LOG_FILE="/tmp/mpcomm_target_${port}.log"

            log_info "  [$idx] Waiting for $ip:$port to be ready (remaining timeout: $((READY_TIMEOUT - PHASE_A_ROUNDS))s)..."
            ELAPSED=0
            MAX_ELAPSED=$((READY_TIMEOUT - PHASE_A_ROUNDS))
            [ "$MAX_ELAPSED" -lt 5 ] && MAX_ELAPSED=5
            TARGET_READY=false
            while [ "$ELAPSED" -lt "$MAX_ELAPSED" ]; do
                if ! $(ssh_cmd "$ip") "kill -0 $pid 2>/dev/null"; then
                    log_error "  [$idx] $ip (PID $pid) - process died during startup!"
                    log_error "  Log tail:"
                    $(ssh_cmd "$ip") "tail -20 ${LOG_FILE} 2>/dev/null" || true
                    ALL_READY=false
                    break
                fi
                if $(ssh_cmd "$ip") "grep -q '${READY_MARKER}' ${LOG_FILE} 2>/dev/null"; then
                    TARGET_READY=true
                    break
                fi
                sleep 1
                ELAPSED=$((ELAPSED + 1))
            done

            if $TARGET_READY; then
                log_info "  [$idx] $ip:$port - ready (took $((PHASE_A_ROUNDS + ELAPSED))s total)"
            elif $ALL_READY; then
                log_error "  [$idx] $ip:$port - NOT ready after ${READY_TIMEOUT}s!"
                log_error "  Log tail:"
                $(ssh_cmd "$ip") "tail -20 ${LOG_FILE} 2>/dev/null" || true
                ALL_READY=false
            fi
        done
    fi
fi

if ! $ALL_READY && ! $DRY_RUN; then
    log_error "Some targets failed to become ready. Check logs above."
    cleanup
    exit 1
fi
log_info "All targets ready."
echo ""

# ---- Step 7: Run Initiator ----
log_step "Step 7: Running initiator on local machine ($INITIATOR_IP)..."
echo ""

# Build --target arguments
TARGET_ARGS=""
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    ip="${TARGET_IPS[$i]}"
    port="${TARGET_PORTS[$i]}"
    TARGET_ARGS+="--target t${i}:${ip}:${port} "
done

# Resolve local initiator binary path
LOCAL_BIN=""
if [ -x "${TESTS_INSTALL_DIR}/build/scatter_test" ]; then
    LOCAL_BIN="${TESTS_INSTALL_DIR}/build/scatter_test"
    log_info "Local binary found: $LOCAL_BIN"
elif [ -x "${BINARY_PATH}" ]; then
    LOCAL_BIN="${BINARY_PATH}"
    log_info "Local binary found (fallback): $LOCAL_BIN"
else
    # Binary not found locally — attempt local deploy
    log_warn "Local binary not found, deploying tests..."
    if local_deploy_tests; then
        LOCAL_BIN="$BUILT_BINARY_PATH"
    else
        log_error "  Tried: ${TESTS_INSTALL_DIR}/build/scatter_test"
        log_error "  Tried: ${BINARY_PATH}"
        exit 1
    fi
fi

# Build initiator command
INITIATOR_CMD="${LOCAL_BIN} ${TARGET_ARGS}"

# Add optional arguments
[ -n "$SIZE" ]       && INITIATOR_CMD+="--size ${SIZE} "
[ -n "$ITERATIONS" ] && INITIATOR_CMD+="--iterations ${ITERATIONS} "
[ -n "$WARMUP" ]     && INITIATOR_CMD+="--warmup ${WARMUP} "
[ -n "$BATCH_SIZE" ] && INITIATOR_CMD+="--batch-size ${BATCH_SIZE} "
[ -n "$GPU_DEVICE" ] && INITIATOR_CMD+="--gpu ${GPU_DEVICE} "
[ -n "$RUN_BOTH" ]   && INITIATOR_CMD+="${RUN_BOTH} "
[ -n "$TEST_TYPE" ]  && INITIATOR_CMD+="--test-type ${TEST_TYPE} "

# NUMA nodes for initiator
if [ -n "$NUM_NUMAS" ]; then
    INITIATOR_CMD+="--num-numas ${NUM_NUMAS} "
elif [ -n "$INITIATOR_NUMAS" ]; then
    INITIATOR_CMD+="--num-numas ${INITIATOR_NUMAS} "
fi

# Export environment and run
export MPCOMM_NIC_FILTER
export MPCOMM_QPS_PER_CONNECTION
export MPCOMM_POLL_INTERVAL
export MPCOMM_MAX_SEND_WR
export MPCOMM_PXN_ENABLE
export MPCOMM_PXN_NVLINK_ALPHA
export MPCOMM_MAX_RDMA_TRANSFER_SIZE
export MPCOMM_MAX_OUTSTANDING_PER_QP
if [ -n "${MPCOMM_LOG_LEVEL}" ]; then
    export MPCOMM_LOG_LEVEL
fi

echo "============================================================"
echo "  Initiator Command:"
echo "  $INITIATOR_CMD"
echo "============================================================"
echo ""

if $DRY_RUN; then
    log_warn "DRY RUN - skipping actual execution"
    echo ""
    log_info "To run for real, remove --dry-run flag."
    exit 0
fi

# Execute initiator (in foreground, output goes to terminal)
INITIATOR_EXIT_CODE=0
eval "$INITIATOR_CMD" || INITIATOR_EXIT_CODE=$?

echo ""
echo "============================================================"
if [ $INITIATOR_EXIT_CODE -eq 0 ]; then
    log_info "Test completed successfully!"
else
    log_error "Test failed with exit code: $INITIATOR_EXIT_CODE"
fi
echo "============================================================"

# Cleanup is handled by the EXIT trap
exit $INITIATOR_EXIT_CODE
