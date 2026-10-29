"""Focused contract tests for image and PDF evidence extraction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from loader import DATASET_DIR, load_all  # noqa: E402
from parsers import parse_file  # noqa: E402


class MockLLMClient:
    no_llm = False

    def __init__(self):
        self.calls = []

    def generate_json(self, prompt, schema, file=None):
        self.calls.append((prompt, schema, file))
        if Path(file).suffix.lower() == ".png":
            return {
                "name": "Example User", "user_id": "user_123", "account_id": "account_123",
                "email": "  PERSON@EXAMPLE.COM ", "phone": "+1 555 0100",
                "support_ticket": "support_123", "orders": ["order_1"],
                "unexpected_model_field": "must be discarded",
            }
        return {"document_kind": "LEGAL_RETENTION_REGISTER", "rows": [{"user_id": "user_123", "order": "order_123",
                          "reason": "legal hold", "retain_until": "2027-01-01",
                          "name": None, "email": None, "phone": None,
                          "support_ticket": None, "reference_id": None, "reference_ids": [],
                          "unexpected_model_field": "must be discarded"}],
                "unexpected_model_field": "must be discarded"}


class MockNoLLMClient:
    no_llm = True

    @staticmethod
    def generate_json(prompt, schema, file=None):
        return None


def test_image_and_pdf_fact_contracts_and_no_llm_flag():
    ds = load_all(DATASET_DIR)
    media_rows = ds.evidence_files.loc[
        ds.evidence_files.file_path.str.lower().str.endswith((".png", ".pdf"))
    ]
    assert len(media_rows) == 15
    mock = MockLLMClient()
    outputs = {}
    for _, row in media_rows.iterrows():
        facts, scope = parse_file(row, DATASET_DIR, llm=mock)
        outputs[str(row["file_id"])] = facts
        assert scope == {}
        assert facts
        assert all(fact.file_id == row["file_id"] for fact in facts)

    image_fact = outputs["evidence_04"][0]
    assert image_fact.category == "USER_PROFILE"
    assert image_fact.resource_id == "account_123"
    assert image_fact.emails == ("person@example.com",)
    assert image_fact.user_ids == ("user_123",)
    assert outputs["evidence_04"][1].category == "SUPPORT_MESSAGE"
    assert outputs["evidence_04"][1].resource_id == "support_123"
    pdf_fact = outputs["evidence_27"][0]
    assert pdf_fact.category == "LEGAL_HOLD_RECORD"
    assert pdf_fact.state == "RETAINED"
    assert '"retain_until": "2027-01-01"' in pdf_fact.raw_ref
    assert "unexpected_model_field" not in pdf_fact.raw_ref
    assert len(mock.calls) == 15

    import parsers.image as image_parser
    import parsers.pdf as pdf_parser

    for _, row in media_rows.iterrows():
        facts, scope = parse_file(row, DATASET_DIR, llm=MockNoLLMClient())
        assert facts == [] and scope == {}
        module = image_parser if str(row.file_path).lower().endswith(".png") else pdf_parser
        assert module.NO_LLM_USED is True


def test_pdf_support_attachment_keeps_resource_and_ticket_references():
    ds = load_all(DATASET_DIR)
    row = ds.evidence_files.loc[ds.evidence_files.file_id.eq("evidence_58")].iloc[0]

    class AttachmentMock:
        no_llm = False

        @staticmethod
        def generate_json(prompt, schema, file=None):
            return {
                "document_kind": "SUPPORT_ATTACHMENT",
                "rows": [{
                    "user_id": None, "order": None, "reason": None, "retain_until": None,
                    "name": "Priya Raman", "email": "PRIYA.RAMAN@GMAIL.COM",
                    "phone": "+91 98765 73142", "support_ticket": "CS-4827",
                    "reference_id": "support_001", "reference_ids": ["support_001", "CS-4827"],
                }],
            }

    facts, _ = parse_file(row, DATASET_DIR, llm=AttachmentMock())
    assert len(facts) == 1
    fact = facts[0]
    assert fact.resource_id == "support_001"
    assert fact.category == "SUPPORT_ATTACHMENT"
    assert fact.emails == ("priya.raman@gmail.com",)
    assert "CS-4827" in fact.raw_ref
