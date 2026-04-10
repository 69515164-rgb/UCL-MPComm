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
  --skip-deploy         Skip auto-deployment, fail if mpcomm not installed
--startup-wait SECS   Timeout for targets to become ready (default: 30)
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
        --skip-deploy)    SKIP_DEPLOY=true; shift ;;
        --startup-wait)   STARTUP_WAIT="$2"; shift 2 ;;
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

    if [ ${#REMOTE_PIDS[@]} -gt 0 ]; then
        for entry in "${REMOTE_PIDS[@]}"; do
            local ip="${entry%%:*}"
            local pid="${entry#*:}"
            log_info "  Killing PID $pid on $ip"
            $(ssh_cmd "$ip") "kill $pid 2>/dev/null; kill -9 $pid 2>/dev/null" 2>/dev/null || true
        done
    fi

    if $SSH_VERIFIED; then
        for ip in "${TARGET_IPS[@]}"; do
            $(ssh_cmd "$ip") "pkill -f 'scatter_test --mode target' 2>/dev/null" 2>/dev/null || true
        done
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

# Check remote (target) machines
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    ip="${TARGET_IPS[$i]}"
    if $DRY_RUN; then
        log_debug "  Would check mpcomm on $ip"
        continue
    fi
    if $(ssh_cmd "$ip") "python3 -c 'import mpcomm' 2>/dev/null" &>/dev/null; then
        REMOTE_VER=$($(ssh_cmd "$ip") "python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null" || echo "unknown")
        log_info "  [$i] $ip - mpcomm installed (version: $REMOTE_VER)"
    else
        log_warn "  [$i] $ip - mpcomm NOT installed"
        DEPLOY_NEEDED_IPS+=("$ip")
    fi
done

if [ ${#DEPLOY_NEEDED_IPS[@]} -gt 0 ]; then
    if $SKIP_DEPLOY; then
        log_error "mpcomm not installed on ${#DEPLOY_NEEDED_IPS[@]} machine(s) and --skip-deploy is set."
log_error "Run deploy_all.sh first, or remove --skip-deploy to auto-deploy."
        exit 1
    fi

    log_step "Auto-deploying mpcomm on ${#DEPLOY_NEEDED_IPS[@]} machine(s)..."
    DEPLOY_FAIL=false
    for ip in "${DEPLOY_NEEDED_IPS[@]}"; do
        if [ "$ip" = "LOCAL" ]; then
            log_info "  Deploying mpcomm on local machine ($INITIATOR_IP) (this may take a few minutes)..."
            if $DRY_RUN; then
                log_debug "  Would run: wget -qO- '${DEPLOY_URL}' | bash"
                continue
            fi
            DEPLOY_OUTPUT=$(wget -qO- "${DEPLOY_URL}" | bash 2>&1) || {
                log_error "  local ($INITIATOR_IP) - deployment FAILED"
                log_error "  Output (last 20 lines):"
                echo "$DEPLOY_OUTPUT" | tail -20
                DEPLOY_FAIL=true
                continue
            }
            if python3 -c 'import mpcomm' 2>/dev/null; then
                LOCAL_VER=$(python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null || echo "unknown")
                log_info "  local ($INITIATOR_IP) - mpcomm deployed successfully (version: $LOCAL_VER)"
            else
                log_error "  local ($INITIATOR_IP) - deployment completed but mpcomm import still fails"
                DEPLOY_FAIL=true
            fi
        else
            log_info "  Deploying mpcomm on $ip (this may take a few minutes)..."
            if $DRY_RUN; then
                log_debug "  Would run: $(ssh_cmd "$ip") 'wget -qO- \"${DEPLOY_URL}\" | bash'"
                continue
            fi
            DEPLOY_OUTPUT=$($(ssh_cmd "$ip") "wget -qO- '${DEPLOY_URL}' | bash" 2>&1) || {
                log_error "  $ip - deployment FAILED"
                log_error "  Output (last 20 lines):"
                echo "$DEPLOY_OUTPUT" | tail -20
                DEPLOY_FAIL=true
                continue
            }
            if $(ssh_cmd "$ip") "python3 -c 'import mpcomm' 2>/dev/null" &>/dev/null; then
                REMOTE_VER=$($(ssh_cmd "$ip") "python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null" || echo "unknown")
                log_info "  $ip - mpcomm deployed successfully (version: $REMOTE_VER)"
            else
                log_error "  $ip - deployment completed but mpcomm import still fails"
                DEPLOY_FAIL=true
            fi
        fi
    done

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
log_step "Step 3: Locating scatter_test binary on all targets..."

declare -a REMOTE_BINARY_PATHS=()
declare -a REMOTE_WORK_DIRS=()

ALL_BINARY_OK=true
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    ip="${TARGET_IPS[$i]}"
    if $DRY_RUN; then
        log_debug "  Would resolve binary path on $ip"
        REMOTE_BINARY_PATHS+=("${TESTS_INSTALL_DIR}/build/scatter_test")
        REMOTE_WORK_DIRS+=("${TESTS_INSTALL_DIR}")
        continue
    fi

    if $(ssh_cmd "$ip") "test -x '${TESTS_INSTALL_DIR}/build/scatter_test'" &>/dev/null; then
        REMOTE_BINARY_PATHS+=("${TESTS_INSTALL_DIR}/build/scatter_test")
        REMOTE_WORK_DIRS+=("${TESTS_INSTALL_DIR}")
        log_info "  [$i] $ip - binary found: ${TESTS_INSTALL_DIR}/build/scatter_test"
    elif [ -n "${REMOTE_WORK_DIR:-}" ] && $(ssh_cmd "$ip") "test -x '${REMOTE_WORK_DIR}/${BINARY_PATH}'" &>/dev/null; then
        REMOTE_BINARY_PATHS+=("${REMOTE_WORK_DIR}/${BINARY_PATH}")
        REMOTE_WORK_DIRS+=("$REMOTE_WORK_DIR")
        log_info "  [$i] $ip - binary found (fallback): ${REMOTE_WORK_DIR}/${BINARY_PATH}"
    else
        # Binary not found — attempt remote deploy
        log_warn "  [$i] $ip - binary not found, deploying tests..."
        if remote_deploy_tests "$ip" "[$i] $ip"; then
            REMOTE_BINARY_PATHS+=("$BUILT_BINARY_PATH")
            REMOTE_WORK_DIRS+=("$BUILT_TESTS_DIR")
        else
            ALL_BINARY_OK=false
        fi
    fi
done

if ! $ALL_BINARY_OK && ! $DRY_RUN; then
    log_error "Binary missing/build failed on some targets. Aborting."
    exit 1
fi
log_info "Binary verified on all targets."
echo ""

# ---- Step 4: Kill Any Existing Target Processes ----
log_step "Step 4: Cleaning up any existing target processes..."

for ip in "${TARGET_IPS[@]}"; do
    if $DRY_RUN; then
        log_debug "  Would kill existing scatter_test on $ip"
        continue
    fi
    $(ssh_cmd "$ip") "pkill -f 'scatter_test --mode target' 2>/dev/null" || true
done
sleep 1
log_info "Existing processes cleaned."
echo ""

# ---- Step 5: Start Target Processes on All Remote Machines ----
log_step "Step 5: Starting target processes on ${NUM_TARGETS} remote machines..."

ENV_EXPORTS=$(build_env_exports)

for i in $(seq 0 $((NUM_TARGETS - 1))); do
    ip="${TARGET_IPS[$i]}"
    port="${TARGET_PORTS[$i]}"
    numas="${TARGET_NUMA_LIST[$i]}"

    if [ -n "$TARGET_NUMAS" ]; then
        numas="$TARGET_NUMAS"
    fi

    REMOTE_BIN="${REMOTE_BINARY_PATHS[$i]:-${BINARY_PATH}}"
    REMOTE_DIR="${REMOTE_WORK_DIRS[$i]:-${REMOTE_WORK_DIR:-$SCRIPT_DIR}}"

    # Build the target command line
    TARGET_CMD="${ENV_EXPORTS} cd '${REMOTE_DIR}' && "
    TARGET_CMD+="${REMOTE_BIN} "
    TARGET_CMD+="--mode target "
    TARGET_CMD+="--host-id ${ip}:${port} "
    TARGET_CMD+="--tcp-port ${port} "
    TARGET_CMD+="--buffer-size ${BUFFER_SIZE} "
    TARGET_CMD+="--num-numas ${numas}"

    log_info "  [$i] Starting target on $ip:$port (NUMA: $numas)"
    log_debug "  CMD: $TARGET_CMD"

    if $DRY_RUN; then
        continue
    fi

    # Start the target process fully detached from the SSH session.
    # We write a launcher script to the remote machine first (avoids shell quoting issues),
    # then execute it with setsid so it's fully detached from the SSH session.
    PID_FILE="/tmp/mpcomm_target_${port}.pid"
    LOG_FILE="/tmp/mpcomm_target_${port}.log"
    LAUNCHER="/tmp/mpcomm_launch_${port}.sh"

    # Step A: Write the launcher script on the remote machine
    $(ssh_cmd "$ip") bash -s <<LAUNCH_HEREDOC
cat > ${LAUNCHER} << 'INNER_EOF'
#!/bin/bash
${ENV_EXPORTS}
cd '${REMOTE_DIR}'
stdbuf -oL ${REMOTE_BIN} --mode target --host-id ${ip}:${port} --tcp-port ${port} --buffer-size ${BUFFER_SIZE} --num-numas ${numas} > ${LOG_FILE} 2>&1 &
echo \$! > ${PID_FILE}
INNER_EOF
chmod +x ${LAUNCHER}
LAUNCH_HEREDOC

    # Step B: Execute the launcher script in a fully detached session
    $(ssh_cmd "$ip") "setsid ${LAUNCHER} </dev/null >/dev/null 2>&1 &"
    sleep 1

    # Step C: Read back the PID
    REMOTE_PID=$($(ssh_cmd "$ip") "cat ${PID_FILE} 2>/dev/null" || echo "")
    REMOTE_PID=$(echo "$REMOTE_PID" | tail -1 | tr -d '[:space:]')

    if [ -n "$REMOTE_PID" ] && [ "$REMOTE_PID" -gt 0 ] 2>/dev/null; then
        REMOTE_PIDS+=("${ip}:${REMOTE_PID}")
        log_info "  [$i] $ip - started (PID: $REMOTE_PID)"
    else
        log_error "  [$i] $ip - failed to start target"
        exit 1
    fi
done

echo ""

# ---- Step 6: Wait for All Targets to Be Ready ----
log_step "Step 6: Waiting for all targets to be ready..."

READY_MARKER="Waiting for connections..."
READY_TIMEOUT=${STARTUP_WAIT:-30}
# Ensure at least 10s timeout for readiness polling
if [ "$READY_TIMEOUT" -lt 10 ]; then
    READY_TIMEOUT=10
fi

ALL_READY=true
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    ip="${TARGET_IPS[$i]}"
    port="${TARGET_PORTS[$i]}"
    entry="${REMOTE_PIDS[$i]}"
    pid="${entry#*:}"
    LOG_FILE="/tmp/mpcomm_target_${port}.log"

    if $DRY_RUN; then
        continue
    fi

    log_info "  [$i] Waiting for $ip:$port to be ready (timeout: ${READY_TIMEOUT}s)..."

    ELAPSED=0
    TARGET_READY=false
    while [ "$ELAPSED" -lt "$READY_TIMEOUT" ]; do
        # First check if the process is still alive
        if ! $(ssh_cmd "$ip") "kill -0 $pid 2>/dev/null"; then
            log_error "  [$i] $ip (PID $pid) - process died during startup!"
            log_error "  Log tail:"
            $(ssh_cmd "$ip") "tail -20 ${LOG_FILE} 2>/dev/null" || true
            ALL_READY=false
            break
        fi

        # Check if the ready marker appears in the log
        if $(ssh_cmd "$ip") "grep -q '${READY_MARKER}' ${LOG_FILE} 2>/dev/null"; then
            TARGET_READY=true
            break
        fi

        sleep 1
        ELAPSED=$((ELAPSED + 1))
    done

    if $TARGET_READY; then
        log_info "  [$i] $ip:$port - ready (took ${ELAPSED}s)"
    elif $ALL_READY; then
        # Only print timeout error if we haven't already printed a "process died" error
        log_error "  [$i] $ip:$port - NOT ready after ${READY_TIMEOUT}s!"
        log_error "  Log tail:"
        $(ssh_cmd "$ip") "tail -20 ${LOG_FILE} 2>/dev/null" || true
        ALL_READY=false
    fi
done

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
