#!/usr/bin/env python3
"""Report ELF headers, program segments, sections and any retained symbols."""
from pathlib import Path
import argparse
import json
import struct


def cstring(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    return data[offset:end if end >= 0 else len(data)].decode("utf-8", "replace")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = args.file.read_bytes()
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
    (_, kind, machine, version, entry, phoff, shoff, flags, ehsize, phentsize,
     phnum, shentsize, shnum, shstrndx) = header
    segments = []
    for index in range(phnum):
        fields = struct.unpack_from("<IIIIIIII", data, phoff + index * phentsize)
        segments.append(dict(zip(("type", "offset", "vaddr", "paddr", "file_size", "memory_size", "flags", "align"), fields)))
    sections = [struct.unpack_from("<IIIIIIIIII", data, shoff + index * shentsize) for index in range(shnum)]
    string_section = sections[shstrndx]
    strings = data[string_section[4]:string_section[4] + string_section[5]]
    result = {"file": str(args.file), "size": len(data), "type": kind, "machine": machine,
              "entry": entry, "segments": segments, "sections": [], "symbols": []}
    for index, section in enumerate(sections):
        name = cstring(strings, section[0])
        result["sections"].append({"index": index, "name": name, "type": section[1],
                                   "flags": section[2], "address": section[3], "offset": section[4],
                                   "size": section[5], "link": section[6], "info": section[7],
                                   "alignment": section[8], "entry_size": section[9]})
        if section[1] == 2 and section[9]:
            symbols = sections[section[6]]
            symbol_strings = data[symbols[4]:symbols[4] + symbols[5]]
            for offset in range(section[4], section[4] + section[5], section[9]):
                name_offset, value, size, info, other, shndx = struct.unpack_from("<IIIBBH", data, offset)
                result["symbols"].append({"name": cstring(symbol_strings, name_offset), "address": value,
                                          "size": size, "info": info, "section": shndx})
    text = json.dumps(result, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"ELF machine={machine}, entry={entry:#x}, sections={shnum}, symbols={len(result['symbols'])}")
    for section in result["sections"]:
        if section["size"]:
            print(f"{section['name']}: offset={section['offset']:#x} address={section['address']:#x} size={section['size']:#x}")


if __name__ == "__main__":
    main()
