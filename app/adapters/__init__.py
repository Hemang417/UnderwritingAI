# Importing each adapter module triggers its @register_adapter decorator,
# registering it by adapter_key. Nothing else in the app imports these
# modules directly (adapters are looked up by string key at runtime), so
# this package import is what actually populates the registry.
from app.adapters import developer_site, maha_rera  # noqa: F401
