from typing import get_type_hints,get_args
from pprint import pp


# my annotated version 
# class ValidatorResponse(TypedDict):
#     accepted: Annotated[bool,"Is agent response accepted"]
#     content: Annotated[str,"The reason of decision"]

def extract_description(field_type) -> tuple[str,str]:
    """Handles ONLY annotated fields"""
    TYPE_MAP = {bool: "boolean", str: "string", int: "integer", float: "number"}
    args = get_args(field_type)
    return TYPE_MAP[args[0]],str(args[1])

def get_schema(cls):
    """Extracts Pydantic-like schema from Annotated dataclasses"""
    hints = get_type_hints(cls,include_extras=True)
    r = {}
    for name,hint in hints.items():
        _type,desc = extract_description(hint)
        r[name] = {"type":_type,"description":desc}
    return r