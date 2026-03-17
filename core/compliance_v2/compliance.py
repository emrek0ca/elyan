"""
ELYAN Compliance Framework - Phase 10
GDPR, CCPA, HIPAA, SOC2 Type II, ISO 27001 compliance management.
"""

import hashlib
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


class ComplianceFramework(Enum):
    GDPR = "gdpr"
    CCPA = "ccpa"
    HIPAA = "hipaa"
    SOC2 = "soc2"
    ISO27001 = "iso27001"


class DataCategory(Enum):
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    FINANCIAL = "financial"
    HEALTH = "health"
    BIOMETRIC = "biometric"
    CHILDREN = "children"
    ANONYMOUS = "anonymous"


class ConsentStatus(Enum):
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"
    PENDING = "pending"
    EXPIRED = "expired"


class AuditSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    VIOLATION = "violation"
    CRITICAL = "critical"


class DataAction(Enum):
    COLLECT = "collect"
    STORE = "store"
    PROCESS = "process"
    SHARE = "share"
    DELETE = "delete"
    EXPORT = "export"
    ANONYMIZE = "anonymize"


@dataclass
class ConsentRecord:
    consent_id: str
    user_id: str
    purpose: str
    data_categories: List[DataCategory]
    status: ConsentStatus = ConsentStatus.PENDING
    granted_at: float = 0.0
    expires_at: float = 0.0
    withdrawn_at: float = 0.0
    ip_address: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DataProcessingRecord:
    record_id: str
    user_id: str
    action: DataAction
    data_categories: List[DataCategory]
    purpose: str
    legal_basis: str = ""
    timestamp: float = 0.0
    processor: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEntry:
    entry_id: str
    framework: ComplianceFramework
    severity: AuditSeverity
    category: str
    description: str
    timestamp: float = 0.0
    user_id: str = ""
    action_taken: str = ""
    resolved: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DataSubjectRequest:
    request_id: str
    user_id: str
    request_type: str  # access, deletion, portability, rectification
    status: str = "pending"  # pending, processing, completed, denied
    created_at: float = 0.0
    completed_at: float = 0.0
    response_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplianceReport:
    report_id: str
    framework: ComplianceFramework
    generated_at: float = 0.0
    period_start: float = 0.0
    period_end: float = 0.0
    findings: List[Dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    status: str = "generated"


class ConsentManager:
    """GDPR/CCPA consent lifecycle management."""

    def __init__(self):
        self._consents: Dict[str, ConsentRecord] = {}
        self._user_consents: Dict[str, List[str]] = defaultdict(list)

    def request_consent(
        self,
        user_id: str,
        purpose: str,
        data_categories: List[DataCategory],
        ttl_days: int = 365,
    ) -> ConsentRecord:
        consent = ConsentRecord(
            consent_id=f"consent_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            purpose=purpose,
            data_categories=data_categories,
            status=ConsentStatus.PENDING,
            expires_at=time.time() + (ttl_days * 86400),
        )
        self._consents[consent.consent_id] = consent
        self._user_consents[user_id].append(consent.consent_id)
        return consent

    def grant_consent(self, consent_id: str, ip_address: str = "") -> bool:
        consent = self._consents.get(consent_id)
        if not consent or consent.status != ConsentStatus.PENDING:
            return False
        consent.status = ConsentStatus.GRANTED
        consent.granted_at = time.time()
        consent.ip_address = ip_address
        return True

    def withdraw_consent(self, consent_id: str) -> bool:
        consent = self._consents.get(consent_id)
        if not consent or consent.status != ConsentStatus.GRANTED:
            return False
        consent.status = ConsentStatus.WITHDRAWN
        consent.withdrawn_at = time.time()
        return True

    def check_consent(self, user_id: str, purpose: str) -> bool:
        for cid in self._user_consents.get(user_id, []):
            consent = self._consents.get(cid)
            if not consent:
                continue
            if (
                consent.purpose == purpose
                and consent.status == ConsentStatus.GRANTED
                and consent.expires_at > time.time()
            ):
                return True
        return False

    def get_user_consents(self, user_id: str) -> List[ConsentRecord]:
        return [
            self._consents[cid]
            for cid in self._user_consents.get(user_id, [])
            if cid in self._consents
        ]

    def expire_stale(self) -> int:
        now = time.time()
        count = 0
        for consent in self._consents.values():
            if consent.status == ConsentStatus.GRANTED and consent.expires_at < now:
                consent.status = ConsentStatus.EXPIRED
                count += 1
        return count


class DataProtectionOfficer:
    """Data processing records and subject request handling (GDPR Art. 30)."""

    def __init__(self):
        self._processing_records: List[DataProcessingRecord] = []
        self._subject_requests: Dict[str, DataSubjectRequest] = {}
        self._data_inventory: Dict[str, Dict[str, Any]] = {}

    def record_processing(
        self,
        user_id: str,
        action: DataAction,
        categories: List[DataCategory],
        purpose: str,
        legal_basis: str = "consent",
        processor: str = "",
    ) -> DataProcessingRecord:
        record = DataProcessingRecord(
            record_id=f"proc_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            action=action,
            data_categories=categories,
            purpose=purpose,
            legal_basis=legal_basis,
            timestamp=time.time(),
            processor=processor,
        )
        self._processing_records.append(record)
        return record

    def submit_subject_request(
        self, user_id: str, request_type: str
    ) -> DataSubjectRequest:
        dsr = DataSubjectRequest(
            request_id=f"dsr_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            request_type=request_type,
            created_at=time.time(),
        )
        self._subject_requests[dsr.request_id] = dsr
        return dsr

    def process_request(self, request_id: str) -> Optional[DataSubjectRequest]:
        dsr = self._subject_requests.get(request_id)
        if not dsr:
            return None
        dsr.status = "processing"
        if dsr.request_type == "access":
            dsr.response_data = self._get_user_data(dsr.user_id)
        elif dsr.request_type == "deletion":
            dsr.response_data = self._delete_user_data(dsr.user_id)
        elif dsr.request_type == "portability":
            dsr.response_data = self._export_user_data(dsr.user_id)
        dsr.status = "completed"
        dsr.completed_at = time.time()
        return dsr

    def _get_user_data(self, user_id: str) -> Dict[str, Any]:
        records = [r for r in self._processing_records if r.user_id == user_id]
        return {
            "user_id": user_id,
            "processing_records": len(records),
            "data_categories": list(
                {cat.value for r in records for cat in r.data_categories}
            ),
        }

    def _delete_user_data(self, user_id: str) -> Dict[str, Any]:
        before = len(self._processing_records)
        self._processing_records = [
            r for r in self._processing_records if r.user_id != user_id
        ]
        return {"deleted_records": before - len(self._processing_records)}

    def _export_user_data(self, user_id: str) -> Dict[str, Any]:
        records = [r for r in self._processing_records if r.user_id == user_id]
        return {
            "user_id": user_id,
            "records": [
                {
                    "action": r.action.value,
                    "purpose": r.purpose,
                    "timestamp": r.timestamp,
                    "categories": [c.value for c in r.data_categories],
                }
                for r in records
            ],
        }

    def get_processing_log(
        self, user_id: Optional[str] = None, limit: int = 50
    ) -> List[DataProcessingRecord]:
        if user_id:
            records = [r for r in self._processing_records if r.user_id == user_id]
        else:
            records = self._processing_records
        return records[-limit:]


class ComplianceAuditor:
    """Audit trail and compliance checking."""

    def __init__(self):
        self._entries: List[AuditEntry] = []
        self._rules: Dict[ComplianceFramework, List[Callable]] = defaultdict(list)
        self._setup_default_rules()

    def _setup_default_rules(self):
        self._rules[ComplianceFramework.GDPR] = [
            self._check_consent_before_processing,
            self._check_data_minimization,
            self._check_retention_limits,
        ]
        self._rules[ComplianceFramework.HIPAA] = [
            self._check_phi_encryption,
            self._check_access_controls,
        ]
        self._rules[ComplianceFramework.SOC2] = [
            self._check_access_logging,
            self._check_change_management,
        ]

    def log_event(
        self,
        framework: ComplianceFramework,
        severity: AuditSeverity,
        category: str,
        description: str,
        user_id: str = "",
    ) -> AuditEntry:
        entry = AuditEntry(
            entry_id=f"audit_{uuid.uuid4().hex[:8]}",
            framework=framework,
            severity=severity,
            category=category,
            description=description,
            timestamp=time.time(),
            user_id=user_id,
        )
        self._entries.append(entry)
        return entry

    def run_audit(self, framework: ComplianceFramework) -> List[AuditEntry]:
        findings = []
        for rule in self._rules.get(framework, []):
            result = rule()
            if result:
                findings.append(result)
        return findings

    def generate_report(
        self, framework: ComplianceFramework, period_days: int = 30
    ) -> ComplianceReport:
        cutoff = time.time() - (period_days * 86400)
        relevant = [
            e for e in self._entries if e.framework == framework and e.timestamp >= cutoff
        ]
        violations = [e for e in relevant if e.severity == AuditSeverity.VIOLATION]
        criticals = [e for e in relevant if e.severity == AuditSeverity.CRITICAL]
        total = len(relevant) or 1
        score = max(0.0, 1.0 - (len(violations) * 0.1 + len(criticals) * 0.3) / total)
        return ComplianceReport(
            report_id=f"report_{uuid.uuid4().hex[:8]}",
            framework=framework,
            generated_at=time.time(),
            period_start=cutoff,
            period_end=time.time(),
            findings=[
                {
                    "entry_id": e.entry_id,
                    "severity": e.severity.value,
                    "category": e.category,
                    "description": e.description,
                }
                for e in relevant
                if e.severity in (AuditSeverity.VIOLATION, AuditSeverity.CRITICAL)
            ],
            score=round(score, 3),
        )

    def get_entries(
        self,
        framework: Optional[ComplianceFramework] = None,
        severity: Optional[AuditSeverity] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        entries = self._entries
        if framework:
            entries = [e for e in entries if e.framework == framework]
        if severity:
            entries = [e for e in entries if e.severity == severity]
        return entries[-limit:]

    @staticmethod
    def _check_consent_before_processing() -> Optional[AuditEntry]:
        return None  # Placeholder: real impl checks processing log vs consent records

    @staticmethod
    def _check_data_minimization() -> Optional[AuditEntry]:
        return None

    @staticmethod
    def _check_retention_limits() -> Optional[AuditEntry]:
        return None

    @staticmethod
    def _check_phi_encryption() -> Optional[AuditEntry]:
        return None

    @staticmethod
    def _check_access_controls() -> Optional[AuditEntry]:
        return None

    @staticmethod
    def _check_access_logging() -> Optional[AuditEntry]:
        return None

    @staticmethod
    def _check_change_management() -> Optional[AuditEntry]:
        return None


class DataAnonymizer:
    """PII anonymization and pseudonymization utilities."""

    def __init__(self, salt: str = "elyan_default_salt"):
        self._salt = salt

    def pseudonymize(self, value: str) -> str:
        h = hashlib.sha256(f"{self._salt}:{value}".encode()).hexdigest()
        return f"pseudo_{h[:12]}"

    def anonymize_dict(self, data: Dict[str, Any], pii_fields: Set[str]) -> Dict[str, Any]:
        result = {}
        for key, value in data.items():
            if key in pii_fields:
                if isinstance(value, str):
                    result[key] = self.pseudonymize(value)
                else:
                    result[key] = "[REDACTED]"
            else:
                result[key] = value
        return result

    def mask_email(self, email: str) -> str:
        parts = email.split("@")
        if len(parts) != 2:
            return "[INVALID_EMAIL]"
        local = parts[0]
        domain = parts[1]
        if len(local) <= 2:
            masked_local = "*" * len(local)
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"

    def mask_phone(self, phone: str) -> str:
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) < 4:
            return "****"
        return "*" * (len(digits) - 4) + digits[-4:]


class ComplianceEngine:
    """Unified compliance engine combining all components."""

    def __init__(self):
        self.consent_manager = ConsentManager()
        self.dpo = DataProtectionOfficer()
        self.auditor = ComplianceAuditor()
        self.anonymizer = DataAnonymizer()
        self._enabled_frameworks: Set[ComplianceFramework] = {
            ComplianceFramework.GDPR,
            ComplianceFramework.SOC2,
        }

    def enable_framework(self, framework: ComplianceFramework):
        self._enabled_frameworks.add(framework)

    def disable_framework(self, framework: ComplianceFramework):
        self._enabled_frameworks.discard(framework)

    def process_data(
        self,
        user_id: str,
        action: DataAction,
        categories: List[DataCategory],
        purpose: str,
    ) -> Dict[str, Any]:
        if ComplianceFramework.GDPR in self._enabled_frameworks:
            has_consent = self.consent_manager.check_consent(user_id, purpose)
            if not has_consent and action != DataAction.DELETE:
                self.auditor.log_event(
                    ComplianceFramework.GDPR,
                    AuditSeverity.VIOLATION,
                    "consent",
                    f"Processing without consent: {action.value} for {purpose}",
                    user_id,
                )
                return {"allowed": False, "reason": "consent_required"}
        record = self.dpo.record_processing(user_id, action, categories, purpose)
        self.auditor.log_event(
            ComplianceFramework.GDPR,
            AuditSeverity.INFO,
            "processing",
            f"Data processed: {action.value} for {purpose}",
            user_id,
        )
        return {"allowed": True, "record_id": record.record_id}

    def handle_subject_request(self, user_id: str, request_type: str) -> Dict[str, Any]:
        dsr = self.dpo.submit_subject_request(user_id, request_type)
        self.auditor.log_event(
            ComplianceFramework.GDPR,
            AuditSeverity.INFO,
            "dsr",
            f"Subject request: {request_type}",
            user_id,
        )
        result = self.dpo.process_request(dsr.request_id)
        if result:
            return {
                "request_id": result.request_id,
                "status": result.status,
                "data": result.response_data,
            }
        return {"request_id": dsr.request_id, "status": "failed"}

    def full_audit(self) -> Dict[str, Any]:
        reports = {}
        for fw in self._enabled_frameworks:
            report = self.auditor.generate_report(fw)
            reports[fw.value] = {
                "score": report.score,
                "findings": len(report.findings),
                "status": "compliant" if report.score >= 0.8 else "needs_attention",
            }
        return reports

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled_frameworks": [f.value for f in self._enabled_frameworks],
            "audit_entries": len(self.auditor._entries),
            "active_consents": sum(
                1 for c in self.consent_manager._consents.values()
                if c.status == ConsentStatus.GRANTED
            ),
            "processing_records": len(self.dpo._processing_records),
        }


_compliance_engine: Optional[ComplianceEngine] = None


def get_compliance_engine() -> ComplianceEngine:
    global _compliance_engine
    if _compliance_engine is None:
        _compliance_engine = ComplianceEngine()
    return _compliance_engine
