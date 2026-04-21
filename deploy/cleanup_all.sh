#!/bin/bash
# =============================================================================
# MPComm Multi-Node Cleanup Script
#
# Uninstalls the mpcomm Python package and removes the scatter_test install
# directory (default: /opt/mpcomm_tests) on every machine listed in the hosts
# file (both the initiator and all targets).
#
# Usage:
#   bash cleanup_all.sh [options]
#
# Examples:
#   bash cleanup_all.sh --hosts hosts.txt
#   bash cleanup_all.sh --hosts hosts.txt --skip-uninstall   # only remove tests
#   bash cleanup_all.sh --hosts hosts.txt --skip-tests       # only uninstall mpcomm
#   bash cleanup_all.sh --hosts hosts.txt --yes              # skip confirmation
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---- Cleanup-specific defaults ----
SKIP_UNINSTALL=false
SKIP_TESTS=false
ASSUME_YES=false

# ---- Usage ----
usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Uninstall mpcomm and remove scatter_test files on all machines in the hosts
file (initiator + targets).

Options:
  --hosts FILE        Host list file (default: hosts.txt)
  --tests-dir DIR     Test files install directory to remove
                      (default: /opt/mpcomm_tests)
  --skip-uninstall    Do NOT uninstall the mpcomm Python package
  --skip-tests        Do NOT remove the scatter_test install directory
  --ssh-user USER     SSH username (default: root)
  --ssh-port PORT     SSH port (default: 36001)
  --parallel N        Max concurrent SSH operations (default: 20)
  --yes, -y           Do not prompt for confirmation
  --verbose           Enable verbose output
  --dry-run           Print commands without executing
  -h, --help          Show this help

Examples:
  $(basename "$0") --hosts hosts.txt
  $(basename "$0") --hosts hosts.txt --skip-uninstall
  $(basename "$0") --hosts hosts.txt --tests-dir /opt/mpcomm_tests --yes
EOF
    exit 0
}

# ---- Parse Arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hosts)          HOSTS_FILE="$2"; shift 2 ;;
        --tests-dir)      TESTS_INSTALL_DIR="$2"; shift 2 ;;
        --skip-uninstall) SKIP_UNINSTALL=true; shift ;;
        --skip-tests)     SKIP_TESTS=true; shift ;;
        --ssh-user)       SSH_USER="$2"; shift 2 ;;
        --ssh-port)       SSH_PORT="$2"; shift 2 ;;
        --parallel)       PARALLEL_JOBS="$2"; shift 2 ;;
        -y|--yes)         ASSUME_YES=true; shift ;;
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

if $SKIP_UNINSTALL && $SKIP_TESTS; then
    log_error "Both --skip-uninstall and --skip-tests are set; nothing to do."
    exit 1
fi

echo ""
echo "============================================================"
echo "  MPComm Multi-Node Cleanup"
echo "============================================================"
echo "  Hosts file:       $HOSTS_FILE"
echo "  Initiator:        $INITIATOR_IP"
echo "  Targets:          $NUM_TARGETS machine(s)"
for i in $(seq 0 $((NUM_TARGETS - 1))); do
    echo "    [$i] ${TARGET_IPS[$i]}"
done
echo "  Uninstall mpcomm: $( $SKIP_UNINSTALL && echo "NO (skipped)" || echo "YES" )"
echo "  Remove tests dir: $( $SKIP_TESTS && echo "NO (skipped)" || echo "YES ($TESTS_INSTALL_DIR)" )"
echo "  Parallel:         $PARALLEL_JOBS concurrent SSH jobs"
echo "============================================================"
echo ""

if $DRY_RUN; then
    log_warn "DRY RUN mode - commands will be printed but not executed"
    echo ""
fi

# ---- Confirmation prompt ----
if ! $ASSUME_YES && ! $DRY_RUN; then
    log_warn "This will REMOVE mpcomm and/or ${TESTS_INSTALL_DIR} on $((NUM_TARGETS + 1)) machine(s)."
    read -r -p "Proceed? [y/N] " reply
    case "$reply" in
        y|Y|yes|YES) ;;
        *) log_info "Aborted by user."; exit 0 ;;
    esac
    echo ""
fi

# ---- Step 1: Verify SSH Connectivity ----
log_step "Step 1: Verifying SSH connectivity..."
SSH_VERIFIED=false
verify_ssh

# ---- Helpers ----------------------------------------------------------------

# Build the cleanup shell fragment that runs on a single machine.
# It is idempotent: missing packages / directories are not treated as errors.
build_cleanup_cmd() {
    local cmd=""

    if ! $SKIP_UNINSTALL; then
        # Try python3 first, fall back to python. Swallow "not installed" errors.
        cmd+='PYTHON_CMD=""; '
        cmd+='for c in python3 python; do if command -v "$c" >/dev/null 2>&1; then PYTHON_CMD="$c"; break; fi; done; '
        cmd+='if [ -n "$PYTHON_CMD" ]; then '
        cmd+='    if "$PYTHON_CMD" -c "import mpcomm" >/dev/null 2>&1; then '
        cmd+='        echo "[mpcomm] uninstalling..."; '
        cmd+='        "$PYTHON_CMD" -m pip uninstall -y mpcomm >/dev/null 2>&1 || echo "[mpcomm] pip uninstall returned non-zero"; '
        cmd+='    else '
        cmd+='        echo "[mpcomm] not installed, skipping"; '
        cmd+='    fi; '
        cmd+='    if "$PYTHON_CMD" -c "import mpcomm" >/dev/null 2>&1; then '
        cmd+='        echo "[mpcomm] STILL IMPORTABLE after uninstall"; exit 10; '
        cmd+='    else '
        cmd+='        echo "[mpcomm] uninstall OK"; '
        cmd+='    fi; '
        cmd+='else '
        cmd+='    echo "[mpcomm] python not found, skipping uninstall"; '
        cmd+='fi; '
    fi

    if ! $SKIP_TESTS; then
        cmd+='if [ -e "'"$TESTS_INSTALL_DIR"'" ]; then '
        cmd+='    echo "[tests] removing '"$TESTS_INSTALL_DIR"'"; '
        cmd+='    rm -rf "'"$TESTS_INSTALL_DIR"'" || { echo "[tests] rm FAILED"; exit 11; }; '
        cmd+='else '
        cmd+='    echo "[tests] '"$TESTS_INSTALL_DIR"' does not exist, skipping"; '
        cmd+='fi; '
    fi

    cmd+='echo "[done] cleanup complete"'
    echo "$cmd"
}

# ---- Step 2: Cleanup on local (initiator) machine ---------------------------
log_step "Step 2: Cleaning up local (initiator) machine: $INITIATOR_IP ..."
LOCAL_OK=true
CLEANUP_CMD=$(build_cleanup_cmd)

if $DRY_RUN; then
    log_debug "  Would run locally: bash -c '<cleanup script>'"
    log_debug "  Cleanup script: $CLEANUP_CMD"
else
    if ! bash -c "$CLEANUP_CMD"; then
        log_error "  [local] $INITIATOR_IP - cleanup FAILED"
        LOCAL_OK=false
    else
        log_info "  [local] $INITIATOR_IP - cleanup OK"
    fi
fi
echo ""

# ---- Step 3: Cleanup on remote (target) machines in parallel ---------------
log_step "Step 3: Cleaning up $NUM_TARGETS remote target(s) in parallel (jobs: $PARALLEL_JOBS) ..."

remote_failed=()

if $DRY_RUN; then
    for i in $(seq 0 $((NUM_TARGETS - 1))); do
        log_debug "  Would run: $(ssh_cmd "${TARGET_IPS[$i]}") 'bash -c <cleanup script>'"
    done
else
    # Export the cleanup command so the parallel workers inherit it.
    export REMOTE_CLEANUP_CMD="$CLEANUP_CMD"

    _cleanup_one_remote() {
        local idx="$1"
        local ip="$2"
        echo "=== Cleanup on $ip ==="
        # Use bash -s <<<... to avoid any local shell quoting surprises.
        if ! $(ssh_cmd "$ip") "bash -s" <<< "$REMOTE_CLEANUP_CMD"; then
            echo "Cleanup script returned non-zero on $ip"
            return 1
        fi
        echo "Cleanup OK on $ip"
        return 0
    }

    parallel_foreach_host _cleanup_one_remote "cleanup" remote_failed
fi
echo ""

# ---- Summary ----------------------------------------------------------------
echo "============================================================"
if $DRY_RUN; then
    log_info "DRY RUN complete. No changes were made."
elif $LOCAL_OK && [ ${#remote_failed[@]} -eq 0 ]; then
    log_info "Cleanup complete on all $((NUM_TARGETS + 1)) machine(s)."
else
    log_error "Cleanup finished with errors:"
    if ! $LOCAL_OK; then
        log_error "  - local ($INITIATOR_IP) failed"
    fi
    if [ ${#remote_failed[@]} -gt 0 ]; then
        log_error "  - ${#remote_failed[@]} remote target(s) failed:"
        for ip in "${remote_failed[@]}"; do
            log_error "      $ip"
        done
    fi
    echo "============================================================"
    # Keep parallel logs on failure for inspection
    exit 1
fi
echo "============================================================"

# Clean up parallel log dir (unless --verbose was given)
if [ -d "${PARALLEL_LOG_DIR:-}" ] && ! $VERBOSE; then
    rm -rf "$PARALLEL_LOG_DIR" 2>/dev/null || true
fi
