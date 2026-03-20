#!/usr/bin/env bash
# =============================================================================
# Caduceus Installer
# =============================================================================
# Usage: curl -fsSL https://raw.githubusercontent.com/mitchellbernstein/caduceus/main/scripts/install.sh | sh
# This script installs Caduceus — a Hermes-native agent orchestration
# framework — into ~/.hermes/
#
# What gets installed:
#   ~/.hermes/skills/           — all Caduceus Hermes skills
#   ~/.hermes/caduceus/         — QMD collections (agora, projects, agents)
#   ~/.hermes/caduceus.db       — SQLite database (initialized on first run)
#
# For the UI addon, also:
#   ~/.hermes/caduceus-ui/      — Next.js app + FastAPI proxy
# =============================================================================

# Detect the source directory (where this script lives)
# Use ${BASH_SOURCE[0]-} syntax — empty string if unbound (works under set -u)
_bs="${BASH_SOURCE[0]-}"
if [[ -n "$_bs" ]] && [[ -d "$(dirname "$_bs")" ]]; then
    SOURCE_DIR="$(cd "$(dirname "$_bs")" && pwd)"
else
    SOURCE_DIR="$(pwd)"
fi
unset _bs

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CADUCEUS_SKILLS_DIR="$HERMES_HOME/skills"
CADUCEUS_HOME="$HERMES_HOME/caduceus"
CADUCEUS_DB="$HERMES_HOME/caduceus.db"
CADUCEUS_VERSION="0.1.0"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

# =============================================================================
# Helpers
# =============================================================================

info()    { echo -e "${BLUE}[info]${RESET} $1"; }
success() { echo -e "${GREEN}[ok]${RESET} $1"; }
warn()    { echo -e "${YELLOW}[warn]${RESET} $1"; }
error()   { echo -e "${RED}[error]${RESET} $1" >&2; }

section() { echo ""; echo -e "${BOLD}${1}${RESET}"; echo "========================================"; }

# Detect the source directory (where this script lives)
SOURCE_DIR="${BASH_SOURCE[0]:-}"
if [[ -n "$SOURCE_DIR" ]] && [[ -d "$(dirname "$SOURCE_DIR")" ]]; then
    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SOURCE_DIR="$(pwd)"
fi

# =============================================================================
# Parse flags
# =============================================================================

INSTALL_UI="false"
SKIP_PREREQS="false"

while [[ $# -gt 0 ]]; do
    case $1 in
        --ui)
            INSTALL_UI="true"
            shift
            ;;
        --skip-prereqs)
            SKIP_PREREQS="true"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --ui          Also install the web UI (Next.js + FastAPI)"
            echo "  --skip-prereqs Skip prerequisite checking"
            echo "  -h, --help    Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# =============================================================================
# Prerequisites
# =============================================================================

check_hermes() {
    if command -v hermes &> /dev/null; then
        HERMES_VERSION=$(hermes --version 2>/dev/null || echo "unknown")
        success "Hermes found: $HERMES_VERSION"
    else
        error "Hermes not found. Install from: https://github.com/NousResearch/hermes-agent"
        echo ""
        echo "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/setup-hermes.sh | sh"
        exit 1
    fi
}

check_prereqs() {
    section "Checking prerequisites"

    # Hermes
    if [[ "$SKIP_PREREQS" != "true" ]]; then
        check_hermes
    fi

    # SQLite
    if command -v sqlite3 &> /dev/null; then
        success "sqlite3 found: $(sqlite3 --version)"
    else
        warn "sqlite3 not found — will use Python's sqlite3 module"
    fi

    # Python
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1)
        success "python3 found: $PYTHON_VERSION"
    else
        error "python3 not found. Required for Caduceus."
        exit 1
    fi

    success "All prerequisites met"
}

# =============================================================================
# Install: Hermes skills
# =============================================================================

install_skills() {
    section "Installing Caduceus skills"

    # Determine source of skills:
    # 1. Local dev: script is in caduceus_private/scripts/ → skills in ../skills/
    # 2. Previous install: skills already at $HERMES_HOME/caduceus/source/skills/
    # 3. Remote (curl | sh): clone the repo to $HERMES_HOME/caduceus/source/

    if [[ -d "$SOURCE_DIR/../skills" ]] && [[ -d "$SOURCE_DIR/../skills/caduceus-orchestrator" ]]; then
        # Local dev
        SKILLS_SOURCE="$SOURCE_DIR/../skills"
        info "Installing from local dev: $SKILLS_SOURCE"
        CLONE_SOURCE="$SOURCE_DIR/.."
        # Python package is at ../caduceus/ (next to scripts/)
        if [[ -d "$SOURCE_DIR/../caduceus" ]]; then
            CADUCEUS_PYTHON_SOURCE="$SOURCE_DIR/../caduceus"
        fi
        # Don't clean up local dev repos
        CLONE_SOURCE=""

    elif [[ -d "$HERMES_HOME/caduceus/source/skills" ]]; then
        # Previous remote install left a clone
        SKILLS_SOURCE="$HERMES_HOME/caduceus/source/skills"
        QMD_SOURCE="$HERMES_HOME/caduceus/source/qmd-collections"
        CADUCEUS_PYTHON_SOURCE="$HERMES_HOME/caduceus/source/caduceus"
        info "Installing from previous clone: $SKILLS_SOURCE"

    elif [[ -d "$SOURCE_DIR/../caduceus" ]]; then
        # Local dev, caduceus python package is at ../caduceus/
        SKILLS_SOURCE="$SOURCE_DIR/../skills"
        CADUCEUS_PYTHON_SOURCE="$SOURCE_DIR/../caduceus"
        CLONE_SOURCE=""
        info "Installing from local dev (python package): $CADUCEUS_PYTHON_SOURCE"

    else
        # Remote install — clone the repo
        info "Cloning Caduceus from GitHub..."
        if ! command -v git &> /dev/null; then
            error "git is required to install Caduceus."
            echo ""
            echo "  Install git first, or clone locally and run:"
            echo "    git clone https://github.com/mitchellbernstein/caduceus"
            echo "    cd caduceus && ./scripts/install.sh"
            exit 1
        fi

        CLONE_DIR="$HERMES_HOME/caduceus/source"
        mkdir -p "$CLONE_DIR"

        info "Cloning to $CLONE_DIR (git clone --depth 1)..."
        if git clone --depth 1 https://github.com/mitchellbernstein/caduceus "$CLONE_DIR" 2>&1; then
            info "Clone complete."
        else
            error "Failed to clone caduceus repo."
            echo ""
            echo "  Check your internet connection, or install locally:"
            echo "    git clone https://github.com/mitchellbernstein/caduceus"
            echo "    cd caduceus && ./scripts/install.sh"
            exit 1
        fi

        SKILLS_SOURCE="$CLONE_DIR/skills"
        QMD_SOURCE="$CLONE_DIR/qmd-collections"
        CADUCEUS_PYTHON_SOURCE="$CLONE_DIR/caduceus"
        CLONE_SOURCE="$CLONE_DIR"
        info "Using cloned source: $SKILLS_SOURCE"
    fi
    mkdir -p "$CADUCEUS_SKILLS_DIR"

    # Copy each skill directory
    for skill_dir in "$SKILLS_SOURCE"/caduceus-*; do
        if [[ -d "$skill_dir" ]]; then
            skill_name=$(basename "$skill_dir")
            info "Installing skill: $skill_name"
            cp -r "$skill_dir" "$CADUCEUS_SKILLS_DIR/"
        fi
    done

    success "Skills installed to $CADUCEUS_SKILLS_DIR"
    echo ""
    echo "  Installed skills:"
    for skill in "$CADUCEUS_SKILLS_DIR"/caduceus-*; do
        if [[ -d "$skill" ]]; then
            echo "    - $(basename "$skill")"
        fi
    done
}

# =============================================================================
# Install: QMD collections
# =============================================================================

install_qmd() {
    section "Installing QMD collections"

    # QMD_SOURCE is set by install_skills if we cloned
    if [[ -n "${QMD_SOURCE:-}" ]] && [[ -d "$QMD_SOURCE" ]]; then
        info "Copying QMD structure from $QMD_SOURCE"
        mkdir -p "$CADUCEUS_HOME"
        cp -r "$QMD_SOURCE/"* "$CADUCEUS_HOME/" 2>/dev/null || true
    elif [[ -d "$SOURCE_DIR/../qmd-collections" ]]; then
        info "Copying QMD structure from $SOURCE_DIR/../qmd-collections"
        mkdir -p "$CADUCEUS_HOME"
        cp -r "$SOURCE_DIR/../qmd-collections/"* "$CADUCEUS_HOME/" 2>/dev/null || true
    else
        # Create default structure
        mkdir -p "$CADUCEUS_HOME/agenda/coordination"
        mkdir -p "$CADUCEUS_HOME/agenda/learnings"
        mkdir -p "$CADUCEUS_HOME/agenda/decisions"
        mkdir -p "$CADUCEUS_HOME/projects"
        mkdir -p "$CADUCEUS_HOME/agents"
    fi

    success "QMD collections installed to $CADUCEUS_HOME"
}

# =============================================================================
# Install: SQLite schema
# =============================================================================

install_db() {
    section "Initializing SQLite database"

    # Schema can come from:
    # 1. The python package source (CADUCEUS_PYTHON_SOURCE/db/schema.sql)
    # 2. $HERMES_HOME/caduceus/python/caduceus/db/schema.sql (after python package installed)
    # 3. The clone source (CLONE_SOURCE/caduceus/db/schema.sql)

    local schema=""

    if [[ -n "${CADUCEUS_PYTHON_SOURCE:-}" ]] && [[ -f "$CADUCEUS_PYTHON_SOURCE/db/schema.sql" ]]; then
        schema="$CADUCEUS_PYTHON_SOURCE/db/schema.sql"
    elif [[ -f "$HERMES_HOME/caduceus/python/caduceus/db/schema.sql" ]]; then
        schema="$HERMES_HOME/caduceus/python/caduceus/db/schema.sql"
    elif [[ -n "${CLONE_SOURCE:-}" ]] && [[ -f "$CLONE_SOURCE/caduceus/db/schema.sql" ]]; then
        schema="$CLONE_SOURCE/caduceus/db/schema.sql"
    fi

    if [[ -z "$schema" ]]; then
        warn "Schema SQL not found — database will be created on first run"
        return
    fi

    info "Applying schema from $schema"
    if command -v sqlite3 &> /dev/null; then
        sqlite3 "$CADUCEUS_DB" < "$schema"
        success "Database initialized at $CADUCEUS_DB"
    else
        python3 -c "
import sqlite3, sys
schema = open('$schema').read()
conn = sqlite3.connect('$CADUCEUS_DB')
conn.executescript(schema)
conn.close()
print('Database initialized at $CADUCEUS_DB')
"
    fi
}

# =============================================================================
# Install: Python package (for imports)
# =============================================================================

install_python_package() {
    section "Installing Python package"

    # CADUCEUS_PYTHON_SOURCE is set by install_skills
    if [[ -z "${CADUCEUS_PYTHON_SOURCE:-}" ]]; then
        warn "Python package source not found — skipping"
        return
    fi

    if [[ ! -d "$CADUCEUS_PYTHON_SOURCE" ]]; then
        warn "Python package directory not found at $CADUCEUS_PYTHON_SOURCE — skipping"
        return
    fi

    CADUCEUS_PKG_DIR="$HERMES_HOME/caduceus/python"
    mkdir -p "$CADUCEUS_PKG_DIR"

    # Copy the entire caduceus/ package directory into CADUCEUS_PKG_DIR/
    # so it ends up as CADUCEUS_PKG_DIR/caduceus/ (the nested structure Python expects)
    local src_parent="$(dirname "$CADUCEUS_PYTHON_SOURCE")"
    local pkg_name="$(basename "$CADUCEUS_PYTHON_SOURCE")"
    if ! cp -r "$src_parent/$pkg_name" "$CADUCEUS_PKG_DIR/"; then
        # Fallback: copy contents directly if above fails
        cp -r "$CADUCEUS_PYTHON_SOURCE"/* "$CADUCEUS_PKG_DIR/" 2>/dev/null || true
    fi

    # Add to PYTHONPATH so `import caduceus` works from any context
    # Also write to shell rc so it persists across sessions
    info "Setting up PYTHONPATH for caduceus..."
    PYTHONPATH_EXPORT="$CADUCEUS_PKG_DIR"
    SHELL_RC=""
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        if [[ -f "$rc" ]]; then
            SHELL_RC="$rc"
            break
        fi
    done

    if [[ -n "$SHELL_RC" ]]; then
        if ! grep -q "CADUCEUS_PYTHON.*caduceus/python" "$SHELL_RC" 2>/dev/null; then
            echo "" >> "$SHELL_RC"
            echo "# Caduceus Python package" >> "$SHELL_RC"
            echo "export PYTHONPATH=\"$PYTHONPATH_EXPORT:\$PYTHONPATH\"" >> "$SHELL_RC"
            info "Added PYTHONPATH to $SHELL_RC"
        fi
        export PYTHONPATH="$PYTHONPATH_EXPORT:$PYTHONPATH"
    fi

    # Verify it works
    if python3 -c "import caduceus; from caduceus.orchestrator import MissionExecutor; print('OK')" 2>/dev/null; then
        success "Python package ready: import caduceus"
    else
        success "Python package installed to $CADUCEUS_PKG_DIR"
        info "For current shell, run: export PYTHONPATH=\"$PYTHONPATH_EXPORT:\$PYTHONPATH\""
    fi
}

# =============================================================================
# Register skills with Hermes
# =============================================================================

register_skills() {
    section "Registering skills"

    if ! command -v hermes &> /dev/null; then
        warn "Hermes not found — skipping skill registration"
        warn "Restart Hermes or run 'hermes skills sync' to load the skills"
        return
    fi

    # Hermes auto-discovers skills in ~/.hermes/skills/
    # The skills we installed are already in the right place
    info "Skills are in $CADUCEUS_SKILLS_DIR — Hermes will auto-discover them"

    # List installed skills
    echo ""
    echo "  Caduceus skills (in $CADUCEUS_SKILLS_DIR):"
    for skill in "$CADUCEUS_SKILLS_DIR"/caduceus-*; do
        if [[ -d "$skill" ]]; then
            echo "    ✓ $(basename "$skill")"
        fi
    done

    success "Skills ready — Hermes will load them on next start"
}

# =============================================================================
# Install: UI addon
# =============================================================================

install_ui() {
    if [[ "$INSTALL_UI" != "true" ]]; then
        return
    fi

    section "Installing UI addon"

    warn "UI addon not yet implemented in this version"
    echo ""
    echo "  Phase 2 will add:"
    echo "    - Next.js web UI (localhost:3000)"
    echo "    - FastAPI thin server (localhost:8000)"
    echo "    - WebSocket real-time updates"
    echo ""
    echo "  Run '$(basename "$0") --ui' again after Phase 2 is released."

    # TODO(Phase 2):
    # 1. Clone caduceus-ui repo or extract from tarball
    # 2. Run pnpm install
    # 3. Create .env.local with API URL
    # 4. Print dev.sh instructions
}

cleanup_clone() {
    # Remove .git from the clone to save space (keep the source dir for re-runs)
    if [[ -n "${CLONE_SOURCE:-}" ]] && [[ -d "$CLONE_SOURCE/.git" ]]; then
        info "Cleaning up git history..."
        rm -rf "$CLONE_SOURCE/.git" 2>/dev/null || true
        success "Clone cleaned (git history removed, source kept at $CLONE_SOURCE)"
    fi
}

# =============================================================================
# Done
# =============================================================================

done_message() {
    section "Caduceus $CADUCEUS_VERSION installed"

    echo -e "  ${GREEN}✓${RESET} Skills installed   → $CADUCEUS_SKILLS_DIR"
    echo -e "  ${GREEN}✓${RESET} QMD collections   → $CADUCEUS_HOME"
    echo -e "  ${GREEN}✓${RESET} Database          → $CADUCEUS_DB"
    echo -e "  ${GREEN}✓${RESET} Python package    → $HERMES_HOME/caduceus/python/"

    if [[ "$INSTALL_UI" == "true" ]]; then
        echo -e "  ${YELLOW}○${RESET} Web UI addon     → Phase 2"
    fi

    echo ""
    echo -e "${BOLD}Next steps:${RESET}"
    echo ""
    echo "  1. Restart Hermes (or start a new session)"
    echo "     hermes chat"
    echo ""
    echo "  2. Load the orchestrator skill:"
    echo "     /skills caduceus-orchestrator"
    echo ""
    echo "  3. Bootstrap your first project:"
    echo "     'bootstrap a new project with Themis'"
    echo ""
    echo "  4. Or try a quick task:"
    echo "     'run the researcher on the UGC workflow'"
    echo ""
    echo -e "${BOLD}Documentation:${RESET}"
    echo "  ~/.hermes/caduceus/agenda/decisions/README.md"
    echo ""
    echo -e "${BOLD}Uninstall:${RESET}"
    echo "  rm -rf $CADUCEUS_SKILLS_DIR/caduceus-*"
    echo "  rm -rf $CADUCEUS_HOME"
    echo "  rm -f $CADUCEUS_DB"
    echo ""
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo ""
    echo "========================================"
    echo -e "  ${BOLD}Caduceus${RESET} $CADUCEUS_VERSION — Hermes-native agent orchestration"
    echo "========================================"

    check_prereqs
    install_skills
    install_qmd
    install_db
    install_python_package
    cleanup_clone
    register_skills

    if [[ "$INSTALL_UI" == "true" ]]; then
        install_ui
    fi

    done_message
}

main
