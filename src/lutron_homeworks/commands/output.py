from enum import Enum
from typing import Union

from ..types import CommandDefinition as Cmd
from .base import CommandResponseProcessors, LutronCommand, CommandSchema

class OutputAction(Enum):
    ZONE_LEVEL       = 1          # Set/Get Zome Level
    START_RAISE      = 2          # Set Start raising
    START_LOWER      = 3          # Set Start lowering
    STOP_RAISE_LOWER = 4          # Set Stop raising/lowering
    PULSE_TIME       = 5          # Set Pulse time
    
output_command_definitions = [
    Cmd(OutputAction.ZONE_LEVEL, CommandResponseProcessors.to_float),
    Cmd.SET(OutputAction.START_RAISE, CommandResponseProcessors.to_int, no_response=True),
    Cmd.SET(OutputAction.START_LOWER, CommandResponseProcessors.to_int, no_response=True),
    Cmd.SET(OutputAction.STOP_RAISE_LOWER, CommandResponseProcessors.to_int, no_response=True),
    Cmd.SET(OutputAction.PULSE_TIME, CommandResponseProcessors.to_int, no_response=True),
]

schema = CommandSchema("OUTPUT,{iid},{action}", output_command_definitions)

class OutputCommand(LutronCommand[OutputAction], schema=schema):

    def __init__(self, iid: int, action: Union[int, OutputAction]):
        """
        Initialize an output command.
        
        Args:
            action (Union[int, OutputAction]): Output action to perform. Either a value from 
                OutputAction or an integer value corresponding to an action.
        """
        # Convert int to enum if needed
        if isinstance(action, int):
            try: 
                output_action = OutputAction(action)
            except ValueError:
                raise ValueError(f"Invalid output action: {action}")
        elif isinstance(action, OutputAction):
            output_action = action
        else:
            raise ValueError(f"Invalid output action: {action}")

        super().__init__(action=output_action)

        self.iid = iid

    @classmethod
    def get_zone_level(cls, iid: int) -> 'OutputCommand':
        """
        Get the current zone level.

        Args:
            iid (int): The IntegrationID of the output element
        """
        return cls(iid, OutputAction.ZONE_LEVEL)
    
    @classmethod
    def set_zone_level(cls, iid: int, level: float) -> 'OutputCommand':
        """
        Set the zone level.

        Args:
            iid (int): The IntegrationID of the output element
            level (float): The level to set the output to as a float between 0 and 100
        """
        cmd = cls(iid, OutputAction.ZONE_LEVEL)
        return cmd.set([level])

    @classmethod
    def start_raise(cls, iid: int) -> 'OutputCommand':
        """
        Start raising the zone.

        Args:
            iid (int): The IntegrationID of the output element
        """
        return cls(iid, OutputAction.START_RAISE)
    
    @classmethod
    def start_lower(cls, iid: int) -> 'OutputCommand':
        """
        Start lowering the zone.

        Args:
            iid (int): The IntegrationID of the output element
        """
        return cls(iid, OutputAction.START_LOWER)
    
    @classmethod
    def stop_raise_lower(cls, iid: int) -> 'OutputCommand':
        """
        Stop raising/lowering the zone.

        Args:
            iid (int): The IntegrationID of the output element
        """
        return cls(iid, OutputAction.STOP_RAISE_LOWER)
    
    @classmethod
    def set_pulse_time(cls, iid: int, pulse_time: int) -> 'OutputCommand':
        """
        Set the pulse time for a pulsed output device.

        Args:
            iid (int): The IntegrationID of the output element
            pulse_time (int): The pulse time in seconds
        """
        return cls(iid, OutputAction.PULSE_TIME).set([pulse_time])