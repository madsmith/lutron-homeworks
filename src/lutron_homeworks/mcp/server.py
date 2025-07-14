import argparse
import asyncio
import importlib.metadata
from fastmcp import FastMCP
import logging
from opentelemetry import trace
import sys

from lutron_homeworks.client import LutronHomeworksClient
from lutron_homeworks.commands import AreaCommand, OutputCommand
from lutron_homeworks.mcp.config import LutronConfig
from lutron_homeworks.database.database import LutronDatabase
from lutron_homeworks.database.loader import LutronXMLDataLoader
from lutron_homeworks.database.types import LutronArea, LutronOutput, LutronEntity
from lutron_homeworks.database.filters import FilterLibrary

version = importlib.metadata.version("lutron-homeworks")
tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)

def mcp_tool(fn):
    setattr(fn, "__mcp_tool__", True)
    return fn

class LutronMCPTools:
    def __init__(self, client: LutronHomeworksClient, database: LutronDatabase):
        self.client = client
        self.database = database


    @tracer.start_as_current_span("register_tools")
    def register_tools(self, server: FastMCP):
        """Register all tools with the MCP server"""
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and getattr(attr, "__mcp_tool__", False):
                server.tool(attr)
    
    @mcp_tool
    @tracer.start_as_current_span("say_hello")
    def say_hello(self) -> str:
        return "Hello, MCP!"

    #================================================================
    # Database tools
    #================================================================

    @mcp_tool
    @tracer.start_as_current_span("get_areas")
    def get_areas(self) -> list[LutronArea]:
        areas = self.database.getAreas()
        return areas

    @mcp_tool
    @tracer.start_as_current_span("get_outputs")
    def get_outputs(self) -> list[LutronOutput]:
        outputs = self.database.getOutputs()
        return outputs

    @mcp_tool
    @tracer.start_as_current_span("get_output_by_iid")
    def get_output_by_iid(self, iid: int) -> LutronOutput | None:
        output = self.database.getOutputsByIID(iid)
        return output

    @mcp_tool
    @tracer.start_as_current_span("get_entities")
    def get_entities(self) -> list[LutronEntity]:
        entities = self.database.getEntities()
        for entity in entities:
            print(entity)
        return entities

    #================================================================
    # Lutron Server tools
    #================================================================

    @mcp_tool
    @tracer.start_as_current_span("get_output_level")
    async def get_output_level(self, iid: int):
        output = self.database.getOutputsByIID(iid)
        if output is None:
            raise RuntimeError(f"Output {iid} not found")
        
        command = OutputCommand.get_zone_level(iid)
        response = await self.client.execute_command(command)
        return response.data

    @mcp_tool
    @tracer.start_as_current_span("set_output_level")
    async def set_output_level(self, iid: int, level: int):

        # Verify the output exists
        output = self.database.getOutputsByIID(iid)
        print(output)
        if output is None:
            raise RuntimeError(f"Output {iid} not found")
        
        self._validate_level(level)
        
        # Set the output level
        command = OutputCommand.set_zone_level(iid, level)
        print(command.formatted_command)
        await self.client.execute_command(command)

    @mcp_tool
    @tracer.start_as_current_span("set_area_level")
    async def set_area_level(self, area_id: int, level: int):
        """
        Set the level of an "Area".  The "Area" is a group of outputs that are controlled together.
        Generally it represents a room or zone in the home. 
        
        Args:
            area_id: The IntegrationID of the area
            level: The level to set the area to as a float between 0 and 100
        """
        area = self.database.getAreasById(area_id)
        if area is None:
            raise RuntimeError(f"Area {area_id} not found")
        
        self._validate_level(level)
        
        command = AreaCommand.set_zone_level(area_id, level)
        print(command.formatted_command)
        await self.client.execute_command(command)

    #================================================================
    # Internal functions
    #================================================================
    
    def _validate_level(self, level: int):
        if level < 0 or level > 100:
            raise RuntimeError(f"Level {level} is not between 0 and 100")

@tracer.start_as_current_span("run_server")
async def run_server(args):
    server = FastMCP(
        "mcp-lutron-homeworks",
        instructions="""
        mcp-lutron-homeworks is a suite of tools as an MCP server allowing for the control
        of a Lutron Homeworks home automation server. Allowing for the control of lights,
        fans, shades and other devices/outputs and areas in the home.
        """,
        version=version
    )

    # Load configuration details
    kwargs = {}
    config_map = {
        "lutron_server": "server_host",
        "lutron_port": "server_port",
        "username": "username",
        "password": "password",
        "config": "config_path",
        "mode": "mode",
        "host": "listen_host",
        "port": "listen_port",
    }
    for arg, key in config_map.items():
        if getattr(args, arg):
            kwargs[key] = getattr(args, arg)

    config = LutronConfig(**kwargs)
    
    # Make sure we have a valid server
    server_address = config.server_host

    # Server must be set
    if not server_address:
        logger.error("Missing Lutron Server address")
        raise RuntimeError("Missing Lutron Server address")

    # Initialize the database
    loader = LutronXMLDataLoader(config.database_address, "cache")
    loader.set_cache_only(config.cache_only)
    database = LutronDatabase(loader)

    # Apply filters to database
    with tracer.start_as_current_span("apply_filters"):
        filter_count = 0
        for filter_name, instances in config.filters.items():
            for filter_args in instances:
                filter = FilterLibrary.get_filter(filter_name, filter_args)
                if filter is None:
                    raise RuntimeError(f"Filter {filter_name} not found")
                logger.debug(f"Applying filter {filter_name} with args {filter_args}")
                database.enable_filter(filter_name, filter_args)
                filter_count += 1
        logger.info(f"Applied {filter_count} filters to database")
    
    # Load the database
    with tracer.start_as_current_span("load_database"):
        database.load()

    # Initialize the client
    client = LutronHomeworksClient(
        server_address,
        config.username,
        config.password,
        config.server_port,
    )

    # Connect to the client
    await client.connect()

    tools = LutronMCPTools(client, database)

    # Register all tool functions (to be implemented)
    tools.register_tools(server)
    
    transport = config.mode

    if transport == 'stdio':
        transport_kwargs = {}
    else:
        assert config.listen_host, "Host is required for non-stdio mode"
        assert config.listen_port, "Port is required for non-stdio mode"

        transport_kwargs = {
            "host": config.listen_host,
            "port": config.listen_port,
        }

    with tracer.start_as_current_span("MCP Server"):
        await server.run_async(transport, **transport_kwargs)
