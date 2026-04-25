from __future__ import annotations

from langfuse import Evaluation
from scripts.curate_langfuse_datasets import _dataset_item_from_trace
from scripts.run_evals import _eval_context, conversation_quality_eval, deterministic_eval


def test_eval_functions_return_langfuse_evaluations() -> None:
    deterministic_scores = deterministic_eval(
        input={},
        output={"assistant_text": "Listo, la factura quedo validada.", "latency_ms": 12},
        expected_output={"required_substrings": ["factura"]},
        metadata={},
    )
    conversation_scores = conversation_quality_eval(
        input={},
        output={"assistant_text": "Necesito el CUIT para avanzar."},
        expected_output={"missing_fields": ["CUIT"]},
        metadata={},
    )

    assert all(isinstance(score, Evaluation) for score in deterministic_scores)
    assert all(isinstance(score, Evaluation) for score in conversation_scores)
    assert {score.name for score in deterministic_scores} >= {"task_success", "error"}


def test_curated_trace_preserves_attachment_manifests() -> None:
    manifest = {
        "manifest": {
            "filename": "factura.jpg",
            "storage_uri": "s3://sumampa-attachments/attachments/factura.jpg",
            "sha256": "a" * 64,
        },
        "artifacts": [{"kind": "image", "filename": "factura.jpg"}],
    }
    item = _dataset_item_from_trace(
        {
            "id": "trace-1",
            "session_id": "conversation-1",
            "user_id": "user-1",
            "input": {
                "text": "Carga esta factura.",
                "attachments": [
                    {
                        "filename": "factura.jpg",
                        "content_type": "image/jpeg",
                        "has_content_base64": True,
                    }
                ],
            },
            "metadata": {"transport.channel": "whatsapp"},
            "observations": [
                {
                    "name": "attachments.prepare",
                    "output": {"attachments": [manifest]},
                }
            ],
        },
        use_output_as_expected=False,
    )

    assert item["input"]["conversation_id"] == "conversation-1"
    assert item["input"]["attachment_placeholders"][0]["filename"] == "factura.jpg"
    assert item["input"]["attachment_manifests"] == [manifest]
    assert item["metadata"]["attachment_manifests"] == [manifest]


def test_eval_context_includes_curated_attachment_manifests() -> None:
    context = _eval_context(
        {
            "context": {"customer_name": "Sumampa SRL"},
            "attachment_manifests": [{"manifest": {"storage_uri": "s3://file"}}],
        }
    )

    assert context["customer_name"] == "Sumampa SRL"
    assert context["attachment_manifests"] == [{"manifest": {"storage_uri": "s3://file"}}]
