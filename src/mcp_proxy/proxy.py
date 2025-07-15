import argparse
from fastmcp import FastMCP
from fastmcp.server.proxy import ProxyClient
import sys

from mcp_proxy.config import ProxyConfig

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Bridge remote MCP server to local stdio")
    parser.add_argument("--url", type=str, default=None,
                        help="URL of the remote MCP server, e.g., http://localhost:8060/mcp/")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to the config file")

    args = parser.parse_args()

    config = ProxyConfig(proxy_url=args.url, config_path=args.config)

    if config.proxy_url is None and not config.mcpServers:
        parser.print_usage()
        return 1

    if config.proxy_url:
        proxy = FastMCP.as_proxy(
            ProxyClient(config.proxy_url),
            name="Remote-to-Local Bridge"
        )
    else:
        mcpConfig = {
            "mcpServers": config.mcpServers
        }
        proxy = FastMCP.as_proxy(
            mcpConfig,
            name="Composite MCP Proxy"
        )
    
    proxy.run()  # Defaults to stdio transport

# Run locally via stdio for Claude Desktop
if __name__ == "__main__":
    sys.exit(main())