"""
Entity Reading and Filtering Service
Reads nodes from a project's knowledge map (graph_store: Graphiti on FalkorDB)
and filters those matching predefined entity types.

The module and class keep their old Zep-era names so importers did not change.
"""

import time
from typing import Dict, Any, List, Optional, Set, Callable, TypeVar
from dataclasses import dataclass, field

from ..utils.logger import get_logger
from . import graph_store

logger = get_logger('mirofish.zep_entity_reader')

# For generic return type
T = TypeVar('T')


@dataclass
class EntityNode:
    """Entity node data structure"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    # Related edge information
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
    # Related node information
    related_nodes: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
            "related_edges": self.related_edges,
            "related_nodes": self.related_nodes,
        }
    
    def get_entity_type(self) -> Optional[str]:
        """Get entity type (excluding default Entity label)"""
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None


@dataclass
class FilteredEntities:
    """Filtered entity collection"""
    entities: List[EntityNode]
    entity_types: Set[str]
    total_count: int
    filtered_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "entity_types": list(self.entity_types),
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
        }


class ZepEntityReader:
    """
    Entity Reading and Filtering Service
    
    Main functionality:
    1. Read all nodes from the knowledge map
    2. Filter nodes matching predefined entity types (nodes with Labels beyond just Entity)
    3. Get related edges and associated node information for each entity
    """
    
    def __init__(self, store: Optional["graph_store.GraphStore"] = None):
        self.store = store or graph_store.get_store()
    
    def _call_with_retry(
        self, 
        func: Callable[[], T], 
        operation_name: str,
        max_retries: int = 3,
        initial_delay: float = 2.0
    ) -> T:
        """Call func, retrying transient failures with exponential backoff.
        A missing graph is not transient and is raised straight away."""
        last_exception = None
        delay = initial_delay
        
        for attempt in range(max_retries):
            try:
                return func()
            except graph_store.GraphNotFound:
                raise
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Graph {operation_name} attempt {attempt + 1} failed: {str(e)[:100]}, "
                        f"retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Graph {operation_name} failed after {max_retries} attempts: {str(e)}")
        
        raise last_exception
    
    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """All nodes in the graph: uuid, name, labels, summary, attributes"""
        logger.info(f"Fetching all nodes from graph {graph_id}...")
        nodes = self._call_with_retry(lambda: self.store.get_all_nodes(graph_id), "list nodes")
        nodes_data = [{
            "uuid": n["uuid"],
            "name": n["name"],
            "labels": n["labels"],
            "summary": n["summary"],
            "attributes": n["attributes"],
        } for n in nodes]
        logger.info(f"Fetched {len(nodes_data)} nodes total")
        return nodes_data

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """All relationships in the graph"""
        logger.info(f"Fetching all edges from graph {graph_id}...")
        edges = self._call_with_retry(lambda: self.store.get_all_edges(graph_id), "list edges")
        edges_data = [self._edge_summary(e) for e in edges]
        logger.info(f"Fetched {len(edges_data)} edges total")
        return edges_data
    
    @staticmethod
    def _edge_summary(edge: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "uuid": edge["uuid"],
            "name": edge["name"],
            "fact": edge["fact"],
            "source_node_uuid": edge["source_node_uuid"],
            "target_node_uuid": edge["target_node_uuid"],
            "attributes": edge["attributes"],
        }
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        """All relationships touching one node (empty list on failure)"""
        try:
            edges = self._call_with_retry(
                func=lambda: self.store.get_node_edges(graph_id, node_uuid),
                operation_name=f"get node edges (node={node_uuid[:8]}...)"
            )
            return [self._edge_summary(e) for e in edges]
        except Exception as e:
            logger.warning(f"Failed to get edges for node {node_uuid}: {str(e)}")
            return []
    
    def filter_defined_entities(
        self, 
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        Filter nodes matching predefined entity types
        
        Filtering logic:
        - If a node's Labels only contain "Entity", the entity doesn't match our predefined types, skip it
        - If a node's Labels contain labels other than "Entity" and "Node", it matches a predefined type, keep it
        
        Args:
            graph_id: Graph ID
            defined_entity_types: Predefined entity type list (optional, if provided only keep these types)
            enrich_with_edges: Whether to get related edge info for each entity
            
        Returns:
            FilteredEntities: Filtered entity collection
        """
        logger.info(f"Starting entity filtering for graph {graph_id}...")

        # Labels are stored as normalized PascalCase type names; normalize
        # the requested filter the same way so older snake_case ontologies
        # (saved before normalization existed) still match.
        if defined_entity_types:
            from ..utils.naming import to_pascal_case
            defined_entity_types = [to_pascal_case(t) for t in defined_entity_types]

        # Get all nodes
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)
        
        # Get all edges (for subsequent association lookups)
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        
        # Build node UUID to node data mapping
        node_map = {n["uuid"]: n for n in all_nodes}
        
        # Filter matching entities
        filtered_entities = []
        entity_types_found = set()
        
        for node in all_nodes:
            labels = node.get("labels", [])
            
            # Filtering logic: Labels must contain labels other than "Entity" and "Node"
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]
            
            if not custom_labels:
                # Only default labels, skip
                continue
            
            # If predefined types are specified, check for match
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]
            
            entity_types_found.add(entity_type)
            
            # Create entity node object
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )
            
            # Get related edges and nodes
            if enrich_with_edges:
                related_edges = []
                related_node_uuids = set()
                
                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])
                    elif edge["target_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])
                
                entity.related_edges = related_edges
                
                # Get basic info of related nodes
                related_nodes = []
                for related_uuid in related_node_uuids:
                    if related_uuid in node_map:
                        related_node = node_map[related_uuid]
                        related_nodes.append({
                            "uuid": related_node["uuid"],
                            "name": related_node["name"],
                            "labels": related_node["labels"],
                            "summary": related_node.get("summary", ""),
                        })
                
                entity.related_nodes = related_nodes
            
            filtered_entities.append(entity)
        
        logger.info(f"Filtering complete: total nodes {total_count}, matching {len(filtered_entities)}, "
                   f"entity types: {entity_types_found}")
        
        return FilteredEntities(
            entities=filtered_entities,
            entity_types=entity_types_found,
            total_count=total_count,
            filtered_count=len(filtered_entities),
        )
    
    def get_entity_with_context(
        self, 
        graph_id: str, 
        entity_uuid: str
    ) -> Optional[EntityNode]:
        """
        Get a single entity with its full context (edges and related nodes, with retry mechanism)
        
        Args:
            graph_id: Graph ID
            entity_uuid: Entity UUID
            
        Returns:
            EntityNode or None
        """
        try:
            # Get node with retry mechanism
            node = self._call_with_retry(
                func=lambda: self.store.get_node(graph_id, entity_uuid),
                operation_name=f"get node details (uuid={entity_uuid[:8]}...)"
            )
            
            if not node:
                return None
            
            # Get node edges
            edges = self.get_node_edges(graph_id, entity_uuid)
            
            # Get all nodes for association lookup
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}
            
            # Process related edges and nodes
            related_edges = []
            related_node_uuids = set()
            
            for edge in edges:
                if edge["source_node_uuid"] == entity_uuid:
                    related_edges.append({
                        "direction": "outgoing",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "target_node_uuid": edge["target_node_uuid"],
                    })
                    related_node_uuids.add(edge["target_node_uuid"])
                else:
                    related_edges.append({
                        "direction": "incoming",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "source_node_uuid": edge["source_node_uuid"],
                    })
                    related_node_uuids.add(edge["source_node_uuid"])
            
            # Get related node info
            related_nodes = []
            for related_uuid in related_node_uuids:
                if related_uuid in node_map:
                    related_node = node_map[related_uuid]
                    related_nodes.append({
                        "uuid": related_node["uuid"],
                        "name": related_node["name"],
                        "labels": related_node["labels"],
                        "summary": related_node.get("summary", ""),
                    })
            
            return EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=node["labels"],
                summary=node["summary"],
                attributes=node["attributes"],
                related_edges=related_edges,
                related_nodes=related_nodes,
            )
            
        except graph_store.GraphNotFound:
            raise
        except Exception as e:
            logger.error(f"Failed to get entity {entity_uuid}: {str(e)}")
            return None
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> List[EntityNode]:
        """
        Get all entities of a specified type
        
        Args:
            graph_id: Graph ID
            entity_type: Entity type (e.g. "Student", "PublicFigure", etc.)
            enrich_with_edges: Whether to get related edge info
            
        Returns:
            Entity list
        """
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities
