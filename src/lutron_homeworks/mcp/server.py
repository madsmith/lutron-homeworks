import argparse
import asyncio
import importlib.metadata
from fastmcp import FastMCP
import logging
from opentelemetry import trace
import re
import sys
import functools

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

def mcp_tool(*, tags=None):
    def decorator(fn):
        setattr(fn, "__mcp_tool__", True)
        setattr(fn, "__mcp_tool_tags__", tags)
        return fn
    return decorator

class InternalToolError(Exception):
    """Exception raised when an internal tool fails"""
    def __init__(self, original: Exception):
        self.original = original
        
    def __str__(self):
        return f"Internal Tool Error: [{type(self.original).__name__}] {self.original}"

def error_handler(fn):
    """Decorator to catch and log exceptions in MCP tools.
    Preserves function signature for FastMCP compatibility."""
    @functools.wraps(fn)  # This preserves the original function signature
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Internal Tool Error: '{fn.__name__}': [{type(e).__name__}] {e}")
            raise InternalToolError(e)
    return wrapper

class LutronMCPTools:
    def __init__(self, config: LutronConfig, client: LutronHomeworksClient, database: LutronDatabase):
        self.config = config
        self.client = client
        self.database = database


    @tracer.start_as_current_span("register_tools")
    def register_tools(self, server: FastMCP):
        """Register all tools with the MCP server"""
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and getattr(attr, "__mcp_tool__", False):
                tags = getattr(attr, "__mcp_tool_tags__", None)
                server.tool(attr, tags=tags)
    
    @mcp_tool(tags={"debug"})
    @tracer.start_as_current_span("say_hello")
    def say_hello(self) -> str:
        """ Debugging purposes only """
        return "Hello, MCP!"

    #================================================================
    # Database tools
    #================================================================

    @mcp_tool(tags={"database"})
    @error_handler
    @tracer.start_as_current_span("get_areas")
    def get_areas(self) -> list[LutronArea]:
        """
        Get all areas in the Lutron system.
        
        Returns a list of all areas (rooms, floors, etc.) defined in the Lutron database.
        Each area contains information about its Integration ID (IID), name, path in the hierarchy, and 
        related properties.
        
        Returns:
            list[LutronArea]: A list of LutronArea objects representing all areas in the system
        """
        areas = self.database.getAreas()
        return areas

    @mcp_tool(tags={"database", "deprecated"})
    @error_handler
    @tracer.start_as_current_span("get_outputs")
    def get_outputs(self) -> list[LutronOutput]:
        """
        Get all outputs in the Lutron system.
        
        Returns a list of all outputs (lights, shades, etc.) defined in the Lutron database.
        Each output contains information about its Integration ID (IID), name, type, and current state.
        
        Returns:
            list[LutronOutput]: A list of LutronOutput objects representing all outputs in the system
        """
        outputs = self.database.getOutputs()
        return outputs

    @mcp_tool(tags={"database", "deprecated"})
    @error_handler
    @tracer.start_as_current_span("get_output_by_iid")
    def get_output_by_iid(self, iid: int) -> LutronOutput | None:
        """
        Get a specific output by its Integration ID (IID).
        
        Retrieves a single output device (light, shade, etc.) by its unique Integration ID.
        This is useful when you need to access a specific device by its ID rather than
        searching through all outputs.
        
        Args:
            iid (int): The Integration ID of the output to retrieve
            
        Returns:
            LutronOutput | None: The LutronOutput object if found, or None if no output exists with the given IID
        """
        output = self.database.getOutputsByIID(iid)
        return output


    @mcp_tool(tags={"database"})
    @error_handler
    @tracer.start_as_current_span("get_custom_output_subtypes")
    def get_custom_output_subtypes(self) -> list[str]:
        """
        Get a list of all custom output subtypes.
        
        Retrieves a list of all custom output subtypes defined in the Lutron database.
        This is useful when you need to access all custom output subtypes in the system.
        
        Returns:
            list[str]: A list of custom output subtypes
        """
        type_map = self.config.type_map

        return list(type_map.keys())
        
    
    @mcp_tool(tags={"database"})
    @error_handler
    @tracer.start_as_current_span("get_outputs_by_subtype")
    def get_outputs_by_subtype(self, subtype: str) -> list[LutronOutput]:
        """
        Get all outputs of a specific subtype.
        
        Retrieves a list of all outputs (lights, shades, etc.) of a specific subtype.
        This is useful when you need to access all outputs of a specific type.
        
        Args:
            subtype (str): The subtype of the output to retrieve
            
        Returns:
            list[LutronOutput]: A list of LutronOutput objects representing all outputs of the specified subtype
        """
        subtype = self._normalize_subtype(subtype)
        self._validate_subtype(subtype)
        
        outputs = self.database.getOutputsByType(subtype)
        return outputs

    @mcp_tool(tags={"database", "search"})
    @error_handler
    @tracer.start_as_current_span("find_outputs_by_subtype")
    def find_outputs_by_subtype(self, subtype: str, name: str) -> list[LutronOutput]:
        """
        Find outputs in the database by subtype and name. Returns any outputs that match the sequence
        of words in the name.  Fuzzy matching against a limited list of synonyms is
        also applied in the search.

        Args:
            subtype (str): The subtype of the output to retrieve
            name (str): The name to search for

        Returns:
            list[LutronOutput]: A list of LutronOutput objects representing the 
            outputs that match the search, or an empty list if no matches are found
        """
        subtype = self._normalize_subtype(subtype)
        self._validate_subtype(subtype)

        return self._do_search(name, self.database.getOutputsByType(subtype))

    @mcp_tool(tags={"database", "deprecated"})
    @error_handler
    @tracer.start_as_current_span("get_entities")
    def get_entities(self) -> list[LutronEntity]:
        """
        Get all entities in the Lutron system.
        
        Returns a list of all entities (areas, outputs, keypads, etc.) defined in the Lutron database.
        This is the most comprehensive view of all items in the system, including areas, outputs,
        and other device types.
        
        Returns:
            list[LutronEntity]: A list of LutronEntity objects representing all entities in the system
        """
        entities = self.database.getEntities()
        
        return entities

    @mcp_tool(tags={"database", "search"})
    @error_handler
    @tracer.start_as_current_span("find_area_by_area_name")
    def find_areas_by_area_name(self, name: str) -> list[LutronArea]:
        """
        Find areas in the database by name of area (including heirarchical areas like floors). Returns
        any areas that match the sequence of words in the name.  Fuzzy matching against a limited list
        of synonyms is also applied in the search.

        Args:
            name (str): The name to search for

        Returns:
            list[LutronArea]: A list of LutronArea objects representing the 
            areas that match the search, or an empty list if no matches are found
        """
        return self._do_search(name, self.database.getAreas())

    @mcp_tool(tags={"database", "search"})
    @error_handler
    @tracer.start_as_current_span("find_output_by_output_name")
    def find_outputs_by_output_name(self, name: str) -> list[LutronOutput]:
        """
        Find outputs in the database by name of output (including heirarchical entities like areas
        names and floor names). Returns any outputs that match the sequence of words in the name.
        Fuzzy matching against a limited list of synonyms is also applied in the search.

        Args:
            name (str): The name to search for

        Returns:
            list[LutronOutput]: A list of LutronOutput objects representing the 
            outputs that match the search, or an empty list if no matches are found
        """
        return self._do_search(name, self.database.getOutputs())

    #================================================================
    # Lutron Server tools
    #================================================================

    @mcp_tool(tags={"control", "output"})
    @error_handler
    @tracer.start_as_current_span("get_output_level")
    async def get_output_level(self, iid: int) -> float:
        """
        Get the current level of an output device.

        Args:
            iid (int): The Integration ID of the output to retrieve

        Returns:
            float: The current level of the output as a float between 0 and 100
        """
        output = self.database.getOutputsByIID(iid)
        if output is None:
            raise RuntimeError(f"Output {iid} not found")
        
        command = OutputCommand.get_zone_level(iid)
        response = await self.client.execute_command(command)
        return response.data

    @mcp_tool(tags={"control", "output"})
    @error_handler
    @tracer.start_as_current_span("set_output_level")
    async def set_output_level(self, iid: int, level: float):
        """
        Set the level of an output device.

        Args:
            iid (int): The Integration ID of the output to set
            level (float): The level to set the output to as a float between 0 and 100
        """
        # Verify the output exists
        output = self.database.getOutputsByIID(iid)
        if output is None:
            raise RuntimeError(f"Output {iid} not found")
        
        self._validate_level(level)
        
        # Set the output level
        command = OutputCommand.set_zone_level(iid, level)
        
        await self.client.execute_command(command)

    @mcp_tool(tags={"control", "area"})
    @error_handler
    @tracer.start_as_current_span("get_area_level")
    async def get_area_level(self, area_id: int):
        """
        Get the level of an "Area".  The "Area" is a group of outputs that are controlled together.
        Generally it represents a room or zone in the home.  The result is the average level of all
        outputs in the area.
        
        Args:
            area_id: The IntegrationID of the area
            
        Returns:
            dict: Containing the "average_level" and "outputs" keys where "average_level" is the 
            average level of all outputs in the area and "outputs" is a list of output objects
            with the "iid" and "level" keys
        """
        # area = self.database.getAreasById(area_id)
        # if area is None:
        #     raise RuntimeError(f"Area {area_id} not found")

        # outputs = self.database.getOutputs()
        # values = []
        # for output in outputs:
        #     if output.parent_db_id == area_id:
        #         values.append(output.level)
        
        
        command = AreaCommand.get_zone_level(area_id)
        response = await self.client.execute_command(command)

        return response

    @mcp_tool(tags={"control", "area"})
    @error_handler
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

        await self.client.execute_command(command)

    #================================================================
    # Internal functions
    #================================================================
    
    def _validate_level(self, level: float):
        if level < 0 or level > 100:
            raise ValueError(f"Level {level} is not between 0 and 100")

    def _normalize_subtype(self, subtype: str) -> str:
        return subtype.lower()
    
    def _validate_subtype(self, subtype: str):
        type_map = self.config.type_map
        if subtype not in type_map:
            raise ValueError(f"Invalid subtype: {subtype}. Valid subtypes are: {type_map.keys()}")

    def _build_search_re(self, name: str) -> re.Pattern:
        synonyms = self.config.synonyms
        normalized_synonyms = [
            set(synonym.lower() for synonym in synonym_set)
            for synonym_set in synonyms
        ]
        def build_part_pattern(part: str) -> str:
            for synonym_set in normalized_synonyms:
                if part in synonym_set:
                    # Build a regex pattern that matches any of the synonyms
                    escaped_synonyms = [re.escape(synonym) for synonym in synonym_set]
                    return f"({'|'.join(escaped_synonyms)})"
            return part
        
        name_normalized = name.lower()

        name_parts = name_normalized.split(" ")

        name_pattern = ""
        for part in name_parts:
            part_pattern = build_part_pattern(part)
            name_pattern += f".*{part_pattern}"
        if name_pattern:
            name_pattern += ".*"
        
        return re.compile(name_pattern)

    def _do_search(self, name: str, objects: list[LutronEntity]) -> list[LutronEntity]:
        results = []

        # Build the regex pattern
        name_re = self._build_search_re(name)

        for entity in objects:
            if name_re.match(entity.path.lower()):
                results.append(entity)
        
        return results


@tracer.start_as_current_span("run_server")
async def run_server(args):
    server = FastMCP(
        "mcp-lutron-homeworks",
        instructions="""
        mcp-lutron-homeworks is a suite of tools as an MCP server allowing for the control
        of a Lutron Homeworks home automation server. Allowing for the control of lights,
        fans, shades and other devices/outputs and areas in the home.
        """,
        version=version,
        include_tags={"control", "database", "search"},
        exclude_tags={"deprecated"}
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

    # Apply custom type map to database
    with tracer.start_as_current_span("apply_custom_type_map"):
        if config.type_map:
            database.apply_custom_type_map(config.type_map)

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

    tools = LutronMCPTools(config, client, database)

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
        await server.run_async(transport, show_banner=False, **transport_kwargs)
