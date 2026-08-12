from __future__ import annotations

import pytest

from litlib.cellulase import (
    CellulaseMeasurement,
    normalize_measurement,
    normalize_records,
    normalize_substrate,
    reconstruct_construct_sequence,
    select_maxima,
)


def measurement(**updates):
    values = {
        "accession": "P12345",
        "construct_id": "P12345-wt",
        "sequence_sha256": "a" * 64,
        "sequence_provenance": "canonical_uniprot",
        "enzyme_class": "endoglucanase",
        "substrate_raw": "CMC",
        "substrate_normalized": "cmc",
        "metric_type": "specific_activity",
        "metric_family": "specific_activity",
        "value_raw": 10,
        "unit_raw": "U/mg",
        "value_standardized": 10,
        "unit_standardized": "umol/min/mg",
        "temperature_c": 50,
        "ph": 5,
        "evidence_doi": "10.1000/test",
    }
    values.update(updates)
    return CellulaseMeasurement(**values)


def test_maximum_is_selected_only_within_compatible_group():
    records = [
        measurement(value_standardized=10),
        measurement(value_standardized=20, temperature_c=60),
        measurement(value_standardized=100, substrate_raw="Avicel", substrate_normalized="avicel"),
        measurement(value_standardized=99, metric_family="kcat", metric_type="kcat", unit_standardized="s-1"),
    ]
    maxima = select_maxima(records)
    assert {(r.substrate_normalized, r.metric_family, r.value_standardized) for r in maxima} == {
        ("cmc", "specific_activity", 20),
        ("avicel", "specific_activity", 100),
        ("cmc", "kcat", 99),
    }


def test_tied_maxima_are_marked_plateau():
    maxima = select_maxima([measurement(value_standardized=10), measurement(value_standardized=10)])
    assert len(maxima) == 2
    assert all(record.maximum_scope == "plateau_or_tied" for record in maxima)


def test_relative_activity_is_not_selected_as_absolute_maximum():
    record = measurement(
        metric_type="relative_activity", metric_family="relative_activity",
        value_standardized=100, unit_standardized="%",
    )
    assert select_maxima([record]) == []


def test_safe_substrate_and_unit_normalization():
    assert normalize_substrate("carboxymethyl cellulose") == "cmc"
    converted = normalize_measurement(1000, "mU/mg")
    assert converted["value"] == 1 and converted["unit"] == "umol/min/mg"
    assert normalize_measurement(5, "U/mL")["status"] == "exact"
    assert normalize_measurement(5, "IU/g")["status"] == "not_convertible"

    record = normalize_records([measurement(value_raw=1000, value_standardized=None, unit_raw="mU/mg")])[0]
    assert record.substrate_normalized == "cmc"
    assert record.value_standardized == 1
    assert record.unit_standardized == "umol/min/mg"


def test_missing_state_is_validated():
    record = measurement(missing_fields={"ph": "not_reported"})
    record.validate_missing_fields()
    with pytest.raises(ValueError):
        measurement(missing_fields={"ph": "invented_state"}).validate_missing_fields()


def test_reconstruct_construct_requires_explicit_mutations_and_truncation():
    result = reconstruct_construct_sequence("MABCDEF", ["A2V"], "2-5")
    assert result["sequence"] == "VBCD"
    assert result["sequence_provenance"] == "derived_from_explicit_mutations"
    assert result["retained_residue_range"] == "2-5"

    with pytest.raises(ValueError):
        reconstruct_construct_sequence("MABC", ["B2insX"])
    with pytest.raises(ValueError):
        reconstruct_construct_sequence("MABC", ["D2V"])
