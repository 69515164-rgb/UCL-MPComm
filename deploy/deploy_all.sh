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

# ---- Usage ----
usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Deploy mpcomm and build scatter_test on all machines in the hosts file.

Options:
  --hosts FILE          Host list file (default: hosts.txt)
  --deploy-url URL      Custom deploy script URL
  --deploy-tests-url URL Custom test deploy script URL
  --tests-dir DIR        Test files install directory (default: /opt/mpcomm_tests)
  --skip-deploy         Skip mpcomm installation (only build binary)
  --skip-build          Skip scatter_test build (only install mpcomm)
  --ssh-user USER       SSH username (default: root)
  --ssh-port PORT       SSH port (default: 36001)
  --verbose             Enable verbose output
  --dry-run             Print commands without executing
  -h, --help            Show this help

Examples:
  $(basename "$0") --hosts hosts.txt
  $(basename "$0") --hosts hosts.txt --skip-build
EOF
    exit 0
}

# ---- Parse Arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hosts)          HOSTS_FILE="$2"; shift 2 ;;
        --deploy-url)     DEPLOY_URL="$2"; shift 2 ;;
        --deploy-tests-url) DEPLOY_TESTS_URL="$2"; shift 2 ;;
        --tests-dir)      TESTS_INSTALL_DIR="$2"; shift 2 ;;
        --skip-deploy)    SKIP_DEPLOY=true; shift ;;
        --skip-build)     SKIP_BUILD=true; shift ;;
        --ssh-user)       SSH_USER="$2"; shift 2 ;;
        --ssh-port)       SSH_PORT="$2"; shift 2 ;;
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

    # --- Check/deploy on remote (target) machines ---
    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        ip="${TARGET_IPS[$i]}"
        if $DRY_RUN; then
            log_debug "  Would check/deploy binary on $ip"
            continue
        fi

        if $(ssh_cmd "$ip") "test -x '${TESTS_INSTALL_DIR}/build/scatter_test'" &>/dev/null; then
            log_info "  [$i] $ip - binary found: ${TESTS_INSTALL_DIR}/build/scatter_test"
        else
            log_warn "  [$i] $ip - binary not found, deploying tests..."
            if ! remote_deploy_tests "$ip" "[$i] $ip"; then
                ALL_BINARY_OK=false
            fi
        fi
    done

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
