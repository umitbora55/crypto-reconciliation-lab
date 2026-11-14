"""Standalone release entry for the pinned runtime/release semantic contract."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location('fixed_admission_semantics',
    Path(__file__).resolve().parents[1] / 'crypto_reconciliation_lab/admission/scope.py')
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
CONTRACT_PATH = _MODULE.CONTRACT_PATH
CONTRACT_BYTES = _MODULE.CONTRACT_BYTES
CONTRACT_SHA256 = _MODULE.CONTRACT_SHA256
identity = _MODULE.identity
load_scope = _MODULE.load_scope
require = _MODULE.require
unique_object = _MODULE.unique_object
validate_plan = _MODULE.validate_plan
validate_schedule = _MODULE.validate_schedule
validate_report = _MODULE.validate_report
