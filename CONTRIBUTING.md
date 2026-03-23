# Contributing to Elyan

Thank you for your interest in contributing to Elyan! This document provides guidelines and instructions for contributing.

## Code of Conduct

This project adheres to a Code of Conduct that all contributors are expected to follow. Please see [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) for details.

## How to Contribute

### Reporting Bugs

Before creating a bug report, please check the [issue list](https://github.com/emrek0ca/elyan/issues) to avoid duplicates.

When filing a bug report, include:

- **Clear title** — Specific, descriptive issue title
- **Step-by-step reproduction** — How to trigger the bug
- **Expected behavior** — What should happen
- **Actual behavior** — What actually happened
- **Environment** — Python version, OS, LLM provider used
- **Logs/Error messages** — Full traceback if available

### Suggesting Features

Feature suggestions are welcome! Please create an issue with:

- **Clear description** — What feature and why it's useful
- **Use cases** — Specific scenarios where this would help
- **Proposed behavior** — How it should work
- **Reference materials** — Links to related projects or documentation

### Pull Requests

1. **Fork the repository** and create a feature branch

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Write tests first** — This project practices test-driven development

   ```bash
   # Create test file in tests/
   pytest tests/your_test.py -v
   ```

3. **Implement the feature** — Follow existing code patterns

4. **Run the full test suite** — Ensure no regressions

   ```bash
   pytest tests/ -v --ignore=tests/test_office_tools.py
   ```

5. **Update documentation** — Add docstrings, update README if needed

6. **Commit with a clear message**

   ```bash
   git commit -m "feat: Add X feature"
   # or
   git commit -m "fix: Resolve Y issue"
   # or
   git commit -m "docs: Update Z documentation"
   ```

7. **Push to your fork** and create a Pull Request

   ```bash
   git push origin feature/your-feature-name
   ```

## Code Style Guidelines

### Python Code

- **Python 3.11+** required
- **Type hints** on all functions and methods
- **Docstrings** for all classes and public methods
- **Black** formatting (80-line limit for readability)
- **PEP 8** conventions

Example:

```python
def process_message(message: str, max_length: int = 1000) -> dict:
    """
    Process an inbound message with length validation.

    Args:
        message: Raw message text from user
        max_length: Maximum allowed message length (default 1000)

    Returns:
        dict with keys:
        - success (bool): Whether processing succeeded
        - text (str): Processed message
        - warnings (list): Any processing warnings

    Raises:
        ValueError: If message exceeds max_length
    """
    if len(message) > max_length:
        raise ValueError(f"Message exceeds {max_length} characters")

    return {
        "success": True,
        "text": message.strip(),
        "warnings": [],
    }
```

### Documentation

- Use **Markdown** for all documentation
- **Clear headings** with proper hierarchy
- **Code blocks** with language specified
- **Links** to related docs and references
- **Examples** showing common use cases

## Testing Requirements

### Test Coverage

- All new code must have corresponding tests
- Aim for **80%+ code coverage** on new modules
- Run tests locally before submitting PR:

```bash
pytest tests/ -v --cov=core --cov-report=html
```

### Test Organization

```
tests/
├── unit/              # Fast, isolated tests
├── integration/       # Module interaction tests
├── e2e/              # End-to-end workflow tests
└── test_*.py         # Test files
```

### Test Naming

- Test files: `test_<module_name>.py`
- Test functions: `test_<specific_scenario>`
- Use clear assertions with meaningful messages

Example:

```python
def test_intent_detection_with_invalid_input():
    """Intent detector should handle None gracefully."""
    detector = QuickIntentDetector()
    result = detector.detect(None)
    assert result is not None
    assert result.category == "unknown"
```

## Development Setup

### Prerequisites

- Python 3.11 or later
- pip or poetry for package management
- git

### Local Development

```bash
# Clone the repository
git clone https://github.com/emrek0ca/elyan.git
cd elyan

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Start development
python -m cli.main chat
```

### Before Submitting

```bash
# Format code
black .

# Check types
mypy core/ --ignore-missing-imports

# Run all tests
pytest tests/ -v --ignore=tests/test_office_tools.py

# Check coverage
pytest tests/ --cov=core --cov-report=term-missing
```

## Documentation Standards

### Docstring Format

Use Google-style docstrings for all public classes and methods:

```python
def execute_task(task: TaskDefinition, timeout: int = 30) -> TaskResult:
    """Execute a task with optional timeout.

    Args:
        task: The task to execute
        timeout: Maximum execution time in seconds (default 30)

    Returns:
        TaskResult containing:
        - success (bool): Whether task succeeded
        - output (str): Task output/result
        - error (str): Error message if failed

    Raises:
        TimeoutError: If execution exceeds timeout
        ValueError: If task definition is invalid

    Note:
        This function is async-compatible via TaskResult.
    """
```

### Module Documentation

Every module should have a docstring at the top:

```python
"""
Intent Router — Multi-tier intent detection system.

This module implements a 3-tier intent detection system:
1. Quick Pattern Matching (~5ms) — Regex patterns for common intents
2. Semantic Analysis (~100ms) — Embedding-based similarity
3. LLM Fallback — When higher-confidence routing is needed

Usage:
    from core.intent_router import route_intent
    intent = route_intent("open application")
"""
```

## Commit Message Guidelines

Follow conventional commits format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat` — New feature
- `fix` — Bug fix
- `docs` — Documentation changes
- `style` — Code style changes (no logic change)
- `refactor` — Code refactoring
- `perf` — Performance improvements
- `test` — Test additions/modifications
- `chore` — Build, CI, dependency updates

**Examples:**

```
feat(intent_parser): Add Turkish verb conjugation patterns

Adds support for Turkish verb conjugation in quick intent detection,
improving accuracy for command-like intents by 12%.

Related-To: #42
```

```
fix(task_engine): Prevent memory leak in task history

Clear completed tasks from memory after 1 hour to prevent unbounded
growth in long-running sessions.

Fixes #55
```

## Release Process

Releases are handled by maintainers. The process:

1. Version bump in `pyproject.toml` following [SemVer](https://semver.org/)
2. Update [`RELEASES.md`](./RELEASES.md) with changes
3. Create GitHub release with tag
4. Deploy to package repositories if applicable

## Questions?

- **Documentation** → Check [README.md](./README.md) and [OPERATING_MODES.md](./OPERATING_MODES.md)
- **Architecture** → See [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md)
- **Issues** → Open a [GitHub Issue](https://github.com/emrek0ca/elyan/issues)
- **Discussions** → Start a [GitHub Discussion](https://github.com/emrek0ca/elyan/discussions)

## Thank You

We appreciate your contributions to making Elyan better! 🙏
