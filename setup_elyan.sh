#!/bin/bash

################################################################################
# ELYAN - One-Command Installation Script
# This script downloads and sets up the complete Elyan system (v1.0.0)
#
# Usage: bash setup_elyan.sh [options]
#   --clean              Remove all existing installations and start fresh
#   --skip-venv          Don't create virtual environment
#   --install-extras     Install optional dependencies (voice, extra adapters)
#   --help               Show this help message
#
# Author: Elyan Team
# Last Updated: 2026-03-17
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/emrek0ca/bot.git"
BRANCH="main"
INSTALL_DIR="${HOME}/.elyan"
REPO_DIR="${INSTALL_DIR}/repo"
VENV_DIR="${INSTALL_DIR}/venv"
LOG_FILE="${INSTALL_DIR}/setup.log"

# Flags
CLEAN_INSTALL=false
SKIP_VENV=false
INSTALL_EXTRAS=false

################################################################################
# Functions
################################################################################

log() {
    echo -e "${BLUE}[Elyan]${NC} $1" | tee -a "$LOG_FILE"
}

success() {
    echo -e "${GREEN}✓${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}✗${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

warning() {
    echo -e "${YELLOW}!${NC} $1" | tee -a "$LOG_FILE"
}

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        error "$1 is not installed. Please install $1 first."
    fi
    success "$1 is installed"
}

check_requirements() {
    print_header "System Requirements Check"

    log "Checking system requirements..."

    check_command "git"
    check_command "python3"

    # Check Python version
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    log "Python version: $PYTHON_VERSION"

    if python3 -c "import sys; exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
        success "Python 3.9+ is installed"
    else
        error "Python 3.9 or later is required (found $PYTHON_VERSION)"
    fi
}

setup_directories() {
    print_header "Setting Up Directories"

    if [ "$CLEAN_INSTALL" = true ]; then
        log "Cleaning previous installation..."
        rm -rf "$INSTALL_DIR"
        success "Previous installation removed"
    fi

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$REPO_DIR"
    mkdir -p "${INSTALL_DIR}/data"
    mkdir -p "${INSTALL_DIR}/logs"

    success "Directories created: $INSTALL_DIR"
}

clone_repository() {
    print_header "Downloading Elyan Repository"

    if [ -d "$REPO_DIR/.git" ]; then
        log "Repository already exists, updating..."
        cd "$REPO_DIR"
        git fetch origin
        git checkout $BRANCH
        git pull origin $BRANCH
    else
        log "Cloning repository from $REPO_URL..."
        git clone -b $BRANCH "$REPO_URL" "$REPO_DIR"
    fi

    cd "$REPO_DIR"
    success "Repository ready at $REPO_DIR"
}

setup_virtual_environment() {
    if [ "$SKIP_VENV" = true ]; then
        warning "Skipping virtual environment setup"
        return
    fi

    print_header "Setting Up Python Virtual Environment"

    if [ -d "$VENV_DIR" ]; then
        log "Virtual environment already exists"
    else
        log "Creating virtual environment at $VENV_DIR..."
        python3 -m venv "$VENV_DIR"
        success "Virtual environment created"
    fi

    log "Activating virtual environment..."
    source "$VENV_DIR/bin/activate"

    log "Upgrading pip, setuptools, wheel..."
    pip install --upgrade pip setuptools wheel 2>&1 | grep -i "successfully\|already"
}

install_dependencies() {
    print_header "Installing Python Dependencies"

    cd "$REPO_DIR"

    log "Reading requirements.txt..."
    if [ ! -f "requirements.txt" ]; then
        error "requirements.txt not found in $REPO_DIR"
    fi

    log "Installing dependencies..."
    pip install -r requirements.txt 2>&1 | tail -20

    if [ "$INSTALL_EXTRAS" = true ]; then
        log "Installing optional dependencies..."
        # Install optional voice dependencies
        pip install \
            openai-whisper>=20240927 \
            pyttsx3>=2.90 \
            pydub>=0.25.0 \
            2>&1 | tail -10
        success "Optional dependencies installed"
    fi

    success "All dependencies installed"
}

run_tests() {
    print_header "Running Test Suite"

    cd "$REPO_DIR"

    if ! command -v pytest &> /dev/null; then
        warning "pytest not found, skipping tests"
        return
    fi

    log "Running Phase 5 tests..."
    python3 -m pytest tests/test_weeks1112_modules.py -v --tb=short 2>&1 | tail -20

    if [ $? -eq 0 ]; then
        success "All tests passed!"
    else
        warning "Some tests failed, but installation is complete"
    fi
}

create_activation_script() {
    print_header "Creating Activation Script"

    ACTIVATION_SCRIPT="${INSTALL_DIR}/activate.sh"

    cat > "$ACTIVATION_SCRIPT" << 'EOF'
#!/bin/bash
# Activate Elyan environment

INSTALL_DIR="${HOME}/.elyan"
VENV_DIR="${INSTALL_DIR}/venv"
REPO_DIR="${INSTALL_DIR}/repo"

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo "Elyan environment activated"
    echo "Repository: $REPO_DIR"
else
    echo "Error: Virtual environment not found at $VENV_DIR"
    exit 1
fi
EOF

    chmod +x "$ACTIVATION_SCRIPT"
    success "Activation script created: $ACTIVATION_SCRIPT"
}

create_launch_script() {
    print_header "Creating Launch Scripts"

    cd "$REPO_DIR"

    # Create desktop launcher for macOS
    if [ "$(uname)" = "Darwin" ]; then
        LAUNCHER="${INSTALL_DIR}/Elyan.sh"

        cat > "$LAUNCHER" << 'EOF'
#!/bin/bash
INSTALL_DIR="${HOME}/.elyan"
VENV_DIR="${INSTALL_DIR}/venv"
REPO_DIR="${INSTALL_DIR}/repo"

source "$VENV_DIR/bin/activate"
cd "$REPO_DIR"
python3 -m core.agent "$@"
EOF

        chmod +x "$LAUNCHER"
        success "Launch script created: $LAUNCHER"
    fi

    # Create CLI wrapper
    CLI_WRAPPER="${INSTALL_DIR}/elyan"

    cat > "$CLI_WRAPPER" << 'EOF'
#!/bin/bash
INSTALL_DIR="${HOME}/.elyan"
VENV_DIR="${INSTALL_DIR}/venv"
REPO_DIR="${INSTALL_DIR}/repo"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Elyan is not installed. Run: bash setup_elyan.sh"
    exit 1
fi

source "$VENV_DIR/bin/activate"
cd "$REPO_DIR"
python3 "$REPO_DIR/scripts/cli.py" "$@"
EOF

    chmod +x "$CLI_WRAPPER"
    success "CLI wrapper created: $CLI_WRAPPER"

    # Create symlink in /usr/local/bin if possible
    if [ -w /usr/local/bin ]; then
        ln -sf "$CLI_WRAPPER" /usr/local/bin/elyan
        success "Created /usr/local/bin/elyan symlink"
    else
        warning "Cannot create /usr/local/bin symlink (needs sudo). Run:"
        warning "  sudo ln -s $CLI_WRAPPER /usr/local/bin/elyan"
    fi
}

create_config() {
    print_header "Creating Configuration"

    CONFIG_DIR="${INSTALL_DIR}/config"
    mkdir -p "$CONFIG_DIR"

    CONFIG_FILE="${CONFIG_DIR}/elyan.yaml"

    if [ ! -f "$CONFIG_FILE" ]; then
        cat > "$CONFIG_FILE" << 'EOF'
# Elyan Configuration
# Edit this file to customize Elyan behavior

app:
  name: Elyan
  version: "1.0.0"
  debug: false

# LLM Configuration
llm:
  # Primary provider (groq, gemini, claude, gpt4)
  provider: groq
  model: llama-3.3-70b-versatile
  temperature: 0.7
  max_tokens: 4000

# Learning System
learning:
  enabled: true
  persistence: sqlite
  storage_path: ~/.elyan/data/learning

# Memory
memory:
  episodic_enabled: true
  semantic_enabled: true
  max_episodes: 1000

# Security
security:
  enable_audit_logging: true
  require_https: false
  cors_enabled: true

# API Rate Limiting
rate_limiting:
  enabled: true
  requests_per_minute: 60
  burst_size: 10

# Monitoring
monitoring:
  enabled: true
  metrics_port: 9090
  log_level: INFO
EOF
        success "Configuration created: $CONFIG_FILE"
    else
        log "Configuration already exists"
    fi
}

verify_installation() {
    print_header "Verifying Installation"

    cd "$REPO_DIR"

    CHECKS_PASSED=0
    CHECKS_TOTAL=0

    # Check 1: Repository
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    if [ -d "$REPO_DIR/.git" ]; then
        success "Repository verified"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        error "Repository not found"
    fi

    # Check 2: Virtual Environment
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    if [ -f "$VENV_DIR/bin/python" ]; then
        success "Virtual environment verified"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        warning "Virtual environment not found (may have skipped)"
    fi

    # Check 3: Core modules
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    REQUIRED_FILES=(
        "core/learning_engine.py"
        "core/autonomous_coding_agent.py"
        "core/production_monitor.py"
        "core/api_rate_limiter.py"
        "core/custom_model_framework.py"
        "core/documentation_generator.py"
    )

    ALL_FILES_EXIST=true
    for file in "${REQUIRED_FILES[@]}"; do
        if [ ! -f "$REPO_DIR/$file" ]; then
            warning "Missing: $file"
            ALL_FILES_EXIST=false
        fi
    done

    if [ "$ALL_FILES_EXIST" = true ]; then
        success "All core modules present"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    fi

    # Check 4: Tests
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    if [ -f "$REPO_DIR/tests/test_weeks1112_modules.py" ]; then
        success "Test suite present"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        warning "Test suite not found"
    fi

    echo ""
    log "Verification: $CHECKS_PASSED/$CHECKS_TOTAL checks passed"
}

print_summary() {
    print_header "Installation Complete! 🎉"

    echo ""
    echo -e "${GREEN}Elyan v1.0.0 has been successfully installed!${NC}"
    echo ""
    echo "Installation Details:"
    echo "  Install Directory: $INSTALL_DIR"
    echo "  Repository: $REPO_DIR"
    if [ "$SKIP_VENV" = false ]; then
        echo "  Virtual Environment: $VENV_DIR"
    fi
    echo "  Configuration: ${INSTALL_DIR}/config/elyan.yaml"
    echo "  Logs: ${INSTALL_DIR}/logs/"
    echo ""
    echo "Next Steps:"
    echo ""
    echo "  1. Activate the environment:"
    echo "     source ${INSTALL_DIR}/activate.sh"
    echo ""
    echo "  2. Verify installation:"
    echo "     python3 -m pytest tests/test_weeks1112_modules.py -v"
    echo ""
    echo "  3. Configure Elyan:"
    echo "     Edit ${INSTALL_DIR}/config/elyan.yaml"
    echo ""
    echo "  4. Set API keys (if needed):"
    echo "     export GROQ_API_KEY='your-key'"
    echo "     export GOOGLE_API_KEY='your-key'"
    echo ""
    echo "  5. Run Elyan:"
    if [ -w /usr/local/bin ] && [ -L /usr/local/bin/elyan ]; then
        echo "     elyan --help"
    else
        echo "     bash ${INSTALL_DIR}/Elyan.sh --help"
    fi
    echo ""
    echo "Documentation:"
    echo "  API Docs: $REPO_DIR/docs/"
    echo "  GitHub: $REPO_URL"
    echo "  Issues: ${REPO_URL}/issues"
    echo ""
    echo "Support:"
    echo "  For issues, visit: ${REPO_URL}/issues"
    echo "  Documentation: See docs/ folder"
    echo ""
}

show_help() {
    cat << EOF
${BLUE}ELYAN Installation Script${NC}

Usage: bash setup_elyan.sh [OPTIONS]

OPTIONS:
  --clean              Remove all existing installations and start fresh
  --skip-venv          Don't create virtual environment (use system Python)
  --install-extras     Install optional dependencies (voice, extra channels)
  --help               Show this help message

EXAMPLES:
  # Standard installation
  bash setup_elyan.sh

  # Clean installation (removes previous setup)
  bash setup_elyan.sh --clean

  # Skip virtual environment
  bash setup_elyan.sh --skip-venv

  # Installation with optional features
  bash setup_elyan.sh --install-extras

For more information, visit: https://github.com/emrek0ca/bot

EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --clean)
                CLEAN_INSTALL=true
                shift
                ;;
            --skip-venv)
                SKIP_VENV=true
                shift
                ;;
            --install-extras)
                INSTALL_EXTRAS=true
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                ;;
        esac
    done
}

################################################################################
# Main Execution
################################################################################

main() {
    print_header "ELYAN v1.0.0 - One-Command Installation"

    # Initialize log file
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "Setup started at $(date)" > "$LOG_FILE"

    # Parse command line arguments
    parse_arguments "$@"

    # Run installation steps
    check_requirements
    setup_directories
    clone_repository

    if [ "$SKIP_VENV" = false ]; then
        setup_virtual_environment
    fi

    install_dependencies
    create_config
    create_activation_script
    create_launch_script
    verify_installation

    # Run tests
    if command -v pytest &> /dev/null; then
        read -p "Run test suite? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            run_tests
        fi
    fi

    print_summary

    log "Setup completed successfully!"
    log "Log file: $LOG_FILE"
}

# Run main function
main "$@"
