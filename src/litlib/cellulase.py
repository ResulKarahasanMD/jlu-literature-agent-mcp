"""Yapılandırılmış selülaz ölçümleri ve temkinli maksimum seçimi.

Kayıtlar eksik alanlara karşı bilerek hoşgörülüdür. Modül, uyumsuz birimler, substratlar,
yapılar ya da metrik aileleri arasında ham değerleri asla karşılaştırmaz.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MISSING_STATES = {
    "not_reported", "not_measured", "not_applicable", "supplement_unavailable",
    "figure_pending", "unclear", "not_extracted", "not_verified",
}
METRIC_FAMILIES = {
    "specific_activity", "volumetric_activity", "substrate_mass_activity",
    "filter_paper_activity", "vmax", "kcat", "kcat_over_km", "relative_activity",
}
SEQUENCE_PROVENANCE = {
    "reported_exact", "canonical_uniprot", "derived_from_explicit_mutations",
    "derived_from_explicit_truncation", "unresolved",
}

SUBSTRATE_ALIASES = {
    "carboxymethyl cellulose": "cmc",
    "carboxymethylcellulose": "cmc",
    "cm-cellulose": "cmc",
    "avicel": "avicel",
    "microcrystalline cellulose": "avicel",
    "phosphoric acid swollen cellulose": "pasc",
    "pasc": "pasc",
    "filter paper": "filter_paper",
    "whatman no. 1": "filter_paper",
    "cellobiose": "cellobiose",
    "p-nitrophenyl-beta-d-glucopyranoside": "pnp_glucose",
    "pnpg": "pnp_glucose",
    "p-nitrophenyl-beta-d-cellobioside": "pnp_cellobioside",
    "pnpc": "pnp_cellobioside",
}

UNIT_CONVERSIONS = {
    ("mU/mg", "umol/min/mg"): 0.001,
    ("U/mg", "umol/min/mg"): 1.0,
    ("kat/kg", "umol/min/mg"): 60.0,
    ("nkat/mg", "umol/min/mg"): 0.06,
    ("min^-1", "s^-1"): 1 / 60,
    ("min-1", "s^-1"): 1 / 60,
    ("h^-1", "s^-1"): 1 / 3600,
    ("h-1", "s^-1"): 1 / 3600,
    ("K", "degC"): 1.0,
    ("degF", "degC"): 1.0,
}
CANONICAL_UNITS = {
    "umol/min/mg", "U/mL", "U/g", "FPU/mL", "s^-1", "M^-1 s^-1", "mM", "uM", "%",
}


def normalize_substrate(value: str) -> str:
    """Yalnız yerleşik takma adları normalleştirir; bilinmeyen substrat adlarını korur."""
    cleaned = " ".join(value.strip().casefold().split())
    return SUBSTRATE_ALIASES.get(cleaned, cleaned)


_MUTATION_RE = re.compile(r"^(?P<from>[A-Za-z])(?P<pos>\d+)(?P<to>[A-Za-z])$")


def reconstruct_construct_sequence(
    reference_sequence: str,
    mutations: list[str] | None = None,
    retained_residue_range: str = "",
) -> dict:
    """Yapıyı yalnız açıkça verilen ikameler ve kalıntı aralığından yeniden kurar.

    Kabul edilen ikameler ``A123V`` gibi kısa biçimlerdir. Belirsiz HGVS ya da
    ekleme/silme tanımları tahmin edilmez, reddedilir.
    """
    sequence = "".join(reference_sequence.split()).upper()
    if not sequence or not sequence.isalpha():
        raise ValueError("reference_sequence geçerli bir protein dizisi değil")
    chars = list(sequence)
    applied: list[str] = []
    for raw in mutations or []:
        match = _MUTATION_RE.fullmatch(raw.strip())
        if not match:
            raise ValueError(f"mutasyon bilgisi kesin olarak ayrıştırılamadı: {raw}")
        position = int(match.group("pos"))
        if position < 1 or position > len(chars):
            raise ValueError(f"mutasyon konumu referans dizinin dışında: {raw}")
        old = match.group("from").upper()
        new = match.group("to").upper()
        if chars[position - 1] != old:
            raise ValueError(f"mutasyonun özgün kalıntısı referans diziyle uyuşmuyor: {raw}, gerçekte: {chars[position - 1]}")
        chars[position - 1] = new
        applied.append(f"{old}{position}{new}")
    start, end = 1, len(chars)
    if retained_residue_range:
        range_match = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", retained_residue_range)
        if not range_match:
            raise ValueError(f"kesme aralığı kesin olarak ayrıştırılamadı: {retained_residue_range}")
        start, end = map(int, range_match.groups())
        if start < 1 or end < start or end > len(chars):
            raise ValueError(f"kesme aralığı referans dizinin dışında: {retained_residue_range}")
    result = "".join(chars[start - 1:end])
    return {
        "sequence": result,
        "sequence_sha256": hashlib.sha256(result.encode("ascii")).hexdigest(),
        "sequence_provenance": (
            "derived_from_explicit_mutations" if applied
            else "derived_from_explicit_truncation" if retained_residue_range
            else "canonical_uniprot"
        ),
        "mutations": applied,
        "retained_residue_range": f"{start}-{end}" if retained_residue_range else "",
    }


def normalize_measurement(value: float, unit: str) -> dict:
    """Güvenli birim çiftlerini dönüştürür, belirsiz dönüşümleri açıkça reddeder.

    ``U/mL`` protein konsantrasyonu olmadan ``U/mg``'ye çevrilemez; değer
    ``not_convertible`` durumuyla değiştirilmeden döndürülür.
    """
    raw_unit = unit.strip()
    target = {
        "mU/mg": "umol/min/mg", "U/mg": "umol/min/mg", "kat/kg": "umol/min/mg",
        "nkat/mg": "umol/min/mg", "min^-1": "s^-1", "min-1": "s^-1",
        "h^-1": "s^-1", "h-1": "s^-1", "K": "degC", "degF": "degC",
    }.get(raw_unit)
    if target is None and raw_unit in CANONICAL_UNITS:
        return {
            "value": value, "unit": raw_unit, "status": "exact",
            "method": "unchanged",
        }
    if target is None:
        return {
            "value": value, "unit": raw_unit, "status": "not_convertible",
            "method": "unknown_or_context_dependent_unit",
        }
    if (raw_unit, target) not in UNIT_CONVERSIONS:
        return {
            "value": value, "unit": raw_unit, "status": "not_convertible",
            "method": "missing_conversion",
        }
    converted = value * UNIT_CONVERSIONS[(raw_unit, target)]
    if raw_unit == "K":
        converted = value - 273.15
    elif raw_unit == "degF":
        converted = (value - 32) * 5 / 9
    return {
        "value": converted, "unit": target, "status": "converted",
        "method": f"{raw_unit}->{target}",
    }


class CellulaseMeasurement(BaseModel):
    model_config = ConfigDict(extra="allow")

    record_id: str = ""
    accession: str
    construct_id: str = ""
    sequence_sha256: str = ""
    sequence_provenance: str = "unresolved"
    enzyme_class: str = ""
    organism: str = ""
    mutations: list[str] = Field(default_factory=list)
    retained_residue_range: str = ""
    substrate_raw: str = ""
    substrate_normalized: str = ""
    metric_type: str
    metric_family: str = ""
    value_raw: float | None = None
    unit_raw: str = ""
    value_standardized: float | None = None
    unit_standardized: str = ""
    temperature_c: float | None = None
    ph: float | None = None
    buffer: str = ""
    assay_method: str = ""
    assay_time: str = ""
    evidence_doi: str = ""
    source_page: int | None = None
    source_table: str = ""
    source_figure: str = ""
    source_supplement: str = ""
    extraction_method: str = "text"
    digitized: bool = False
    digitization_uncertainty: str = ""
    relative_anchor_value: float | None = None
    relative_anchor_unit: str = ""
    derived: bool = False
    missing_fields: dict[str, str] = Field(default_factory=dict)
    quality_grade: str = "Candidate"
    review_status: str = "pending"
    maximum_scope: str = ""

    @field_validator("sequence_provenance")
    @classmethod
    def validate_sequence_provenance(cls, value: str) -> str:
        if value not in SEQUENCE_PROVENANCE:
            raise ValueError(f"unknown sequence_provenance: {value}")
        return value

    @field_validator("metric_family")
    @classmethod
    def validate_metric_family(cls, value: str) -> str:
        if value and value not in METRIC_FAMILIES:
            raise ValueError(f"unknown metric_family: {value}")
        return value

    def validate_missing_fields(self) -> None:
        for field_name, state in self.missing_fields.items():
            if state not in MISSING_STATES:
                raise ValueError(f"unknown missing state for {field_name}: {state}")

    @property
    def comparable_key(self) -> tuple[str, str, str, str, str]:
        """Yalnız maksimum için yarışabilecek kayıtları gruplar."""
        return (
            self.sequence_sha256 or self.construct_id or self.accession,
            self.substrate_normalized or normalize_substrate(self.substrate_raw),
            self.metric_family or self.metric_type,
            self.unit_standardized or self.unit_raw,
            self.assay_method.casefold().strip(),
        )


def load_jsonl(path: Path | str) -> list[CellulaseMeasurement]:
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(CellulaseMeasurement.model_validate_json(line))
    return records


def write_jsonl(path: Path | str, records: list[CellulaseMeasurement]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(record.model_dump_json() + "\n" for record in records),
        encoding="utf-8",
    )


def select_maxima(records: list[CellulaseMeasurement]) -> list[CellulaseMeasurement]:
    """Maksimumları yalnız uyumlu yapı/substrat/metrik/birim grupları içinde seçer."""
    groups: dict[tuple[str, str, str, str, str], list[CellulaseMeasurement]] = defaultdict(list)
    for record in records:
        record.validate_missing_fields()
        if record.value_standardized is None or record.metric_family == "relative_activity":
            continue
        groups[record.comparable_key].append(record)
    maxima = []
    for grouped in groups.values():
        highest = max(record.value_standardized for record in grouped)
        winners = [record for record in grouped if record.value_standardized == highest]
        for record in winners:
            copy = record.model_copy(deep=True)
            copy.maximum_scope = "maximum_observed_in_compatible_group"
            if len(winners) > 1:
                copy.maximum_scope = "plateau_or_tied"
            maxima.append(copy)
    return maxima


def normalize_records(records: list[CellulaseMeasurement]) -> list[CellulaseMeasurement]:
    """Kayıtları güvenli substrat/birim normalleştirmesiyle, ham alanları koruyarak döndürür."""
    normalized = []
    for record in records:
        copy = record.model_copy(deep=True)
        copy.substrate_normalized = copy.substrate_normalized or normalize_substrate(copy.substrate_raw)
        if copy.value_raw is not None and copy.unit_raw:
            result = normalize_measurement(copy.value_raw, copy.unit_raw)
            copy.value_standardized = result["value"]
            copy.unit_standardized = result["unit"]
            copy.extra_normalization_status = result["status"]
            copy.extra_normalization_method = result["method"]
        normalized.append(copy)
    return normalized


def validate_jsonl(path: Path | str) -> dict[str, Any]:
    records = load_jsonl(path)
    errors = []
    for index, record in enumerate(records, start=1):
        try:
            record.validate_missing_fields()
        except ValueError as exc:
            errors.append({"line": index, "error": str(exc)})
    return {"records": len(records), "errors": errors, "valid": not errors}
