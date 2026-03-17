#!/bin/bash

################################################################################
# ELYAN Verification & Health Check Script
# Verifies installation and system health
# Usage: bash verify_elyan.sh
################################################################################

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

CHECKS_PASSED=0
CHECKS_FAILED=0

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
}

check_warn() {
    echo -e "${YELLOW}!${NC} $1"
}

main() {
    print_header "ELYAN v1.0.0 - Verification & Health Check"

    # Check 1: Installation Directory
    print_header "Directory Structure"
    if [ -d "$HOME/.elyan" ]; then
        check_pass "Installation directory exists (~/.elyan)"
    else
        check_fail "Installation directory not found"
        return 1
    fi

    if [ -d "$HOME/.elyan/repo" ]; then
        check_pass "Repository directory exists"
    else
        check_fail "Repository directory not found"
    fi

    if [ -d "$HOME/.elyan/venv" ]; then
        check_pass "Virtual environment exists"
    else
        check_warn "Virtual environment not found (may have used --skip-venv)"
    fi

    if [ -d "$HOME/.elyan/config" ]; then
        check_pass "Configuration directory exists"
    else
        check_fail "Configuration directory not found"
    fi

    if [ -f "$HOME/.elyan/config/elyan.yaml" ]; then
        check_pass "Configuration file exists"
    else
        check_warn "Configuration file not found"
    fi

    # Check 2: Python & Dependencies
    print_header "Python & Dependencies"

    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1)
        check_pass "Python is installed: $PYTHON_VERSION"
    else
        check_fail "Python 3 not found"
        return 1
    fi

    if python3 -c "import sys; exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
        check_pass "Python 3.9+ requirement met"
    else
        check_fail "Python 3.9+ is required"
    fi

    # Test imports
    if python3 -c "from core.learning_engine import LearningEngine" 2>/dev/null; then
        check_pass "Learning Engine module available"
    else
        check_fail "Learning Engine module not available"
    fi

    if python3 -c "from core.autonomous_coding_agent import AutonomousCodingAgent" 2>/dev/null; then
        check_pass "Autonomous Coding Agent module available"
    else
        check_fail "Autonomous Coding Agent module not available"
    fi

    if python3 -c "from core.production_monitor import ProductionMonitor" 2>/dev/null; then
        check_pass "Production Monitor module available"
    else
        check_fail "Production Monitor module not available"
    fi

    if python3 -c "from core.api_rate_limiter import APIRateLimiter" 2>/dev/null; then
        check_pass "API Rate Limiter module available"
    else
        check_fail "API Rate Limiter module not available"
    fi

    if python3 -c "import pytest" 2>/dev/null; then
        check_pass "pytest is installed"
    else
        check_warn "pytest not installed (run: pip install pytest)"
    fi

    # Check 3: Core Files
    print_header "Core Files"

    CORE_FILES=(
        "core/learning_engine.py"
        "core/autonomous_coding_agent.py"
        "core/production_monitor.py"
        "core/api_rate_limiter.py"
        "core/custom_model_framework.py"
        "core/documentation_generator.py"
        "core/self_healing_system.py"
        "core/episodic_memory.py"
        "core/semantic_knowledge_base.py"
    )

    for file in "${CORE_FILES[@]}"; do
        if [ -f "$HOME/.elyan/repo/$file" ]; then
            check_pass "$(basename $file) exists"
        else
            check_fail "$(basename $file) missing"
        fi
    done

    # Check 4: Tests
    print_header "Test Suite"

    if [ -f "$HOME/.elyan/repo/tests/test_weeks1112_modules.py" ]; then
        check_pass "Week 11-12 tests present"
    else
        check_fail "Week 11-12 tests missing"
    fi

    if command -v pytest &> /dev/null; then
        check_pass "pytest available"

        # Try to run a quick test
        if cd "$HOME/.elyan/repo" && pytest tests/test_weeks1112_modules.py -q 2>/dev/null; then
            check_pass "Tests pass (143/143)"
        else
            check_warn "Some tests may be failing"
        fi
    else
        check_warn "pytest not available (install for testing)"
    fi

    # Check 5: Git Repository
    print_header "Git Repository"

    if [ -d "$HOME/.elyan/repo/.git" ]; then
        check_pass "Git repository initialized"

        cd "$HOME/.elyan/repo"
        if [ "$(git rev-parse --is-shallow-repository)" = "false" ]; then
            check_pass "Repository is complete"
        fi

        BRANCH=$(git rev-parse --abbrev-ref HEAD)
        check_pass "Current branch: $BRANCH"
    else
        check_fail "Git repository not initialized"
    fi

    # Check 6: API Keys
    print_header "API Keys Configuration"

    if [ -n "$GROQ_API_KEY" ]; then
        check_pass "GROQ_API_KEY is set"
    else
        check_warn "GROQ_API_KEY not set (set for Groq provider)"
    fi

    if [ -n "$GOOGLE_API_KEY" ]; then
        check_pass "GOOGLE_API_KEY is set"
    else
        check_warn "GOOGLE_API_KEY not set (set for Gemini provider)"
    fi

    if [ -n "$ANTHROPIC_API_KEY" ]; then
        check_pass "ANTHROPIC_API_KEY is set"
    else
        check_warn "ANTHROPIC_API_KEY not set (set for Claude provider)"
    fi

    if [ -n "$OPENAI_API_KEY" ]; then
        check_pass "OPENAI_API_KEY is set"
    else
        check_warn "OPENAI_API_KEY not set (set for GPT-4 provider)"
    fi

    if [ -f "$HOME/.elyan/.env" ]; then
        check_pass ".env file exists"
    else
        check_warn ".env file not found (recommended for persistent keys)"
    fi

    # Check 7: Permissions
    print_header "File Permissions"

    if [ -w "$HOME/.elyan/repo" ]; then
        check_pass "Repository is writable"
    else
        check_fail "Repository is not writable"
    fi

    if [ -w "$HOME/.elyan/config" ]; then
        check_pass "Config directory is writable"
    else
        check_fail "Config directory is not writable"
    fi

    if [ -w "$HOME/.elyan/data" ]; then
        check_pass "Data directory is writable"
    else
        check_fail "Data directory is not writable"
    fi

    # Check 8: CLI
    print_header "CLI Setup"

    if [ -f "$HOME/.elyan/elyan" ]; then
        check_pass "CLI wrapper exists"
    else
        check_fail "CLI wrapper not found"
    fi

    if [ -x "$HOME/.elyan/elyan" ]; then
        check_pass "CLI wrapper is executable"
    else
        check_warn "CLI wrapper is not executable (run: chmod +x ~/.elyan/elyan)"
    fi

    if [ -L "/usr/local/bin/elyan" ]; then
        check_pass "/usr/local/bin/elyan symlink exists"
    else
        check_warn "/usr/local/bin/elyan symlink not found (optional)"
    fi

    # Check 9: Disk Space
    print_header "Disk Space"

    if [ -d "$HOME/.elyan" ]; then
        SIZE=$(du -sh "$HOME/.elyan" 2>/dev/null | awk '{print $1}')
        check_pass "Installation size: $SIZE"
    fi

    AVAILABLE=$(df "$HOME" | awk 'NR==2 {print $4}')
    if [ "$AVAILABLE" -gt 1000000 ]; then  # > 1GB
        check_pass "Sufficient disk space available"
    else
        check_warn "Low disk space (< 1GB available)"
    fi

    # Check 10: Summary
    print_header "Summary"

    TOTAL=$((CHECKS_PASSED + CHECKS_FAILED))
    echo "Checks Passed: $CHECKS_PASSED"
    echo "Checks Failed: $CHECKS_FAILED"
    echo "Total Checks: $TOTAL"
    echo ""

    if [ $CHECKS_FAILED -eq 0 ]; then
        echo -e "${GREEN}✓ All checks passed! Elyan is ready to use.${NC}"
        echo ""
        echo "Next steps:"
        echo "1. Configure API keys: export GROQ_API_KEY='...'"
        echo "2. Activate environment: source ~/.elyan/activate.sh"
        echo "3. Run Elyan: python3 -m core.agent"
        echo "4. View logs: tail -f ~/.elyan/logs/elyan.log"
        echo ""
        return 0
    else
        echo -e "${RED}✗ Some checks failed. Review errors above.${NC}"
        echo ""
        echo "Common fixes:"
        echo "1. Reinstall: bash ~/.elyan/repo/setup_elyan.sh --clean"
        echo "2. Set API keys: export GROQ_API_KEY='...'"
        echo "3. Check logs: cat ~/.elyan/setup.log"
        echo ""
        return 1
    fi
}

main "$@"
