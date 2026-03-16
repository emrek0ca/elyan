"""
Validators - Pre-execution validation and safety checks

Comprehensive validation framework for tool execution with:
- Parameter validation
- Permission checks
- Safety constraints
- Risk assessment
- Resource limits

Part of RELIABILITY FOUNDATION (Hafta 1-2)
"""

from typing import Any, Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass
from enum import Enum
import os
import re
from pathlib import Path

from core.execution_model import ExecutionError, ErrorSeverity, ErrorCategory
from core.tool_schemas import get_schema_registry, ToolSchema
from utils.logger import get_logger

logger = get_logger("validators")


class ValidationLevel(Enum):
    """Validation strictness levels"""
    STRICT = "strict"
    NORMAL = "normal"
    LENIENT = "lenient"


class RiskLevel(Enum):
    """Risk assessment levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ValidationContext:
    """Context for validation operations"""
    user_id: Optional[str] = None
    permission_level: int = 0  # 0-10, higher = more permissions
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None
    resource_limits: Optional[Dict[str, float]] = None
    environment_vars: Optional[Dict[str, str]] = None


@dataclass
class ValidationResult:
    """Result of validation operation"""
    is_valid: bool
    errors: List[str] = None
    warnings: List[str] = None
    risk_level: RiskLevel = RiskLevel.LOW
    suggestions: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.suggestions is None:
            self.suggestions = []

    def to_execution_error(self) -> Optional[ExecutionError]:
        """Convert to ExecutionError if validation failed"""
        if self.is_valid:
            return None

        return ExecutionError(
            message="; ".join(self.errors) if self.errors else "Validation failed",
            category=ErrorCategory.VALIDATION_ERROR,
            severity=ErrorSeverity.ERROR,
            code="VALIDATION_FAILED",
            context={
                "errors": self.errors,
                "warnings": self.warnings,
                "risk_level": self.risk_level.value,
            },
            suggestions=self.suggestions,
            recoverable=False,
        )


class ParameterValidator:
    """Validates tool parameters"""

    @staticmethod
    def validate_parameters(
        tool_name: str,
        params: Dict[str, Any],
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """
        Validate tool parameters against schema

        Returns:
            ValidationResult with errors if invalid
        """
        result = ValidationResult(is_valid=True)

        # Get schema from registry
        registry = get_schema_registry()
        schema = registry.get(tool_name)

        if not schema:
            logger.debug(f"Şema bulunamadı: {tool_name} (No schema for tool)")
            return result  # Allow if no schema

        # Validate using schema
        is_valid, errors = schema.validate_params(params)
        if not is_valid:
            result.is_valid = False
            result.errors = errors
            return result

        # Sanitize parameters
        sanitized_params = schema.sanitize_params(params)

        return result

    @staticmethod
    def validate_parameter_types(
        tool_name: str,
        params: Dict[str, Any],
    ) -> ValidationResult:
        """Validate that parameter types match schema"""
        result = ValidationResult(is_valid=True)
        registry = get_schema_registry()
        schema = registry.get(tool_name)

        if not schema:
            return result

        for param in schema.parameters:
            if param.name in params:
                value = params[param.name]
                is_valid, error = param.validate(value)
                if not is_valid:
                    result.is_valid = False
                    result.errors.append(error)

        return result


class PathValidator:
    """Validates file and directory paths"""

    # Blocked paths
    BLOCKED_PATHS = {
        "/System",
        "/Library",
        "/bin",
        "/sbin",
        "/usr/bin",
        "/usr/sbin",
        "/etc",
        "C:\\Windows",
        "C:\\Program Files",
    }

    # Blocked extensions for sensitive files
    BLOCKED_EXTENSIONS = {".exe", ".dll", ".so", ".dylib", ".sh", ".bat", ".cmd"}

    @staticmethod
    def validate_path(
        path: str,
        must_exist: bool = False,
        must_be_writable: bool = False,
        block_system_paths: bool = True,
    ) -> ValidationResult:
        """
        Validate file path safety

        Returns:
            ValidationResult with errors if path is unsafe
        """
        result = ValidationResult(is_valid=True)

        if not path:
            result.is_valid = False
            result.errors.append("Yol boş (Path is empty)")
            return result

        try:
            path_obj = Path(path).resolve()
            path_str = str(path_obj)

            # Check if path exists
            if must_exist and not path_obj.exists():
                result.is_valid = False
                result.errors.append(f"Yol bulunamadı: {path} (Path not found)")
                return result

            # Check if path is writable
            if must_be_writable:
                parent = path_obj.parent if path_obj.is_file() else path_obj
                if not os.access(parent, os.W_OK):
                    result.is_valid = False
                    result.errors.append(f"Yol yazılabilir değil: {path} (Path is not writable)")
                    return result

            # Check for system paths
            if block_system_paths:
                for blocked in PathValidator.BLOCKED_PATHS:
                    if path_str.startswith(blocked):
                        result.is_valid = False
                        result.errors.append(f"Sistem yoluna erişim engellendi: {path} (Access to system path blocked)")
                        return result

            # Check file extension
            suffix = path_obj.suffix.lower()
            if suffix in PathValidator.BLOCKED_EXTENSIONS:
                result.is_valid = False
                result.errors.append(f"Dosya türü engellendi: {suffix} (File type blocked)")
                return result

            # Add warnings
            if path_obj.is_dir() and not os.access(path_obj, os.R_OK):
                result.warnings.append(f"Dizin okunabilir değil: {path}")

            result.is_valid = True
            return result

        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Yol doğrulaması hatası: {str(e)}")
            return result

    @staticmethod
    def validate_directory_path(
        path: str,
        must_exist: bool = True,
        must_be_writable: bool = False,
    ) -> ValidationResult:
        """Validate directory path"""
        result = PathValidator.validate_path(
            path,
            must_exist=must_exist,
            must_be_writable=must_be_writable,
        )

        if result.is_valid:
            path_obj = Path(path)
            if not path_obj.is_dir():
                result.is_valid = False
                result.errors.append(f"Yol bir dizin değil: {path} (Path is not a directory)")

        return result


class PermissionValidator:
    """Validates user permissions"""

    @staticmethod
    def validate_tool_access(
        tool_name: str,
        context: ValidationContext,
    ) -> ValidationResult:
        """Check if user has permission to use tool"""
        result = ValidationResult(is_valid=True)

        if not context:
            return result

        # Check blocked tools
        if context.blocked_tools and tool_name in context.blocked_tools:
            result.is_valid = False
            result.errors.append(f"Araç engellendi: {tool_name} (Tool is blocked)")
            result.risk_level = RiskLevel.HIGH
            return result

        # Check allowed tools whitelist
        if context.allowed_tools and tool_name not in context.allowed_tools:
            result.is_valid = False
            result.errors.append(f"Araç izin verilmedi: {tool_name} (Tool not allowed)")
            result.risk_level = RiskLevel.HIGH
            return result

        return result

    @staticmethod
    def validate_permission_level(
        required_level: int,
        context: ValidationContext,
    ) -> ValidationResult:
        """Check if user has sufficient permission level"""
        result = ValidationResult(is_valid=True)

        if not context:
            return result

        if context.permission_level < required_level:
            result.is_valid = False
            result.errors.append(
                f"İzin seviyesi yetersiz: {context.permission_level} < {required_level} "
                f"(Permission level insufficient)"
            )
            result.risk_level = RiskLevel.HIGH
            return result

        return result


class ResourceValidator:
    """Validates resource usage"""

    @staticmethod
    def validate_resource_limits(
        resource_name: str,
        estimated_usage: float,
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """Check if estimated resource usage is within limits"""
        result = ValidationResult(is_valid=True)

        if not context or not context.resource_limits:
            return result

        limit = context.resource_limits.get(resource_name)
        if limit is None:
            return result

        if estimated_usage > limit:
            result.is_valid = False
            result.errors.append(
                f"Kaynak limiti aşıldı: {resource_name} "
                f"({estimated_usage:.1f} > {limit:.1f}) "
                f"(Resource limit exceeded)"
            )
            result.risk_level = RiskLevel.MEDIUM
            result.suggestions.append(f"Kullanımı {limit:.1f} altında tutun (Keep usage under {limit:.1f})")

        if estimated_usage > limit * 0.8:
            result.warnings.append(f"Kaynak kullanımı yüksek: {resource_name} ({estimated_usage:.1f}/{limit:.1f})")

        return result

    @staticmethod
    def validate_memory_usage(
        estimated_mb: float,
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """Check memory usage limits"""
        return ResourceValidator.validate_resource_limits("memory_mb", estimated_mb, context)

    @staticmethod
    def validate_disk_usage(
        estimated_mb: float,
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """Check disk usage limits"""
        return ResourceValidator.validate_resource_limits("disk_mb", estimated_mb, context)

    @staticmethod
    def validate_timeout(
        estimated_seconds: float,
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """Check timeout limits"""
        return ResourceValidator.validate_resource_limits("timeout_seconds", estimated_seconds, context)


class RiskAssessment:
    """Assesses risk of operations"""

    RISKY_OPERATIONS = {
        "delete": RiskLevel.HIGH,
        "remove": RiskLevel.HIGH,
        "destroy": RiskLevel.HIGH,
        "uninstall": RiskLevel.HIGH,
        "shutdown": RiskLevel.CRITICAL,
        "restart": RiskLevel.CRITICAL,
        "format": RiskLevel.CRITICAL,
        "modify_system": RiskLevel.CRITICAL,
        "modify_security": RiskLevel.CRITICAL,
    }

    @staticmethod
    def assess_risk(
        tool_name: str,
        action: str,
        params: Dict[str, Any],
    ) -> RiskLevel:
        """Assess overall risk of operation"""
        risk = RiskLevel.LOW

        # Check action risk
        action_lower = action.lower()
        for risky_keyword, risky_level in RiskAssessment.RISKY_OPERATIONS.items():
            if risky_keyword in action_lower:
                risk = risky_level
                break

        # Check tool risk
        tool_lower = tool_name.lower()
        if any(keyword in tool_lower for keyword in ["system", "security", "admin", "root"]):
            if risk == RiskLevel.LOW:
                risk = RiskLevel.MEDIUM

        # Check parameter risk
        for key, value in params.items():
            if isinstance(value, str):
                if "/*" in value or "*" in value:
                    risk = max(risk, RiskLevel.MEDIUM)

        return risk

    @staticmethod
    def requires_approval(risk_level: RiskLevel) -> bool:
        """Check if operation requires user approval"""
        return risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


class ComprehensiveValidator:
    """Comprehensive validator combining all checks"""

    @staticmethod
    def validate_execution(
        tool_name: str,
        action: str,
        params: Dict[str, Any],
        context: Optional[ValidationContext] = None,
        validation_level: ValidationLevel = ValidationLevel.NORMAL,
    ) -> ValidationResult:
        """
        Comprehensive validation before execution

        Returns:
            ValidationResult with all validation results
        """
        result = ValidationResult(is_valid=True)
        logger.info(f"Çalıştırma doğrulanıyor: {tool_name}/{action}")

        # 1. Tool access check
        if context:
            access_result = PermissionValidator.validate_tool_access(tool_name, context)
            if not access_result.is_valid:
                result.is_valid = False
                result.errors.extend(access_result.errors)
                return result

        # 2. Parameter validation
        param_result = ParameterValidator.validate_parameters(tool_name, params, context)
        if not param_result.is_valid:
            result.is_valid = False
            result.errors.extend(param_result.errors)
            if validation_level == ValidationLevel.STRICT:
                return result

        # 3. Path validation for file operations
        if tool_name in ("list_files", "read_file", "write_file", "delete_file"):
            if "path" in params:
                path_result = PathValidator.validate_path(params["path"])
                if not path_result.is_valid:
                    result.is_valid = False
                    result.errors.extend(path_result.errors)

        # 4. Risk assessment
        risk_level = RiskAssessment.assess_risk(tool_name, action, params)
        result.risk_level = risk_level

        if RiskAssessment.requires_approval(risk_level):
            result.warnings.append(
                f"Yüksek riskli işlem: {action} (High-risk operation requires approval)"
            )
            result.suggestions.append(
                "Bu işlemi gerçekleştirmek için onay almayı düşünün. "
                "(Consider obtaining approval before proceeding.)"
            )

        # 5. Resource validation
        if context and context.resource_limits:
            timeout_result = ResourceValidator.validate_timeout(10.0, context)
            if not timeout_result.is_valid:
                result.is_valid = False
                result.errors.extend(timeout_result.errors)

        logger.info(f"Doğrulama tamamlandı: geçerli={result.is_valid}, risk={result.risk_level.value}")
        return result
