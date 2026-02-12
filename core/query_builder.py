"""
Natural Language Query Builder
Convert natural language to SQL/NoSQL queries
"""

import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger

logger = get_logger("query_builder")


class QueryType(Enum):
    """Types of queries"""
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    COUNT = "count"
    AGGREGATE = "aggregate"


@dataclass
class QueryComponents:
    """Parsed query components"""
    query_type: QueryType
    table: Optional[str] = None
    columns: List[str] = None
    conditions: List[Tuple[str, str, Any]] = None  # (column, operator, value)
    order_by: Optional[List[Tuple[str, str]]] = None  # (column, direction)
    limit: Optional[int] = None
    group_by: Optional[List[str]] = None
    aggregation: Optional[Dict[str, str]] = None  # {column: function}

    def __post_init__(self):
        if self.columns is None:
            self.columns = []
        if self.conditions is None:
            self.conditions = []
        if self.order_by is None:
            self.order_by = []
        if self.group_by is None:
            self.group_by = []
        if self.aggregation is None:
            self.aggregation = {}


class NaturalLanguageQueryBuilder:
    """
    Natural Language Query Builder
    - Convert natural language to SQL
    - Support for SELECT, INSERT, UPDATE, DELETE
    - Condition parsing (WHERE clauses)
    - Aggregation (COUNT, SUM, AVG, etc.)
    - Ordering and limiting
    - Database abstraction
    """

    def __init__(self):
        # Keywords for query type detection
        self.select_keywords = ['show', 'get', 'find', 'list', 'select', 'retrieve', 'bul', 'göster', 'getir', 'listele']
        self.insert_keywords = ['add', 'create', 'insert', 'ekle', 'oluştur']
        self.update_keywords = ['update', 'change', 'modify', 'set', 'güncelle', 'değiştir']
        self.delete_keywords = ['delete', 'remove', 'drop', 'sil', 'kaldır']
        self.count_keywords = ['count', 'how many', 'number of', 'kaç', 'sayı']

        # Comparison operators
        self.operator_map = {
            'equals': '=',
            'is': '=',
            'equal to': '=',
            'eşit': '=',
            'greater than': '>',
            'büyük': '>',
            'less than': '<',
            'küçük': '<',
            'contains': 'LIKE',
            'içerir': 'LIKE',
            'starts with': 'LIKE',
            'başlar': 'LIKE',
            'ends with': 'LIKE',
            'biter': 'LIKE',
        }

        # Aggregation functions
        self.aggregations = ['count', 'sum', 'avg', 'min', 'max', 'average', 'toplam', 'ortalama']

        logger.info("Natural Language Query Builder initialized")

    def parse_natural_language(self, nl_query: str) -> QueryComponents:
        """Parse natural language query into components"""
        nl_query_lower = nl_query.lower()

        # Detect query type
        query_type = self._detect_query_type(nl_query_lower)

        # Extract table name
        table = self._extract_table(nl_query_lower)

        # Extract components based on query type
        if query_type == QueryType.SELECT or query_type == QueryType.COUNT:
            components = QueryComponents(
                query_type=query_type,
                table=table,
                columns=self._extract_columns(nl_query_lower),
                conditions=self._extract_conditions(nl_query_lower),
                order_by=self._extract_order_by(nl_query_lower),
                limit=self._extract_limit(nl_query_lower)
            )

            # Check for aggregation
            if any(agg in nl_query_lower for agg in self.aggregations):
                components.aggregation = self._extract_aggregation(nl_query_lower)
                components.group_by = self._extract_group_by(nl_query_lower)

        elif query_type == QueryType.INSERT:
            components = QueryComponents(
                query_type=query_type,
                table=table,
                columns=self._extract_columns(nl_query_lower)
            )

        elif query_type == QueryType.UPDATE:
            components = QueryComponents(
                query_type=query_type,
                table=table,
                conditions=self._extract_conditions(nl_query_lower)
            )

        elif query_type == QueryType.DELETE:
            components = QueryComponents(
                query_type=query_type,
                table=table,
                conditions=self._extract_conditions(nl_query_lower)
            )

        else:
            components = QueryComponents(query_type=QueryType.SELECT, table=table)

        return components

    def _detect_query_type(self, query: str) -> QueryType:
        """Detect type of query from natural language"""
        if any(kw in query for kw in self.count_keywords):
            return QueryType.COUNT

        if any(kw in query for kw in self.select_keywords):
            return QueryType.SELECT

        if any(kw in query for kw in self.insert_keywords):
            return QueryType.INSERT

        if any(kw in query for kw in self.update_keywords):
            return QueryType.UPDATE

        if any(kw in query for kw in self.delete_keywords):
            return QueryType.DELETE

        # Default to SELECT
        return QueryType.SELECT

    def _extract_table(self, query: str) -> Optional[str]:
        """Extract table name from query"""
        # Look for "from <table>" or "in <table>" patterns
        patterns = [
            r'from\s+(\w+)',
            r'in\s+(?:the\s+)?(\w+)',
            r'(\w+)\s+table',
            r'(\w+)\s+tablosunda',
            r'(\w+)\s+içinde'
        ]

        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                return match.group(1)

        return None

    def _extract_columns(self, query: str) -> List[str]:
        """Extract column names from query"""
        # Look for "columns", "fields", or comma-separated lists
        columns = []

        # Check for explicit column mentions
        column_pattern = r'(?:columns?|fields?)\s+([\w,\s]+)'
        match = re.search(column_pattern, query)

        if match:
            col_str = match.group(1)
            columns = [c.strip() for c in col_str.split(',')]

        # If no explicit columns, return empty (will be interpreted as SELECT *)
        return columns if columns else ['*']

    def _extract_conditions(self, query: str) -> List[Tuple[str, str, Any]]:
        """Extract WHERE conditions from query"""
        conditions = []

        # Pattern: <column> <operator> <value>
        # Examples: "age greater than 25", "name equals John", "yaş 25'ten büyük"

        # Numeric conditions
        numeric_pattern = r'(\w+)\s+(greater than|less than|equals?|büyük|küçük|eşit)\s+(\d+)'
        for match in re.finditer(numeric_pattern, query):
            column = match.group(1)
            operator_text = match.group(2)
            value = int(match.group(3))

            operator = self.operator_map.get(operator_text, '=')
            conditions.append((column, operator, value))

        # String conditions
        string_pattern = r'(\w+)\s+(is|equals?|contains?|eşit|içerir)\s+["\']?(\w+)["\']?'
        for match in re.finditer(string_pattern, query):
            column = match.group(1)
            operator_text = match.group(2)
            value = match.group(3)

            operator = self.operator_map.get(operator_text, '=')
            if 'contain' in operator_text or 'içerir' in operator_text:
                value = f"%{value}%"
            conditions.append((column, operator, value))

        # "where" clause extraction
        where_pattern = r'where\s+(.+?)(?:\s+order\s+|\s+limit\s+|$)'
        where_match = re.search(where_pattern, query)
        if where_match:
            where_clause = where_match.group(1)
            # Simple parsing: column = value
            simple_cond = r'(\w+)\s*=\s*["\']?([^"\']+)["\']?'
            for match in re.finditer(simple_cond, where_clause):
                column = match.group(1)
                value = match.group(2).strip()
                conditions.append((column, '=', value))

        return conditions

    def _extract_order_by(self, query: str) -> List[Tuple[str, str]]:
        """Extract ORDER BY clause"""
        order_by = []

        # Pattern: "order by <column> <direction>"
        pattern = r'order\s+by\s+(\w+)(?:\s+(asc|desc|ascending|descending|artan|azalan))?'
        match = re.search(pattern, query)

        if match:
            column = match.group(1)
            direction = match.group(2) if match.group(2) else 'asc'

            # Normalize direction
            if direction in ['desc', 'descending', 'azalan']:
                direction = 'DESC'
            else:
                direction = 'ASC'

            order_by.append((column, direction))

        return order_by

    def _extract_limit(self, query: str) -> Optional[int]:
        """Extract LIMIT clause"""
        # Pattern: "limit <number>" or "first <number>" or "top <number>"
        patterns = [
            r'limit\s+(\d+)',
            r'first\s+(\d+)',
            r'top\s+(\d+)',
            r'ilk\s+(\d+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                return int(match.group(1))

        return None

    def _extract_aggregation(self, query: str) -> Dict[str, str]:
        """Extract aggregation functions"""
        aggregation = {}

        # Pattern: <function>(<column>) or <function> of <column>
        patterns = [
            r'(count|sum|avg|average|min|max)\s*\(\s*(\w+)\s*\)',
            r'(count|sum|avg|average|min|max)\s+of\s+(\w+)',
            r'(toplam|ortalama)\s+(\w+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                func = match.group(1).upper()
                column = match.group(2)

                # Normalize function names
                if func in ['AVERAGE', 'ORTALAMA']:
                    func = 'AVG'
                elif func == 'TOPLAM':
                    func = 'SUM'

                aggregation[column] = func

        return aggregation

    def _extract_group_by(self, query: str) -> List[str]:
        """Extract GROUP BY clause"""
        # Pattern: "group by <column>"
        pattern = r'group\s+by\s+([\w,\s]+)'
        match = re.search(pattern, query)

        if match:
            col_str = match.group(1)
            return [c.strip() for c in col_str.split(',')]

        return []

    def build_sql(self, components: QueryComponents) -> str:
        """Build SQL query from components"""
        if components.query_type == QueryType.SELECT:
            return self._build_select(components)
        elif components.query_type == QueryType.COUNT:
            return self._build_count(components)
        elif components.query_type == QueryType.INSERT:
            return self._build_insert(components)
        elif components.query_type == QueryType.UPDATE:
            return self._build_update(components)
        elif components.query_type == QueryType.DELETE:
            return self._build_delete(components)

        return ""

    def _build_select(self, comp: QueryComponents) -> str:
        """Build SELECT query"""
        # SELECT clause
        if comp.aggregation:
            select_parts = []
            for column, func in comp.aggregation.items():
                select_parts.append(f"{func}({column})")
            if comp.group_by:
                select_parts.extend(comp.group_by)
            select_clause = ", ".join(select_parts)
        else:
            select_clause = ", ".join(comp.columns) if comp.columns else "*"

        query = f"SELECT {select_clause}"

        # FROM clause
        if comp.table:
            query += f" FROM {comp.table}"

        # WHERE clause
        if comp.conditions:
            where_parts = []
            for column, operator, value in comp.conditions:
                if isinstance(value, str):
                    where_parts.append(f"{column} {operator} '{value}'")
                else:
                    where_parts.append(f"{column} {operator} {value}")
            query += " WHERE " + " AND ".join(where_parts)

        # GROUP BY clause
        if comp.group_by:
            query += " GROUP BY " + ", ".join(comp.group_by)

        # ORDER BY clause
        if comp.order_by:
            order_parts = [f"{col} {direction}" for col, direction in comp.order_by]
            query += " ORDER BY " + ", ".join(order_parts)

        # LIMIT clause
        if comp.limit:
            query += f" LIMIT {comp.limit}"

        return query + ";"

    def _build_count(self, comp: QueryComponents) -> str:
        """Build COUNT query"""
        query = "SELECT COUNT(*)"

        if comp.table:
            query += f" FROM {comp.table}"

        if comp.conditions:
            where_parts = []
            for column, operator, value in comp.conditions:
                if isinstance(value, str):
                    where_parts.append(f"{column} {operator} '{value}'")
                else:
                    where_parts.append(f"{column} {operator} {value}")
            query += " WHERE " + " AND ".join(where_parts)

        return query + ";"

    def _build_insert(self, comp: QueryComponents) -> str:
        """Build INSERT query"""
        if not comp.table:
            return "-- Table name required for INSERT"

        columns_str = ", ".join(comp.columns) if comp.columns and comp.columns != ['*'] else ""
        query = f"INSERT INTO {comp.table}"

        if columns_str:
            query += f" ({columns_str})"

        query += " VALUES (?);"  # Placeholder for values

        return query

    def _build_update(self, comp: QueryComponents) -> str:
        """Build UPDATE query"""
        if not comp.table:
            return "-- Table name required for UPDATE"

        query = f"UPDATE {comp.table} SET ?"  # Placeholder for SET clause

        if comp.conditions:
            where_parts = []
            for column, operator, value in comp.conditions:
                if isinstance(value, str):
                    where_parts.append(f"{column} {operator} '{value}'")
                else:
                    where_parts.append(f"{column} {operator} {value}")
            query += " WHERE " + " AND ".join(where_parts)

        return query + ";"

    def _build_delete(self, comp: QueryComponents) -> str:
        """Build DELETE query"""
        if not comp.table:
            return "-- Table name required for DELETE"

        query = f"DELETE FROM {comp.table}"

        if comp.conditions:
            where_parts = []
            for column, operator, value in comp.conditions:
                if isinstance(value, str):
                    where_parts.append(f"{column} {operator} '{value}'")
                else:
                    where_parts.append(f"{column} {operator} {value}")
            query += " WHERE " + " AND ".join(where_parts)
        else:
            query += " -- WARNING: No conditions, will delete all rows"

        return query + ";"

    def nl_to_sql(self, natural_language_query: str) -> str:
        """Convert natural language to SQL query"""
        components = self.parse_natural_language(natural_language_query)
        sql = self.build_sql(components)

        logger.info(f"Converted NL to SQL: {natural_language_query[:50]}... -> {sql[:100]}...")

        return sql


# Global instance
_query_builder: Optional[NaturalLanguageQueryBuilder] = None


def get_query_builder() -> NaturalLanguageQueryBuilder:
    """Get or create global query builder instance"""
    global _query_builder
    if _query_builder is None:
        _query_builder = NaturalLanguageQueryBuilder()
    return _query_builder
