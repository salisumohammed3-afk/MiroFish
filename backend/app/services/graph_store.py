"""
Knowledge map store: Graphiti (a library) on a self-hosted FalkorDB.

This is the one place Forecast talks to its knowledge graphs. Everything else
(graph building, persona generation, simulation memory, the report agent and
the API) calls the synchronous functions here and gets plain dicts back, in
the same shapes the old Zep code produced, so the frontend did not change.

How it works:
- Graphiti is async; Forecast is threaded Flask. One background thread runs an
  event loop that owns every Graphiti, FalkorDB and Anthropic object. Flask
  threads hand work to that loop and wait for the answer.
- Each Forecast graph id ("mirofish_<16 hex>") is its own FalkorDB graph.
- Graphiti does not remember a graph's ontology, so it is stored as a small
  ForecastMeta node inside the graph itself and passed to every add.
- Extraction uses Claude (Anthropic). Embeddings and reranking run locally with
  small sentence-transformers models, so they cost nothing per call.
"""

import asyncio
import atexit
import copy
import json
import os
import threading
import time
import uuid as uuidlib
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..config import Config
from ..utils.logger import get_logger
from ..utils.naming import normalize_ontology_names, to_pascal_case, to_screaming_snake

logger = get_logger('mirofish.graph_store')

# Graphiti reads these at import time, so set them before it is ever imported.
os.environ.setdefault('GRAPHITI_TELEMETRY_ENABLED', 'false')
os.environ.setdefault('EMBEDDING_DIM', str(Config.GRAPHITI_EMBEDDING_DIM))

# Field names an ontology attribute must not use, because Graphiti's own node
# and edge models already have them (EntityNode / EntityEdge model fields).
ENTITY_RESERVED = {'uuid', 'name', 'group_id', 'labels', 'created_at',
                   'name_embedding', 'summary', 'attributes'}
EDGE_RESERVED = {'uuid', 'group_id', 'source_node_uuid', 'target_node_uuid', 'created_at',
                 'name', 'fact', 'fact_embedding', 'episodes', 'expired_at',
                 'valid_at', 'invalid_at', 'reference_time', 'attributes'}

MISSING_GRAPH_MESSAGE = (
    "This project's knowledge map is missing. Maps made before October 2026 lived "
    "in a service Forecast no longer uses. Rebuild the map from the project to continue."
)


class GraphNotFound(LookupError):
    """The graph id does not exist in the store (for example an old Zep graph)."""

    def __init__(self, graph_id: str):
        self.graph_id = graph_id
        super().__init__(MISSING_GRAPH_MESSAGE)


class GraphStoreNotConfigured(RuntimeError):
    pass


# ============================================================== configuration

def missing_config() -> List[str]:
    """Names of the settings the store still needs, empty when ready."""
    missing = []
    if not Config.FALKORDB_HOST:
        missing.append('FALKORDB_HOST')
    if not Config.GRAPHITI_ANTHROPIC_API_KEY:
        missing.append('GRAPHITI_ANTHROPIC_API_KEY')
    return missing


def is_configured() -> bool:
    return not missing_config()


# ============================================================== ontology

def _attr_fields(attributes: List[Dict[str, Any]], reserved: set, prefix: str):
    annotations, fields = {}, {}
    for attr in attributes or []:
        raw = str(attr.get('name') or '').strip()
        if not raw:
            continue
        name = f'{prefix}_{raw}' if raw.lower() in reserved else raw
        if not name.isidentifier():
            continue
        annotations[name] = Optional[str]
        fields[name] = Field(default=None, description=attr.get('description') or name)
    return annotations, fields


def _model(class_name: str, doc: str, annotations, fields):
    return type(class_name, (BaseModel,), {'__doc__': doc, '__annotations__': annotations, **fields})


def build_types(ontology: Optional[Dict[str, Any]]):
    """Turn Forecast's ontology JSON into Graphiti's entity/edge type models.

    Returns (entity_types, edge_types, edge_type_map), each None when empty.
    Names are normalised the same way the old Zep code did, so labels saved
    before the move still match.
    """
    ontology = ontology or {}
    entity_types: Dict[str, type] = {}
    for e in ontology.get('entity_types', []) or []:
        name = to_pascal_case(e.get('name', ''))
        if name == 'Entity' or name in entity_types:
            continue
        ann, fields = _attr_fields(e.get('attributes'), ENTITY_RESERVED, 'entity')
        entity_types[name] = _model(name, e.get('description') or f'A {name} entity.', ann, fields)

    edge_types: Dict[str, type] = {}
    edge_type_map: Dict[Tuple[str, str], List[str]] = {}
    for r in ontology.get('edge_types', []) or []:
        name = to_screaming_snake(r.get('name', ''))
        if name == 'RELATES_TO' or name in edge_types:
            continue
        ann, fields = _attr_fields(r.get('attributes'), EDGE_RESERVED, 'edge')
        class_name = ''.join(w.capitalize() for w in name.split('_')) or 'Edge'
        edge_types[name] = _model(class_name, r.get('description') or f'A {name} relationship.', ann, fields)
        pairs = r.get('source_targets') or []
        if not pairs:
            edge_type_map.setdefault(('Entity', 'Entity'), []).append(name)
        for st in pairs:
            key = (to_pascal_case(st.get('source') or 'Entity'), to_pascal_case(st.get('target') or 'Entity'))
            if name not in edge_type_map.setdefault(key, []):
                edge_type_map[key].append(name)

    return entity_types or None, edge_types or None, edge_type_map or None


# ============================================================== conversions

def _iso(value) -> Optional[str]:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _clean_attrs(attrs) -> Dict[str, Any]:
    if not attrs:
        return {}
    return {k: v for k, v in dict(attrs).items() if not str(k).endswith('_embedding')}


def node_to_dict(node) -> Dict[str, Any]:
    return {
        'uuid': node.uuid,
        'name': node.name or '',
        'labels': list(node.labels or []),
        'summary': node.summary or '',
        'attributes': _clean_attrs(getattr(node, 'attributes', None)),
        'created_at': _iso(getattr(node, 'created_at', None)),
    }


def edge_to_dict(edge) -> Dict[str, Any]:
    name = edge.name or ''
    return {
        'uuid': edge.uuid,
        'name': name,
        'fact': edge.fact or '',
        'fact_type': name,
        'source_node_uuid': edge.source_node_uuid,
        'target_node_uuid': edge.target_node_uuid,
        'attributes': _clean_attrs(getattr(edge, 'attributes', None)),
        'created_at': _iso(getattr(edge, 'created_at', None)),
        'valid_at': _iso(getattr(edge, 'valid_at', None)),
        'invalid_at': _iso(getattr(edge, 'invalid_at', None)),
        'expired_at': _iso(getattr(edge, 'expired_at', None)),
        'episodes': [str(e) for e in (getattr(edge, 'episodes', None) or [])],
    }


# ============================================================== the store

class GraphStore:
    """Synchronous facade over an async backend that lives on one loop thread."""

    def __init__(self, backend_factory: Callable[[], Awaitable[Any]]):
        self._factory = backend_factory
        self._backend = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._start_lock = threading.Lock()
        self._ontology_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._write_locks: Dict[str, asyncio.Lock] = {}

    # ---------------------------------------------------------- runtime

    def _ensure_started(self):
        if self._backend is not None:
            return
        with self._start_lock:
            if self._backend is not None:
                return
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True, name='graphiti-loop')
            thread.start()
            try:
                backend = asyncio.run_coroutine_threadsafe(self._factory(), loop).result(timeout=300)
            except Exception:
                loop.call_soon_threadsafe(loop.stop)
                raise
            self._loop, self._thread, self._backend = loop, thread, backend

    def _run(self, make_coro: Callable[[Any], Awaitable[Any]], timeout: Optional[float] = 300):
        self._ensure_started()
        future = asyncio.run_coroutine_threadsafe(make_coro(self._backend), self._loop)
        return future.result(timeout=timeout)

    def shutdown(self):
        if self._backend is None or self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._backend.close(), self._loop).result(timeout=30)
        except Exception as e:  # pragma: no cover
            logger.warning(f'Graph store close failed: {e}')
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
        self._backend = None
        self._loop = None

    # ---------------------------------------------------------- graphs

    def graph_exists(self, graph_id: str) -> bool:
        if not graph_id:
            return False
        return graph_id in self._run(lambda b: b.list_graphs())

    def _require(self, graph_id: str):
        if not self.graph_exists(graph_id):
            raise GraphNotFound(graph_id)

    def create_graph(self, name: str, description: str = '') -> str:
        graph_id = f'mirofish_{uuidlib.uuid4().hex[:16]}'

        async def go(b):
            await b.ensure_indices(graph_id)
            await b.write_meta(graph_id, {
                'name': name, 'description': description,
                'created_at': datetime.now(timezone.utc).isoformat(),
            })

        self._run(go)
        self._ontology_cache[graph_id] = None
        return graph_id

    def delete_graph(self, graph_id: str) -> None:
        self._run(lambda b: b.delete_graph(graph_id))
        self._ontology_cache.pop(graph_id, None)

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        ontology = normalize_ontology_names(copy.deepcopy(ontology or {}))
        build_types(ontology)  # fail early on anything Graphiti would reject

        async def go(b):
            meta = await b.read_meta(graph_id) or {}
            meta['ontology'] = json.dumps(ontology)
            await b.write_meta(graph_id, meta)

        self._run(go)
        self._ontology_cache[graph_id] = ontology

    def get_ontology(self, graph_id: str) -> Optional[Dict[str, Any]]:
        if graph_id in self._ontology_cache:
            return self._ontology_cache[graph_id]
        meta = self._run(lambda b: b.read_meta(graph_id)) or {}
        raw = meta.get('ontology')
        ontology = json.loads(raw) if raw else None
        self._ontology_cache[graph_id] = ontology
        return ontology

    # ---------------------------------------------------------- writes

    def add_text(self, graph_id: str, text: str, *, name: Optional[str] = None,
                 source: str = 'text', source_description: str = 'Forecast document',
                 reference_time: Optional[datetime] = None, timeout: float = 900,
                 retry_delay: float = 5.0) -> Dict[str, Any]:
        """Add one piece of text. Returns when Graphiti has fully processed it."""
        self._require(graph_id)
        entity_types, edge_types, edge_type_map = build_types(self.get_ontology(graph_id))
        kwargs = dict(
            name=name or f'episode-{uuidlib.uuid4().hex[:8]}',
            body=text,
            source=source,
            source_description=source_description,
            reference_time=reference_time or datetime.now(timezone.utc),
            entity_types=entity_types,
            edge_types=edge_types,
            edge_type_map=edge_type_map,
        )

        async def go(b):
            # Graphiti wants one episode per graph at a time.
            lock = self._write_locks.setdefault(graph_id, asyncio.Lock())
            async with lock:
                return await b.add_episode(graph_id, **kwargs)

        last_error = None
        for attempt in range(2):
            try:
                episode_uuid, n_nodes, n_edges = self._run(go, timeout=timeout)
                return {'episode_uuid': episode_uuid, 'node_count': n_nodes, 'edge_count': n_edges}
            except Exception as e:
                last_error = e
                if attempt == 0:
                    logger.warning(f'Adding text to {graph_id} failed ({str(e)[:200]}), retrying once')
                    time.sleep(retry_delay)
        raise last_error

    def add_texts(self, graph_id: str, chunks: List[str], *,
                  progress_callback: Optional[Callable[[str, float], None]] = None,
                  source_description: str = 'Forecast document') -> List[str]:
        total = len(chunks)
        uuids = []
        for i, chunk in enumerate(chunks, start=1):
            result = self.add_text(graph_id, chunk, name=f'chunk-{i:04d}',
                                   source='text', source_description=source_description)
            uuids.append(result['episode_uuid'])
            if progress_callback:
                progress_callback(f'Reading chunk {i} of {total} into the map', i / total if total else 1.0)
        return uuids

    # ---------------------------------------------------------- reads

    def get_all_nodes(self, graph_id: str, max_items: int = 2000, page_size: int = 500) -> List[Dict[str, Any]]:
        self._require(graph_id)
        out, cursor = [], None
        while len(out) < max_items:
            limit = min(page_size, max_items - len(out))
            page = self._run(lambda b: b.list_nodes(graph_id, limit=limit, cursor=cursor))
            out.extend(node_to_dict(n) for n in page)
            if len(page) < limit:
                break
            cursor = page[-1].uuid
        return out

    def get_all_edges(self, graph_id: str, page_size: int = 1000) -> List[Dict[str, Any]]:
        self._require(graph_id)
        out, cursor = [], None
        while True:
            page = self._run(lambda b: b.list_edges(graph_id, limit=page_size, cursor=cursor))
            out.extend(edge_to_dict(e) for e in page)
            if len(page) < page_size:
                break
            cursor = page[-1].uuid
        return out

    def get_node(self, graph_id: str, node_uuid: str) -> Optional[Dict[str, Any]]:
        self._require(graph_id)
        node = self._run(lambda b: b.get_node(graph_id, node_uuid))
        return node_to_dict(node) if node is not None else None

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        self._require(graph_id)
        return [edge_to_dict(e) for e in self._run(lambda b: b.get_node_edges(graph_id, node_uuid))]

    def search(self, graph_id: str, query: str, *, limit: int = 10, scope: str = 'edges',
               reranker: str = 'rrf') -> Dict[str, List[Dict[str, Any]]]:
        if scope not in ('edges', 'nodes', 'both'):
            raise ValueError(f'Unknown search scope: {scope}')
        if reranker not in ('rrf', 'cross_encoder'):
            raise ValueError(f'Unknown reranker: {reranker}')
        self._require(graph_id)
        edges, edge_scores, nodes, node_scores = self._run(
            lambda b: b.search(graph_id, query, scope, reranker, limit))
        edge_dicts = []
        for i, e in enumerate(edges):
            d = edge_to_dict(e)
            d['score'] = edge_scores[i] if i < len(edge_scores) else None
            edge_dicts.append(d)
        node_dicts = []
        for i, n in enumerate(nodes):
            d = node_to_dict(n)
            d['score'] = node_scores[i] if i < len(node_scores) else None
            node_dicts.append(d)
        return {'edges': edge_dicts, 'nodes': node_dicts}

    def token_usage(self) -> Dict[str, Any]:
        self._ensure_started()
        return self._backend.token_usage()


# ============================================================== process-wide store

_store: Optional[GraphStore] = None
_store_lock = threading.Lock()


def get_store() -> GraphStore:
    """The process-wide store, built on first use."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                if not is_configured():
                    raise GraphStoreNotConfigured(
                        'Knowledge map store is not configured: missing ' + ', '.join(missing_config()))
                from .graphiti_backend import create_backend
                _store = GraphStore(backend_factory=create_backend)
                atexit.register(_store.shutdown)
    return _store


def set_store(store: Optional[GraphStore]) -> None:
    """Swap the process-wide store (tests)."""
    global _store
    _store = store
