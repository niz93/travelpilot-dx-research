# TeleAtlas / Blaupunkt TravelPilot DX: technical report

Research date: 14 November 2026  
Target: COMAND 2.0/2.5 and other DX-compatible devices  
Hardware status: no physical head unit was tested

## 1. Executive summary

Eleven local CloneCD disc sets were examined: nine from 2013–2014 and two from 2010–2011. All were converted to ISO and inventoried; five were fully extracted with SHA-256 manifests.

The discs contain compiled Bosch formats rather than directly usable GDF source. `MAP00001.MAP` contains TPMAP2; `NAVxxxxx.DAT` files contain TPNAV2_COMPRESSED streams. Compilation metadata including `gdf_syntax.GDF_3_0.1.1` proves GDF input to the Bosch pipeline, not equivalence between compiled records and ISO GDF records.

TPMAP2 geometry can be decoded and rendered. The TPNAV2 container and decompressor are validated, and selected local node/link graphs are recovered. A complete editor, global router, WGS84 conversion, and tested modified disc remain unavailable.

## 2. Source media

The 2013–2014 sets cover Alps, Benelux, France, Germany, Italy, Major Roads of Europe, Scandinavia, Spain/Portugal, and Czech Republic/Poland. The added sets are TeleAtlas Europe 2010–2011 and Teleatlas Polska Ceska 2010–2011.

The two added sets contain 723 files / 475,693,373 bytes and 385 files / 246,261,983 bytes respectively. Their MAP files are TPMAP2-compatible and identify `MG3_2010.1`, project data `2009.09`, and `gdf_syntax.GDF_3_0.1.1`.

Five checked `NAVECE_M.EXE` copies are identical: 1,579,561 bytes, SHA-256 `6fa3cfd7331d28a2f417f0b8b566dd625157d0d8d5f43452c3892195d1a443f1`.

## 3. CloneCD and sector preservation

Each source set consists of `.ccd`, `.img`, and `.sub`. The examined tracks use one session, `MODE=1`, `DataTracksScrambled=0`, and 2,352-byte raw sectors. ISO retains only the 2,048-byte user-data area and therefore does not preserve raw headers, EDC/ECC, or subchannel data.

Recovered Mode 1 layout:

| Offset | Size | Content |
|---:|---:|---|
| 0 | 12 | Sync |
| 12 | 4 | BCD MSF and mode, including the 150-sector offset |
| 16 | 2048 | ISO user data |
| 2064 | 4 | EDC |
| 2068 | 8 | Reserved |
| 2076 | 172 | ECC P |
| 2248 | 104 | ECC Q |

For Germany, 335,541 of 335,584 sectors reconstructed exactly. For Czech/Poland, 128,648 of 128,912 matched exactly. Remaining differences were confined to service areas; user data matched. Special sector contents and subchannel anomalies must not automatically be “repaired.” These observations alone do not prove copy protection.

## 4. Main file groups

| Group | Established role or status |
|---|---|
| `MAP00001.MAP` | Main TPMAP2 cartographic container; one per disc |
| `NAVxxxxx.DAT` | TPNAV2_COMPRESSED navigation data |
| `NAVECE_M.EXE` | NEC V810 navigation executable |
| `QUADIDX.DAT` | Large separate index associated with GIS/iPublish |
| `RF_*.DAT` | MERIAN/iPublish data |
| `V01_*`, `V01_N06*` | Language/speech resources |
| `*.NTL`, `*.DNL`, `CCTMCLUT.DAT` | RDS-TMC tables/data |
| `CONFIG.SYS`, `PARAM.SYS` | Program, language, and head-unit configuration |
| `INFO.TXT` | Build identity, versions, countries, TMC and date |
| `DFLASHDL.BEX` | Download/update component, not a map editor |

All 1,983 NAV files in the initially extracted Germany, Czech/Poland, and Major Roads sets contain TPNAV2_COMPRESSED signatures within their first 16 KiB. The signature offset is not fixed.

## 5. TPMAP2

### 5.1 Origin

Checked 2013–2014 MAP files contain:

```text
CD-FORMAT MG3_2013.1 VERSION 1.1_LINUX
```

They also contain GDF syntax metadata, project names, map names, and compiler parameters. The on-disc result is compiled TPMAP2, not ASCII Sequential GDF. GDF-capable GIS tools do not directly produce TPMAP2 or TPNAV2.

### 5.2 Indexed header and directories

On three primary samples:

- little-endian uint32 at `0x04` equals file size;
- four signed int32 values at `+8/+0xc/+0x10/+0x14` are global `min_x/min_y/max_x/max_y` in internal units;
- uint16 at `0x24` points to seven uint16 header offsets;
- four 16-byte level descriptors follow `TPMAP2\0\0`;
- descriptor `+8` is uint32 count and `+12` is uint32 directory offset;
- each directory entry is `<uint32 data_offset, uint32 data_length>`;
- the first L0 directory entry follows all 64 descriptor bytes rather than aliasing the final descriptor.

Descriptor bytes `+1/+2` hold x/y subdivisions; `+3` is the coordinate shift. Byte zero matches the level number. Bytes `+4..+7` are not fully classified. The level count is the product of subdivision factors through that level.

### 5.3 Block layout

```text
0x00  uint32 block_length
0x04  uint16 table_a_offset
0x06  uint16 table_a_count
0x08  uint16 table_b_lines_offset
0x0a  uint16 table_b_lines_count
0x0c  uint16 table_c_points_offset
0x0e  uint16 table_c_points_count
```

All offsets are relative to the block start.

Table A has 16-byte polygon/contour records with an offset and count for signed16 coordinate pairs. Table B has 12-byte line records with a coordinate offset, point count, and auxiliary/text-related fields. Table C has 12-byte point records with inline signed16 x/y and variable-length labels. Marker values `0xf1/0xf2` occur in selected auxiliary or label records; not every related field is universally a string pointer.

### 5.4 Hierarchical addressing and coordinates

For a level/index pair, derive the hierarchical cells by repeated division, then narrow the global bounds through each selected cell:

```text
remainder = index
for current = level … 1:
    cell[current] = remainder % (div_x[current] * div_y[current])
    remainder //= div_x[current] * div_y[current]

for current = 1 … level:
    cell_x = cell[current] % div_x[current]
    cell_y = cell[current] // div_x[current]
    step_x = (max_x - min_x) // div_x[current]
    step_y = (max_y - min_y) // div_y[current]
    bounds = selected cell inside previous bounds

centre = max - ((max - min + 1) // 2)
absolute_x = centre_x + (int16_x << level_shift)
absolute_y = centre_y + (int16_y << level_shift)
```

Coordinates within 64 internal units of a tile edge are snapped to that edge. Neighboring indices cannot generally be obtained by adding one global row width because index order is hierarchical.

The projection, datum, and transformation to WGS84 are not established. Division by `1e7` and naming the axes longitude/latitude remain hypotheses.

### 5.5 Validation, styles and labels

The directory validator checked every directory range in three MAP files. An extended deterministic sample accepted 458 block bodies with no parse errors. Full L1/L2 renders were produced for Germany, Czech/Poland, and Major Roads, with selected detailed L3 tiles and neighboring-tile groups.

Five MAP files passed 62,135 tile-address round trips. These checks are implemented in `tools/test_tpmap_geometry.py`; private source files are required for that integration test.

Recovered line-style mappings:

```text
0x10–0x17 → 0x20–0x27
0xd0      → 0x30
0xf0      → 0x50
```

Selected `0xd0` auxiliary records yielded `DONAU`, `NECKAR`, `RHEIN`, `BEROUNKA`, `LABE`, `OHRE`, and `VLTAVA`. This does not prove that every `0xd0` record is a river. Types `0x10` and `0xf0` are not conclusively classified; `0xf0` is only a road-geometry candidate.

The feature survey covers 5,354 sampled blocks without parse errors. It is not an exhaustive census of all L3 bodies.

## 6. TPNAV2

### 6.1 Container and decompression

Recovered remapping layout:

```text
primary header: 26 bytes
+0x04 uint32 table_header_offset

table header:
+0  uint32 entry_count
+4  uint32 table_offset
+8  uint32 field08
+12 uint32 field0c

entry: 16 bytes, little-endian <I H H I H H>
+0   logical_offset
+4   logical_size
+6   field06
+8   physical_offset
+12  physical_size
+14  compression_flag: 0 = raw, 1 = decompress
```

Firmware searches backward for an exact logical offset/size match. The LZ stream uses LSB-first control bits, a separate literal stream, and byte-oriented overlap backreferences. Control and literal streams meet exactly at physical entry boundaries.

| Set | Files | Entries | Compressed | Raw | Logical bytes | Errors |
|---|---:|---:|---:|---:|---:|---:|
| Main NAV | 5 | 2,758 | 1,788 | 970 | 56,739,154 | 0 |
| Regional NAV | 4 | 1,057 | 1,034 | 23 | 3,664,865 | 0 |
| **Total** | **9** | **3,815** | **2,822** | **993** | **60,404,019** | **0** |

Declared-size and stream-boundary checks also returned zero mismatches. See `results/main-five-validation.json` and `results/regional-validation.json`.

### 6.2 Local graph clusters

Established common graph header fields:

```text
+0x00 uint16 total size
+0x08 int32 base X
+0x0c int32 base Y
+0x10 uint8 coordinate shift
+0x12 <uint16 offset, uint16 count> boundary coordinates
+0x16 uint16 section-presence flags
+0x18 uint16 section-table offset
```

The section table contains `<uint16 offset, uint16 count>` pairs in set-bit order. Section `0x0040` contains 6-byte nodes, `0x0080` contains 12-byte links, and `0x0400` contains node coordinates. Link flag bits select nested four-byte descriptors; bit `0x0002` selects intermediate shape coordinates.

Coordinates are `base + (delta << shift)`. The normal form uses signed16 pairs; a wide form uses two 24-bit values. The wide branch is supported by a synthetic unit test but was not observed among the 128 examined real candidates.

Endpoint recovery requires two passes:

1. Read each node's uint16 link references. `value & 0x3ff` is a one-based link index and `0x8000` selects its second endpoint.
2. Overwrite the corresponding link endpoint with the current node number.
3. Only then construct `first node → shape points → second node` paths.

Raw endpoint fields cannot correctly be validated before this rewrite. Unresolved values are retained as masked raw values and reported separately.

| File | Candidates | Fully locally consistent |
|---|---:|---:|
| Germany `NAV20050.DAT` | 2 | 0 |
| Germany `NAV20051.DAT` | 22 | 11 |
| Europe 2010–2011 `NAV20099.DAT` | 71 | 0 |
| Czech/Poland 2010–2011 `NAV20001.DAT` | 33 | 26 |
| **Total** | **128** | **37** |

A zero means no fully local graph under the strict criterion, not absence of navigation data. Other blocks parse structurally but have unresolved endpoints. Cross-cluster or external references are not yet established.

Control examples:

- Czech/Poland entry 241: 11 nodes, 11 links, 21 references, zero conflicts/errors.
- Germany entry 158: 346 nodes, 356 links, 709 references, zero conflicts/errors.

## 7. Executable and emulation

`NAVECE_M.EXE` is ELF32 little-endian for NEC V810 (`e_machine=36`), with no symbol table. It is not a desktop Linux or Windows CE executable. A normal virtual machine does not supply the V810 processor, memory map, CD calls, CAN/peripherals, graphics, input, audio, and initialization environment of a head unit.

Static decoder recovery has been more productive than treating a generic VM as a ready viewer. A full head-unit UI or emulation environment is not implemented.

## 8. Modification and recording experiments

The experimental same-length patcher replaces an ISO extent only in a CloneCD copy, requires equal byte length, recalculates affected EDC/ECC, and copies `.ccd` and `.sub`. It can refuse to overwrite known special sectors when supplied with a verification report.

The regression test changed one byte in `CONFIG.SYS`, affecting only LBA 5037; all other 128,911 sectors and `.sub` were preserved. This proves a low-level operation on a PC, not map editing or compatibility with a head unit.

A real map update additionally requires:

1. current road geometry, restrictions, addresses, and POI;
2. valid source data for Bosch compilation or an equivalent writer;
3. TPMAP2 and TPNAV2 serialization;
4. rebuilt QUADIDX and related search/routing tables;
5. version and integrity reconciliation;
6. ISO/raw reconstruction without losing original characteristics;
7. CD-R recording and physical head-unit testing.

No complete working chain for these steps is claimed. No CD-R recording or head-unit test was performed.

## 9. Current capability matrix

| Task | Status |
|---|---|
| Inspect disc filesystem | Complete and validated on 11 ISO files |
| Extract five source sets with hashes | Complete |
| Read TPMAP2 metadata/directories | Complete for checked formats |
| Render TPMAP2 geometry | Working in internal units |
| Decompress TPNAV2 | Validated on 3,815 entries |
| Recover local TPNAV2 nodes/links | Working for 37 of 128 candidates |
| Render fully classified roads | Incomplete; type semantics remain unresolved |
| Build a global routing graph | Incomplete; cross-cluster links and attributes are missing |
| Convert coordinates to WGS84 | Not established |
| Edit a road and serialize all data | Not implemented |
| Build an updated map from OSM | No working pipeline |
| Validate a modified CD-R on hardware | Not performed |

## 10. Next research target

Recover nonlocal/cross-cluster TPNAV2 endpoint references. Aligning the resulting graph with TPMAP2 geometry should also help resolve the semantics of `0x10` and `0xf0` without guessing from appearance alone.
