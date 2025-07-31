import asyncio
import logging
import sys
from typing import Dict, List, Callable, Any, Optional, Tuple
from unittest.mock import MagicMock
from asyncio import IncompleteReadError

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    stream=sys.stdout,
)

import pytest
import pytest_asyncio

from lutron_homeworks.client import LutronHomeworksClient
from lutron_homeworks.types import LutronSpecialEvents

logger = logging.getLogger(__name__)


class MockLutronServer:
    """A mock Lutron Homeworks server for testing"""
    
    def __init__(self, host='127.0.0.1', port=0):
        self.host = host
        self.port = port  # 0 means OS will assign a free port
        self.server = None
        self.clients = []
        self.command_responses = {}
        self.login_timeout = None
        self.command_timeout = None
        self.disconnect_after_n_commands = None
        self.command_count = 0
        self.should_fail_connection = False
        self.login_attempts = 0
        self.expected_username = "default"
        self.expected_password = "default"

    async def start(self):
        """Start the mock server"""
        self.server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        # Get the assigned port if we used 0
        if self.port == 0:
            for sock in self.server.sockets:
                self.port = sock.getsockname()[1]
                break
        
        logger.info(f"Mock Lutron server started on {self.host}:{self.port}")
        return self

    def add_command_response(self, command: str, response: str):
        """Add a command response to the server"""
        self.command_responses[command] = response

    def set_login_timeout(self, seconds: int):
        """Set a timeout during login to simulate slow response"""
        self.login_timeout = seconds

    def set_command_timeout(self, seconds: int):
        """Set a timeout for command responses to simulate slow response"""
        self.command_timeout = seconds

    def set_disconnect_after_commands(self, count: int):
        """Set server to disconnect after n commands"""
        self.disconnect_after_n_commands = count

    def set_fail_connection(self, should_fail: bool):
        """Set whether the server should refuse connections"""
        self.should_fail_connection = should_fail

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a client connection"""
        if self.should_fail_connection:
            writer.close()
            await writer.wait_closed()
            return

        self.clients.append((reader, writer))
        addr = writer.get_extra_info('peername')
        logger.info(f"Client connected from {addr}")
        
        try:
            # Login sequence
            writer.write(b"login: ")
            await writer.drain()
            
            if self.login_timeout:
                await asyncio.sleep(self.login_timeout)
            
            username = await reader.readuntil(b"\r\n")
            username = username.decode('ascii').strip()
            
            writer.write(b"password: ")
            await writer.drain()
            
            password = await reader.readuntil(b"\r\n")
            password = password.decode('ascii').strip()
            
            self.login_attempts += 1
            if username == self.expected_username and password == self.expected_password:
                # Login successful
                writer.write(b"QNET>")
                await writer.drain()
                
                # Process commands
                while not reader.at_eof():
                    try:
                        data = await reader.readuntil(b"\r\n")
                        print(f"READ: {data}")
                        cmd = data.decode('ascii').strip()
                        
                        if cmd == "":
                            writer.write(b"QNET>")
                            await writer.drain()
                            continue
                        
                        # Handle logout command specially
                        if cmd.lower() == "logout":
                            logger.info(f"Server received logout command: {cmd}")
                            break  # Exit the command loop which will close the connection
                        
                        self.command_count += 1
                        
                        # Check if we should disconnect
                        if self.disconnect_after_n_commands and self.command_count >= self.disconnect_after_n_commands:
                            logger.info(f"Disconnecting after {self.command_count} commands")
                            break
                        
                        # Process command
                        if self.command_timeout:
                            logger.debug(f"Waiting for command to complete with timeout: {self.command_timeout} seconds")
                            await asyncio.sleep(self.command_timeout)
                        
                        # Get response for command
                        response = self.command_responses.get(cmd, f"ERROR,Unknown command: {cmd}")
                        writer.write(f"{response}\r\nQNET>".encode('ascii'))
                        await writer.drain()
                        
                    except asyncio.IncompleteReadError:
                        break
            else:
                # Login failed
                writer.write(b"Login failed\r\n")
                await writer.drain()
        except IncompleteReadError:
            pass
        except Exception as e:
            logger.error(f"Error handling client: {e}")
            import traceback
            traceback.print_exc()
        finally:
            writer.close()
            await writer.wait_closed()
            if (reader, writer) in self.clients:
                self.clients.remove((reader, writer))
            logger.info(f"Client disconnected from {addr}")

    def disconnect_all_clients(self):
        """Force disconnect all clients"""
        for _, writer in self.clients:
            writer.close()

    async def stop(self):
        """Stop the mock server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("Mock Lutron server stopped")


@pytest_asyncio.fixture()
async def mock_lutron_server():
    """Fixture to provide a mock Lutron server"""
    server = MockLutronServer()
    await server.start()
    
    # Add some default command responses
    server.add_command_response("?SYSTEM,1", "~SYSTEM,1,2")
    server.add_command_response("?OUTPUT,1", "~OUTPUT,1,1,100")
    
    yield server
    
    await server.stop()


@pytest_asyncio.fixture()
async def lutron_client():
    # Setup the client
    host = "10.0.0.91"
    port = 23
    username = "default"
    password = "default"
    keepalive_interval = 10

    logger.info("Creating Lutron client...")
    client = LutronHomeworksClient(
        host=host,
        username=username,
        password=password,
        port=port,
        keepalive_interval=keepalive_interval,
    )
    
    yield client
    
    # Cleanup after tests
    await client.close()
    await asyncio.sleep(0.1)  # Allow server to process closure


class TestLutronClient:
    
    @pytest.mark.asyncio
    async def test_connect_and_command(self, lutron_client: LutronHomeworksClient):
        logger.debug("Connecting to Lutron server...")
        await lutron_client.connect()
        assert lutron_client.connected, "Should connect successfully to Lutron server"

        system_response_holder = {}
        lutron_client.subscribe('system_response', lambda data: system_response_holder.update(data))

        await lutron_client.send_raw('?SYSTEM,1')
        await asyncio.sleep(0.5)  # Wait for any responses/keepalive
        
        print(system_response_holder)

    @pytest.mark.skip()
    @pytest.mark.asyncio
    async def test_monitor_events_for_duration(self, lutron_client: LutronHomeworksClient):
        await lutron_client.connect()
        assert lutron_client.connected, "Should connect successfully to Lutron server"
        
        await asyncio.sleep(30)  # Wait for any responses/keepalive


class TestLutronClientMockedServer:
    
    @pytest_asyncio.fixture
    async def mocked_client(self, mock_lutron_server: MockLutronServer):
        # Create a client that connects to our mock server
        client = LutronHomeworksClient(
            host=mock_lutron_server.host,
            port=mock_lutron_server.port,
            username="default",
            password="default",
            keepalive_interval=1  # Short keepalive for faster tests
        )
        
        yield client
        
        # Cleanup
        await client.close()
    
    @pytest.mark.asyncio
    async def test_connect_to_mock_server(self, mocked_client: LutronHomeworksClient, mock_lutron_server: MockLutronServer):
        # Test basic connection to our mock server
        await mocked_client.connect()
        assert mocked_client.connected, "Client should connect to mock server"
        assert mocked_client.command_ready, "Client should be ready to send commands"
        assert mock_lutron_server.login_attempts == 1, "Server should record login attempt"
    
    @pytest.mark.asyncio
    async def test_command_response(self, mocked_client: LutronHomeworksClient, mock_lutron_server: MockLutronServer):
        # Test sending commands and receiving responses
        await mocked_client.connect()
        assert mocked_client.connected, "Client should connect to mock server"
        
        response = None
        def response_handler(data: list):
            nonlocal response
            print(f"Received response: {data}")
            response = data

        def print_event_handler(data: list):
            print(f"Received event: {data}")
        
        mocked_client.subscribe('SYSTEM', response_handler)
        mocked_client.subscribe(LutronSpecialEvents.AllEvents.value, print_event_handler)
        
        # Add a specific response for our test command
        mock_lutron_server.add_command_response("?SYSTEM,2", "~SYSTEM,2,MockTest")
        
        # Send command
        await mocked_client.send_raw("?SYSTEM,2")
        await asyncio.sleep(.5)  # Brief wait for response
        
        print("RESPONSE: ", response)
        assert response is not None, "Response should not be None"
        assert response[0] == 2, "Response should have action 2"
        assert response[1] == 'MockTest', "Response should match our mock data"
    
    @pytest.mark.asyncio
    async def test_server_disconnect(self, mocked_client: LutronHomeworksClient, mock_lutron_server: MockLutronServer):
        # Test client handling server disconnect
        await mocked_client.connect()
        assert mocked_client.connected, "Client should connect to mock server"
        assert mocked_client.command_ready, "Client should be ready for commands"
        
        # Simulate server disconnect after 2 commands
        mock_lutron_server.set_disconnect_after_commands(2)
        
        # Send a couple of commands to trigger disconnect
        await mocked_client.send_raw("?SYSTEM,1")
        await mocked_client.send_raw("?SYSTEM,2")
        
        # Wait for disconnect detection in client's internal loop
        # The client's reader task should detect the disconnection
        for _ in range(10):  # Try for up to 5 seconds (0.5s * 10)
            await asyncio.sleep(0.5)
            if not mocked_client.connected:
                break
        
        # Client should detect the disconnection
        assert not mocked_client.connected, "Client should detect server disconnection"
        assert not mocked_client.command_ready, "Client should not be ready for commands after disconnect"
    
    @pytest.mark.asyncio 
    async def test_connection_timeout(self, mocked_client: LutronHomeworksClient, mock_lutron_server: MockLutronServer):
        # Test client handling slow login response
        mock_lutron_server.set_login_timeout(3)  # 5 second login delay
        
        # Set shorter timeout on client
        mocked_client._read_timeout = 1  # Timeout after 1 second
        
        # Attempt connection - should fail due to timeout
        await mocked_client.connect()
        
        assert not mocked_client.connected, "Client should fail to connect due to timeout"
    
    
    @pytest.mark.asyncio
    async def test_logout_command(self, mocked_client: LutronHomeworksClient, mock_lutron_server: MockLutronServer):
        # Test client properly handling logout command
        await mocked_client.connect()
        assert mocked_client.connected, "Client should connect to mock server"
        
        # Logout the client
        await mocked_client.close()
        
        # Wait for disconnect to be detected
        await asyncio.sleep(0.5)
        
        # Client should register as disconnected
        assert not mocked_client.connected, "Client should disconnect after logout"
    