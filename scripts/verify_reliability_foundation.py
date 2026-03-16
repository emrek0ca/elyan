#!/usr/bin/env python3
"""
Verification Script for RELIABILITY FOUNDATION

Verifies that all RELIABILITY FOUNDATION modules are:
1. Importable without errors
2. Contain all required components
3. Properly integrated
4. Have complete documentation

Usage:
    python scripts/verify_reliability_foundation.py [--full] [--verbose]
"""

import sys
import importlib
import inspect
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger

logger = get_logger("verify_rf")

# Expected modules and components
REQUIRED_MODULES = {
    "core.execution_model": [
        "ExecutionStatus",
        "ErrorSeverity",
        "ErrorCategory",
        "ExecutionError",
        "ExecutionMetrics",
        "TaskExecutionState",
        "ToolExecutionResult",
        "PartialFailureInfo",
    ],
    "core.tool_schemas": [
        "ParameterType",
        "ParameterSchema",
        "ToolSchema",
        "SchemaRegistry",
        "get_schema_registry",
        "create_string_param",
        "create_integer_param",
        "create_file_path_param",
        "create_enum_param",
    ],
    "core.json_repair": [
        "JSONRepair",
        "repair_json",
        "safe_json_loads",
        "extract_json_from_text",
    ],
    "core.execution_report": [
        "ReportFormat",
        "ExecutionReport",
        "ExecutionReportBuilder",
    ],
    "core.validators": [
        "ValidationLevel",
        "RiskLevel",
        "ValidationContext",
        "ValidationResult",
        "ParameterValidator",
        "PathValidator",
        "PermissionValidator",
        "ResourceValidator",
        "RiskAssessment",
        "ComprehensiveValidator",
    ],
    "core.reliability_integration": [
        "ExecutionGuard",
        "JSONRepairIntegration",
        "ExecutionTracker",
        "get_execution_tracker",
        "validate_before_execution",
        "sanitize_and_validate_params",
        "assess_operation_risk",
    ],
}


def verify_imports(verbose=False):
    """Verify all modules can be imported"""
    print("=" * 70)
    print("1. CHECKING IMPORTS")
    print("=" * 70)

    all_ok = True

    for module_name, components in REQUIRED_MODULES.items():
        try:
            module = importlib.import_module(module_name)
            status = "✓ OK"
            print(f"{status}: {module_name}")

            if verbose:
                for component in components:
                    if hasattr(module, component):
                        obj = getattr(module, component)
                        obj_type = (
                            "class" if inspect.isclass(obj) else "function" if inspect.isfunction(obj) else "constant"
                        )
                        print(f"   ✓ {component} ({obj_type})")
                    else:
                        print(f"   ✗ {component} (NOT FOUND)")
                        all_ok = False

        except ImportError as e:
            print(f"✗ FAILED: {module_name} - {e}")
            all_ok = False
        except Exception as e:
            print(f"✗ ERROR: {module_name} - {e}")
            all_ok = False

    return all_ok


def verify_components(verbose=False):
    """Verify all required components exist"""
    print("\n" + "=" * 70)
    print("2. CHECKING COMPONENTS")
    print("=" * 70)

    all_ok = True

    for module_name, components in REQUIRED_MODULES.items():
        try:
            module = importlib.import_module(module_name)

            for component in components:
                if hasattr(module, component):
                    print(f"✓ {module_name}.{component}")
                else:
                    print(f"✗ {module_name}.{component} NOT FOUND")
                    all_ok = False

        except ImportError as e:
            print(f"✗ Cannot check {module_name}: {e}")
            all_ok = False

    return all_ok


def test_basic_functionality():
    """Test basic functionality of each module"""
    print("\n" + "=" * 70)
    print("3. TESTING BASIC FUNCTIONALITY")
    print("=" * 70)

    all_ok = True

    # Test ExecutionModel
    try:
        from core.execution_model import ExecutionError, ErrorCategory, ErrorSeverity

        error = ExecutionError(
            message="Test",
            category=ErrorCategory.VALIDATION_ERROR,
            severity=ErrorSeverity.ERROR,
            code="TEST",
        )
        assert error.message == "Test"
        print("✓ ExecutionModel: ExecutionError creation works")
    except Exception as e:
        print(f"✗ ExecutionModel: {e}")
        all_ok = False

    # Test ToolSchemas
    try:
        from core.tool_schemas import create_string_param, ParameterSchema

        schema = create_string_param("test", required=True)
        assert schema.name == "test"
        print("✓ ToolSchemas: Parameter creation works")
    except Exception as e:
        print(f"✗ ToolSchemas: {e}")
        all_ok = False

    # Test JSONRepair
    try:
        from core.json_repair import JSONRepair

        success, result, error = JSONRepair.repair_and_parse('{"key": "value"}')
        assert success is True
        assert result["key"] == "value"
        print("✓ JSONRepair: JSON parsing works")
    except Exception as e:
        print(f"✗ JSONRepair: {e}")
        all_ok = False

    # Test ExecutionReport
    try:
        from core.execution_report import ExecutionReport, ExecutionReportBuilder

        report = ExecutionReport(execution_id="test", task_id="test")
        assert report.execution_id == "test"
        print("✓ ExecutionReport: Report creation works")
    except Exception as e:
        print(f"✗ ExecutionReport: {e}")
        all_ok = False

    # Test Validators
    try:
        from core.validators import PathValidator, ValidationResult

        result = PathValidator.validate_path("/tmp")
        assert isinstance(result, ValidationResult)
        print("✓ Validators: Path validation works")
    except Exception as e:
        print(f"✗ Validators: {e}")
        all_ok = False

    # Test Integration
    try:
        from core.reliability_integration import get_execution_tracker, ExecutionTracker

        tracker = get_execution_tracker()
        assert isinstance(tracker, ExecutionTracker)
        print("✓ ReliabilityIntegration: Tracker works")
    except Exception as e:
        print(f"✗ ReliabilityIntegration: {e}")
        all_ok = False

    return all_ok


def check_documentation():
    """Check that modules have documentation"""
    print("\n" + "=" * 70)
    print("4. CHECKING DOCUMENTATION")
    print("=" * 70)

    all_ok = True

    for module_name in REQUIRED_MODULES.keys():
        try:
            module = importlib.import_module(module_name)
            if module.__doc__:
                print(f"✓ {module_name}: Has module docstring")
            else:
                print(f"⚠ {module_name}: No module docstring")
                all_ok = False
        except Exception as e:
            print(f"✗ {module_name}: {e}")
            all_ok = False

    return all_ok


def verify_files_exist():
    """Verify all required files exist"""
    print("\n" + "=" * 70)
    print("5. CHECKING FILE EXISTENCE")
    print("=" * 70)

    all_ok = True
    required_files = [
        "core/execution_model.py",
        "core/tool_schemas.py",
        "core/json_repair.py",
        "core/execution_report.py",
        "core/validators.py",
        "core/reliability_integration.py",
        "tests/test_reliability_foundation.py",
    ]

    base_path = Path(__file__).parent.parent

    for file_path in required_files:
        full_path = base_path / file_path
        if full_path.exists():
            size_kb = full_path.stat().st_size / 1024
            print(f"✓ {file_path} ({size_kb:.1f} KB)")
        else:
            print(f"✗ {file_path} NOT FOUND")
            all_ok = False

    return all_ok


def print_summary(results):
    """Print verification summary"""
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)

    checks = [
        ("Imports", results.get("imports", False)),
        ("Components", results.get("components", False)),
        ("Functionality", results.get("functionality", False)),
        ("Documentation", results.get("documentation", False)),
        ("File Existence", results.get("files", False)),
    ]

    all_passed = all(result for _, result in checks)

    for check_name, passed in checks:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{status}: {check_name}")

    print("\n" + "=" * 70)
    if all_passed:
        print("✓ ALL CHECKS PASSED - RELIABILITY FOUNDATION VERIFIED")
    else:
        print("✗ SOME CHECKS FAILED - SEE ABOVE FOR DETAILS")
    print("=" * 70)

    return all_passed


def main():
    """Main verification"""
    import argparse

    parser = argparse.ArgumentParser(description="Verify RELIABILITY FOUNDATION")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--full", "-f", action="store_true", help="Full verification (includes all checks)")

    args = parser.parse_args()

    print("\n")
    print("█" * 70)
    print("█ RELIABILITY FOUNDATION VERIFICATION")
    print("█" * 70)

    results = {
        "imports": verify_imports(args.verbose),
        "components": verify_components(args.verbose),
        "functionality": test_basic_functionality(),
        "documentation": check_documentation(),
        "files": verify_files_exist(),
    }

    all_passed = print_summary(results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
