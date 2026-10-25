"""Persist sync inputs and explicit approvals inside existing label evidence."""

import json


IDENTITY_FIELDS = ("category", "subcategory", "producto_es", "store")


def evidence_dict(raw):
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {"original_evidence": raw}
    return value if isinstance(value, dict) else {"original_evidence": value}


def sync_inputs(product):
    return {"version": 1, **{key: product[key] for key in IDENTITY_FIELDS},
            "needs_review": bool(product["needs_review"])}


def identity(inputs):
    return {key: inputs.get(key) for key in IDENTITY_FIELDS}


def same_identity(previous, current):
    return isinstance(previous, dict) and previous.get("version") == 1 and identity(previous) == identity(current)


def is_approved(evidence, inputs, subcategory_id):
    return evidence.get("approval") == {"identity": identity(inputs), "subcategory_id": subcategory_id}


def assignment_evidence(product, previous=None):
    """An assignment starts fresh, retaining an outstanding taxonomy split review."""
    old = evidence_dict(previous["evidence"]) if previous else {}
    reasons = ["taxonomy_split"] if "taxonomy_split" in old.get("review_reasons", []) else []
    if product["needs_review"]:
        reasons.append("upstream")
    return {"sync_inputs": sync_inputs(product), "review_reasons": reasons}
