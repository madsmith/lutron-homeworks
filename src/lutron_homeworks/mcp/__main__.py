import asyncio
import argparse
import logging
import sys
import traceback
from lutron_homeworks.mcp.server import version
  
from lutron_homeworks.mcp.server import run_server

logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Lutron Homeworks MCP Server")
    parser.add_argument("--version", "-v", action="version", version=f"%(prog)s v{version}")
    parser.add_argument(
        "--mode", "-m", 
        choices=["stdio", "sse", "http", "streamable-http"],
        default=None,
        help="Server transport mode (default: stdio)")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")
    parser.add_argument("--config", "-c", default="config.yaml", help="Path to config file (default: config.yaml)", metavar="PATH")

    server_group = parser.add_argument_group("MCP Server Mode Options")
    server_group.add_argument("--port", "-p", type=int, default=None, help="Port to run the server on (default: 8060)")
    server_group.add_argument("--host", "-H", default=None, help="Host to run the server on (default: 0.0.0.0)")

    config_group = parser.add_argument_group("Lutron Server Configuration")
    config_group.add_argument("--lutron-server", "-ls", default=None, help="Lutron server (default: empty)", metavar="ADDRESS")
    config_group.add_argument("--lutron-port", "-lp", type=int, default=None, help="Lutron server port (default: 23)")
    config_group.add_argument("--username", "--user", "-U", default=None, help="Lutron username (default: default)")
    config_group.add_argument("--password", "--pass", "-P", default=None, help="Lutron password (default: default)")

    cache_group = parser.add_argument_group("Lutron Database Options")
    cache_group.add_argument("--database-address", default=None, help="Database address (default: empty). If not set, will use Lutron server", metavar="ADDRESS")
    cache_group.add_argument("--cache-only", default=None, action="store_true", help="Cache only (default: false)")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    
    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unhandled Error: {e} [{type(e).__name__}]")
        if args.debug:
            logger.error(traceback.format_exc())
        sys.exit(1)
    

if __name__ == "__main__":
    main()