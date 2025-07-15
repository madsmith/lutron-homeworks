import asyncio
from enum import Enum
from statistics import fmean
from typing import Any, List, Union

from ..types import (
    CommandDefinition as Cmd,
    LutronSpecialEvents,
    ExecuteContext,
    UnsubscribeFnT
)
from .base import CommandSchema, CommandResponseProcessors, LutronCommand
from .output import OutputAction

class AreaAction(Enum):
    ZONE_LEVEL       = 1          # Set/Get Zome Level
    START_RAISE      = 2          # Set Start raising
    START_LOWER      = 3          # Set Start lowering
    STOP_RAISE_LOWER = 4          # Set Stop raising/lowering
    SCENE            = 6          # Set/Get Scene
    
area_command_definitions = [
    Cmd(AreaAction.ZONE_LEVEL, None),
    Cmd.SET(AreaAction.START_RAISE, None, no_response=True),
    Cmd.SET(AreaAction.START_LOWER, None, no_response=True),
    Cmd.SET(AreaAction.STOP_RAISE_LOWER, None, no_response=True),
    # TODO: handle non-response from invalid scene numbers
    Cmd(AreaAction.SCENE, CommandResponseProcessors.to_int_or_unknown),
]

schema = CommandSchema("AREA,{iid},{action}", area_command_definitions)

class AreaCommand(LutronCommand[AreaAction], schema=schema):

    def __init__(self, iid: int, action: Union[int, AreaAction]):
        """
        Initialize an area command.
        
        Args:
            action (Union[int, AreaAction]): Area action to perform. Either a value from 
                AreaAction or an integer value corresponding to an action.
        """
        # Convert int to enum if needed
        if isinstance(action, int):
            try: 
                area_action = AreaAction(action)
            except ValueError:
                raise ValueError(f"Invalid area action: {action}")
        elif isinstance(action, AreaAction):
            area_action = action
        else:
            raise ValueError(f"Invalid area action: {action}")

        super().__init__(action=area_action)

        self.iid = iid

        if self.action == AreaAction.ZONE_LEVEL:
            self.execute_hook = self._multi_output_aggregator
            

    
    @classmethod
    def set_zone_level(cls, iid: int, level: float) -> 'AreaCommand':
        """
        Set the zone level.

        Args:
            iid (int): The IntegrationID of the area
            level (float): The level to set the output to as a float between 0 and 100
        """
        cmd = cls(iid, AreaAction.ZONE_LEVEL)
        return cmd.set([level])

    @classmethod
    def get_zone_level(cls, iid: int) -> 'AreaCommand':
        """
        Get the zone level.

        Args:
            iid (int): The IntegrationID of the area
        """
        return cls(iid, AreaAction.ZONE_LEVEL)
        
    @classmethod
    def start_raise(cls, iid: int) -> 'AreaCommand':
        """
        Start raising the zone.

        Args:
            iid (int): The IntegrationID of the area
        """
        return cls(iid, AreaAction.START_RAISE)
    
    @classmethod
    def start_lower(cls, iid: int) -> 'AreaCommand':
        """
        Start lowering the zone.

        Args:
            iid (int): The IntegrationID of the area
        """
        return cls(iid, AreaAction.START_LOWER)
    
    @classmethod
    def stop_raise_lower(cls, iid: int) -> 'AreaCommand':
        """
        Stop raising/lowering the zone.

        Args:
            iid (int): The IntegrationID of the area
        """
        return cls(iid, AreaAction.STOP_RAISE_LOWER)
    
    @classmethod
    def get_scene(cls, iid: int) -> 'AreaCommand':
        """
        Get the scene for the area.

        Args:
            iid (int): The IntegrationID of the area
        """
        return cls(iid, AreaAction.SCENE)
    
    @classmethod
    def set_scene(cls, iid: int, scene: int) -> 'AreaCommand':
        """
        Set the scene for the area.

        Args:
            iid (int): The IntegrationID of the area
            scene (int): The scene to set
        """
        return cls(iid, AreaAction.SCENE).set([scene])

    @classmethod
    def _multi_output_aggregator(cls, context: ExecuteContext):

        collected_outputs = []
        def _collect_output(event_data: List[Any], future: asyncio.Future, unsubscribe_all: UnsubscribeFnT):
            nonlocal collected_outputs
            if event_data[1] == OutputAction.ZONE_LEVEL.value:
                collected_outputs.append(event_data)
         
        async def _command_complete(event_data: Any, future: asyncio.Future, unsubscribe_all: UnsubscribeFnT):
            # Implement a busy loop to wait for outputs to stabilize
            prev_count = 0
            current_count = len(collected_outputs)
            
            # Keep checking for new outputs until we stop receiving them or max iterations reached
            while current_count > prev_count:
                prev_count = current_count
                await asyncio.sleep(0.1)  # Wait a short time
                current_count = len(collected_outputs)
            
            # Once outputs have stabilized, calculate the average
            average_level = None
            if len(collected_outputs) > 0:
                average_level = fmean([output[2] for output in collected_outputs])
            unsubscribe_all()
            result = {
                "average_level": average_level,
                "outputs": [{"iid": output[0], "level": output[2]} for output in collected_outputs]
            }
            future.set_result(result)

        # Subscribe to OUTPUT events
        client = context.client
        event_tokens = context.event_tokens
        future = context.future
        unsubscribe_all = context.unsubscribe_all

        event_tokens.append(client.subscribe("OUTPUT", lambda event_data: _collect_output(event_data, future, unsubscribe_all)))
        event_tokens.append(client.subscribe(LutronSpecialEvents.CommandPrompt.value, lambda event_data: _command_complete(event_data, future, unsubscribe_all)))

        