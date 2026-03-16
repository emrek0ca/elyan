"""
Tool Schemas - Schema validation and parameter checking for tools

Provides comprehensive schema validation for tool parameters before execution,
with support for Turkish field names and user-friendly error messages.

Part of RELIABILITY FOUNDATION (Hafta 1-2)
"""

from typing import Any, Dict, List, Optional, Callable, Union, Tuple
from dataclasses import dataclass
from enum import Enum
import re
from utils.logger import get_logger

logger = get_logger("tool_schemas")


class ParameterType(Enum):
    """Supported parameter types"""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    LIST = "list"
    DICT = "dict"
    FILE_PATH = "file_path"
    DIRECTORY_PATH = "directory_path"
    URL = "url"
    EMAIL = "email"
    REGEX = "regex"
    ENUM = "enum"
    ANY = "any"


@dataclass
class ParameterSchema:
    """
    Schema definition for a single parameter

    Attributes:
        name (str): Parameter name
        type (ParameterType): Expected type
        required (bool): Whether parameter is required
        default (Any): Default value if not provided
        description (str): Parameter description (Turkish/English)
        min_length (Optional[int]): Minimum length (for strings/lists)
        max_length (Optional[int]): Maximum length (for strings/lists)
        min_value (Optional[float]): Minimum numeric value
        max_value (Optional[float]): Maximum numeric value
        allowed_values (Optional[List[Any]]): Enum values
        pattern (Optional[str]): Regex pattern for validation
        validator (Optional[Callable]): Custom validation function
        sanitizer (Optional[Callable]): Function to sanitize value
    """
    name: str
    type: ParameterType
    required: bool = False
    default: Any = None
    description: str = ""
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[List[Any]] = None
    pattern: Optional[str] = None
    validator: Optional[Callable[[Any], bool]] = None
    sanitizer: Optional[Callable[[Any], Any]] = None

    def validate(self, value: Any) -> Tuple[bool, Optional[str]]:
        """
        Validate a value against this schema

        Returns:
            (is_valid, error_message)
        """
        # Check if value is provided
        if value is None:
            if self.required:
                return False, f"Parametre '{self.name}' zorunludur. (Parameter '{self.name}' is required.)"
            return True, None

        # Apply sanitizer if available
        if self.sanitizer:
            value = self.sanitizer(value)

        # Type validation
        type_valid, type_error = self._validate_type(value)
        if not type_valid:
            return False, type_error

        # Length validation
        if self.min_length is not None and len(str(value)) < self.min_length:
            return False, f"'{self.name}' minimum {self.min_length} karakter olmalıdır. (Minimum {self.min_length} characters required.)"

        if self.max_length is not None and len(str(value)) > self.max_length:
            return False, f"'{self.name}' maksimum {self.max_length} karakter olabilir. (Maximum {self.max_length} characters allowed.)"

        # Range validation
        if self.min_value is not None and isinstance(value, (int, float)):
            if value < self.min_value:
                return False, f"'{self.name}' minimum {self.min_value} olmalıdır. (Minimum value is {self.min_value}.)"

        if self.max_value is not None and isinstance(value, (int, float)):
            if value > self.max_value:
                return False, f"'{self.name}' maksimum {self.max_value} olabilir. (Maximum value is {self.max_value}.)"

        # Enum validation
        if self.allowed_values is not None and value not in self.allowed_values:
            vals_str = ", ".join(str(v) for v in self.allowed_values)
            return False, f"'{self.name}' bu değerlerden biri olmalıdır: {vals_str} (Value must be one of: {vals_str})"

        # Pattern validation
        if self.pattern is not None:
            if not re.match(self.pattern, str(value)):
                return False, f"'{self.name}' format geçersiz. ('{self.name}' has invalid format.)"

        # Custom validation
        if self.validator is not None:
            try:
                if not self.validator(value):
                    return False, f"'{self.name}' özel doğrulama başarısız. (Custom validation failed for '{self.name}'.)"
            except Exception as e:
                return False, f"'{self.name}' doğrulama hatası: {str(e)} (Validation error: {str(e)})"

        return True, None

    def _validate_type(self, value: Any) -> Tuple[bool, Optional[str]]:
        """Validate value type"""
        if self.type == ParameterType.ANY:
            return True, None

        type_checks = {
            ParameterType.STRING: isinstance(value, str),
            ParameterType.INTEGER: isinstance(value, int) and not isinstance(value, bool),
            ParameterType.FLOAT: isinstance(value, (int, float)) and not isinstance(value, bool),
            ParameterType.BOOLEAN: isinstance(value, bool),
            ParameterType.LIST: isinstance(value, list),
            ParameterType.DICT: isinstance(value, dict),
            ParameterType.FILE_PATH: isinstance(value, str),
            ParameterType.DIRECTORY_PATH: isinstance(value, str),
            ParameterType.URL: isinstance(value, str),
            ParameterType.EMAIL: isinstance(value, str),
            ParameterType.REGEX: isinstance(value, str),
            ParameterType.ENUM: True,
        }

        if not type_checks.get(self.type, False):
            type_name = self.type.value
            return False, f"'{self.name}' tipi {type_name} olmalıdır. ('{self.name}' must be of type {type_name}.)"

        return True, None

    def sanitize(self, value: Any) -> Any:
        """Apply sanitizer if available"""
        if self.sanitizer:
            return self.sanitizer(value)
        return value


@dataclass
class ToolSchema:
    """
    Complete schema for a tool

    Attributes:
        tool_name (str): Tool name
        description (str): Tool description (Turkish/English)
        parameters (List[ParameterSchema]): Parameter schemas
        required_parameters (List[str]): Required parameter names
        pre_execution_checks (Optional[Callable]): Pre-execution validation function
        expected_output_type (Optional[str]): Expected output type description
    """
    tool_name: str
    description: str = ""
    parameters: List[ParameterSchema] = None
    required_parameters: List[str] = None
    pre_execution_checks: Optional[Callable[[Dict[str, Any]], Tuple[bool, Optional[str]]]] = None
    expected_output_type: Optional[str] = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = []
        if self.required_parameters is None:
            self.required_parameters = []

    def validate_params(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate all parameters

        Returns:
            (is_valid, error_messages)
        """
        errors: List[str] = []

        # Check for required parameters
        for param_name in self.required_parameters:
            if param_name not in params or params[param_name] is None:
                errors.append(f"Parametre zorunlu: {param_name} (Required parameter: {param_name})")

        # Validate each parameter
        param_map = {p.name: p for p in self.parameters}

        for param_name, value in params.items():
            if param_name in param_map:
                is_valid, error_msg = param_map[param_name].validate(value)
                if not is_valid:
                    errors.append(error_msg)

        # Run pre-execution checks if available
        if self.pre_execution_checks:
            try:
                is_valid, error_msg = self.pre_execution_checks(params)
                if not is_valid and error_msg:
                    errors.append(error_msg)
            except Exception as e:
                errors.append(f"Ön-çalıştırma kontrolü hatası: {str(e)} (Pre-execution check error: {str(e)})")

        return len(errors) == 0, errors

    def sanitize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Apply sanitizers to all parameters"""
        param_map = {p.name: p for p in self.parameters}
        sanitized = {}

        for param_name, value in params.items():
            if param_name in param_map:
                sanitized[param_name] = param_map[param_name].sanitize(value)
            else:
                sanitized[param_name] = value

        return sanitized

    def get_parameter(self, name: str) -> Optional[ParameterSchema]:
        """Get parameter schema by name"""
        for p in self.parameters:
            if p.name == name:
                return p
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "tool_name": self.tool_name,
            "description": self.description,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type.value,
                    "required": p.required,
                    "default": p.default,
                    "description": p.description,
                    "min_length": p.min_length,
                    "max_length": p.max_length,
                    "min_value": p.min_value,
                    "max_value": p.max_value,
                    "allowed_values": p.allowed_values,
                    "pattern": p.pattern,
                }
                for p in self.parameters
            ],
            "required_parameters": self.required_parameters,
            "expected_output_type": self.expected_output_type,
        }


class SchemaRegistry:
    """Registry for tool schemas"""

    def __init__(self):
        self.schemas: Dict[str, ToolSchema] = {}

    def register(self, schema: ToolSchema) -> None:
        """Register a tool schema"""
        self.schemas[schema.tool_name] = schema
        logger.info(f"Kayıtlı şema (Registered schema): {schema.tool_name}")

    def get(self, tool_name: str) -> Optional[ToolSchema]:
        """Get schema by tool name"""
        return self.schemas.get(tool_name)

    def validate(self, tool_name: str, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate tool parameters"""
        schema = self.get(tool_name)
        if not schema:
            logger.warning(f"Şema bulunamadı (Schema not found): {tool_name}")
            return True, []  # Allow if no schema defined

        return schema.validate_params(params)

    def sanitize(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize tool parameters"""
        schema = self.get(tool_name)
        if not schema:
            return params

        return schema.sanitize_params(params)

    def list_schemas(self) -> List[str]:
        """List all registered schemas"""
        return list(self.schemas.keys())


# Global registry
_schema_registry = SchemaRegistry()


def get_schema_registry() -> SchemaRegistry:
    """Get global schema registry"""
    return _schema_registry


# Helper functions for common parameter types
def create_string_param(
    name: str,
    required: bool = False,
    description: str = "",
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    pattern: Optional[str] = None,
) -> ParameterSchema:
    """Create a string parameter schema"""
    return ParameterSchema(
        name=name,
        type=ParameterType.STRING,
        required=required,
        description=description,
        min_length=min_length,
        max_length=max_length,
        pattern=pattern,
    )


def create_integer_param(
    name: str,
    required: bool = False,
    description: str = "",
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> ParameterSchema:
    """Create an integer parameter schema"""
    return ParameterSchema(
        name=name,
        type=ParameterType.INTEGER,
        required=required,
        description=description,
        min_value=min_value,
        max_value=max_value,
    )


def create_file_path_param(
    name: str,
    required: bool = False,
    description: str = "",
) -> ParameterSchema:
    """Create a file path parameter schema"""
    return ParameterSchema(
        name=name,
        type=ParameterType.FILE_PATH,
        required=required,
        description=description,
    )


def create_enum_param(
    name: str,
    allowed_values: List[Any],
    required: bool = False,
    description: str = "",
) -> ParameterSchema:
    """Create an enum parameter schema"""
    return ParameterSchema(
        name=name,
        type=ParameterType.ENUM,
        required=required,
        description=description,
        allowed_values=allowed_values,
    )
