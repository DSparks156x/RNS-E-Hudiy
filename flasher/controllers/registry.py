"""Controller-family registry and operation-level gating."""
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class ControllerFamily:
    name: str
    module: int
    module_aliases: tuple[str, ...]
    protocol_module: str
    patches_module: str
    operations: frozenset[str]
    part_prefixes: tuple[str, ...] = ()

    def protocol(self):
        return import_module(self.protocol_module)

    def patches(self):
        return import_module(self.patches_module)

    def supports(self, operation: str) -> bool:
        return operation in self.operations

    def matches_identification(self, info: dict) -> bool:
        part = str(info.get("software_part_number", info.get("part_number", ""))).strip().upper()
        return bool(part and any(part.startswith(prefix) for prefix in self.part_prefixes))

    def validate_identification(self, info: dict) -> None:
        if self.part_prefixes and not self.matches_identification(info):
            part = info.get("software_part_number", info.get("part_number", "<empty>"))
            raise ValueError(
                f"Module 0x{self.module:02X} identified as {part!r}, not {self.name}")


FAMILIES = (
    ControllerFamily(
        name="haldex-gen4",
        module=0x0A,
        module_aliases=("awd", "haldex", "haldex-gen4", "allrad"),
        protocol_module="flasher.controllers.haldex_gen4.protocol",
        patches_module="flasher.controllers.haldex_gen4.patches",
        operations=frozenset({"identify", "readout", "flash"}),
        part_prefixes=("0BR", "0AY", "0BS"),
    ),
    ControllerFamily(
        name="pq-eps",
        module=0x09,
        module_aliases=("eps", "steering", "pq-eps"),
        protocol_module="flasher.controllers.pq_eps.protocol",
        patches_module="flasher.controllers.pq_eps.patches",
        operations=frozenset({"identify", "readout", "eeprom", "flash"}),
        part_prefixes=("1K0909144", "8J0909144"),
    ),
)


def module_choices() -> tuple[str, ...]:
    return tuple(alias for family in FAMILIES for alias in family.module_aliases)


def get_family(name: str) -> ControllerFamily:
    selected = name.lower()
    for family in FAMILIES:
        if selected == family.name:
            return family
    raise ValueError(f"Unknown controller family: {name}")


def parse_module(value) -> int:
    if isinstance(value, int):
        module = value
    else:
        selected = str(value).strip().lower()
        for family in FAMILIES:
            if selected in family.module_aliases:
                return family.module
        try:
            module = int(selected, 0)
        except ValueError:
            try:
                module = int(selected, 16 if any(c in "abcdef" for c in selected) else 10)
            except ValueError as exc:
                aliases = ", ".join(module_choices())
                raise ValueError(
                    f"Unknown module {value!r}; use a raw logical ID or alias: {aliases}") from exc
    if not 0 <= module <= 0x7F:
        raise ValueError("TP2 logical module ID must be within 0x00..0x7F")
    return module


def family_for_module(module, *, operation: str | None = None) -> ControllerFamily:
    module = parse_module(module)
    matches = [candidate for candidate in FAMILIES if candidate.module == module]
    if len(matches) != 1:
        raise ValueError(f"No controller family is registered for module 0x{module:02X}")
    family = matches[0]
    if operation is not None and not family.supports(operation):
        raise ValueError(
            f"Module 0x{module:02X} ({family.name}) does not support {operation}")
    return family
