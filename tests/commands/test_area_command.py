import asyncio
import logging
import random
import sys
import pytest
import pytest_asyncio
from pathlib import Path
from omegaconf import DictConfig, ListConfig, OmegaConf

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

from lutron_homeworks.client import LutronHomeworksClient
from lutron_homeworks.commands import AreaCommand


TEST_IID = 25


@pytest.fixture()
def server_config():
    try:
        config_path = Path(__file__).parent / "server_config.yaml"
        config = OmegaConf.load(config_path)
        yield config
    except Exception as e:
        pytest.skip("Server config (server_config.yaml) not found")

@pytest_asyncio.fixture()
async def lutron_client(server_config: DictConfig | ListConfig):
    """Setup fixture for Lutron client, similar to test_lutron.py"""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        stream=sys.stdout,
    )

    host = server_config.get('host')
    port = int(server_config.get('port', 23))
    username = server_config.get('username')
    password = server_config.get('password')
    keepalive_interval = 10

    client = LutronHomeworksClient(
        host=host,
        username=username,
        password=password,
        port=port,
        keepalive_interval=keepalive_interval,
    )

    await client.connect()
    
    yield client
    
    # Ensure the client is closed after tests
    await client.close()
    await asyncio.sleep(0.1)


# Manual test for executing an OutputCommand directly (can be run in VSCode directly)
@pytest.mark.asyncio
async def test_manual_area_command(lutron_client: LutronHomeworksClient):
    """Test executing an AreaCommand manually to get zone level."""
    # Create the command for IID
    cmd = AreaCommand.get_zone_level(TEST_IID)

    assert cmd.formatted_command == f"?AREA,{TEST_IID},1"
    
    # Execute the command against the Lutron client
    result = await cmd.execute(lutron_client)
    
    # Print the result
    logger.debug(f"Result: {result} [{type(result)}]")
    
    # Return for further inspection
    return result


# Test for getting zone level
@pytest.mark.asyncio
async def test_get_zone_level(lutron_client: LutronHomeworksClient):
    """Test OutputCommand.get_zone_level() to get the current level of a zone (IID)."""
    # Create the output zone level command for IID
    cmd = AreaCommand.get_zone_level(TEST_IID)
    
    # Execute the command against a real Lutron system
    result = await cmd.execute(lutron_client)
    
    # The result should be a float between 0 and 100
    assert result is not None
    logger.debug(f"Zone {TEST_IID} level: {result}")
    
    # Verify it has the expected components
    assert isinstance(result, dict)
    assert "average_level" in result
    assert "outputs" in result
    assert 0 <= result["average_level"] <= 100
    assert len(result["outputs"]) > 0
    for output in result["outputs"]:
        assert "iid" in output
        assert "level" in output
        assert isinstance(output["iid"], int)
        assert isinstance(output["level"], float)


# Check for the format of a set_level command without executing it
@pytest.mark.asyncio
async def test_set_zone_level_format():
    """Test OutputCommand.set_zone_level() to set the level of a zone (IID)."""
    cmd = AreaCommand.set_zone_level(TEST_IID, 50.0)
    
    assert f"#AREA,{TEST_IID},1,50.0" in cmd.formatted_command

@pytest.mark.asyncio
async def test_set_zone_level(lutron_client: LutronHomeworksClient):
    """Test AreaCommand.set_zone_level() to set the level of a zone (IID)."""
    # Create the output zone level command for IID
    target_level = random.randint(0, 100)

    # Create the output zone level command for IID
    cmd = AreaCommand.set_zone_level(TEST_IID, target_level)
    
    # Execute the command against a real Lutron system
    result = await cmd.execute(lutron_client)
    
    # The result should be a float between 0 and 100
    assert result is not None
    logger.debug(f"Zone {TEST_IID} level: {result}")
    
    # Verify it has the expected components
    assert isinstance(result, dict)
    assert "average_level" in result
    assert result["average_level"] is not None
    assert "outputs" in result
    assert 0 <= result["average_level"] <= 100
    assert len(result["outputs"]) > 0
    for output in result["outputs"]:
        assert "iid" in output
        assert "level" in output
        assert isinstance(output["iid"], int)
        assert isinstance(output["level"], float)

# Test for setting zone level
@pytest.mark.asyncio
async def test_set_and_get_zone_level(lutron_client: LutronHomeworksClient):
    """Test setting and then getting a zone level to verify the change."""
    # Create the commands for IID
    
    # First get current level
    get_cmd = OutputCommand.get_zone_level(TEST_IID)
    original_level = await get_cmd.execute(lutron_client)
    logger.debug(f"Original level of zone {TEST_IID}: {original_level}")
    
    # Set to a different level (50% if original wasn't 50%, otherwise 25%)
    new_level = 75.0 if original_level != 75.0 else 25.0
    set_cmd = OutputCommand.set_zone_level(TEST_IID, new_level)
    await set_cmd.execute(lutron_client)
    logger.debug(f"Set zone {TEST_IID} to level: {new_level}")
    
    # Wait a moment for command to take effect
    await asyncio.sleep(2)
    
    # Get level again to verify
    get_cmd = OutputCommand.get_zone_level(TEST_IID)
    updated_level = await get_cmd.execute(lutron_client)
    logger.debug(f"Updated level of zone {TEST_IID}: {updated_level}")
    
    # Verify level was set (allow small tolerance for floating point)
    assert abs(updated_level - new_level) < 0.1
    
    # Set back to original level
    set_cmd = OutputCommand.set_zone_level(TEST_IID, original_level)
    await set_cmd.execute(lutron_client)
    logger.debug(f"Restored zone {TEST_IID} to original level: {original_level}")
