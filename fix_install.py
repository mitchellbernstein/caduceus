#!/usr/bin/env python3
import sys

with open('scripts/install.sh') as f:
    content = f.read()

old_main = """main() {
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
}"""

register_agents_fn = """register_agents() {
    section "Registering built-in agents"

    local python_path=""
    if [[ -n "${CADUCEUS_PYTHON_SOURCE:-}" ]]; then
        python_path="$(dirname "$CADUCEUS_PYTHON_SOURCE")"
    elif [[ -d "$HERMES_HOME/caduceus/python" ]]; then
        python_path="$HERMES_HOME/caduceus/python"
    fi

    if [[ -z "$python_path" ]]; then
        warn "Could not find python package path — skipping agent seeding"
        return
    fi

    info "Seeding 7 built-in Theoi agents..."
    local seeded_count
    seeded_count=$(PYTHONPATH="$python_path" python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$python_path')
from caduceus import init_db, seed_agents
import os
os.environ['CADUCEUS_DB_PATH'] = os.path.expanduser('$CADUCEUS_DB')
init_db()
seeded = seed_agents()
print(len(seeded))
" 2>&1) || true

    if [[ -n "$seeded_count" ]] && [[ "$seeded_count" != "0" ]]; then
        success "Registered $seeded_count agents: orchestrator, engineer, researcher, writer, themis, kairos, monitor"
    else
        info "Agents already seeded (or DB not ready yet)"
    fi
}

main() {
    echo ""
    echo "========================================"
    echo -e "  ${BOLD}Caduceus${RESET} $CADUCEUS_VERSION — Hermes-native agent orchestration"
    echo "========================================"

    check_prereqs
    install_skills
    install_qmd
    install_python_package
    install_db
    cleanup_clone
    register_skills

    if [[ "$INSTALL_UI" == "true" ]]; then
        install_ui
    fi

    done_message
}"""

new_content = content.replace(old_main, register_agents_fn)
if new_content == content:
    print("ERROR: main() not found in install.sh")
    sys.exit(1)

with open('scripts/install.sh', 'w') as f:
    f.write(new_content)
print("OK - main() and register_agents() updated")
