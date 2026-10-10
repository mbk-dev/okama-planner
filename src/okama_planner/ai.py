"""Restricted AI API: identity resolution and database contents stay inside Planner.

Trusted local applications use PlannerStore; MCP must use this module exclusively.
"""

import copy
import functools
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from okama_planner import api
from okama_planner.privacy import sanitize_request as _sanitize_request
from okama_planner.storage import PlannerStore

T = TypeVar('T')
_PROOF_KEY = secrets.token_bytes(32)
_ERROR = 'Planner operation rejected; use valid anonymous codes and financial inputs.'


def _boundary(function: Callable[..., T]) -> Callable[..., T]:
    """Never expose values, SQL, paths or chained exception messages to an AI caller."""
    @functools.wraps(function)
    def call(*args: Any, **kwargs: Any) -> T:
        try:
            return function(*args, **kwargs)
        except Exception:
            raise ValueError(_ERROR) from None
    return call


def _proof(result: dict[str, Any]) -> str:
    payload = {key: value for key, value in result.items() if key != 'privacy_proof'}
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hmac.new(_PROOF_KEY, encoded, hashlib.sha256).hexdigest()


def _seal(result: dict[str, Any]) -> dict[str, Any]:
    safe = copy.deepcopy(result)
    safe['privacy_proof'] = _proof(safe)
    return safe


@_boundary
def sanitize_request(request: Any) -> dict[str, Any]:
    return _sanitize_request(request)


@_boundary
def forecast(request: Any) -> dict[str, Any]:
    """Calculate only after personal/display text has been replaced by opaque codes."""
    return _seal(api.forecast(_sanitize_request(request)))


@_boundary
def compare_portfolio_modes(baseline: Any, variant: Any) -> dict[str, Any]:
    """Compare masked requests and seal the component results for optional export."""
    result = api.compare_portfolio_modes(_sanitize_request(baseline), _sanitize_request(variant))
    result['baseline'] = _seal(result['baseline'])
    result['variant'] = _seal(result['variant'])
    return result


@_boundary
def export_report(
    scenarios: Sequence[dict[str, Any]], target: Path | str, *, brand: Any = None,
    language: str = 'en',
) -> Path:
    """Export only untouched AI results from this process, with neutral local branding.

    The original trusted export remains available for a human's client deliverables.
    User-selected scenario names and local brand contacts/logos never enter this artifact.
    """
    from okama_planner.reports import ReportBrand, export_report as trusted_export

    safe = []
    for index, scenario in enumerate(scenarios, 1):
        result = scenario['result']
        proof = result.get('privacy_proof')
        if not isinstance(proof, str) or not hmac.compare_digest(proof, _proof(result)):
            raise ValueError('Unsealed or changed AI result')
        request = _sanitize_request(scenario['request'])
        # The native exporter validates the request's digest and financial consistency.
        safe.append({'label': f'scenario-{index:04d}', 'request': request,
                     'result': {key: value for key, value in result.items() if key != 'privacy_proof'}})
    trusted_export(safe, target, brand=ReportBrand(company='Planner', contact=''), language=language)
    return Path(target)


def _code(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'c-\d{4,}', value):
        raise ValueError('Invalid client code')
    return value


def _client(record: dict[str, Any]) -> dict[str, Any]:
    code = record['code']
    safe = {key: record[key] for key in ('code', 'sex', 'birth_year', 'primary_channel', 'ips_sent_at')}
    fields = {'full_name': 'name', 'email': 'email', 'phone': 'phone', 'telegram': 'telegram',
              'telegram_id': 'telegram-id', 'whatsapp': 'whatsapp', 'max_messenger': 'max', 'note': 'note'}
    for key, suffix in fields.items():
        safe[key] = None if record[key] is None else f'{code}-{suffix}'
    safe['brokers'] = (None if record['brokers'] is None else
                       [f'{code}-broker-{index:04d}' for index, _ in enumerate(record['brokers'], 1)])
    return safe


def _residency(code: str, record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {'code': code, 'year': record['year'], 'country': record['country'],
            'note': None if record['note'] is None else f'{code}-residency-note'}


class PlannerAI:
    """One configured local database; no schema, SQL, identities or internal row IDs are returned."""

    @_boundary
    def __init__(self, database: Path | str) -> None:
        self.__database = Path(database).resolve(strict=True)
        with PlannerStore.open(self.__database):
            pass

    @_boundary
    def client_get(self, code: str) -> dict[str, Any]:
        with PlannerStore.open(self.__database) as store:
            return _client(store.get_client(_code(code)))

    @_boundary
    def client_list(self) -> list[dict[str, Any]]:
        with PlannerStore.open(self.__database) as store:
            return [_client(record) for record in store.list_clients()]

    @_boundary
    def client_update(self, code: str, changes: dict[str, Any]) -> dict[str, Any]:
        if set(changes) - {'sex', 'birth_year', 'ips_sent_at'}:
            raise ValueError('Identity edits require local human intake')
        with PlannerStore.open(self.__database) as store:
            return _client(store.update_client(_code(code), changes))

    @_boundary
    def client_set_tax_residency(self, code: str, year: int, country: str) -> dict[str, Any]:
        with PlannerStore.open(self.__database) as store:
            # Update country/year while retaining the private local note internally.
            existing = store.get_tax_residency(_code(code), year)
            record = store.set_tax_residency(code, year, country,
                                            note=existing['note'] if existing else None)
            return _residency(code, record)

    @_boundary
    def client_get_tax_residency(self, code: str, year: int) -> dict[str, Any] | None:
        with PlannerStore.open(self.__database) as store:
            return _residency(_code(code), store.get_tax_residency(code, year))

    @_boundary
    def client_list_plans(self, code: str) -> list[dict[str, Any]]:
        with PlannerStore.open(self.__database) as store:
            return [{'code': code, 'version': record['version']} for record in store.list_plans(_code(code))]

    @_boundary
    def client_save_plan(self, code: str, request: Any) -> dict[str, Any]:
        safe = _sanitize_request(request)
        with PlannerStore.open(self.__database) as store:
            identifier = store.save_plan(_code(code), safe)
            version = next(row['version'] for row in store.list_plans(code) if row['id'] == identifier)
            return {'code': code, 'version': version}

    @_boundary
    def client_load_plan(self, code: str, version: int) -> dict[str, Any]:
        if type(version) is not int or version < 1:
            raise ValueError('Invalid version')
        with PlannerStore.open(self.__database) as store:
            row = next((row for row in store.list_plans(_code(code)) if row['version'] == version), None)
            if row is None:
                raise ValueError('Unknown plan version')
            return _sanitize_request(store.load_plan(row['id']))

    @_boundary
    def client_forecast(self, code: str, version: int) -> dict[str, Any]:
        return forecast(self.client_load_plan(code, version))
