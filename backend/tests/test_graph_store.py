"""Tests for the knowledge map store (app/services/graph_store.py).

The store runs Graphiti on its own event loop thread and hands back plain
dicts. Here the Graphiti/FalkorDB backend is replaced by an in-memory fake, so
these tests check the store's own behaviour: ontology handling, data shapes,
missing graphs, retries, progress and thread safety. A separate integration
test (test_graph_store_falkordb.py) runs the real backend against FalkorDB.
"""

import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import graph_store as gs


# ---------------------------------------------------------------- fake backend

def _node(uuid, name, labels, summary="", attributes=None, created_at=None):
    return SimpleNamespace(uuid=uuid, name=name, labels=labels, summary=summary,
                           attributes=attributes or {}, created_at=created_at)


def _edge(uuid, name, fact, src, tgt, **kw):
    return SimpleNamespace(uuid=uuid, name=name, fact=fact, source_node_uuid=src,
                           target_node_uuid=tgt, attributes=kw.get("attributes", {}),
                           created_at=kw.get("created_at"), valid_at=kw.get("valid_at"),
                           invalid_at=kw.get("invalid_at"), expired_at=kw.get("expired_at"),
                           episodes=kw.get("episodes", []))


class FakeBackend:
    """In-memory stand-in for the Graphiti/FalkorDB backend (async API)."""

    def __init__(self):
        self.graphs = {}          # graph_id -> {"meta": dict|None, "nodes": [], "edges": []}
        self.indexed = []
        self.episodes = []        # kwargs of every add_episode call
        self.fail_next_adds = 0
        self.searches = []
        self.closed = False
        self.loop_threads = set()

    def _seen(self):
        self.loop_threads.add(threading.current_thread().name)

    async def ensure_indices(self, graph_id):
        self._seen()
        self.indexed.append(graph_id)
        self.graphs.setdefault(graph_id, {"meta": None, "nodes": [], "edges": []})

    async def list_graphs(self):
        self._seen()
        return list(self.graphs)

    async def delete_graph(self, graph_id):
        self._seen()
        self.graphs.pop(graph_id, None)

    async def write_meta(self, graph_id, data):
        self._seen()
        self.graphs.setdefault(graph_id, {"meta": None, "nodes": [], "edges": []})["meta"] = dict(data)

    async def read_meta(self, graph_id):
        self._seen()
        g = self.graphs.get(graph_id)
        return dict(g["meta"]) if g and g["meta"] else None

    async def add_episode(self, graph_id, **kwargs):
        self._seen()
        if self.fail_next_adds:
            self.fail_next_adds -= 1
            raise RuntimeError("rate limited")
        self.episodes.append({"graph_id": graph_id, **kwargs})
        n = len(self.episodes)
        return f"ep-{n}", 2, 1

    async def list_nodes(self, graph_id, limit=None, cursor=None):
        self._seen()
        nodes = sorted(self.graphs[graph_id]["nodes"], key=lambda n: n.uuid, reverse=True)
        if cursor:
            nodes = [n for n in nodes if n.uuid < cursor]
        return nodes[:limit] if limit else nodes

    async def list_edges(self, graph_id, limit=None, cursor=None):
        self._seen()
        edges = sorted(self.graphs[graph_id]["edges"], key=lambda e: e.uuid, reverse=True)
        if cursor:
            edges = [e for e in edges if e.uuid < cursor]
        return edges[:limit] if limit else edges

    async def get_node(self, graph_id, node_uuid):
        self._seen()
        for n in self.graphs[graph_id]["nodes"]:
            if n.uuid == node_uuid:
                return n
        return None

    async def get_node_edges(self, graph_id, node_uuid):
        self._seen()
        return [e for e in self.graphs[graph_id]["edges"]
                if node_uuid in (e.source_node_uuid, e.target_node_uuid)]

    async def search(self, graph_id, query, scope, reranker, limit):
        self._seen()
        self.searches.append((graph_id, query, scope, reranker, limit))
        g = self.graphs[graph_id]
        edges = [e for e in g["edges"] if query.lower() in e.fact.lower()][:limit] if scope in ("edges", "both") else []
        nodes = [n for n in g["nodes"] if query.lower() in n.name.lower()][:limit] if scope in ("nodes", "both") else []
        return edges, [1.0] * len(edges), nodes, [0.5] * len(nodes)

    def token_usage(self):
        return {"input_tokens": 10, "output_tokens": 5, "calls": 1}

    async def close(self):
        self.closed = True


@pytest.fixture
def fake():
    return FakeBackend()


@pytest.fixture
def store(fake):
    async def factory():
        return fake
    s = gs.GraphStore(backend_factory=factory)
    yield s
    s.shutdown()


ONTOLOGY = {
    "entity_types": [
        {"name": "public_figure", "description": "A named person in the news.",
         "attributes": [{"name": "role", "description": "Their job"},
                        {"name": "name", "description": "Clashes with a reserved field"},
                        {"name": "labels", "description": "Also reserved in Graphiti"}]},
        {"name": "Company", "description": "A business.", "attributes": []},
        {"name": "Entity", "description": "Default type, must be skipped", "attributes": []},
    ],
    "edge_types": [
        {"name": "worksFor", "description": "Employment.",
         "source_targets": [{"source": "public_figure", "target": "Company"}],
         "attributes": [{"name": "fact", "description": "Reserved on edges"},
                        {"name": "since", "description": "Start year"}]},
        {"name": "competes_with", "description": "Rivalry.", "source_targets": [],
         "attributes": []},
    ],
}


# ---------------------------------------------------------------- ontology

def test_build_types_normalises_names_and_reserved_fields():
    entity_types, edge_types, edge_type_map = gs.build_types(ONTOLOGY)
    assert set(entity_types) == {"PublicFigure", "Company"}
    fields = set(entity_types["PublicFigure"].model_fields)
    assert fields == {"role", "entity_name", "entity_labels"}
    assert entity_types["PublicFigure"].__doc__ == "A named person in the news."
    assert set(edge_types) == {"WORKS_FOR", "COMPETES_WITH"}
    assert set(edge_types["WORKS_FOR"].model_fields) == {"edge_fact", "since"}
    assert edge_type_map[("PublicFigure", "Company")] == ["WORKS_FOR"]
    # An edge type with no declared pairs may link any two entities.
    assert "COMPETES_WITH" in edge_type_map[("Entity", "Entity")]


def test_build_types_passes_graphiti_validation():
    from graphiti_core.utils.ontology_utils.entity_types_utils import validate_entity_types
    entity_types, _, _ = gs.build_types(ONTOLOGY)
    assert validate_entity_types(entity_types)


def test_build_types_empty_ontology():
    assert gs.build_types({}) == (None, None, None)


# ---------------------------------------------------------------- lifecycle

def test_create_graph_makes_id_indexes_and_meta(store, fake):
    gid = store.create_graph("Test map", "desc")
    assert gid.startswith("mirofish_") and len(gid) == len("mirofish_") + 16
    assert fake.indexed == [gid]
    assert fake.graphs[gid]["meta"]["name"] == "Test map"
    assert store.graph_exists(gid)
    assert not store.graph_exists("mirofish_missing")


def test_all_backend_work_runs_on_the_store_loop_thread(store, fake):
    store.create_graph("x")
    assert fake.loop_threads == {"graphiti-loop"}


def test_set_ontology_persists_and_reloads_after_restart(fake):
    async def factory():
        return fake
    first = gs.GraphStore(backend_factory=factory)
    gid = first.create_graph("x")
    first.set_ontology(gid, ONTOLOGY)
    first.shutdown()

    # A new store (as after a server restart) reads the ontology back from the graph.
    second = gs.GraphStore(backend_factory=factory)
    try:
        assert second.get_ontology(gid)["entity_types"][0]["name"] == "PublicFigure"
        second.add_text(gid, "Alice works for Acme.")
        call = fake.episodes[-1]
        assert set(call["entity_types"]) == {"PublicFigure", "Company"}
        assert call["edge_type_map"][("PublicFigure", "Company")] == ["WORKS_FOR"]
    finally:
        second.shutdown()


def test_set_ontology_keeps_existing_meta(store, fake):
    gid = store.create_graph("Named")
    store.set_ontology(gid, ONTOLOGY)
    assert fake.graphs[gid]["meta"]["name"] == "Named"


def test_delete_graph(store, fake):
    gid = store.create_graph("x")
    store.delete_graph(gid)
    assert gid not in fake.graphs
    assert not store.graph_exists(gid)


def test_shutdown_closes_backend(fake):
    async def factory():
        return fake
    s = gs.GraphStore(backend_factory=factory)
    s.graph_exists("anything")
    s.shutdown()
    assert fake.closed


# ---------------------------------------------------------------- writes

def test_add_text_without_ontology_sends_no_types(store, fake):
    gid = store.create_graph("x")
    out = store.add_text(gid, "hello", source="message", source_description="sim")
    assert out == {"episode_uuid": "ep-1", "node_count": 2, "edge_count": 1}
    call = fake.episodes[0]
    assert call["entity_types"] is None and call["edge_types"] is None
    assert call["source"] == "message"
    assert call["source_description"] == "sim"
    assert call["reference_time"].tzinfo is not None


def test_add_text_retries_once(store, fake):
    gid = store.create_graph("x")
    fake.fail_next_adds = 1
    assert store.add_text(gid, "hello", retry_delay=0)["episode_uuid"] == "ep-1"


def test_add_text_gives_up_after_retry(store, fake):
    gid = store.create_graph("x")
    fake.fail_next_adds = 2
    with pytest.raises(RuntimeError):
        store.add_text(gid, "hello", retry_delay=0)


def test_add_text_on_missing_graph_raises_graph_not_found(store):
    with pytest.raises(gs.GraphNotFound):
        store.add_text("mirofish_gone", "hello")


def test_add_texts_reports_progress_per_chunk(store, fake):
    gid = store.create_graph("x")
    seen = []
    uuids = store.add_texts(gid, ["a", "b", "c"], progress_callback=lambda m, p: seen.append((m, p)))
    assert uuids == ["ep-1", "ep-2", "ep-3"]
    assert [round(p, 2) for _, p in seen] == [0.33, 0.67, 1.0]
    assert "3 of 3" in seen[-1][0]
    assert [c["name"] for c in fake.episodes] == ["chunk-0001", "chunk-0002", "chunk-0003"]


# ---------------------------------------------------------------- reads

@pytest.fixture
def populated(store, fake):
    gid = store.create_graph("x")
    t = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
    fake.graphs[gid]["nodes"] = [
        _node("n1", "Alice Byrne", ["Entity", "PublicFigure"], "CEO of Acme", {"role": "CEO"}, t),
        _node("n2", "Acme Ltd", ["Company", "Entity"], "A firm", {}, t),
        _node("n3", "Loose", ["Entity"], "", {}, None),
    ]
    fake.graphs[gid]["edges"] = [
        _edge("e1", "WORKS_FOR", "Alice Byrne leads Acme Ltd", "n1", "n2",
              created_at=t, valid_at=t, episodes=["ep-1"]),
    ]
    return gid


def test_get_all_nodes_shape(store, populated):
    nodes = store.get_all_nodes(populated)
    assert {n["uuid"] for n in nodes} == {"n1", "n2", "n3"}
    alice = next(n for n in nodes if n["uuid"] == "n1")
    assert alice == {"uuid": "n1", "name": "Alice Byrne", "labels": ["Entity", "PublicFigure"],
                     "summary": "CEO of Acme", "attributes": {"role": "CEO"},
                     "created_at": "2026-10-27T10:00:00+00:00"}


def test_get_all_nodes_pages_and_caps(store, fake):
    gid = store.create_graph("x")
    fake.graphs[gid]["nodes"] = [_node(f"n{i:04d}", f"N{i}", ["Entity"]) for i in range(25)]
    assert len(store.get_all_nodes(gid, page_size=10)) == 25
    assert len(store.get_all_nodes(gid, page_size=10, max_items=12)) == 12


def test_get_all_edges_shape(store, populated):
    edges = store.get_all_edges(populated)
    assert edges == [{
        "uuid": "e1", "name": "WORKS_FOR", "fact": "Alice Byrne leads Acme Ltd",
        "fact_type": "WORKS_FOR", "source_node_uuid": "n1", "target_node_uuid": "n2",
        "attributes": {}, "created_at": "2026-10-27T10:00:00+00:00",
        "valid_at": "2026-10-27T10:00:00+00:00", "invalid_at": None, "expired_at": None,
        "episodes": ["ep-1"],
    }]


def test_get_all_edges_empty_graph_is_empty_list(store):
    gid = store.create_graph("x")
    assert store.get_all_edges(gid) == []


def test_reads_on_missing_graph_raise_graph_not_found(store):
    for call in (lambda: store.get_all_nodes("mirofish_gone"),
                 lambda: store.get_all_edges("mirofish_gone"),
                 lambda: store.get_node("mirofish_gone", "n1"),
                 lambda: store.search("mirofish_gone", "q")):
        with pytest.raises(gs.GraphNotFound) as err:
            call()
        assert "rebuild" in str(err.value).lower()


def test_get_node_and_edges(store, populated):
    assert store.get_node(populated, "n2")["name"] == "Acme Ltd"
    assert store.get_node(populated, "nope") is None
    assert [e["uuid"] for e in store.get_node_edges(populated, "n2")] == ["e1"]


def test_search_edges_and_nodes(store, fake, populated):
    out = store.search(populated, "acme", limit=5, scope="both", reranker="cross_encoder")
    assert [e["fact"] for e in out["edges"]] == ["Alice Byrne leads Acme Ltd"]
    assert out["edges"][0]["score"] == 1.0
    assert [n["name"] for n in out["nodes"]] == ["Acme Ltd"]
    assert fake.searches[-1] == (populated, "acme", "both", "cross_encoder", 5)


def test_search_rejects_bad_scope(store, populated):
    with pytest.raises(ValueError):
        store.search(populated, "q", scope="everything")


def test_concurrent_reads_from_many_threads(store, populated):
    results, errors = [], []

    def work():
        try:
            results.append(len(store.get_all_nodes(populated)))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and results == [3] * 12


def test_token_usage_passthrough(store):
    assert store.token_usage()["calls"] == 1


# ---------------------------------------------------------------- configuration

def test_missing_config_lists_what_is_absent(monkeypatch):
    monkeypatch.setattr(gs.Config, "FALKORDB_HOST", None)
    monkeypatch.setattr(gs.Config, "GRAPHITI_ANTHROPIC_API_KEY", None)
    missing = gs.missing_config()
    assert "FALKORDB_HOST" in missing and "GRAPHITI_ANTHROPIC_API_KEY" in missing
    assert not gs.is_configured()


def test_configured_when_host_and_key_present(monkeypatch):
    monkeypatch.setattr(gs.Config, "FALKORDB_HOST", "falkordb.railway.internal")
    monkeypatch.setattr(gs.Config, "GRAPHITI_ANTHROPIC_API_KEY", "sk-ant-test")
    assert gs.missing_config() == []
    assert gs.is_configured()
