"""Shared Supabase client construction.

Only this module and the concrete ``Supabase*Source`` classes import the
``supabase`` package - the Protocols in ``adapters/`` stay stdlib-only per the
architecture invariant that only concrete adapters depend on a third-party
client.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Construct (once) a Supabase client from env vars.

    Requires ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` - the service
    role key, never the anon key, since this is a server-only, single-user
    backend (see ``supabase/schema.sql``'s RLS posture).
    """
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)
