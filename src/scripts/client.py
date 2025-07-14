import asyncio
import argparse
import json
import os
import shlex
import sys
import traceback
from typing import Dict, List, Any, Optional
from mcp.shared.exceptions import McpError


from fastmcp import Client

async def list_items(client: Client, item_type: Optional[str] = None, verbose: int = 0):
    """List MCP server items of the specified type or all if none specified"""
    if item_type in (None, "all", "tools"):
        tools = await client.list_tools()
        if tools:
            print("Available tools:")
            for tool in tools:
                print(f"  - {tool.name}")
                if verbose > 0:
                    if tool.description:
                        print(multi_indent(tool.description, 8))
                    if verbose > 1:
                        if tool.inputSchema:
                            print("        Input Schema:")
                            print(format_schema(tool.inputSchema, 12))
                        if tool.outputSchema:
                            print("        Output Schema:")
                            print(format_schema(tool.outputSchema, 12))
                    if tool.annotations:
                        print(multi_indent(tool.annotations, 8))
            print()
        elif item_type == "tools":
            print("No tools found")

    if item_type in (None, "all", "prompts"):
        prompts = await client.list_prompts()
        if prompts:
            print("Available prompts:")
            for prompt in prompts:
                print(f"  {prompt.name}")
            print()
        elif item_type == "prompts":
            print("No prompts found")   

    if item_type in (None, "all", "resources"):
        resources = await client.list_resources()
        if resources:
            print("Available resources:")
            for resource in resources:
                print(f"  {resource.name}")
            print()
        elif item_type == "resources":
            print("No resources found")

    if item_type in (None, "all", "templates"):
        templates = await client.list_resource_templates()
        if templates:
            print("Available resource templates:")
            for template in templates:
                print(f"  {template.name}")
            print()
        elif item_type == "templates":
            print("No resource templates found")

def multi_indent(message: str, indent: int = 4) -> str:
    """Indent a multi-line string"""
    return "\n".join([" " * indent + line for line in message.split("\n")])

def format_schema(schema: dict[str, Any], indent: int = 4) -> str:
    """Format a schema for display"""
    schema_str = json.dumps(schema, indent=2)
    return multi_indent(schema_str, indent)
    
async def call_tool(client: Client, tool_name: str, args: list[str] = []):
    """Call an MCP tool with the provided arguments"""
    # Get available tools to validate the tool name
    tools = await client.list_tools()

    # Check for exact match first
    exact_match = next((t for t in tools if t.name == tool_name), None)
    
    if exact_match:
        matched_tool = exact_match
    else:
        # Look for partial matches
        partial_matches = [t for t in tools if tool_name.lower() in t.name.lower()]
        
        if len(partial_matches) == 1:
            # If only one partial match, use it
            matched_tool = partial_matches[0]
        elif len(partial_matches) > 1:
            # Multiple partial matches, show options in a more readable format
            print(f"\nPossible tool matches: {", ".join([match.name for match in partial_matches])}")
            return
        else:
            # No matches at all
            print(f"Error: No tools matching '{tool_name}' found")
            return
    
    # Parse arguments
    if args:
        try:
            parser = argparse.ArgumentParser()
            for param_name, param in matched_tool.inputSchema['properties'].items():
                param_type = None
                if param['type'] == 'integer':
                    param_type = int
                elif param['type'] == 'number':
                    param_type = float
                elif param['type'] == 'boolean':
                    param_type = bool
                elif param['type'] == 'string':
                    param_type = str
                parser.add_argument(param_name, type=param_type)
            
            parsed_args = parser.parse_args(args)
            # print(parsed_args)
            args = {k: v for k, v in vars(parsed_args).items() if v is not None}
        except Exception as e:
            print(f"Error parsing arguments: {e}")
            return
        except argparse.ArgumentError as e:
            print(f"Error parsing arguments: {e}")
            return
    
    try:
        print(f"Calling {matched_tool.name} with arguments: {args}")
        results = await client.call_tool(matched_tool.name, args, timeout=5)
        
        # Print results
        results = results.data
        print("\nResults:")
        if results is None:
            print("No results")
        elif isinstance(results, list):
            for i, result in enumerate(results):
                print(result)
        else:
            print(results)
    except Exception as e:
        print(e)
        # traceback.print_exc()

async def process_command(client: Client, command: str):
    """Process a user command"""
    if not command.strip():
        return True
    
    parts = shlex.split(command)
    cmd = parts[0].lower()
    
    if cmd in ("exit", "quit", "q"):
        return False
    elif cmd in ("ls", "list"):
        verbose = 0
        if len(parts) > 1 and (parts[1].lower() == "-v" or parts[1].lower() == "-vv"):
            verbose = 1 if parts[1].lower() == "-v" else 2
            parts.pop(1)
        if len(parts) > 1:
            await list_items(client, parts[1], verbose)
        else:
            await list_items(client, verbose=verbose)
    elif cmd in ("help", "?"):
        print_help()
    elif cmd == "connect":
        if len(parts) > 1:
            print(f"Connecting to {parts[1]}")
            # Would implement reconnection here
        else:
            print("Usage: connect <url>")
    else:
        # Assume it's a tool name
        tool_name = cmd
        args = parts[1:] if len(parts) > 1 else []
        await call_tool(client, tool_name, args)
    
    return True

def print_help():
    """Print help information"""
    print("\nAvailable commands:")
    print("  ls, list [all|tools|prompts|resources|templates] - List MCP server components")
    print("  <tool_name> [args...] - Call an MCP tool")
    print("  connect <url> - Connect to a different MCP server")
    print("  help - Show this help message")
    print("  exit, quit, q - Exit the program\n")

async def interactive_client(connect_url):
    """Run the interactive MCP client"""
    print(f"Connecting to MCP server at {connect_url}...")

    should_exit = False
    replay_command = None
    
    while not should_exit:
        try:
            async with Client(connect_url, timeout=1) as client:
                print("Connected! Type 'help' for available commands.\n")
                
                if not replay_command:
                    # Initial listing of tools
                    await list_items(client, "tools")
                
                # REPL loop
                while True:
                    try:
                        if replay_command:
                            command = replay_command
                            replay_command = None
                        else:
                            command = input("\nmcp> ")
                            replay_command = command
                        should_continue = await process_command(client, command)
                        replay_command = None

                        if not should_continue:
                            should_exit = True
                            break
                    except KeyboardInterrupt:
                        print("\nUse 'exit' to quit")
                    except EOFError as e:
                        should_exit = True
                        print("\nExiting...")
                        break
                    except McpError as e:
                        print(f"Connection error: reconnecting...")
                        break
                    except RuntimeError as e:
                        print(f"Runtime Error: {e}, {type(e)}")
                        # traceback.print_exc()
                        break
                    except Exception as e:
                        print(f"Error: {e}, {type(e)}")
                        # traceback.print_exc()
                        break
                    except asyncio.CancelledError as e:
                        print("Cancelled")
                        # traceback.print_exc()
                        pass
        except Exception as e:
            if should_exit:
                return 1
    
    return 0

def main():
    parser = argparse.ArgumentParser(description="Interactive MCP client")
    parser.add_argument(
        "--transport", "-t", 
        default="http://localhost:8060/mcp/", 
        help="MCP server URL or path to script file"
    )
    args = parser.parse_args()
    
    transport = args.transport
    
    try:
        return asyncio.run(interactive_client(transport))
    except KeyboardInterrupt:
        print("\nExiting...")
        return 0

if __name__ == "__main__":
    sys.exit(main())