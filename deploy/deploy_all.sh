#!/bin/bash
# =============================================================================
# MPComm Multi-Node Deploy Script
#
# Ensures mpcomm is installed and scatter_test binary is built on all machines
# listed in the hosts file. Run this before multi_node_test.sh.
#
# Usage:
#   bash deploy_all.sh [options]
#
# Examples:
#   bash deploy_all.sh --hosts hosts.txt
#   bash deploy_all.sh --hosts hosts.txt --skip-deploy   # only build binary
#   bash deploy_all.sh --hosts hosts.txt --skip-build     # only install mpcomm
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---- Deploy-specific defaults ----
SKIP_DEPLOY=false
SKIP_BUILD=false
DEBUG_BUILD=false

# ---- Usage ----
usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Deploy mpcomm and build scatter_test on all machines in the hosts file.

Options:
  --hosts FILE          Host list file (default: hosts.txt)
  --version VER         mpcomm version to deploy (default: resolved from VERSION file on mirror)
  --deploy-url URL      Custom deploy script URL
  --deploy-tests-url URL Custom test deploy script URL
  --tests-dir DIR        Test files install directory (default: /opt/mpcomm_tests)
  --skip-deploy         Skip mpcomm installation (only build binary)
  --skip-build          Skip scatter_test build (only install mpcomm)
  --debug               Install debug build of mpcomm (passed to deploy_mpcomm.sh)
  --ssh-user USER       SSH username (default: root)
  --ssh-port PORT       SSH port (default: 36001)
  --parallel N          Max concurrent SSH operations (default: 20)
  --verbose             Enable verbose output
  --dry-run             Print commands without executing
  -h, --help            Show this help

Examples:
  $(basename "$0") --hosts hosts.txt
  $(basename "$0") --hosts hosts.txt --skip-build
  $(basename "$0") --hosts hosts_100.txt --parallel 30
EOF
    exit 0
}

# ---- Parse Arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hosts)          HOSTS_FILE="$2"; shift 2 ;;
        --version)        MPCOMM_VERSION="$2"; shift 2 ;;
        --version=*)      MPCOMM_VERSION="${1#*=}"; shift ;;
        --deploy-url)     DEPLOY_URL="$2"; shift 2 ;;
        --deploy-tests-url) DEPLOY_TESTS_URL="$2"; shift 2 ;;
        --tests-dir)      TESTS_INSTALL_DIR="$2"; shift 2 ;;
        --skip-deploy)    SKIP_DEPLOY=true; shift ;;
        --skip-build)     SKIP_BUILD=true; shift ;;
        --debug)          DEBUG_BUILD=true; shift ;;
        --ssh-user)       SSH_USER="$2"; shift 2 ;;
        --ssh-port)       SSH_PORT="$2"; shift 2 ;;
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

# Flag passed through to deploy_mpcomm.sh / deploy_tests.sh when --debug is set.
DEBUG_FLAG=""
$DEBUG_BUILD && DEBUG_FLAG="--debug"

# Resolve the target version once so every node deploys the same version.
if ! $DRY_RUN; then
    resolve_mpcomm_version || exit 1
fi

echo ""
echo "============================================================"
echo "  MPComm Multi-Node Deploy"
echo "============================================================"
echo "  Hosts file:    $HOSTS_FILE"
echo "  Initiator:     $INITIATOR_IP (port: $INITIATOR_PORT)"
echo "  Targets:       $NUM_TARGETS machine(s)"
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    echo "    [$i] ${TARGET_IPS[$i]}:${TARGET_PORTS[$i]}"
done
echo "  Skip deploy:   $SKIP_DEPLOY"
echo "  Skip build:    $SKIP_BUILD"
echo "  Debug build:   $DEBUG_BUILD"
echo "  Version:       ${MPCOMM_VERSION:-<resolve at runtime>}"
echo "  Parallel:      $PARALLEL_JOBS concurrent SSH jobs"
echo "============================================================"
echo ""

if $DRY_RUN; then
    log_warn "DRY RUN mode - commands will be printed but not executed"
    echo ""
fi

# ---- Step 1: Verify SSH Connectivity ----
log_step "Step 1: Verifying SSH connectivity..."
SSH_VERIFIED=false
verify_ssh

# ---- Step 2: Check mpcomm installation & auto-deploy if needed ----
if ! $SKIP_DEPLOY; then
    log_step "Step 2: Checking mpcomm installation on all machines..."

    DEPLOY_NEEDED_IPS=()

    # Check local (initiator) machine first
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
        _check_mpcomm_remote() {
            local idx="$1"
            local ip="$2"
            local ok_marker="/tmp/mpcomm_check_ok_$$_${idx}"
            if $(ssh_cmd "$ip") "python3 -c 'import mpcomm' 2>/dev/null" &>/dev/null; then
                local ver
                ver=$($(ssh_cmd "$ip") "python3 -c 'import mpcomm; print(mpcomm.__version__)' 2>/dev/null" || echo "unknown")
                echo "INSTALLED version=$ver"
                # Mark success via a sentinel file the parent can read.
                echo "$ver" > "$ok_marker"
                return 0
            else
                echo "NOT_INSTALLED"
                return 1
            fi
        }

        check_failed=()
        parallel_foreach_host _check_mpcomm_remote "check_mpcomm" check_failed

        # All non-failed indices are installed; failed indices need deploy.
        # Reconstruct by checking sentinel files.
        for i in $(seq 0 $((NUM_TARGETS - 1))); do
            ip="${TARGET_IPS[$i]}"
            sentinel="/tmp/mpcomm_check_ok_$$_${i}"
            if [ -f "$sentinel" ]; then
                ver=$(cat "$sentinel")
                log_info "  [$i] $ip - mpcomm installed (version: $ver)"
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
        log_step "Auto-deploying mpcomm on ${#DEPLOY_NEEDED_IPS[@]} machine(s) in parallel..."
        DEPLOY_FAIL=false

        # ---- Deploy on local machine (if needed) synchronously first ----
        for ip in "${DEPLOY_NEEDED_IPS[@]}"; do
            if [ "$ip" = "LOCAL" ]; then
                log_info "  Deploying mpcomm on local machine ($INITIATOR_IP) (this may take a few minutes)..."
                if $DRY_RUN; then
                    log_debug "  Would run: wget -qO- '${DEPLOY_URL}' | bash -s -- ${DEBUG_FLAG} --version=${MPCOMM_VERSION:-<latest>}"
                    break
                fi
                DEPLOY_OUTPUT=$(wget -qO- "${DEPLOY_URL}" | bash -s -- ${DEBUG_FLAG} --version="${MPCOMM_VERSION}" 2>&1) || {
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

        # ---- Deploy on remote machines in parallel ----
        REMOTE_DEPLOY_INDICES=()
        for ip in "${DEPLOY_NEEDED_IPS[@]}"; do
            [ "$ip" = "LOCAL" ] && continue
            # Find the index of this ip in TARGET_IPS
            for i in $(seq 0 $((NUM_TARGETS - 1))); do
                if [ "${TARGET_IPS[$i]}" = "$ip" ]; then
                    REMOTE_DEPLOY_INDICES+=("$i")
                    break
                fi
            done
        done

        if [ ${#REMOTE_DEPLOY_INDICES[@]} -gt 0 ] && ! $DRY_RUN; then
            log_info "  Deploying mpcomm on ${#REMOTE_DEPLOY_INDICES[@]} remote machine(s) (parallel: $PARALLEL_JOBS, may take a few minutes)..."
            _deploy_mpcomm_remote() {
                local idx="$1"
                local ip="$2"
                echo "=== Deploying mpcomm on $ip ==="
                if ! $(ssh_cmd "$ip") "wget -qO- '${DEPLOY_URL}' | bash -s -- ${DEBUG_FLAG} --version=${MPCOMM_VERSION}" 2>&1; then
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
            remote_deploy_failed=()
            parallel_foreach_host _deploy_mpcomm_remote "deploy_mpcomm" remote_deploy_failed "${REMOTE_DEPLOY_INDICES[@]}"
            if [ ${#remote_deploy_failed[@]} -gt 0 ]; then
                DEPLOY_FAIL=true
            fi
        elif $DRY_RUN; then
            for idx in "${REMOTE_DEPLOY_INDICES[@]}"; do
                log_debug "  Would run: $(ssh_cmd "${TARGET_IPS[$idx]}") 'wget -qO- \"${DEPLOY_URL}\" | bash -s -- ${DEBUG_FLAG} --version=${MPCOMM_VERSION}'"
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
else
    log_info "Step 2: Skipped (--skip-deploy)"
    echo ""
fi

# ---- Step 3: Locate or build scatter_test binary on all machines ----
if ! $SKIP_BUILD; then
    log_step "Step 3: Locating/deploying scatter_test binary on all machines..."

    ALL_BINARY_OK=true

    # --- Check/deploy on local (initiator) machine ---
    log_info "  [local] $INITIATOR_IP - checking binary..."
    if ! $DRY_RUN; then
        if [ -x "${TESTS_INSTALL_DIR}/build/scatter_test" ]; then
            log_info "  [local] $INITIATOR_IP - binary found: ${TESTS_INSTALL_DIR}/build/scatter_test"
        elif [ -x "${BINARY_PATH}" ]; then
            log_info "  [local] $INITIATOR_IP - binary found (fallback): ${BINARY_PATH}"
        else
            log_warn "  [local] $INITIATOR_IP - binary not found, deploying tests..."
            if ! local_deploy_tests; then
                ALL_BINARY_OK=false
            fi
        fi
    else
        log_debug "  Would check/deploy binary on local machine"
    fi

    # --- Check/deploy on remote (target) machines in parallel ---
    if ! $DRY_RUN; then
        # Phase 1: check which targets are missing the binary (parallel).
        # A sentinel file is created by successful checkers.
        _check_binary_remote() {
            local idx="$1"
            local ip="$2"
            local sentinel="/tmp/mpcomm_bin_ok_$$_${idx}"
            if $(ssh_cmd "$ip") "test -x '${TESTS_INSTALL_DIR}/build/scatter_test'" &>/dev/null; then
                echo "FOUND on $ip"
                : > "$sentinel"
                return 0
            fi
            echo "NOT FOUND on $ip"
            # Return 0 so parallel framework doesn't mark it as failure;
            # we treat "missing" as a known state, not an error.
            return 0
        }
        check_failed=()
        parallel_foreach_host _check_binary_remote "check_binary" check_failed

        BUILD_NEEDED_INDICES=()
        for i in $(seq 0 $((NUM_TARGETS - 1))); do
            ip="${TARGET_IPS[$i]}"
            sentinel="/tmp/mpcomm_bin_ok_$$_${i}"
            if [ -f "$sentinel" ]; then
                log_info "  [$i] $ip - binary found: ${TESTS_INSTALL_DIR}/build/scatter_test"
                rm -f "$sentinel"
            else
                log_warn "  [$i] $ip - binary not found, will deploy tests"
                BUILD_NEEDED_INDICES+=("$i")
            fi
        done

        # Phase 2: deploy tests on all machines that need it (parallel).
        if [ ${#BUILD_NEEDED_INDICES[@]} -gt 0 ]; then
            log_info "  Deploying tests on ${#BUILD_NEEDED_INDICES[@]} machine(s) (parallel: $PARALLEL_JOBS)..."
            _deploy_tests_remote() {
                local idx="$1"
                local ip="$2"
                echo "=== Deploying tests on $ip ==="
                if ! $(ssh_cmd "$ip") "wget -qO- '${DEPLOY_TESTS_URL}' | bash -s -- --install-dir=${TESTS_INSTALL_DIR} --version=${MPCOMM_VERSION}" 2>&1; then
                    echo "deploy_tests.sh FAILED on $ip"
                    return 1
                fi
                if ! $(ssh_cmd "$ip") "test -x '${TESTS_INSTALL_DIR}/build/scatter_test'" &>/dev/null; then
                    echo "Binary missing after deploy on $ip"
                    return 1
                fi
                echo "Binary deployed: ${TESTS_INSTALL_DIR}/build/scatter_test on $ip"
                return 0
            }
            build_failed=()
            parallel_foreach_host _deploy_tests_remote "deploy_tests" build_failed "${BUILD_NEEDED_INDICES[@]}"
            if [ ${#build_failed[@]} -gt 0 ]; then
                ALL_BINARY_OK=false
            fi
        fi
    else
        for i in $(seq 0 $((NUM_TARGETS - 1))); do
            log_debug "  Would check/deploy binary on ${TARGET_IPS[$i]}"
        done
    fi

    if ! $ALL_BINARY_OK && ! $DRY_RUN; then
        log_error "Binary missing/build failed on some machines. Aborting."
        exit 1
    fi
    log_info "Binary verified on all machines."
    echo ""
else
    log_info "Step 3: Skipped (--skip-build)"
    echo ""
fi

echo "============================================================"
log_info "Deployment complete! All machines are ready."
log_info "Run multi_node_test.sh to start testing."
echo "============================================================"

# Clean up parallel log dir (unless --verbose was given)
if [ -d "${PARALLEL_LOG_DIR:-}" ] && ! $VERBOSE; then
    rm -rf "$PARALLEL_LOG_DIR" 2>/dev/null || true
fi
