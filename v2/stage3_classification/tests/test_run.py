"""Exercise CLI selection and persistence with fake API clients and a real temp DB."""

import sys
from types import SimpleNamespace

import pytest

from v2.stage1_extraction.store import ProcessedDataStore
from v2.stage2_normalization.store import NormalizedDataStore
from v2.stage3_classification import classifier, run
from v2.stage3_classification.classifier import ClassificationResult
from v2.stage3_classification.search import ProductSearch
from v2.stage3_classification.store import ClassificationStore


@pytest.fixture
def harness(tmp_path, monkeypatch):
    path = str(tmp_path / "data.db")
    ProcessedDataStore(path)
    norm = NormalizedDataStore(path)
    db = ClassificationStore(path)
    state = SimpleNamespace(db=db, calls=[], searches=[], fail=set(), search_ok=True,
                            on_classify=None, gate=True)

    def add(store, name, source="embed_llm"):
        norm.insert_normalized_item(None, f"{store}_{name}", store, "2026-01-01", "2026-01-01",
                                    name, "discrete_units", 1, 2, 2, [])
        if source:
            db.upsert_label(name, "Lácteos", "Leche", source, store=store, producto_es="Before")

    class FakeClassifier:
        calls = 0

        def classify(self, name, store, neighbours, gate, search):
            state.calls.append((store, name, search))
            self.calls += 1
            if state.on_classify:
                state.on_classify(name)
            if name in state.fail:
                raise RuntimeError("API failed")
            return ClassificationResult(name, store, "After", "Lácteos", "Yogur",
                                        "search_llm" if search and search["success"] else "embed_llm",
                                        .9, False)

    class FakeTavily:
        def search(self, **kwargs):
            state.searches.append(kwargs)
            if not state.search_ok:
                raise RuntimeError("quota exceeded")
            return {"results": [{"url": "https://www.jumbo.com/producten/melk", "title": "Milk", "content": "milk"}]}

    monkeypatch.setattr(run, "settings", SimpleNamespace(PROCESSED_DB=path, OLD_DATA_CSV="unused", TOKEN_USAGE_DB="unused"))
    monkeypatch.setattr(run, "load_old_labels", lambda _: [])
    monkeypatch.setattr(run, "seed_labels", lambda *_: 0)
    monkeypatch.setattr(run, "Embedder", lambda _: SimpleNamespace(api_calls=0))
    monkeypatch.setattr(run, "Matcher", lambda *_: SimpleNamespace(neighbours=lambda names: [[] for _ in names]))
    monkeypatch.setattr(run, "passes_gate", lambda _: state.gate)
    monkeypatch.setattr(run, "ProductSearch", lambda db: ProductSearch(db, client=FakeTavily()))
    monkeypatch.setattr(classifier, "Classifier", FakeClassifier)
    monkeypatch.setattr(run, "CostReport", lambda _: SimpleNamespace(by_stage=lambda: []))

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["classify", *args])
        run.main()

    state.add = add
    state.invoke = invoke
    return state


def test_store_filtered_rebuild_preserves_other_store(harness):
    h = harness
    h.add("ah", "AH MILK")
    h.add("jumbo", "JUMBO MILK")
    before = h.db.get_label("JUMBO MILK")
    h.invoke("--rebuild", "--store", "ah", "--no-search")
    assert [c[:2] for c in h.calls] == [("ah", "AH MILK")]
    assert h.db.get_label("JUMBO MILK") == before
    assert h.db._query("SELECT category, producto_es FROM classified_data WHERE store='jumbo'") == [
        {"category": "Lácteos", "producto_es": "Before"}]


def test_rebuild_deduplicates_before_limit_and_protects_labels(harness):
    h = harness
    for store, name, source in [("ah", "A", "embed_llm"), ("jumbo", "A", "embed_llm"),
                                ("ah", "B", "search_llm"), ("ah", "C", "manual"),
                                ("ah", "D", "old_data"), ("jumbo", "E", None)]:
        h.add(store, name, source)
    before = {name: h.db.get_label(name) for name in ("C", "D")}
    h.invoke("--rebuild", "--limit", "2", "--no-search")
    assert [c[1] for c in h.calls] == ["A", "B"]
    assert {name: h.db.get_label(name) for name in before} == before
    assert h.db.get_label("E") is None
    assert all(r["producto_es"] == "After" for r in h.db._query("SELECT producto_es FROM classified_data WHERE item_name='A'"))


def test_failed_rebuild_preserves_previous_label(harness):
    h = harness
    h.add("ah", "A")
    h.add("ah", "B")
    before = h.db.get_label("A")
    h.fail.add("A")
    h.invoke("--rebuild", "--no-search")
    assert h.db.get_label("A") == before
    assert h.db.get_label("B")["producto_es"] == "After"


def test_search_retry_prefers_failed_store_and_bypasses_gate(harness):
    h = harness
    h.add("ah", "MILK")
    h.add("jumbo", "MILK")
    h.db.save_search("jumbo", "MILK", "old query", False, [], "quota exceeded")
    h.invoke("--retry-failed-search")
    assert [c[:2] for c in h.calls] == [("jumbo", "MILK")]
    assert len(h.searches) == 1
    assert h.calls[0][2]["success"]
    assert h.db.get_search("jumbo", "MILK")["success"]
    assert h.db.get_label("MILK")["source"] == "search_llm"
    h.invoke("--retry-failed-search")
    assert len(h.calls) == len(h.searches) == 1


def test_failed_retry_keeps_existing_label_and_remains_retryable(harness, capsys):
    h = harness
    h.add("ah", "MILK")
    h.db.save_search("ah", "MILK", "old query", False, [])
    before = h.db.get_label("MILK")
    h.search_ok = False
    h.invoke("--retry-failed-search")
    assert h.db.get_label("MILK") == before
    assert h.calls == []
    assert "previous label retained" in capsys.readouterr().out
    h.search_ok = True
    h.invoke("--retry-failed-search")
    assert h.db.get_label("MILK")["producto_es"] == "After"


def test_retry_leaves_protected_successful_and_other_store_labels_alone(harness):
    h = harness
    for name, source, store in [("MANUAL", "manual", "ah"), ("SEED", "old_data", "ah"),
                                 ("OK", "embed_llm", "ah"), ("JUMBO", "embed_llm", "jumbo")]:
        h.add(store, name, source)
        h.db.save_search(store, name, "query", name == "OK", [])
    before = h.db.get_labels()
    h.invoke("--retry-failed-search", "--store", "ah")
    assert not h.calls and not h.searches
    assert h.db.get_labels() == before


def test_llm_failure_after_search_refresh_preserves_label_and_rebuild_reuses_cache(harness):
    h = harness
    h.add("ah", "MILK")
    h.db.save_search("ah", "MILK", "old query", False, [])
    before = h.db.get_label("MILK")
    h.fail.add("MILK")
    h.invoke("--retry-failed-search")
    assert h.db.get_label("MILK") == before
    assert h.db.get_search("ah", "MILK")["success"]
    h.fail.clear()
    h.gate = False
    h.invoke("--rebuild")
    assert len(h.searches) == 1
    assert h.db.get_label("MILK")["producto_es"] == "After"


@pytest.mark.parametrize("source", ["manual", "old_data"])
def test_rebuild_does_not_overwrite_label_protected_during_api_call(harness, source):
    h = harness
    h.add("ah", "MILK")
    h.on_classify = lambda name: h.db.upsert_label(name, "Lácteos", "Huevos", source)
    h.invoke("--rebuild", "--no-search")
    assert h.db.get_label("MILK")["source"] == source
    assert h.db.get_label("MILK")["subcategory"] == "Huevos"


def test_dry_run_uses_retry_worklist_and_does_not_change_labels(harness, capsys):
    h = harness
    h.add("ah", "A")
    h.add("jumbo", "A")
    h.add("ah", "B")
    h.db.save_search("jumbo", "A", "query", False, [])
    before = h.db.get_labels()
    h.invoke("--rebuild", "--retry-failed-search", "--limit", "1", "--dry-run")
    output = capsys.readouterr().out
    # B sorts before the selected Jumbo retry pair; limiting happens after selection.
    assert "Selected items: 1" in output and "Would call Tavily for 0 items" in output
    assert not h.calls and not h.searches
    assert h.db.get_labels() == before
    h.invoke("--retry-failed-search", "--dry-run")
    assert "Would call Tavily for 1 items" in capsys.readouterr().out
    assert not h.calls and not h.searches


@pytest.mark.parametrize("args", [("--limit", "0"), ("--limit", "-1"),
                                  ("--retry-failed-search", "--no-search")])
def test_invalid_cli_options_rejected(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["classify", *args])
    with pytest.raises(SystemExit) as error:
        run.parse_args()
    assert error.value.code == 2
