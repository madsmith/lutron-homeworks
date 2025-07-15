from importlib.resources import files
import os
from pathlib import Path
from omegaconf import OmegaConf, DictConfig, ListConfig
from typing import Any

class ProxyConfig:
    def __init__(
        self,
        proxy_url: str | None = None,
        mcpServers: dict | None = None,
        config_path: str | None = None,
    ):
        self._proxy_url: str | None = proxy_url
        self._mcpServers: dict | None = mcpServers
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
    def proxy_url(self) -> str:
        """Get the remote MCP server URL"""
        if self._proxy_url:
            return self._proxy_url
        server = self._config_get("MCP_PROXY_URL", "mcp-proxy.url")
        return server
        
    @property
    def mcpServers(self) -> dict:
        """Get the MCP servers configuration for composite proxy"""
        if self._mcpServers:
            return self._mcpServers
        
        # Check if we have MCP servers defined in config
        servers = self._config_get(None, "mcpServers", None)

        if servers:
            result = self._deep_copy(servers)
            return result
        
        return None

    
    def _deep_copy(self, obj) -> dict | list:
        if isinstance(obj, dict) or isinstance(obj, DictConfig):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        elif isinstance(obj, list) or isinstance(obj, ListConfig):
            return [self._deep_copy(v) for v in obj]
        else:
            return obj

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
        if "MCP_PROXY_CONFIG" in os.environ:
            return os.environ["MCP_PROXY_CONFIG"]
        
        # Then look in user home directory, default to that if it exists
        user_config = Path.home() / ".config" / "mcp-proxy" / "config.yaml"
        if user_config.exists():
            return str(user_config)
        
        # Then look in current directory
        cwd_config = Path.cwd() / "config.yaml"
        if cwd_config.exists():
            return str(cwd_config)
            
        # Finally, fall back to package resource
        try:
            return str(files("scripts").joinpath("proxy", "config.yaml"))
        except (ImportError, FileNotFoundError):
            # If package resource not found, return a default path
            return str(user_config)

