"""Non-reversible display aliases for the AI-only planning boundary."""

from datetime import date
import re
from typing import Any

from okama_planner.api import _parse_request

_TEXT_FIELDS = {'name', 'label', 'role', 'replaces_asset', 'reserve_label'}
_ID_FIELDS = {'segment_id', 'household_segment_id', 'destination', 'group_id', 'asset'}
_CODE = re.compile(r'^anon-\d{6}$')
_DATE_FIELDS = {'t0', 'start_month', 'end_month', 'accumulation_last_date_pin', 'withdrawal_last_date_pin'}
_ENUMS = {
    'distribution': {'norm', 'lognorm', 't'}, 'portfolio_mode': {'single', 'per_goal'},
    'savings_mode': {'pooled', 'separate'}, 'kind': {'income', 'expense', 'lump', 'reserve_topup',
                                                 'retirement_income'},
    'asset_class': {'portfolio', 'reserve', 'non_working', 'third_party', 'savings'},
    'end_rule': {'none', 'until_retirement', 'until_month'}, 'amount_basis': {'amount', 'expense_share'},
    'period': {'none', 'year', 'half-year', 'quarter', 'month'}, 'action': {'retain', 'transfer_to'},
    'transfer_policy': {'none', 'ordered', 'unrestricted'}, 'buffer_policy': {'retain', 'planned_targets'},
    'purchase_execution': {'all_or_nothing'}, 'method': {'synchronized_bootstrap'},
    'funding_source_order': {'cash', 'buffer', 'segment'},
    'reserve_funding_source_order': {'cash', 'buffer', 'segment'},
    'event_priority': {'expense', 'mortgage_payment'},
}


def _public_symbol(value: str) -> str:
    import okama
    namespace = value.rsplit('.', 1)[-1]
    # Fetch only public namespace catalogs, never query a private candidate symbol.
    if namespace not in okama.namespaces:
        raise ValueError('Unconfirmed market namespace')
    catalog = okama.symbols_in_namespace(namespace)
    if value not in set(catalog['symbol']):
        raise ValueError('Unconfirmed public market symbol')
    return value


def _technical_string(value: str, field: str) -> str:
    if field in _ENUMS and value in _ENUMS[field]:
        return value
    if field == 'event_priority' and re.fullmatch(r'goal:-?\d+', value):
        return value
    if field == 'currency' and re.fullmatch(r'[A-Z]{3}', value):
        return value
    if field == 'symbol':
        return _public_symbol(value)
    if field in _DATE_FIELDS:
        if not value and field.endswith('last_date_pin'):
            return value
        if re.fullmatch(r'\d{4}-\d{2}(?:-\d{2})?', value):
            date.fromisoformat(value if len(value) == 10 else value + '-01')
            return value
    raise ValueError('Unexpected free text in a technical field')


class _Aliases:
    """One request-local mapping preserves all label and identifier references."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.aliases: dict[str, str] = {}
        self.reserved: set[str] = set()
        self.collect(data)

    def collect(self, value: Any) -> None:
        if isinstance(value, str) and _CODE.fullmatch(value):
            self.reserved.add(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                self.collect(key)
                self.collect(item)
        elif isinstance(value, list):
            for item in value:
                self.collect(item)

    def alias(self, value: str) -> str:
        if _CODE.fullmatch(value):
            return value
        if value not in self.aliases:
            index = len(self.aliases) + 1
            code = f'anon-{index:06d}'
            while code in self.reserved:
                index += 1
                code = f'anon-{index:06d}'
            self.aliases[value] = code
            self.reserved.add(code)
        return self.aliases[value]

    def visit(self, value: Any, field: str = '') -> Any:
        if isinstance(value, str):
            return (self.alias(value) if field in _TEXT_FIELDS | _ID_FIELDS
                    else _technical_string(value, field))
        if isinstance(value, list):
            if field in {'household_funding_order', 'transfer_order'}:
                return [self.alias(item) for item in value]
            # Allocation weights are model rows; contribution weights are a mapping.
            return [self.visit(item, '' if isinstance(item, dict) else field) for item in value]
        if isinstance(value, dict):
            if field in {'asset_returns', 'goal_savings_rates', 'weights'}:
                items = sorted(value.items()) if field == 'asset_returns' else value.items()
                return {self.alias(key): self.visit(item) for key, item in items}
            return {key: self.visit(item, key) for key, item in value.items()}
        return value


def sanitize_request(request: Any) -> dict[str, Any]:
    """Replace personal/display text without returning a reverse identity map.

    Codes remain stable for the same request layout. Registry identity uses c-NNNN;
    financial enums, currencies, dates and public market symbols retain their meanings.
    """
    data = _parse_request(request).model_dump(mode='json')
    return _parse_request(_Aliases(data).visit(data)).model_dump(mode='json')
