from enum import Enum
from typing import Union

from ..types import CommandDefinition as Cmd
from .base import CommandResponseProcessors, LutronCommand, CommandSchema

class AreaAction(Enum):
    ZONE_LEVEL       = 1          # Set/Get Zome Level
    START_RAISE      = 2          # Set Start raising
    START_LOWER      = 3          # Set Start lowering
    STOP_RAISE_LOWER = 4          # Set Stop raising/lowering
    SCENE            = 6          # Set/Get Scene
    
area_command_definitions = [
    Cmd(AreaAction.ZONE_LEVEL, None, no_response=True),
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