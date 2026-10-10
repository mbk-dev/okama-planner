"""The AI boundary must never expose trusted identity or unsealed report payloads."""
import copy
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from okama_planner import forecast as trusted_forecast
from okama_planner.storage import PlannerStore

NAME = "Synthetic Secretname"
EMAIL = "private-marker@example.invalid"


def request() -> dict:
    data = json.loads(Path('examples/readme-request.json').read_text())
    data['mc_number'] = 10
    data['plan']['persons'][0]['name'] = NAME
    data['plan']['persons'][0]['role'] = NAME
    data['plan']['assets'][3]['label'] = EMAIL
    data['plan']['goals'][0]['replaces_asset'] = EMAIL
    data['plan']['goals'][0]['label'] = NAME
    data['plan']['goal_savings_rates'] = {NAME: .0388, 'Home purchase': .0388}
    return data


def boundary():
    from okama_planner import ai
    return ai


def assert_private(value: object) -> None:
    encoded = json.dumps(value, ensure_ascii=False)
    assert NAME not in encoded
    assert EMAIL not in encoded


def test_registry_masks_every_identity_and_note_without_mutating_database(tmp_path: Path) -> None:
    with PlannerStore.initialize(tmp_path/'clients.db') as store:
        raw = store.create_client({'full_name': NAME, 'email': EMAIL, 'phone': NAME,
                                   'telegram_id': 123456789, 'brokers': [NAME], 'note': EMAIL})
    api = boundary().PlannerAI(tmp_path/'clients.db')
    safe = api.client_get(raw['code'])
    assert safe['code'] == raw['code']
    assert safe['full_name'] == raw['code']+'-name'
    assert safe['email'] == raw['code']+'-email'
    assert 'id' not in safe
    assert_private(safe)
    assert_private(api.client_list())
    with PlannerStore.open(tmp_path/'clients.db') as store:
        assert store.get_client(raw['code']) == raw


@pytest.mark.parametrize(
    'changes', [{'full_name': NAME}, {'email': EMAIL}, {'note': NAME}, {'brokers': [NAME]}]
)
def test_ai_identity_writes_are_rejected_atomically(tmp_path: Path, changes: dict) -> None:
    with PlannerStore.initialize(tmp_path/'clients.db') as store:
        before = store.create_client({'full_name': NAME})
    api = boundary().PlannerAI(tmp_path/'clients.db')
    with pytest.raises(ValueError) as caught:
        api.client_update(before['code'], changes)
    assert_private(str(caught.value))
    with PlannerStore.open(tmp_path/'clients.db') as store:
        assert store.get_client(before['code']) == before
    assert api.client_update(before['code'], {'birth_year': 1980})['birth_year'] == 1980


def test_stored_plan_is_masked_and_ai_versions_remain_owned_by_client(tmp_path: Path) -> None:
    with PlannerStore.initialize(tmp_path/'clients.db') as store:
        code = store.create_client({'full_name': NAME})['code']
        other = store.create_client({'full_name': 'Other'})['code']
        store.save_plan(code, request(), note=NAME)
    api = boundary().PlannerAI(tmp_path/'clients.db')
    safe = api.client_load_plan(code, 1)
    assert_private(safe)
    assert safe['plan']['goals'][0]['replaces_asset'] == safe['plan']['assets'][3]['label']
    assert safe['plan']['goals'][0]['label'] in safe['plan']['goal_savings_rates']
    assert api.client_list_plans(code) == [{'code': code, 'version': 1}]
    assert api.client_list_plans(other) == []
    with pytest.raises(ValueError):
        api.client_load_plan(other, 1)
    assert api.client_save_plan(code, request()) == {'code': code, 'version': 2}
    with PlannerStore.open(tmp_path/'clients.db') as store:
        stored = store.load_plan(store.list_plans(code)[1]['id']).model_dump(mode='json')
        assert_private(stored)
        assert store.load_plan(store.list_plans(code)[0]['id']).plan.persons[0].name == NAME


def test_forecast_keeps_money_and_dates_while_masking_all_display_fields() -> None:
    native = trusted_forecast(request())
    safe = boundary().forecast(request())
    assert_private(safe)
    assert safe['metrics'] == native['metrics']
    assert safe['charts'] == native['charts']
    assert safe['ledger']['months'] == native['ledger']['months']
    assert 'privacy_proof' in safe


def test_signed_report_is_anonymous_and_rejects_tampering_before_file_creation(tmp_path: Path) -> None:
    ai = boundary()
    safe_request = ai.sanitize_request(request())
    result = ai.forecast(request())
    output = tmp_path/'safe.xlsx'
    ai.export_report([{'label': NAME, 'request': safe_request, 'result': result}], output)
    book = load_workbook(output)
    cells = [cell.value for sheet in book for row in sheet for cell in row]
    assert_private(cells)
    bad = copy.deepcopy(result)
    bad['unexpected'] = EMAIL
    with pytest.raises(ValueError):
        ai.export_report([{'label': 'Scenario', 'request': safe_request, 'result': bad}], tmp_path/'bad.xlsx')
    assert not (tmp_path/'bad.xlsx').exists()
    with pytest.raises(ValueError):
        ai.export_report([{'label': NAME, 'request': request(), 'result': trusted_forecast(request())}],
                         tmp_path/'raw.xlsx')
    assert not (tmp_path/'raw.xlsx').exists()


@pytest.mark.parametrize('code', [NAME, '../clients.db', 'c-0001 OR 1=1'])
def test_errors_do_not_echo_identifiers_or_database_paths(tmp_path: Path, code: str) -> None:
    path = tmp_path / (NAME+'.db')
    PlannerStore.initialize(path).close()
    with pytest.raises(ValueError) as caught:
        boundary().PlannerAI(path).client_get(code)
    assert_private(str(caught.value))
    assert str(path) not in str(caught.value)


def test_local_human_import_creates_and_updates_identity_without_printing_it(tmp_path: Path, capsys) -> None:
    from okama_planner.private_clients import main
    database = tmp_path/'clients.db'
    PlannerStore.initialize(database).close()
    source = tmp_path/'input.json'
    source.write_text(json.dumps({'full_name': NAME, 'email': EMAIL}))
    assert main(['create', '--database', str(database), '--input', str(source)]) == 0
    assert capsys.readouterr().out.strip() == 'c-0001'
    source.write_text(json.dumps({'phone': '+10000000000'}))
    assert main(['update', '--database', str(database), '--input', str(source), '--code', 'c-0001']) == 0
    assert capsys.readouterr().out.strip() == 'c-0001'
    with PlannerStore.open(database) as store:
        assert store.get_client('c-0001')['full_name'] == NAME
        assert store.get_client('c-0001')['phone'] == '+10000000000'
    source.write_text(json.dumps({'bad_private_key': NAME}))
    assert main(['update', '--database', str(database), '--input', str(source), '--code', 'c-0001']) == 2
    assert_private(capsys.readouterr().err)


@pytest.mark.parametrize('field', ['accumulation_last_date_pin', 'withdrawal_last_date_pin'])
def test_unvalidated_technical_dates_cannot_carry_personal_text(field: str) -> None:
    data = request()
    data['plan'][field] = NAME
    with pytest.raises(ValueError) as caught:
        boundary().sanitize_request(data)
    assert_private(str(caught.value))


def test_currency_group_ids_and_joint_references_are_masked_without_changing_capital() -> None:
    from test_multicurrency import multicurrency_request
    from okama_planner.multicurrency import forecast_multicurrency
    data = multicurrency_request()
    data['groups'][0]['group_id'] = 'PrivateName'
    data['household_funding_order'][0] = 'PrivateName'
    data['contribution_schedule'][0]['weights'] = {'PrivateName': .5, 'dollar': .5}
    safe_request = boundary().sanitize_request(data)
    assert 'PrivateName' not in json.dumps(safe_request)
    assert safe_request['groups'][0]['group_id'] == safe_request['household_funding_order'][0]
    assert safe_request['groups'][0]['group_id'] in safe_request['contribution_schedule'][0]['weights']
    native = forecast_multicurrency(data)
    safe = boundary().forecast(data)
    assert safe['metrics'] == native['metrics']
    assert safe['charts'] == native['charts']


def test_masking_is_idempotent_and_aliases_do_not_collide_with_existing_codes() -> None:
    data = request()
    data['plan']['persons'].append({'name': 'anon-000001', 'role': 'adult', 'birth_year': 1990})
    safe = boundary().sanitize_request(data)
    names = [person['name'] for person in safe['plan']['persons']]
    assert len(set(names)) == len(names)
    assert boundary().sanitize_request(safe) == safe


def test_joint_mode_comparison_remains_available_with_coded_goal_priority() -> None:
    from okama_planner.forecast.variants import with_portfolio_mode
    from okama_planner.api import ForecastRequest, compare_portfolio_modes
    data = json.loads(Path('examples/family-per-goal-request.json').read_text())
    data['mc_number'] = 10
    variant = ForecastRequest.model_validate(data)
    baseline = with_portfolio_mode(variant, portfolio_mode='single')
    safe = boundary().compare_portfolio_modes(baseline, variant)
    native = compare_portfolio_modes(baseline, variant)
    assert safe['differences'] == native['differences']
    assert safe['baseline']['metrics'] == native['baseline']['metrics']


def test_unconfirmed_market_symbol_cannot_smuggle_a_name_in_a_stored_plan(
    tmp_path: Path, monkeypatch,
) -> None:
    import okama
    import pandas as pd
    from okama.api import namespaces
    monkeypatch.setattr(namespaces, 'get_namespaces', lambda: {'US': 'Public assets'})
    monkeypatch.setattr(okama, 'symbols_in_namespace', lambda namespace: pd.DataFrame({'symbol': ['SPY.US']}))
    data = request()
    data['return_samples'] = None
    data['plan']['accumulation_holdings'] = [{'symbol': 'PRIVATE_SYNTHETIC_PERSON.SMITH', 'weight': 1.0}]
    with PlannerStore.initialize(tmp_path/'clients.db') as store:
        code = store.create_client({'full_name': NAME})['code']
        store.save_plan(code, data)
    with pytest.raises(ValueError) as caught:
        boundary().PlannerAI(tmp_path/'clients.db').client_load_plan(code, 1)
    assert 'PRIVATE_SYNTHETIC_PERSON' not in str(caught.value)
    data['plan']['accumulation_holdings'][0]['symbol'] = 'PRIVATE_SYNTHETIC_PERSON.US'
    with pytest.raises(ValueError):
        boundary().sanitize_request(data)
    data['plan']['accumulation_holdings'][0]['symbol'] = 'SPY.US'
    assert boundary().sanitize_request(data)['plan']['accumulation_holdings'][0]['symbol'] == 'SPY.US'


def test_json_dictionary_order_does_not_change_anonymous_joint_comparison() -> None:
    from okama_planner.forecast.variants import with_portfolio_mode
    from okama_planner.api import ForecastRequest, compare_portfolio_modes
    variant = json.loads(Path('examples/family-per-goal-request.json').read_text())
    variant['mc_number'] = 10
    baseline_model = with_portfolio_mode(ForecastRequest.model_validate(variant), portfolio_mode='single')
    baseline = baseline_model.model_dump(mode='json')
    baseline['joint_history']['asset_returns'] = dict(
        reversed(list(baseline['joint_history']['asset_returns'].items()))
    )
    native = compare_portfolio_modes(baseline, variant)
    safe = boundary().compare_portfolio_modes(baseline, variant)
    assert safe['differences'] == native['differences']
