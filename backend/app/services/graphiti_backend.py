"""
The real backend behind graph_store: Graphiti 0.31.2 on FalkorDB.

Every method here is async and must run on graph_store's loop thread; the
FalkorDB connection pool and the Anthropic client belong to that loop.

Pieces:
- FalkorDB: one shared async client; each Forecast graph id is a FalkorDB
  graph. One Graphiti instance per graph, whose driver already points at that
  graph, so Graphiti never has to clone drivers per call.
- LLM: Claude through Graphiti's Anthropic client, with our own SDK client so
  429s are retried (Graphiti's default retries only once) and the base URL is
  fixed (a stray ANTHROPIC_BASE_URL in the environment cannot redirect it).
- Embeddings: a local sentence-transformers model (LocalEmbedder).
- Reranking: a local cross-encoder (LocalCrossEncoder), loaded only the first
  time a search asks for cross-encoder reranking.
"""

import asyncio
import json
import threading
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.graphiti_backend')

META_LABEL = 'ForecastMeta'


# ============================================================== local models

_model_lock = threading.Lock()
_models: Dict[str, Any] = {}


def _load_sentence_model(name: str, kind: str):
    """Load (once per process) a sentence-transformers model by name."""
    key = f'{kind}:{name}'
    with _model_lock:
        if key not in _models:
            from sentence_transformers import CrossEncoder, SentenceTransformer
            logger.info(f'Loading local {kind} model {name}')
            if kind == 'embedder':
                _models[key] = SentenceTransformer(name, device='cpu')
            else:
                _models[key] = CrossEncoder(name, device='cpu')
        return _models[key]


def _embedder_base():
    from graphiti_core.embedder.client import EmbedderClient
    return EmbedderClient


def _cross_encoder_base():
    from graphiti_core.cross_encoder.client import CrossEncoderClient
    return CrossEncoderClient


def make_local_embedder(model_name: str, dim: int):
    """A Graphiti EmbedderClient backed by a local sentence-transformers model."""
    Base = _embedder_base()

    class LocalEmbedder(Base):
        def __init__(self):
            self.model_name = model_name
            self.dim = dim

        def _encode(self, texts: List[str]) -> List[List[float]]:
            model = _load_sentence_model(self.model_name, 'embedder')
            vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True,
                                   batch_size=32, show_progress_bar=False)
            out = [v.tolist() for v in vectors]
            if out and len(out[0]) != self.dim:
                raise ValueError(f'Embedding model {self.model_name} returned {len(out[0])} '
                                 f'dimensions, expected {self.dim} (GRAPHITI_EMBEDDING_DIM)')
            return out

        async def create(self, input_data) -> List[float]:
            if isinstance(input_data, str):
                texts = [input_data]
            else:
                texts = [str(x) for x in input_data]
            vectors = await asyncio.get_running_loop().run_in_executor(None, self._encode, texts[:1])
            return vectors[0]

        async def create_batch(self, input_data_list: List[str]) -> List[List[float]]:
            if not input_data_list:
                return []
            return await asyncio.get_running_loop().run_in_executor(
                None, self._encode, [str(x) for x in input_data_list])

    return LocalEmbedder()


def make_local_cross_encoder(model_name: str):
    """A Graphiti CrossEncoderClient backed by a small local cross-encoder.

    Scores are squashed to 0..1 so Graphiti's default minimum score (0) keeps
    every candidate in order instead of dropping the negative raw logits.
    """
    Base = _cross_encoder_base()

    class LocalCrossEncoder(Base):
        def __init__(self):
            self.model_name = model_name

        def _score(self, query: str, passages: List[str]) -> List[float]:
            import torch
            model = _load_sentence_model(self.model_name, 'reranker')
            scores = model.predict([[query, p] for p in passages], activation_fct=torch.nn.Sigmoid(),
                                   show_progress_bar=False)
            return [float(s) for s in scores]

        async def rank(self, query: str, passages: List[str]):
            if not passages:
                return []
            scores = await asyncio.get_running_loop().run_in_executor(None, self._score, query, passages)
            return sorted(zip(passages, scores), key=lambda x: x[1], reverse=True)

    return LocalCrossEncoder()


def preload_models():
    """Load the embedding model now (used at build time and on start)."""
    _load_sentence_model(Config.GRAPHITI_EMBEDDING_MODEL, 'embedder')


# ============================================================== backend

class GraphitiBackend:
    def __init__(self, falkor_client, llm_client, embedder, cross_encoder, max_coroutines: int):
        self.client = falkor_client
        self.llm_client = llm_client
        self.embedder = embedder
        self.cross_encoder = cross_encoder
        self.max_coroutines = max_coroutines
        self._graphitis: Dict[str, Any] = {}
        self._indexed: set = set()

    # ---------------------------------------------------------- helpers

    def _graphiti(self, graph_id: str):
        g = self._graphitis.get(graph_id)
        if g is None:
            from graphiti_core import Graphiti
            from graphiti_core.driver.falkordb_driver import FalkorDriver
            from graphiti_core.helpers import validate_group_id
            validate_group_id(graph_id)
            driver = FalkorDriver(falkor_db=self.client, database=graph_id)
            g = Graphiti(graph_driver=driver, llm_client=self.llm_client, embedder=self.embedder,
                         cross_encoder=self.cross_encoder, max_coroutines=self.max_coroutines)
            self._graphitis[graph_id] = g
        return g

    def _driver(self, graph_id: str):
        return self._graphiti(graph_id).driver

    async def _query(self, graph_id: str, cypher: str, **params):
        graph = self.client.select_graph(graph_id)
        return await graph.query(cypher, params)

    # ---------------------------------------------------------- graphs

    async def ensure_indices(self, graph_id: str):
        driver = self._driver(graph_id)
        init = getattr(driver, '_init_task', None)
        if init is not None:
            try:
                await init
            except Exception as e:  # pragma: no cover
                logger.debug(f'Background index build: {e}')
        await driver.build_indices_and_constraints()
        self._indexed.add(graph_id)

    async def list_graphs(self) -> List[str]:
        return list(await self.client.list_graphs())

    async def delete_graph(self, graph_id: str):
        g = self._graphitis.pop(graph_id, None)
        if g is not None:
            task = getattr(g.driver, '_init_task', None)
            if task is not None and not task.done():
                task.cancel()
        if graph_id in await self.list_graphs():
            await self.client.select_graph(graph_id).delete()
        self._indexed.discard(graph_id)

    async def write_meta(self, graph_id: str, data: Dict[str, Any]):
        await self._query(graph_id, f'MERGE (m:{META_LABEL} {{key: "forecast"}}) SET m.json = $json',
                          json=json.dumps(data))

    async def read_meta(self, graph_id: str) -> Optional[Dict[str, Any]]:
        if graph_id not in await self.list_graphs():
            return None
        res = await self._query(graph_id, f'MATCH (m:{META_LABEL} {{key: "forecast"}}) RETURN m.json')
        if not res.result_set or not res.result_set[0][0]:
            return None
        return json.loads(res.result_set[0][0])

    # ---------------------------------------------------------- writes

    async def add_episode(self, graph_id: str, *, name, body, source, source_description,
                          reference_time, entity_types, edge_types, edge_type_map):
        from graphiti_core.nodes import EpisodeType
        g = self._graphiti(graph_id)
        result = await g.add_episode(
            name=name,
            episode_body=body,
            source_description=source_description,
            reference_time=reference_time,
            source=EpisodeType(source),
            group_id=graph_id,
            entity_types=entity_types,
            edge_types=edge_types,
            edge_type_map=edge_type_map,
        )
        return result.episode.uuid, len(result.nodes), len(result.edges)

    # ---------------------------------------------------------- reads

    async def list_nodes(self, graph_id: str, limit=None, cursor=None):
        from graphiti_core.nodes import EntityNode
        return await EntityNode.get_by_group_ids(self._driver(graph_id), [graph_id],
                                                 limit=limit, uuid_cursor=cursor)

    async def list_edges(self, graph_id: str, limit=None, cursor=None):
        from graphiti_core.edges import EntityEdge
        from graphiti_core.errors import GroupsEdgesNotFoundError
        try:
            return await EntityEdge.get_by_group_ids(self._driver(graph_id), [graph_id],
                                                     limit=limit, uuid_cursor=cursor)
        except GroupsEdgesNotFoundError:
            return []

    async def get_node(self, graph_id: str, node_uuid: str):
        from graphiti_core.errors import NodeNotFoundError
        from graphiti_core.nodes import EntityNode
        try:
            return await EntityNode.get_by_uuid(self._driver(graph_id), node_uuid)
        except NodeNotFoundError:
            return None

    async def get_node_edges(self, graph_id: str, node_uuid: str):
        from graphiti_core.edges import EntityEdge
        return await EntityEdge.get_by_node_uuid(self._driver(graph_id), node_uuid)

    async def search(self, graph_id: str, query: str, scope: str, reranker: str, limit: int):
        from graphiti_core.search import search_config_recipes as recipes
        from graphiti_core.search.search_config import SearchConfig
        cross = reranker == 'cross_encoder'
        edge_recipe = recipes.EDGE_HYBRID_SEARCH_CROSS_ENCODER if cross else recipes.EDGE_HYBRID_SEARCH_RRF
        node_recipe = recipes.NODE_HYBRID_SEARCH_CROSS_ENCODER if cross else recipes.NODE_HYBRID_SEARCH_RRF
        # Never mutate Graphiti's shared module-level recipes.
        config = SearchConfig(
            edge_config=edge_recipe.edge_config.model_copy(deep=True) if scope in ('edges', 'both') else None,
            node_config=node_recipe.node_config.model_copy(deep=True) if scope in ('nodes', 'both') else None,
            limit=limit,
        )
        g = self._graphiti(graph_id)
        res = await g.search_(query, config=config, group_ids=[graph_id])
        return res.edges, res.edge_reranker_scores, res.nodes, res.node_reranker_scores

    # ---------------------------------------------------------- housekeeping

    def token_usage(self) -> Dict[str, Any]:
        tracker = getattr(self.llm_client, 'token_tracker', None)
        if tracker is None:
            return {'input_tokens': 0, 'output_tokens': 0, 'calls': 0, 'by_prompt': {}}
        usage = tracker.get_usage()
        total = tracker.get_total_usage()
        return {
            'input_tokens': total.input_tokens,
            'output_tokens': total.output_tokens,
            'calls': sum(u.call_count for u in usage.values()),
            'by_prompt': {k: {'calls': u.call_count, 'input_tokens': u.total_input_tokens,
                              'output_tokens': u.total_output_tokens} for k, u in usage.items()},
        }

    async def close(self):
        for g in self._graphitis.values():
            task = getattr(g.driver, '_init_task', None)
            if task is not None and not task.done():
                task.cancel()
        self._graphitis.clear()
        try:
            await self.client.aclose()
        except Exception as e:  # pragma: no cover
            logger.debug(f'FalkorDB close: {e}')


def make_falkor_client(host=None, port=None, username=None, password=None):
    from falkordb.asyncio import FalkorDB
    return FalkorDB(host=host or Config.FALKORDB_HOST, port=port or Config.FALKORDB_PORT,
                    username=username if username is not None else Config.FALKORDB_USERNAME,
                    password=password if password is not None else Config.FALKORDB_PASSWORD)


def make_llm_client():
    from anthropic import AsyncAnthropic
    from graphiti_core.llm_client.anthropic_client import AnthropicClient
    from graphiti_core.llm_client.config import LLMConfig
    sdk = AsyncAnthropic(api_key=Config.GRAPHITI_ANTHROPIC_API_KEY,
                         base_url=Config.GRAPHITI_ANTHROPIC_BASE_URL, max_retries=6)
    config = LLMConfig(api_key=Config.GRAPHITI_ANTHROPIC_API_KEY, model=Config.GRAPHITI_LLM_MODEL,
                       small_model=Config.GRAPHITI_LLM_MODEL, max_tokens=Config.GRAPHITI_LLM_MAX_TOKENS)
    return AnthropicClient(config=config, client=sdk)


async def create_backend() -> GraphitiBackend:
    """Factory used by graph_store; runs on the store's loop thread."""
    client = make_falkor_client()
    backend = GraphitiBackend(
        falkor_client=client,
        llm_client=make_llm_client(),
        embedder=make_local_embedder(Config.GRAPHITI_EMBEDDING_MODEL, Config.GRAPHITI_EMBEDDING_DIM),
        cross_encoder=make_local_cross_encoder(Config.GRAPHITI_RERANK_MODEL),
        max_coroutines=Config.GRAPHITI_MAX_COROUTINES,
    )
    await client.list_graphs()  # fail fast if FalkorDB is unreachable or the password is wrong
    return backend
