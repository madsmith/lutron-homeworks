import asyncio
import logging
from opentelemetry import trace
import re
from typing import TYPE_CHECKING, Any, List, Type

from .utils.events import CallbackT, EventBus, EventT, SubscriptionToken
from .types import LutronSpecialEvents
from .constants import *
from .commands import LutronCommand

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)

RE_IS_INTEGER = re.compile(r"^\-?\d+$")
RE_IS_FLOAT = re.compile(r"^\-?\d+\.\d+$")

if TYPE_CHECKING:
    from lutron_homeworks.commands import LutronCommand

class LutronHomeworksClient:
    def __init__(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
        port: int = 23,
        keepalive_interval: int = 60,
    ):
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

        self._login_timeout = 5
        self._write_timeout = 2

        self._idle_read_timeout = 0.2
        self._reconnect_params = {
            'current_delay': 0.25,
            'initial_delay': 0.25,
            'max_delay': 60,
        }

        self._eventbus = EventBus()
        self._lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._disconnected_event = asyncio.Event()

    @property
    def reader(self):
        assert self._reader is not None, "Connection not established. Call connect() first."
        return self._reader

    @property
    def writer(self):
        assert self._writer is not None, "Connection not established. Call connect() first."
        return self._writer
    
    def set_login_timeout(self, timeout: float) -> 'LutronHomeworksClient':
        self._login_timeout = timeout
        return self
    
    def set_write_timeout(self, timeout: float) -> 'LutronHomeworksClient':
        self._write_timeout = timeout
        return self
    
    @tracer.start_as_current_span("Connect")
    async def connect(self) -> bool:
        if self._stop_event.is_set():
            raise RuntimeError("Client is closed, reconnect not permitted.")
        
        self._disconnected_event.clear()
        logger.info(f"Connecting to {self.host}:{self.port}")
        try:
            async with self._lock:
                self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
                self.connected = True

            login_successful = await self._login()
            if not login_successful:
                logger.error("Login failed for reasons unhandled...")
                
                return False
            
            # Reset reconnect delay - upon successful login
            self._reconnect_params['current_delay'] = self._reconnect_params['initial_delay']

            # Start tasks related to successful connection
            self._start_keepalive()
            self._start_output_emitter()
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            await self._schedule_reset()
        
        return self.connected

    @tracer.start_as_current_span("Login")
    async def _login(self) -> bool:
        try:
            # Use wait_for to add timeout to login operation
            return await asyncio.wait_for(
                self._process_login(),
                self._login_timeout
            )
        except asyncio.TimeoutError:
            await self.disconnect()
            self._schedule_reconnect()
            raise TimeoutError(f"Login timed out after {self._login_timeout} seconds")

    async def _process_login(self) -> bool:
        try:
            if self.username is None or self.password is None:
                raise ValueError("Username and password must be provided.")

            logger.debug("Waiting for login prompt...")
            with tracer.start_as_current_span("Find Login Prompt"):
                await self._read_until(b"login: ")
                logger.debug("Sending Username")
                await self._write(self.username + LINE_END)

            with tracer.start_as_current_span("Find Password Prompt"):
                await self._read_until(b"password: ")
                logger.debug("Sending Password")
                await self._write(self.password + LINE_END)

            with tracer.start_as_current_span("Reading Command Ready Prompt"):
                while True:
                    line_bytes = await self._read_line()
                    line = line_bytes.decode('ascii').strip()
                    if line == PROMPT:
                        break
                    if line == "bad login":
                        raise ValueError("Bad login")
                    elif line == "":
                        continue
                    else:
                        logger.debug(f"Unexpected line in login: {line}")

            # Reset the command prompt once after logging in to discard
            # any residual data from the login process (like a \0 char
            # that is showing up attached to the first prompt)
            await self._write(LINE_END)
            with tracer.start_as_current_span("Reading Command Ready Prompt 2"):
                await self._read_prompt()
            
            logger.debug("Login complete.")
            self.command_ready = True

            return True
        except ValueError as e:
            logger.error(f"Invalid login credentials")
            await self.close()
            return False
        except Exception as e:
            logger.error(f"Login failed: {e}")
            await self.disconnect()
            self._schedule_reconnect()
            return False

    async def _read_until(self, end_bytes: bytes, timeout: float | None = None) -> bytes:
        """Read until the given prompt or timeout."""

        prompt_bytes = PROMPT.encode('ascii')

        buf = b""
        try:
            while not buf.endswith(end_bytes):
                chunk = await asyncio.wait_for(self.reader.read(1), timeout=timeout)

                # No bytes, EOF
                if not chunk:
                    logger.debug("Read: End of File detected.")
                    raise ConnectionError("Connection closed by server.")

                buf += chunk
                # logger.debug(f"<< CHUNK READ: {chunk} [{len(chunk)}]")
                if buf.endswith(prompt_bytes):
                    # Remove the prompt from end of buffer
                    # logger.debug(f"Discarding prompt... [{prompt_bytes}]")
                    # buf = buf[:-len(prompt_bytes)]
                    break

            logger.debug(f"<< {buf.rstrip()}")

            return buf
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting for prompt: {end_bytes}")

    async def _read_line(self, timeout: float | None = None) -> bytes:
        line = await self._read_until(LINE_END.encode('ascii'), timeout=timeout)
        logger.debug(f"<< {line.rstrip()}")
        return line

    async def _read_prompt(self, timeout: float | None = None) -> bytes:
        prompt_bytes = PROMPT.encode('ascii')
        return await self._read_until(prompt_bytes, timeout=timeout)
    
    async def _write(self, data: str, timeout: float | None = None) -> None:
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
            
        logger.debug(f">> {data.rstrip()}")
        async with self._lock:
            self.writer.write(data.encode('ascii'))
        
            try:
                # Use wait_for to add timeout to drain operation
                await asyncio.wait_for(self.writer.drain(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.error(f"Write operation timed out after {timeout} seconds")
                raise TimeoutError(f"Write operation timed out after {timeout} seconds")

    def _start_output_emitter(self) -> None:
        if self._output_emitter_task and not self._output_emitter_task.done():
            logger.warning("Output emitter task already running.")
            return
        
        self._output_emitter_task = asyncio.create_task(
            self._output_emitter_loop(),
            name="Lutron-OutputEmitter",
        )
    
    @tracer.start_as_current_span("Output Emitter Loop")
    async def _output_emitter_loop(self) -> None:
        while True:
            disconnect_requested_task = asyncio.create_task(
                self._disconnected_event.wait(),
                name="Lutron-OutputEmitter-DisconnectRequested",
            )
            read_task = asyncio.create_task(
                self._read_line(),
                name="Lutron-OutputEmitter-ReadLine",
            )

            done, pending = await asyncio.wait(
                [disconnect_requested_task, read_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()
            
            if disconnect_requested_task in done:
                logger.debug("Output emitter loop exiting due to disconnect request")
                break

            if read_task in done:
                try:
                    output = read_task.result()
                except ConnectionError:
                    logger.error("Connection closed by server.")
                    await self._schedule_reset()
                    break
                except TimeoutError:
                    # Read timed out which isn't indicative of an error so try again
                    continue
                except BaseException as e:
                    logger.error(f"Error reading from server: {e}")
                    import traceback
                    traceback.print_exc()
                    await self._schedule_reset()
                    break

                try:
                    event, data = self._parse_output(output)
                except BaseException as e:
                    logger.error(f"Error parsing output: {e}")
                    continue

                if event is None:
                    self._eventbus.emit(LutronSpecialEvents.NonResponseEvents.value, output)
                    self._eventbus.emit(LutronSpecialEvents.AllEvents.value, output)
                    continue

                assert event is not None and data is not None, "Parsed output returned invalid event/data"

                self._eventbus.emit(event, data)
                # Re-emit the event in parsed format
                self._eventbus.emit(LutronSpecialEvents.AllEvents.value, data)
            
            logger.debug(f"Output emitter loop exiting")   

    def _parse_output(self, output: bytes) -> tuple[str, Any] | tuple[None, None]:
        line = output.decode('ascii').strip()
        if not line:
            return (None, None)

        if line.startswith(PROMPT):
            self._eventbus.emit(LutronSpecialEvents.CommandPrompt.value, None)
            return (None, None)

        if not line.startswith(COMMAND_RESPONSE_PREFIX):
            return (None, None)
        
        parts = line.split(',')
        event = parts[0][1:]
        data = self._infer_data(parts[1:])

        return (event, data)
    
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
    
    def _start_keepalive(self) -> None:
        if self._keepalive_task and not self._keepalive_task.done():
            logger.warning("Keepalive task already running.")
            return
        
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(),
            name="Lutron-Keepalive",
        )

    @tracer.start_as_current_span("Keepalive Loop")
    async def _keepalive_loop(self) -> None:
        async def do_keepalive() -> None:
            logger.debug(f"Keepalive: Sending heartbeat [{self.keepalive_interval} seconds]")
            await asyncio.sleep(self.keepalive_interval)
            await self._send_heartbeat()
            
        while True:
            disconnect_requested_task = asyncio.create_task(
                self._disconnected_event.wait(),
                name="Lutron-Keepalive-DisconnectRequested",
            )
            keepalive_task = asyncio.create_task(
                do_keepalive(),
                name="Lutron-Keepalive-DoKeepalive",
            )

            done, pending = await asyncio.wait(
                [disconnect_requested_task, keepalive_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()
            
            if disconnect_requested_task in done:
                logger.debug("Keepalive loop exiting due to disconnect request")
                break

            # Check for keepalive failure
            if keepalive_task in done:
                try:
                    result = keepalive_task.result()
                except Exception as e:
                    logger.warning(f"Keepalive failed: {e}")
                    await self._schedule_reset()
                    break

    @tracer.start_as_current_span("Send Heartbeat")
    async def _send_heartbeat(self) -> None:
        """Send a keep-alive/heartbeat command. Customize as needed."""
        if self.connected and self.command_ready:
            logger.debug("Sending heartbeat...")
            await self.send_raw("")

    async def _send_logout(self) -> None:
        if self.connected and self.command_ready:
            logger.debug("Sending logout command...")
            await self.send_raw("LOGOUT")

    @tracer.start_as_current_span("Send Command")
    async def send_raw(self, command: str) -> None:
        if not self.connected or self.writer is None:
            raise ConnectionError("Not connected to Lutron server.")
        await self._write(command + LINE_END)
        logger.debug(f"Command sent: {command}")

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
                logger.debug(f"Executing command {command}")
                return await command.execute(self, timeout=timeout)
    
    def subscribe(
        self,
        event_name: EventT | LutronCommand | Type[LutronCommand] | LutronSpecialEvents,
        callback: CallbackT,
    ) -> SubscriptionToken:
        """
        Subscript to events announced by the Lutron Homeworks server.
        """
        if ((isinstance(event_name, type) and issubclass(event_name, LutronCommand))
            or isinstance(event_name, LutronCommand)):
            event_name = event_name.schema.command_name
        elif isinstance(event_name, LutronSpecialEvents):
            event_name = event_name.value
        
        return self._eventbus.subscribe(event_name, callback)

    def unsubscribe(self, token: SubscriptionToken):
        """
        Removed a previous subscription.
        """
        self._eventbus.unsubscribe(token)

    def _schedule_reconnect(self, delay: float = 5.0) -> None:
        """Schedule a reconnection attempt with exponential backoff.
        
        Args:
            delay: Initial delay before reconnection attempt (seconds)
        """
        if self._reconnect_task and not self._reconnect_task.done():
            return

        delay = self._reconnect_params['current_delay']
        self._reconnect_params['current_delay'] = min(
            self._reconnect_params['current_delay'] * 2,
            self._reconnect_params['max_delay']
        )
        
        async def reconnect() -> None:
            # Check if we should still reconnect (client might have been closed)
            if self._stop_event.is_set():
                logger.debug("Stop event set, cancelling reconnection")
                return
            
            try:
                await asyncio.sleep(delay)
                logger.info(f"Attempting to reconnect...")
                await self.connect()
                if self.connected:
                    logger.info("Reconnection successful")
            except asyncio.CancelledError:
                logger.debug("Reconnection cancelled")
                return
            except Exception as e:
                logger.error(f"Reconnection attempt failed: {e}")
                # Next reconnection attempt will be scheduled by the connect method
                # if it fails with an exception
        
        self._reconnect_task = asyncio.create_task(
            reconnect(),
            name="Lutron-Reconnect",
        )

    async def _schedule_reset(self) -> None:
        logger.info("Scheduling reset...")

        async def do_reset() -> None:
            logger.info("Resetting Lutron client...")
            await self.disconnect()
            logger.info("Scheduling reconnection...")
            self._schedule_reconnect()
        
        self._reset_task = asyncio.create_task(
            do_reset(),
            name="Lutron-Reset",
        )

    @tracer.start_as_current_span('Disconnect')
    async def disconnect(self) -> None:
        logger.info("Disconnecting Lutron client...")

        await self._teardown(full_shutdown=False)

    @tracer.start_as_current_span("Close")
    async def close(self) -> None:
        logger.info("Closing Lutron client...")

        await self._teardown(full_shutdown=True)

    async def _teardown(self, full_shutdown: bool = False) -> None:
        self._disconnected_event.set()
        if full_shutdown:
            self._stop_event.set()
            
        # logger.debug("Teardown: try gather tasks")
        await self._try_gather_tasks(full_shutdown=full_shutdown)

        # logger.debug("Teardown: cancel tasks")
        await self._cancel_tasks(include_reconnect=full_shutdown)

        # Close connection
        # logger.debug("Teardown: Destroy IO")
        async with self._lock:
            if self._writer:
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                    self._writer = None
                except Exception as e:
                    logger.warning(f"Error closing write connection: {e}")
            if self._reader:
                self._reader = None

        self.connected = False
        self.command_ready = False

    async def _try_gather_tasks(self, full_shutdown: bool = False, timeout: float = 0.25) -> None:
        # Attempt to gather all tasks
        try:
            tasks = []
            if self._keepalive_task and not self._keepalive_task.done():
                tasks.append(self._keepalive_task)
            if self._output_emitter_task and not self._output_emitter_task.done():
                tasks.append(self._output_emitter_task)
            if full_shutdown and self._reconnect_task and not self._reconnect_task.done():
                tasks.append(self._reconnect_task)
            
            if not tasks:
                return
            
            gather_task = asyncio.gather(*tasks, return_exceptions=True)

            # Wait for either the gather task to complete or the timeout to elapse
            try: 
                await asyncio.wait_for(gather_task, timeout)
            except asyncio.TimeoutError:
                logger.info("Task gathering timed out")
                gather_task.cancel()

            try:
                await gather_task
            except asyncio.CancelledError:
                # logger.debug("Gather cancelled")
                pass
            except Exception as e:
                logger.warning(f"Error gathering tasks: {e}")

        except asyncio.CancelledError:
            # logger.debug("Gather cancelled")
            pass
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.warning(f"Unhandled exception gathering tasks: {e}")

    async def _cancel_tasks(self, include_reconnect: bool = False) -> None:
        cancelled_tasks = []
        
        if self._keepalive_task and not self._keepalive_task.done():
            logger.debug("Cancelling keepalive task")
            self._keepalive_task.cancel()
            cancelled_tasks.append(self._keepalive_task)
        
        if self._output_emitter_task and not self._output_emitter_task.done():
            logger.debug("Cancelling output emitter task")
            self._output_emitter_task.cancel()
            cancelled_tasks.append(self._output_emitter_task)
        
        if include_reconnect and self._reconnect_task and not self._reconnect_task.done():
            logger.debug("Cancelling reconnect task")
            self._reconnect_task.cancel()
            cancelled_tasks.append(self._reconnect_task)
        
        # Wait for all tasks to complete their cancellation
        if cancelled_tasks:
            try:
                for task in cancelled_tasks:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.warning(f"Error cancelling task: {e}")
            except Exception as e:
                logger.warning(f"Error during task cancellation cleanup: {e}")