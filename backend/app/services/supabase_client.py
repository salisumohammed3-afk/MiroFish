"""
Supabase client singleton for MiroFish backend.
Uses the service_role key for admin operations (bypasses RLS).
"""

from supabase import create_client, Client
from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.supabase')

_client: Client | None = None
_admin_client: Client | None = None


def get_supabase_client() -> Client:
    """Get the public Supabase client (respects RLS when used with user JWT)."""
    global _client
    if _client is None:
        url = Config.SUPABASE_URL
        key = Config.SUPABASE_ANON_KEY
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be configured")
        _client = create_client(url, key)
        logger.info("Supabase public client initialized")
    return _client


def get_supabase_admin() -> Client:
    """Get the admin Supabase client (bypasses RLS via service_role key)."""
    global _admin_client
    if _admin_client is None:
        url = Config.SUPABASE_URL
        key = Config.SUPABASE_SERVICE_ROLE_KEY
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured")
        _admin_client = create_client(url, key)
        logger.info("Supabase admin client initialized")
    return _admin_client
