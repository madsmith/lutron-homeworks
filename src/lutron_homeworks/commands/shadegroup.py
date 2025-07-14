from enum import Enum

from typing import Union

from ..types import CommandDefinition as Cmd
from .base import CommandResponseProcessors, LutronCommand, CommandSchema

class ShadeGroupAction(Enum):
    ZONE_LEVEL       = 1          # Set/Get Zome Level
    START_RAISE      = 2          # Set Start raising
    START_LOWER      = 3          # Set Start lowering
    STOP_RAISE_LOWER = 4          # Set Stop raising/lowering
    CURRENT_PRESET   = 6          # Set Current preset
    
shade_group_command_definitions = [
    Cmd(ShadeGroupAction.ZONE_LEVEL, CommandResponseProcessors.to_float),
    Cmd.SET(ShadeGroupAction.START_RAISE, CommandResponseProcessors.to_int, no_response=True),
    Cmd.SET(ShadeGroupAction.START_LOWER, CommandResponseProcessors.to_int, no_response=True),
    Cmd.SET(ShadeGroupAction.STOP_RAISE_LOWER, CommandResponseProcessors.to_int, no_response=True),
    Cmd.SET(ShadeGroupAction.CURRENT_PRESET, CommandResponseProcessors.to_int),
]

schema = CommandSchema("SHADEGRP,{iid},{action}", shade_group_command_definitions)

class ShadeGroupCommand(LutronCommand[ShadeGroupAction], schema=schema):

    def __init__(self, iid: int, action: Union[int, ShadeGroupAction]):
        """
        Initialize a shade group command.
        
        Args:
            action (Union[int, ShadeGroupAction]): Shade group action to perform. 
                Either a value from ShadeGroupAction or an integer value 
                corresponding to an action.
        """
        # Convert int to enum if needed
        if isinstance(action, int):
            try: 
                shade_group_action = ShadeGroupAction(action)
            except ValueError:
                raise ValueError(f"Invalid shade group action: {action}")
        elif isinstance(action, ShadeGroupAction):
            shade_group_action = action
        else:
            raise ValueError(f"Invalid shade group action: {action}")
            
        super().__init__(action=shade_group_action)

        self.iid = iid

    @classmethod
    def get_zone_level(cls, iid: int) -> 'ShadeGroupCommand':
        """
        Get the shade group level.

        Args:
            iid (int): The IntegrationID of the shade group
        """
        return cls(iid, ShadeGroupAction.ZONE_LEVEL)
    
    @classmethod
    def set_zone_level(cls, iid: int, level: float) -> 'ShadeGroupCommand':
        """
        Set the shade group level.

        Args:
            iid (int): The IntegrationID of the shade group
            level (float): The level to set the shade group to as a float
                between 0 and 100
        """
        cmd = cls(iid, ShadeGroupAction.ZONE_LEVEL)
        return cmd.set([level])

    @classmethod
    def start_raise(cls, iid: int) -> 'ShadeGroupCommand':
        """
        Start raising the shade group.

        Args:
            iid (int): The IntegrationID of the shade group
        """
        return cls(iid, ShadeGroupAction.START_RAISE)
    
    @classmethod
    def start_lower(cls, iid: int) -> 'ShadeGroupCommand':
        """
        Start lowering the shade group.

        Args:
            iid (int): The IntegrationID of the shade group
        """
        return cls(iid, ShadeGroupAction.START_LOWER)
    
    @classmethod
    def stop_raise_lower(cls, iid: int) -> 'ShadeGroupCommand':
        """
        Stop raising/lowering the shade group.

        Args:
            iid (int): The IntegrationID of the shade group
        """
        return cls(iid, ShadeGroupAction.STOP_RAISE_LOWER)
    
    @classmethod
    def get_current_preset(cls, iid: int) -> 'ShadeGroupCommand':
        """
        Get the current preset.

        Args:
            iid (int): The IntegrationID of the shade group
        """
        return cls(iid, ShadeGroupAction.CURRENT_PRESET)