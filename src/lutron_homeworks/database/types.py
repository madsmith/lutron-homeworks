from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class EntityType(str, Enum):
    AREA        = "area"
    OUTPUT      = "output"
    DEVICE      = "device"
    SHADE_GROUP = "shade_group"

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value


@dataclass
class LutronDBEntity:
    db_id: str
    iid: int | None
    name: str
    type: EntityType
    subtype: str | None
    sort_order: int
    parent_db_id: str | None
    path: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        def opt(key: str, cast_fn: Callable[[Any], Any] | None = None) -> Any:
            if cast_fn is None:
                cast_fn = lambda x: x
            return cast_fn(data.get(key)) if key in data else None
        
        return cls(
            db_id=data["db_id"],
            iid=opt("iid", int),
            name=data["name"],
            type=EntityType(data["type"]),
            subtype=opt("subtype", str),
            sort_order=opt("sort_order", int),
            parent_db_id=opt("parent_db_id", str),
            path=opt("path", str)
        )
    
    def with_path(self, path: list[str]):
        self.path = " / ".join(path)
        return self

@dataclass
class LutronArea:
    iid: int
    name: str
    path: str | None

    @classmethod
    def from_entity(cls, entity: LutronDBEntity):
        assert entity.iid is not None, "Can not create LutronArea from entity with no iid"

        return cls(
            entity.iid,
            entity.name,
            entity.path
        )

@dataclass
class LutronOutput:
    iid: int
    output_type: str
    name: str
    path: str | None

    @classmethod
    def from_entity(cls, entity: LutronDBEntity):
        assert entity.iid is not None, "Can not create LutronArea from entity with no iid"
        assert entity.subtype is not None, "Can not create LutronArea from entity with no subtype"

        return cls(
            entity.iid,
            entity.subtype,
            entity.name,
            entity.path
        )


LutronEntity = LutronDBEntity | LutronArea | LutronOutput
