"""
Graph Building Service
Builds a project's knowledge map with Graphiti on FalkorDB (see graph_store.py)
"""

import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from . import graph_store
from .text_processor import TextProcessor


@dataclass
class GraphInfo:
    """Graph information"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class GraphBuilderService:
    """
    Graph Building Service
    Builds and reads knowledge maps through the graph store
    """
    
    def __init__(self, store: Optional["graph_store.GraphStore"] = None):
        self.store = store or graph_store.get_store()
        self.task_manager = TaskManager()
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = Config.DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = Config.DEFAULT_CHUNK_OVERLAP,
        batch_size: int = 1
    ) -> str:
        """
        Build graph asynchronously
        
        Args:
            text: Input text
            ontology: Ontology definition (output from Interface 1)
            graph_name: Graph name
            chunk_size: Text chunk size
            chunk_overlap: Chunk overlap size
            batch_size: Number of chunks per batch
            
        Returns:
            Task ID
        """
        # Create task
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )
        
        # Execute build in background thread
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size)
        )
        thread.daemon = True
        thread.start()
        
        return task_id
    
    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int
    ):
        """Graph building worker thread"""
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message="Starting graph construction..."
            )
            
            # 1. Create graph
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=f"Graph created: {graph_id}"
            )
            
            # 2. Set ontology
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message="Ontology set"
            )
            
            # 3. Split text into chunks
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=f"Text split into {total_chunks} chunks"
            )
            
            # 4. Read every chunk into the map (each call returns once processed)
            self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 70),  # 20-90%
                    message=msg
                )
            )
            
            # 5. Get graph info
            self.task_manager.update_task(
                task_id,
                progress=90,
                message="Retrieving graph info..."
            )
            
            graph_info = self._get_graph_info(graph_id)
            
            # Complete
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })
            
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)
    
    def create_graph(self, name: str) -> str:
        """Create an empty knowledge map and return its id"""
        return self.store.create_graph(name, "MiroFish Social Simulation Graph")
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """Store the map's vocabulary (entity and relationship types) with the map"""
        self.store.set_ontology(graph_id, ontology)
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 1,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """Read chunks into the map one at a time and return their episode uuids.
        
        Graphiti extracts entities and relationships before each call returns,
        so there is no separate wait for processing. batch_size is kept for
        callers written for the old batched API and is ignored.
        """
        return self.store.add_texts(graph_id, chunks, progress_callback=progress_callback)
    
    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """Get graph information"""
        nodes = self.store.get_all_nodes(graph_id)
        edges = self.store.get_all_edges(graph_id)

        # Count entity types
        entity_types = set()
        for node in nodes:
            if node["labels"]:
                for label in node["labels"]:
                    if label not in ["Entity", "Node"]:
                        entity_types.add(label)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types)
        )
    
    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """
        Get complete graph data (with detailed information)
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Dict containing nodes and edges, including timestamps, attributes, and other detailed data
        """
        nodes_data = self.store.get_all_nodes(graph_id)
        edges_data = self.store.get_all_edges(graph_id)

        # Add endpoint names to each relationship for the map view
        node_map = {n["uuid"]: n["name"] for n in nodes_data}
        for edge in edges_data:
            edge["source_node_name"] = node_map.get(edge["source_node_uuid"], "")
            edge["target_node_name"] = node_map.get(edge["target_node_uuid"], "")
        
        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }
    
    def graph_exists(self, graph_id: str) -> bool:
        """Whether the map exists (maps from the old Zep service do not)"""
        return self.store.graph_exists(graph_id)
    
    def delete_graph(self, graph_id: str):
        """Delete graph"""
        self.store.delete_graph(graph_id)
