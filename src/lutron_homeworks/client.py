import asyncio
import logging
from opentelemetry import trace
import re
from typing import TYPE_CHECKING, Any, List

from .utils.events import EventBus, EventT, SubscriptionToken
from .types import LutronSpecialEvents
from .constants import *

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)

RE_IS_INTEGER = re.compile(r"^\-?\d+$")
RE_IS_FLOAT = re.compile(r"^\-?\d+\.\d+$")

if TYPE_CHECKING:
    from lutron_homeworks.commands import LutronCommand

class LutronHomeworksClient:
    def __init__(self, host, username=None, password=None, port=23, keepalive_interval=60):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.keepalive_interval = keepalive_interval

        self._reader = None
        self._writer = None
        self.connected = False
        self.command_ready = False
        self._keepalive_task = None
        self._output_emitter_task = None
        self._reconnect_task = None

        self._read_timeout = 2
        self._write_timeout = 2
        self._idle_read_timeout = 0.2

        self._eventbus = EventBus()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._reconnect_event = asyncio.Event()

    @property
    def reader(self):
        assert self._reader is not None, "Connection not established. Call connect() first."
        return self._reader

    @property
    def writer(self):
        assert self._writer is not None, "Connection not established. Call connect() first."
        return self._writer
    
    @tracer.start_as_current_span("Connect")
    async def connect(self) -> bool:
        async with self._lock:
            self.logger.info(f"Connecting to {self.host}:{self.port}")
            try:
                self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
                self.connected = True
                await self._login()
                self._start_keepalive()
                self._start_output_emitter()
            except Exception as e:
                self.logger.error(f"Connection failed: {e}")
                self.connected = False
                self.command_ready = False
                self._reconnect_later()
        return self.connected

    @tracer.start_as_current_span("Login")
    async def _login(self):
        try:
            if self.username is None or self.password is None:
                raise ValueError("Username and password must be provided.")

            self.logger.debug("Waiting for login prompt...")
            with tracer.start_as_current_span("Find Login Prompt"):
                data = await self._read_until(b"login: ")
                self.logger.debug("Sending Username")
                await self._write(self.username + LINE_END)

            with tracer.start_as_current_span("Find Password Prompt"):
                data = await self._read_until(b"password: ")
                self.logger.debug("Sending Password")
                await self._write(self.password + LINE_END)

            with tracer.start_as_current_span("Reading Command Ready Prompt"):
                await self._read_prompt()

            # Reset the command prompt once after logging in to discard
            # any residual data from the login process (like a \0 char
            # that is showing up attached to the first prompt)
            await self._write("\r\n")
            with tracer.start_as_current_span("Reading Command Ready Prompt 2"):
                await self._read_prompt()
            
            self.logger.debug("Login complete.")
            self.command_ready = True
        except Exception as e:
            self.logger.error(f"Login failed: {e}")
            self.connected = False
            self.command_ready = False
            self._reconnect_later()

    async def _read_until(self, end_bytes: bytes, timeout: float | None = None):
        """Read until the given prompt or timeout."""

        if timeout is None:
            timeout = self._read_timeout
        
        prompt_bytes = PROMPT.encode('ascii')

        buf = b""
        try:
            while not buf.endswith(end_bytes):
                chunk = await asyncio.wait_for(self.reader.read(1), timeout=timeout)
                if not chunk:
                    raise ConnectionError("Connection closed by server.")

                buf += chunk
                # self.logger.debug(f"<< CHUNK READ: {chunk} [{len(chunk)}]")
                if buf.endswith(prompt_bytes):
                    # Remove the prompt from end of buffer
                    # self.logger.debug(f"Discarding prompt... [{prompt_bytes}]")
                    # buf = buf[:-len(prompt_bytes)]
                    break

            self.logger.debug(f"<< {buf.rstrip()}")

            return buf
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting for prompt: {end_bytes}")

    async def _read_line(self, timeout: float | None = None):
        return await self._read_until(LINE_END.encode('ascii'), timeout=timeout)

    async def _read_prompt(self, timeout: float | None = None):
        prompt_bytes = PROMPT.encode('ascii')
        return await self._read_until(prompt_bytes, timeout=timeout)
    
    async def _write(self, data: str, timeout: float | None = None):
        """Write data to the server with an optional timeout.
        
        Args:
            data: The string data to write
            timeout: Maximum time to wait for the write operation to complete
                    (uses self._read_timeout if None)
                    
        Raises:
            TimeoutError: If the write operation times out
        """
        if timeout is None:
            timeout = self._write_timeout
            
        self.logger.debug(f">> {data.rstrip()}")
        self.writer.write(data.encode('ascii'))
        
        try:
            # Use wait_for to add timeout to drain operation
            await asyncio.wait_for(self.writer.drain(), timeout=timeout)
        except asyncio.TimeoutError:
            self.logger.error(f"Write operation timed out after {timeout} seconds")
            raise TimeoutError(f"Write operation timed out after {timeout} seconds")

    def _start_output_emitter(self):
        if self._output_emitter_task and not self._output_emitter_task.done():
            return

        self._output_emitter_task = asyncio.create_task(
            self._output_emitter_loop(),
            name="Lutron-OutputEmitter",
        )
    
    async def _output_emitter_loop(self):
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(0) # Yield to other tasks before reading
                output = await self._read_line(timeout=0.1)

                event, data = self._parse_output(output)
                if event is None:
                    self._eventbus.emit(LutronSpecialEvents.NonResponseEvents.value, output)
                    self._eventbus.emit(LutronSpecialEvents.AllEvents.value, output)
                    continue
                self._eventbus.emit(event, data)
                # Re-emit the event in parsed format
                self._eventbus.emit(LutronSpecialEvents.AllEvents.value, data)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                self.logger.error(f"Error reading from server: {e}")
                # import traceback
                # traceback.print_exc()
                self.connected = False
                self.command_ready = False
                await asyncio.sleep(1)
                self._reconnect_later()

    def _parse_output(self, output: bytes):
        line = output.decode('ascii').strip()
        if not line:
            return None, None

        if line.startswith(PROMPT):
            self._eventbus.emit(LutronSpecialEvents.CommandPrompt.value, None)
            return None, None

        if not line.startswith(COMMAND_RESPONSE_PREFIX):
            return None, None
        
        parts = line.split(',')
        event = parts[0][1:]
        data = self._infer_data(parts[1:])

        return event, data
    
    def _infer_data(self, parts: List[str]) -> List[Any]:
        result = []

        for part in parts:
            value: Any = part
            if RE_IS_INTEGER.match(part):
                value = int(part)
            elif RE_IS_FLOAT.match(part):
                value = float(part)
            result.append(value)

        return result
    
    def _start_keepalive(self):
        if self._keepalive_task and not self._keepalive_task.done():
            return
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(),
            name="Lutron-Keepalive",
        )

    async def _keepalive_loop(self):
        while not self._stop_event.is_set():
            await asyncio.sleep(self.keepalive_interval)
            if not self.connected:
                continue
            try:
                await self.send_heartbeat()
            except Exception as e:
                self.logger.warning(f"Keepalive failed: {e}")
                self.connected = False
                self.command_ready = False
                self._reconnect_later()

    @tracer.start_as_current_span("Send Heartbeat")
    async def send_heartbeat(self):
        """Send a keep-alive/heartbeat command. Customize as needed."""
        self.logger.debug("Sending heartbeat...")
        # Example: await self.send_raw('NOOP')
        pass

    @tracer.start_as_current_span("Send Command")
    async def send_raw(self, command: str):
        async with self._lock:
            if not self.connected or self.writer is None:
                raise ConnectionError("Not connected to Lutron server.")
            await self._write(command + LINE_END)
            self.logger.debug(f"Command sent: {command}")

    @tracer.start_as_current_span("Execute Command")
    async def execute_command(self, command: 'LutronCommand', timeout: float = 5.0):
        """
        Execute a Lutron command and return the response.
        
        Args:
            command: The command to execute
            timeout: Command timeout in seconds

        Returns:
            The command response

        Raises:
            CommandError: If the command fails
            CommandTimeout: If the command times out
            ConnectionError: If not connected
        """
        assert self.connected, "Please connect client before invoking commands."
        assert self.command_ready, "Client wasn't ready to receive commands."
        
        if command.no_response:
            return await command.execute(self, timeout=timeout)
        else:
            async with self._command_lock:
                self.logger.debug(f"Executing command {command}")
                return await command.execute(self, timeout=timeout)
    
    def subscribe(self, event_name: EventT | LutronCommand, callback) -> SubscriptionToken:
        """
        Subscript to events announced by the Lutron Homeworks server.
        """
        if isinstance(event_name, LutronCommand):
            event_name = event_name.schema.command_name
        return self._eventbus.subscribe(event_name, callback)

    def unsubscribe(self, token: SubscriptionToken):
        """
        Removed a previous subscription.
        """
        self._eventbus.unsubscribe(token)

    def _reconnect_later(self, delay: float = 5.0) -> None:
        """Schedule a reconnection attempt with exponential backoff.
        
        Args:
            delay: Initial delay before reconnection attempt (seconds)
        """
        if self._reconnect_task and not self._reconnect_task.done():
            return
        
        async def reconnect() -> None:
            # Check if we should still reconnect (client might have been closed)
            if self._stop_event.is_set():
                self.logger.debug("Stop event set, cancelling reconnection")
                return
            
            await asyncio.sleep(delay)
            self.logger.info(f"Attempting to reconnect...")
            try:
                await self.connect()
                if self.connected:
                    self.logger.info("Reconnection successful")
            except Exception as e:
                self.logger.error(f"Reconnection attempt failed: {e}")
                # Next reconnection attempt will be scheduled by the connect method
                # if it fails with an exception
        
        self._reconnect_task = asyncio.create_task(
            reconnect(),
            name="Lutron-Reconnect",
        )

    @tracer.start_as_current_span("Close")
    async def close(self):
        self.logger.info("Closing Lutron client...")

        self._stop_event.set()

        if self.command_ready:
            self.logger.debug("Sending logout command...")
            await self.send_raw("LOGOUT")
            pass
        
        # Cancel background tasks
        tasks_to_cancel = []
        
        if self._keepalive_task and not self._keepalive_task.done():
            self.logger.debug("Cancelling keepalive task")
            self._keepalive_task.cancel()
            tasks_to_cancel.append(self._keepalive_task)
        
        if self._output_emitter_task and not self._output_emitter_task.done():
            self.logger.debug("Cancelling output emitter task")
            self._output_emitter_task.cancel()
            tasks_to_cancel.append(self._output_emitter_task)
            
        if self._reconnect_task and not self._reconnect_task.done():
            self.logger.debug("Cancelling reconnect task")
            self._reconnect_task.cancel()
            tasks_to_cancel.append(self._reconnect_task)
        
        # Wait for all tasks to complete their cancellation
        if tasks_to_cancel:
            gather_result = await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            self.logger.debug("Cancelled all tasks")
            for result in gather_result:
                if isinstance(result, Exception):
                    self.logger.warning(f"Error cancelling task: {result}")
        
        async with self._lock:
            if self.writer:
                try:
                    self.logger.debug("Closing connection...")
                    self.writer.close()
                    await self.writer.wait_closed()
                except Exception as e:
                    self.logger.warning(f"Error closing connection: {e}")
        
        self.connected = False
        self.command_ready = False