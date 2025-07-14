import asyncio
import datetime
import logging
import sys
from pathlib import Path
import pytest
import pytest_asyncio
from omegaconf import DictConfig, ListConfig, OmegaConf

from lutron_homeworks.commands.system import SystemCommand, SystemAction
from lutron_homeworks.client import LutronHomeworksClient


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


@pytest.mark.asyncio
async def test_manual_system_command(lutron_client):
    """Test manually forming a SystemCommand and executing it with the client"""
    # Manually create a system command for getting time (action 1)
    cmd = SystemCommand(action=SystemAction.TIME)
    
    # Print details about the command
    print(f"Command type: {cmd.command_type}")
    print(f"Command action: {cmd.action}")
    print(f"Formatted command: {cmd.formatted_command}")
    
    # Execute the command against the Lutron client
    print("Executing command...")
    import asyncio
    await asyncio.sleep(3)
    result = await cmd.execute(lutron_client)    
    
    # Print the result
    print(f"Command result: {result}")
    print(f"Result type: {type(result)}")
    
    # Basic assertion to ensure we got a result
    assert result is not None


@pytest.mark.asyncio
async def test_system_get_time(lutron_client):
    """Test SystemCommand.get_time() to get the current system time from a real Lutron system"""
    # Create the system time command
    cmd = SystemCommand.get_time()
    
    # Verify command formatting
    assert cmd.action == SystemAction.TIME
    assert cmd.formatted_command == "?SYSTEM,1"
    
    # Execute the command against a real Lutron system
    print("Executing command...")
    
    result = await cmd.execute(lutron_client)
    print("Result: ", result)
    
    # The result should be a datetime.time object
    assert result is not None
    print(f"Lutron system time: {result}")
    
    # The result should have hour, minute, second components
    assert hasattr(result, 'hour')
    assert hasattr(result, 'minute')
    assert hasattr(result, 'second')


@pytest.mark.asyncio
async def test_system_get_date(lutron_client):
    """Test SystemCommand.get_date() to get the current system date from a real Lutron system"""
    # Create the system date command
    cmd = SystemCommand.get_date()
    
    # Execute the command against a real Lutron system
    result = await cmd.execute(lutron_client)
    
    # The result should be a datetime.date object
    assert result is not None
    print(f"Lutron system date: {result}")
    
    # Verify it has the expected components
    assert hasattr(result, 'year')
    assert hasattr(result, 'month')
    assert hasattr(result, 'day')


@pytest.mark.asyncio
async def test_multiple_system_commands(lutron_client):
    """Test running multiple system commands sequentially"""
    # Get system time
    time_result = await SystemCommand.get_time().execute(lutron_client)
    print(f"System time: {time_result}")
    
    # Get OS revision
    os_rev = await SystemCommand.get_os_rev().execute(lutron_client)
    print(f"OS Revision: {os_rev}")
    
    # Get latitude/longitude
    latlong = await SystemCommand.get_latlong().execute(lutron_client)
    print(f"Lat/Long: {latlong}")
    
    # Everything should have completed successfully
    assert time_result is not None
    # assert os_rev is not None
    assert latlong is not None

@pytest.mark.asyncio
async def test_system_get_os_rev(lutron_client):
    """Test SystemCommand.get_os_rev() to get the current system OS revision from a real Lutron system"""
    # Create the system OS revision command
    cmd = SystemCommand.get_os_rev()
    
    # Execute the command against a real Lutron system
    result = await cmd.execute(lutron_client)
    
    # The result should be a string
    assert result is not None
    print(f"Lutron system OS revision: {result}")
    
    # Verify it has the expected components
    assert isinstance(result, str)
    assert "OS Firmware Revision" in result

@pytest.mark.asyncio
async def test_system_get_timezone(lutron_client):
    """Test SystemCommand.get_timezone() to get the current system timezone from a real Lutron system"""
    # Create the system timezone command
    cmd = SystemCommand.get_timezone()
    
    # Execute the command against a real Lutron system
    result = await cmd.execute(lutron_client)
    
    # The result should be a string
    assert result is not None
    print(f"Lutron system timezone: {result}")
    
    # Verify it has the expected components
    assert isinstance(result, datetime.timedelta)