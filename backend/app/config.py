"""
Configuration Management
Loads configuration uniformly from the .env file in the project root directory
"""

import os
from dotenv import load_dotenv

# Load .env file from project root directory
# Path: MiroFish/.env (relative to backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # If no .env in root directory, try loading environment variables (for production)
    load_dotenv(override=True)


class Config:
    """Flask configuration class"""
    
    # Flask configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON configuration - disable ASCII escaping so non-ASCII characters display directly (instead of \uXXXX format)
    JSON_AS_ASCII = False
    
    # LLM configuration (unified OpenAI format) — used for simulation, profiles, ontology
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Report-specific LLM (optional) — higher-quality model for report generation only
    # Falls back to main LLM config if not set
    REPORT_LLM_API_KEY = os.environ.get('REPORT_LLM_API_KEY')
    REPORT_LLM_BASE_URL = os.environ.get('REPORT_LLM_BASE_URL')
    REPORT_LLM_MODEL_NAME = os.environ.get('REPORT_LLM_MODEL_NAME')
    
    # Supabase configuration
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY')
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
    # Forecast's tables live in their own section of the shared LangSync Platform database.
    SUPABASE_SCHEMA = os.environ.get('SUPABASE_SCHEMA', 'public')
    
    # Knowledge map store: Graphiti (a library) on a self-hosted FalkorDB.
    # FalkorDB is reached over Railway's private network only.
    FALKORDB_HOST = os.environ.get('FALKORDB_HOST')
    FALKORDB_PORT = int(os.environ.get('FALKORDB_PORT', '6379'))
    FALKORDB_USERNAME = os.environ.get('FALKORDB_USERNAME') or None
    FALKORDB_PASSWORD = os.environ.get('FALKORDB_PASSWORD') or None
    # Claude does the reading (entity and relationship extraction).
    GRAPHITI_ANTHROPIC_API_KEY = os.environ.get('GRAPHITI_ANTHROPIC_API_KEY')
    GRAPHITI_ANTHROPIC_BASE_URL = os.environ.get('GRAPHITI_ANTHROPIC_BASE_URL', 'https://api.anthropic.com')
    GRAPHITI_LLM_MODEL = os.environ.get('GRAPHITI_LLM_MODEL', 'claude-haiku-4-5')
    GRAPHITI_LLM_MAX_TOKENS = int(os.environ.get('GRAPHITI_LLM_MAX_TOKENS', '8192'))
    GRAPHITI_MAX_COROUTINES = int(os.environ.get('GRAPHITI_MAX_COROUTINES', '5'))
    # Embeddings and reranking run locally (sentence-transformers), no key.
    # Never change the embedding model or size once maps exist: stored vectors
    # would no longer match new ones.
    GRAPHITI_EMBEDDING_MODEL = os.environ.get('GRAPHITI_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')
    GRAPHITI_EMBEDDING_DIM = int(os.environ.get('GRAPHITI_EMBEDDING_DIM', '384'))
    GRAPHITI_RERANK_MODEL = os.environ.get('GRAPHITI_RERANK_MODEL', 'cross-encoder/ms-marco-MiniLM-L-6-v2')
    
    # File upload configuration
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # Text processing configuration
    # Graphiti makes several Claude calls per chunk, so chunks are larger than
    # they were with Zep (500 / 50) to keep the number of calls down.
    DEFAULT_CHUNK_SIZE = int(os.environ.get('GRAPH_CHUNK_SIZE', '3000'))
    DEFAULT_CHUNK_OVERLAP = int(os.environ.get('GRAPH_CHUNK_OVERLAP', '200'))
    
    # OASIS simulation configuration
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    
    # OASIS platform available actions configuration
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent configuration
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is not configured")
        if not cls.FALKORDB_HOST:
            errors.append("FALKORDB_HOST is not configured")
        if not cls.GRAPHITI_ANTHROPIC_API_KEY:
            errors.append("GRAPHITI_ANTHROPIC_API_KEY is not configured")
        return errors
