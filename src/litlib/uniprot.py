"""UniProt accession sorgusu ve bağlantılı yayınların çıkarılması."""

from __future__ import annotations

import httpx

from litlib.models import normalize_doi

UNIPROT_ENTRY_URL = "https://rest.uniprot.org/uniprotkb/{accession}.json"


def _citation_identifiers(reference: dict) -> dict:
    identifiers = {}
    for database in reference.get("citation", {}).get("citationCrossReferences", []):
        name = database.get("database")
        value = database.get("id")
        if name and value:
            identifiers[name.lower()] = value
    return identifiers


def parse_entry(payload: dict) -> dict:
    """Enzim makalelerini bulmak ve varyantları yeniden kurmak için gereken alanları normalleştirir."""
    primary = payload.get("primaryAccession") or ""
    sequence = payload.get("sequence") or {}
    comments = payload.get("comments") or []
    ec_numbers = []
    for comment in comments:
        if comment.get("commentType") == "CATALYTIC ACTIVITY":
            ec_values = comment.get("reaction", {}).get("ecNumber", []) or []
            if isinstance(ec_values, str):
                ec_values = [ec_values]
            ec_numbers.extend(ec_values)
    proteins = payload.get("proteinDescription", {})
    recommended = proteins.get("recommendedName", {})
    name = (recommended.get("fullName") or {}).get("value")
    genes = [gene.get("geneName", {}).get("value") for gene in payload.get("genes", [])]
    references = []
    for reference in payload.get("references", []):
        citation = reference.get("citation", {})
        identifiers = _citation_identifiers(reference)
        doi = identifiers.get("doi")
        references.append({
            "title": citation.get("title"),
            "doi": normalize_doi(doi) if doi else None,
            "pmid": identifiers.get("pubmed"),
            "pmcid": identifiers.get("pmc"),
            "source": "uniprot",
        })
    return {
        "accession": primary,
        "uniProtkbId": payload.get("uniProtkbId"),
        "protein_name": name,
        "genes": [gene for gene in genes if gene],
        "organism": (payload.get("organism") or {}).get("scientificName"),
        "lineage": (payload.get("organism") or {}).get("lineage", []),
        "ec_numbers": sorted(set(ec_numbers)),
        "sequence": sequence.get("value"),
        "sequence_length": sequence.get("length"),
        "sequence_mass": sequence.get("molWeight"),
        "references": references,
        "source": "UniProt REST",
    }


async def fetch_entry(client: httpx.AsyncClient, accession: str) -> dict:
    response = await client.get(UNIPROT_ENTRY_URL.format(accession=accession.strip()))
    response.raise_for_status()
    return parse_entry(response.json())


def linked_identifiers(entry: dict) -> list[str]:
    """Tekilleştirilmiş DOI/PMID/PMCID tanımlayıcılarını makaledeki sırayla döndürür."""
    result = []
    seen = set()
    for reference in entry.get("references", []):
        for key in ("doi", "pmid", "pmcid"):
            value = reference.get(key)
            if value and value not in seen:
                seen.add(value)
                result.append(value)
    return result
