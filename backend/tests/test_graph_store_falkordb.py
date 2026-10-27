"""Integration tests: graph_store with the real Graphiti backend on a real FalkorDB.

Skipped unless a FalkorDB is reachable. Locally:

    docker run -d --name forecast-falkordb-test -p 16379:6379 -e BROWSER=0 \\
      -e REDIS_ARGS="--requirepass localtestpw" falkordb/falkordb:v4.22.2
    FALKORDB_TEST_HOST=localhost FALKORDB_TEST_PORT=16379 FALKORDB_TEST_PASSWORD=localtestpw pytest

These tests write nodes and relationships with Graphiti's own models and a fake
embedder, so they need no AI key and cost nothing. The live test at the bottom
(GRAPHITI_LIVE_TEST=1) reads real text with Claude and the local embedding
model, and costs a few cents.
"""

import hashlib
import math
import os
from datetime import datetime, timezone

import pytest

HOST = os.environ.get('FALKORDB_TEST_HOST')
PORT = int(os.environ.get('FALKORDB_TEST_PORT', '6379'))
PASSWORD = os.environ.get('FALKORDB_TEST_PASSWORD') or None

pytestmark = pytest.mark.skipif(not HOST, reason='FALKORDB_TEST_HOST not set')

from app.config import Config  # noqa: E402
from app.services import graph_store as gs  # noqa: E402

DIM = Config.GRAPHITI_EMBEDDING_DIM


def _hash_vector(text):
    """Deterministic bag-of-words vector so similar texts land close together."""
    vec = [0.0] * DIM
    for word in text.lower().split():
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _fake_embedder():
    from graphiti_core.embedder.client import EmbedderClient

    class FakeEmbedder(EmbedderClient):
        async def create(self, input_data):
            text = input_data if isinstance(input_data, str) else input_data[0]
            return _hash_vector(text)

        async def create_batch(self, input_data_list):
            return [_hash_vector(t) for t in input_data_list]

    return FakeEmbedder()


def _no_llm():
    """An LLM client that must never be called (these tests write data directly)."""
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig

    class NoLLM(LLMClient):
        async def _generate_response(self, *a, **kw):
            raise AssertionError('the LLM should not be called in these tests')

    return NoLLM(LLMConfig(api_key='unused', model='unused'))


def _fake_cross_encoder():
    from graphiti_core.cross_encoder.client import CrossEncoderClient

    class FakeRanker(CrossEncoderClient):
        async def rank(self, query, passages):
            q = set(query.lower().split())
            scored = [(p, len(q & set(p.lower().split())) / (len(q) or 1)) for p in passages]
            return sorted(scored, key=lambda x: x[1], reverse=True)

    return FakeRanker()


@pytest.fixture
def store():
    from app.services.graphiti_backend import GraphitiBackend, make_falkor_client

    async def factory():
        return GraphitiBackend(
            falkor_client=make_falkor_client(host=HOST, port=PORT, password=PASSWORD, username=None),
            llm_client=_no_llm(), embedder=_fake_embedder(), cross_encoder=_fake_cross_encoder(),
            max_coroutines=5)

    s = gs.GraphStore(backend_factory=factory)
    created = []
    original_create = s.create_graph

    def tracking_create(*a, **kw):
        gid = original_create(*a, **kw)
        created.append(gid)
        return gid

    s.create_graph = tracking_create
    yield s
    for gid in created:
        try:
            s.delete_graph(gid)
        except Exception:
            pass
    s.shutdown()


def _seed(store, gid):
    """Write two people, one company and two relationships with Graphiti's models."""
    from graphiti_core.edges import EntityEdge
    from graphiti_core.nodes import EntityNode

    embedder = _fake_embedder()
    t = datetime(2026, 10, 27, 9, 30, tzinfo=timezone.utc)

    async def go(backend):
        driver = backend._driver(gid)
        alice = EntityNode(name='Alice Byrne', group_id=gid, labels=['Entity', 'Person'],
                           summary='Chief executive of Harbour Tech', attributes={'role': 'CEO'}, created_at=t)
        bob = EntityNode(name='Bob Okafor', group_id=gid, labels=['Entity', 'Person'],
                         summary='Investor', created_at=t)
        harbour = EntityNode(name='Harbour Tech', group_id=gid, labels=['Entity', 'Company'],
                             summary='A Bristol robotics firm', created_at=t)
        for n in (alice, bob, harbour):
            await n.generate_name_embedding(embedder)
            await n.save(driver)
        e1 = EntityEdge(group_id=gid, source_node_uuid=alice.uuid, target_node_uuid=harbour.uuid,
                        name='WORKS_FOR', fact='Alice Byrne runs Harbour Tech as chief executive',
                        episodes=['ep-a'], created_at=t, valid_at=t)
        e2 = EntityEdge(group_id=gid, source_node_uuid=bob.uuid, target_node_uuid=harbour.uuid,
                        name='INVESTS_IN', fact='Bob Okafor invested in Harbour Tech robotics',
                        episodes=['ep-b'], created_at=t, valid_at=t, expired_at=t)
        for e in (e1, e2):
            await e.generate_embedding(embedder)
            await e.save(driver)
        return alice.uuid, harbour.uuid

    return store._run(go)


def test_create_meta_ontology_and_exists(store):
    gid = store.create_graph('Integration map', 'test')
    assert store.graph_exists(gid)
    assert store.get_all_nodes(gid) == []      # the metadata node is not an entity
    assert store.get_all_edges(gid) == []      # Graphiti raises here; the store returns []
    store.set_ontology(gid, {'entity_types': [{'name': 'person', 'description': 'A person',
                                               'attributes': [{'name': 'role', 'description': 'Job'}]}],
                             'edge_types': []})
    store._ontology_cache.clear()              # force a read back from FalkorDB
    assert store.get_ontology(gid)['entity_types'][0]['name'] == 'Person'


def test_reads_shapes_against_falkordb(store):
    gid = store.create_graph('Integration map')
    alice_uuid, harbour_uuid = _seed(store, gid)

    nodes = store.get_all_nodes(gid)
    assert sorted(n['name'] for n in nodes) == ['Alice Byrne', 'Bob Okafor', 'Harbour Tech']
    alice = next(n for n in nodes if n['uuid'] == alice_uuid)
    assert set(alice['labels']) == {'Entity', 'Person'}
    assert alice['attributes'] == {'role': 'CEO'}
    assert alice['created_at'].startswith('2026-10-27T09:30:00')

    edges = store.get_all_edges(gid)
    assert sorted(e['name'] for e in edges) == ['INVESTS_IN', 'WORKS_FOR']
    inv = next(e for e in edges if e['name'] == 'INVESTS_IN')
    assert inv['fact_type'] == 'INVESTS_IN'
    assert inv['expired_at'].startswith('2026-10-27T09:30:00')
    assert inv['episodes'] == ['ep-b']

    assert store.get_node(gid, harbour_uuid)['name'] == 'Harbour Tech'
    assert store.get_node(gid, 'no-such-node') is None
    assert len(store.get_node_edges(gid, harbour_uuid)) == 2


def test_paging_against_falkordb(store):
    gid = store.create_graph('Integration map')
    _seed(store, gid)
    assert len(store.get_all_nodes(gid, page_size=1)) == 3
    assert len(store.get_all_edges(gid, page_size=1)) == 2


def test_search_rrf_and_cross_encoder(store):
    gid = store.create_graph('Integration map')
    _seed(store, gid)
    out = store.search(gid, 'Harbour Tech chief executive', limit=5, scope='edges', reranker='rrf')
    assert out['edges'] and out['edges'][0]['fact'].startswith('Alice Byrne')
    out = store.search(gid, 'Bob Okafor investor', limit=5, scope='both', reranker='cross_encoder')
    assert any(e['name'] == 'INVESTS_IN' for e in out['edges'])
    assert any(n['name'] == 'Bob Okafor' for n in out['nodes'])


def test_graphs_are_isolated(store):
    a = store.create_graph('A')
    b = store.create_graph('B')
    _seed(store, a)
    assert store.get_all_nodes(b) == []
    assert store.search(b, 'Harbour Tech', scope='both')['edges'] == []


def test_delete_and_missing_graph(store):
    gid = store.create_graph('Integration map')
    _seed(store, gid)
    store.delete_graph(gid)
    assert not store.graph_exists(gid)
    with pytest.raises(gs.GraphNotFound):
        store.get_all_nodes(gid)
    with pytest.raises(gs.GraphNotFound):
        store.add_text(gid, 'hello', retry_delay=0)


# ---------------------------------------------------------------- live (costs a few cents)

@pytest.mark.skipif(os.environ.get('GRAPHITI_LIVE_TEST') != '1' or not Config.GRAPHITI_ANTHROPIC_API_KEY,
                    reason='set GRAPHITI_LIVE_TEST=1 and GRAPHITI_ANTHROPIC_API_KEY to read text with Claude')
def test_live_add_episode_with_claude_and_local_embedder():
    from app.services.graphiti_backend import GraphitiBackend, make_falkor_client, make_llm_client, \
        make_local_cross_encoder, make_local_embedder

    async def factory():
        return GraphitiBackend(
            falkor_client=make_falkor_client(host=HOST, port=PORT, password=PASSWORD, username=None),
            llm_client=make_llm_client(),
            embedder=make_local_embedder(Config.GRAPHITI_EMBEDDING_MODEL, Config.GRAPHITI_EMBEDDING_DIM),
            cross_encoder=make_local_cross_encoder(Config.GRAPHITI_RERANK_MODEL),
            max_coroutines=5)

    s = gs.GraphStore(backend_factory=factory)
    gid = s.create_graph('Live test')
    try:
        s.set_ontology(gid, {
            'entity_types': [
                {'name': 'Person', 'description': 'A named individual.',
                 'attributes': [{'name': 'role', 'description': 'Job title'}]},
                {'name': 'Organization', 'description': 'A company or public body.', 'attributes': []},
            ],
            'edge_types': [
                {'name': 'WORKS_FOR', 'description': 'Employment.', 'attributes': [],
                 'source_targets': [{'source': 'Person', 'target': 'Organization'}]},
            ],
        })
        out = s.add_text(gid, 'TEST DOCUMENT. Alice Byrne is the chief executive of Harbour Tech, '
                              'a robotics company in Bristol. Bob Okafor works for Harbour Tech as '
                              'its head of sales.')
        assert out['node_count'] >= 2
        nodes = s.get_all_nodes(gid)
        names = {n['name'] for n in nodes}
        assert any('Harbour' in n for n in names)
        assert any('Person' in n['labels'] for n in nodes)
        assert s.get_all_edges(gid)
        hits = s.search(gid, 'Who runs Harbour Tech?', scope='edges', reranker='cross_encoder')
        assert hits['edges']
        print('token usage', s.token_usage())
    finally:
        s.delete_graph(gid)
        s.shutdown()
