from __future__ import annotations

from litlib.uniprot import linked_identifiers, parse_entry


def test_parse_uniprot_entry_and_references():
    payload = {
        "primaryAccession": "P12345",
        "uniProtkbId": "CELLULASE_TEST",
        "proteinDescription": {"recommendedName": {"fullName": {"value": "Cellulase"}}},
        "genes": [{"geneName": {"value": "celA"}}],
        "organism": {"scientificName": "Test fungus", "lineage": ["Fungi"]},
        "sequence": {"value": "MABC", "length": 4, "molWeight": 400},
        "comments": [{"commentType": "CATALYTIC ACTIVITY", "reaction": {"ecNumber": ["3.2.1.4"]}}],
        "references": [{
            "citation": {
                "title": "Cellulase activity",
                "citationCrossReferences": [
                    {"database": "DOI", "id": "10.1000/test"},
                    {"database": "PubMed", "id": "123456"},
                ],
            }
        }],
    }
    entry = parse_entry(payload)
    assert entry["accession"] == "P12345"
    assert entry["protein_name"] == "Cellulase"
    assert entry["ec_numbers"] == ["3.2.1.4"]
    assert linked_identifiers(entry) == ["10.1000/test", "123456"]
