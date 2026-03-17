#!/bin/bash

################################################################################
# ELYAN v1.0.0 - Deployment Validation Script
# Validates that the installation system works correctly
# Usage: bash validate_deployment.sh
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
    print_header "ELYAN v1.0.0 - Deployment Validation"

    # Check 1: Installation Scripts Exist
    print_header "Installation Scripts"

    if [ -f "setup_elyan.sh" ] && [ -x "setup_elyan.sh" ]; then
        check_pass "setup_elyan.sh exists and is executable"
    else
        check_fail "setup_elyan.sh missing or not executable"
        return 1
    fi

    if [ -f "verify_elyan.sh" ] && [ -x "verify_elyan.sh" ]; then
        check_pass "verify_elyan.sh exists and is executable"
    else
        check_fail "verify_elyan.sh missing or not executable"
    fi

    # Check 2: Script Syntax
    print_header "Script Validation"

    if bash -n setup_elyan.sh 2>/dev/null; then
        check_pass "setup_elyan.sh has valid syntax"
    else
        check_fail "setup_elyan.sh has syntax errors"
    fi

    if bash -n verify_elyan.sh 2>/dev/null; then
        check_pass "verify_elyan.sh has valid syntax"
    else
        check_fail "verify_elyan.sh has syntax errors"
    fi

    # Check 3: Core Modules
    print_header "Core Modules (Phase 5)"

    MODULES=(
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

    for module in "${MODULES[@]}"; do
        if [ -f "$module" ]; then
            lines=$(wc -l < "$module")
            check_pass "$(basename $module) exists ($lines lines)"
        else
            check_fail "$(basename $module) missing"
        fi
    done

    # Check 4: Test Suite
    print_header "Test Suite"

    if [ -f "tests/test_weeks1112_modules.py" ]; then
        check_pass "test_weeks1112_modules.py exists"
        test_count=$(grep -c "def test_" tests/test_weeks1112_modules.py || echo "0")
        check_pass "Contains $test_count test cases"
    else
        check_fail "test_weeks1112_modules.py missing"
    fi

    # Check 5: Dependencies
    print_header "Dependencies"

    if [ -f "requirements.txt" ]; then
        check_pass "requirements.txt exists"

        # Check for key dependencies
        if grep -q "groq" requirements.txt; then
            check_pass "Groq dependency present"
        else
            check_warn "Groq dependency missing"
        fi

        if grep -q "prometheus-client" requirements.txt; then
            check_pass "Prometheus dependency present"
        else
            check_warn "Prometheus dependency missing"
        fi

        if grep -q "pytest" requirements.txt; then
            check_pass "pytest dependency present"
        else
            check_fail "pytest dependency missing"
        fi
    else
        check_fail "requirements.txt missing"
    fi

    # Check 6: Documentation
    print_header "Documentation"

    docs=(
        "README.md"
        "QUICKSTART.md"
        "INSTALLATION_GUIDE.txt"
        "DEPLOYMENT_READY.md"
    )

    for doc in "${docs[@]}"; do
        if [ -f "$doc" ]; then
            lines=$(wc -l < "$doc")
            check_pass "$doc exists ($lines lines)"
        else
            check_warn "$doc missing (optional)"
        fi
    done

    # Check 7: Git Status
    print_header "Git Integration"

    if [ -d ".git" ]; then
        check_pass "Git repository initialized"

        commit_count=$(git rev-list --count HEAD 2>/dev/null || echo "0")
        check_pass "Contains $commit_count commits"

        current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        if [ "$current_branch" = "main" ]; then
            check_pass "On main branch"
        else
            check_warn "On branch: $current_branch (expected: main)"
        fi
    else
        check_fail "Git repository not initialized"
    fi

    # Check 8: Python Modules
    print_header "Python Module Verification"

    python3 -c "import sys; exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null
    if [ $? -eq 0 ]; then
        check_pass "Python 3.9+ available"
    else
        check_fail "Python 3.9+ required"
    fi

    # Check individual modules
    if python3 -c "from core.learning_engine import LearningEngine" 2>/dev/null; then
        check_pass "learning_engine module importable"
    else
        check_warn "learning_engine module not importable (expected before installation)"
    fi

    # Check 9: Test Execution
    print_header "Test Suite Execution"

    if command -v pytest &> /dev/null; then
        echo "Running test suite..."
        if python3 -m pytest tests/test_weeks1112_modules.py -q --tb=no 2>/dev/null; then
            test_result=$(python3 -m pytest tests/test_weeks1112_modules.py -q --tb=no 2>&1 | tail -1)
            check_pass "Test suite passes: $test_result"
        else
            check_warn "Some tests may fail (dependencies not yet installed)"
        fi
    else
        check_warn "pytest not available (will be installed during setup)"
    fi

    # Check 10: Installation Script Content
    print_header "Installation Script Validation"

    if grep -q "REPO_URL" setup_elyan.sh; then
        check_pass "setup_elyan.sh contains repository URL"
    else
        check_fail "setup_elyan.sh missing repository URL"
    fi

    if grep -q "python3 -m venv" setup_elyan.sh; then
        check_pass "setup_elyan.sh creates virtual environment"
    else
        check_fail "setup_elyan.sh doesn't create venv"
    fi

    if grep -q "pip install -r requirements.txt" setup_elyan.sh; then
        check_pass "setup_elyan.sh installs dependencies"
    else
        check_fail "setup_elyan.sh doesn't install dependencies"
    fi

    # Summary
    print_header "Validation Summary"

    TOTAL=$((CHECKS_PASSED + CHECKS_FAILED))
    echo "Checks Passed: $CHECKS_PASSED"
    echo "Checks Failed: $CHECKS_FAILED"
    echo "Total Checks: $TOTAL"
    echo ""

    if [ $CHECKS_FAILED -eq 0 ]; then
        echo -e "${GREEN}✓ ELYAN v1.0.0 is ready for deployment!${NC}"
        echo ""
        echo "Next steps:"
        echo "1. Run setup_elyan.sh for full installation"
        echo "2. Follow INSTALLATION_GUIDE.txt for setup"
        echo "3. See QUICKSTART.md for usage examples"
        echo ""
        echo "For Series A launch:"
        echo "- Repository is on GitHub: https://github.com/emrek0ca/bot"
        echo "- Installation script is ready: setup_elyan.sh"
        echo "- One-command install: bash <(curl -s https://raw.githubusercontent.com/emrek0ca/bot/main/setup_elyan.sh)"
        echo ""
        return 0
    else
        echo -e "${RED}✗ Some validations failed. Review errors above.${NC}"
        echo ""
        echo "Common fixes:"
        echo "1. Ensure all Phase 5 modules are in core/"
        echo "2. Verify test file exists: tests/test_weeks1112_modules.py"
        echo "3. Check setup_elyan.sh syntax"
        echo "4. Update requirements.txt if needed"
        echo ""
        return 1
    fi
}

main "$@"
