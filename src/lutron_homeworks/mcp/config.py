from importlib.resources import files
import os
from pathlib import Path
from omegaconf import OmegaConf, DictConfig, ListConfig
from typing import Any

class LutronConfig:
    def __init__(
        self,
        server_host: str | None = None,
        server_port: int | None = None,
        keepalive_interval: int | None = None,
        username: str | None = None,
        password: str | None = None,
        config_path: str | None = None,
        mode: str | None = None,
        listen_host: str | None = None,
        listen_port: int | None = None,
        cache_only: bool | None = None,
        database_address: str | None = None
    ):
        self._server_host: str | None = server_host
        self._server_port: int | None = server_port
        self._keepalive_interval: int | None = keepalive_interval
        self._database_address: str | None = database_address
        self._username: str | None = username
        self._password: str | None = password
        self._mode: str | None = mode
        self._listen_host: str | None = listen_host
        self._listen_port: int | None = listen_port
        self._cache_only: bool | None = cache_only
        self._filters: dict[str, list[list[Any]]] | None = None
        self._synonyms: list[list[str]] | None = None
        self._type_map: dict[str, list[str]] | None = None
        self._config: DictConfig | ListConfig | None = None

        # Load from config file if provided
        config: DictConfig | ListConfig | None = None
        if config_path is not None and Path(config_path).exists():
            config = OmegaConf.load(config_path)
        
        # Look for default config as fallback
        default_path = self.get_config_path()
        if Path(default_path).exists():
            self._config = OmegaConf.load(default_path)
            if config is not None:
                self._config = OmegaConf.merge(config, self._config)
        elif config is not None:
            self._config = config

    @property
    def server_host(self) -> str:
        """Get the Lutron server address"""
        if self._server_host:
            return self._server_host
        server = self._config_get("LUTRON_SERVER", "lutron.server.host")
        return server

    @property
    def server_port(self) -> int:
        """Get the Lutron server port"""
        if self._server_port:
            return self._server_port
        server_port = self._config_get("LUTRON_SERVER_PORT", "lutron.server.port", 23)
        try: 
            return int(server_port)
        except ValueError:
            raise ValueError(f"Invalid server port: {server_port}")
    
    @property
    def username(self) -> str:
        """Get the Lutron username"""
        if self._username:
            return self._username
        username = self._config_get("LUTRON_USERNAME", "lutron.server.username", "default")
        return username
    
    @property
    def password(self) -> str:
        """Get the Lutron password"""
        if self._password:
            return self._password
        password = self._config_get("LUTRON_PASSWORD", "lutron.server.password", "default")
        return password
    
    @property
    def keepalive_interval(self) -> int:
        if self._keepalive_interval:
            return self._keepalive_interval
        keepalive_interval = self._config_get("LUTRON_KEEPALIVE_INTERVAL", "lutron.server.keepalive_interval", 60)
        try:
            return int(keepalive_interval)
        except ValueError:
            raise ValueError(f"Invalid keepalive interval: {keepalive_interval}")

    @property
    def mode(self) -> str:
        if self._mode:
            return self._mode
        mode = self._config_get("LUTRON_SERVER_MODE", "lutron.mcp.mode", "stdio")
        return mode

    @property
    def listen_host(self) -> str:
        if self._listen_host:
            return self._listen_host
        host = self._config_get("LUTRON_MCP_HOST", "lutron.mcp.host", "0.0.0.0")
        return host
    
    @property
    def listen_port(self) -> int:
        if self._listen_port:
            return self._listen_port
        port = self._config_get("LUTRON_MCP_PORT", "lutron.mcp.port", 8060)
        try:
            return int(port)
        except ValueError:
            raise ValueError(f"Invalid listen port: {port}")
    
    @property
    def database_address(self) -> str:
        if self._database_address:
            return self._database_address
        database_address = self._config_get("LUTRON_DATABASE_ADDRESS", "lutron.database.address", self.server_host)
        return database_address

    @property
    def cache_only(self) -> bool:
        if self._cache_only:
            return self._cache_only
        cache_only = self._config_get("LUTRON_CACHE_ONLY", "lutron.database.cache_only", False)
        return bool(cache_only)
    
    @property
    def filters(self) -> dict[str, list[list[Any]]]:
        if self._filters:
            return self._filters
        filters = self._config_get(None, "lutron.database.filters", [])
        assert not isinstance(filters, str), "Filters must be a list of dictionaries"
        return filters

    @property
    def synonyms(self) -> list[list[str]]:
        if self._synonyms:
            return self._synonyms
        synonyms = self._config_get(None, "lutron.database.synonyms", [])
        assert not isinstance(synonyms, str), "Synonyms must be a list of lists of strings"
        return synonyms

    @property
    def type_map(self) -> dict[str, list[str]]:
        if self._type_map:
            return self._type_map
        type_map = self._config_get(None, "lutron.database.type_map", {})
        assert not isinstance(type_map, str), "Type map must be a dictionary"
        return type_map
    
    def _config_get(self, env_key: str | None, config_key: str, default: Any = None):
        if env_key is not None:
            env_val = os.environ.get(env_key)
            if env_val:
                return env_val
        if self._config is not None:
            return OmegaConf.select(self._config, config_key, default=default)
        return default

    def get_config_path(self):
        # First check if environment variable is set
        if "LUTRON_CONFIG" in os.environ:
            return os.environ["LUTRON_CONFIG"]
        
        # Then look in user home directory, default to that if it exists
        user_config = Path.home() / ".config" / "mcp-lutron-homeworks" / "config.yaml"
        if user_config.exists():
            return str(user_config)
        
        # Then look in current directory
        cwd_config = Path.cwd() / "config.yaml"
        if cwd_config.exists():
            return str(cwd_config)
            
        # Finally, fall back to package resource
        try:
            return str(files("lutron_homeworks").joinpath("config.yaml"))
        except (ImportError, FileNotFoundError):
            # If package resource not found, return a default path
            return str(user_config)

