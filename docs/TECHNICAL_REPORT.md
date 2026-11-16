# TeleAtlas / Blaupunkt TravelPilot DX: technical report

Research date: 14 November 2026  
Target: COMAND 2.0/2.5 and other DX-compatible devices  
Hardware status: no physical head unit was tested; a substitution test disc (generated Krasnodar container in a Czech/Poland 2010-2011 CloneCD copy) is assembled and statically verified, awaiting burning and field test

## 1. Executive summary

Eleven local CloneCD disc sets were examined: nine from 2013–2014 and two from 2010–2011. All were converted to ISO and inventoried; five were fully extracted with SHA-256 manifests.

The discs contain compiled Bosch formats rather than directly usable GDF source. `MAP00001.MAP` contains TPMAP2; `NAVxxxxx.DAT` files contain TPNAV2_COMPRESSED streams. Compilation metadata including `gdf_syntax.GDF_3_0.1.1` proves GDF input to the Bosch pipeline, not equivalence between compiled records and ISO GDF records.

TPMAP2 geometry can be decoded and rendered. The TPNAV2 container and decompressor are validated, and selected local node/link graphs are recovered. A cluster grid and NAV container can be generated from OpenStreetMap data. The addressing question (how the firmware maps a position to a NAV file) is statically resolved: all index/numbering hypotheses are rejected and mount-time scanning of entry-table bounds is the surviving model, pending a trace of the mount path and a head-unit substitution test. A complete editor, global router, road-attribute semantics, and a tested modified disc remain unavailable.

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

### 3.1 Weak-sector copy protection (confirmed 2026-11-15)

Full-image EDC/ECC verification (`tools/verify_clonecd_image.py`) of a pristine Czech/Poland 2010-2011 master shows **264 sectors with intentionally corrupted EDC** in the unallocated gap between the volume descriptors and the first file extent (LBA 807–5010 on that disc, user area filled with a `0x55` pattern). The corrupt LBAs are irregularly spaced (address diffs 1, 5, 10, 20, 21, 25, 31, 35); ECC P/Q are *not* corrupted, so the sectors read fine through error correction but fail an EDC check — the classic weak-sector signature. A Germany 2013-2014 disc shows the same mechanism with a different count (20 scattered sectors from stamp aging).

A head-unit field test (2026-11-15) confirmed this layer is load-bearing: a **fully rebuilt ISO** (new volume layout, all sectors with correct EDC/ECC, generated TPMAP2 map) was rejected by the HU ("not a navigation CD" after rhythmic re-reading of one sector), while byte-identical-except-patches copies of the original image were accepted. The surviving build method is therefore **in-place patching of the donor image** (`tools/patch_donor_image.py`): replace only the MAP extent and the patched NAV extent, recompute EDC/ECC for touched sectors, keep the protection gap, subchannel, TOC and file order untouched.

Independently, the CloneCD "Teleatlas" burn profile amplifies 166 sectors in LBA 93–618 (regular blocks of ~10 with stride 31–41); those sectors carry *correct* EDC in the image and belong to a second, mastering-related layer the recorder expects. Both layers must survive a burn: CloneCD + Teleatlas profile + lowest speed + "Weak Sectors: Amplify".

## 4. Main file groups

| Group | Established role or status |
|---|---|
| `MAP00001.MAP` | Main TPMAP2 cartographic container; one per disc |
| `NAVxxxxx.DAT` | TPNAV2_COMPRESSED navigation data |
| `NAVECE_M.EXE` | NEC V810 navigation executable |
| `QUADIDX.DAT` | Name/POI **search index** (GDF-derived quad index); INFO.TXT tag `Quad-Idx …_GIS`; decoded header, see §4.1 |
| `RF_1_1_{_,G,Z}.DAT` | **Travel-guide search indexes**; INFO.TXT tag `Quad-Idx …_rf …travel_guide.1..3`; same header family as QUADIDX |
| `V01_*`, `V01_N06*` | Language/speech resources |
| `*.NTL`, `*.DNL`, `CCTMCLUT.DAT` | RDS-TMC tables/data |
| `CONFIG.SYS`, `PARAM.SYS` | Program, language, and head-unit configuration |
| `INFO.TXT` | Build identity, versions, countries, TMC and date |
| `DFLASHDL.BEX` | Download/update component, not a map editor |

All 1,983 NAV files in the initially extracted Germany, Czech/Poland, and Major Roads sets contain TPNAV2_COMPRESSED signatures within their first 16 KiB. The signature offset is not fixed.

### 4.1. QUADIDX.DAT / RF: search indexes, not routing

Per-disc `INFO.TXT` lists every index file of the Quad-Idx family explicitly, e.g. Czech/Poland 2010-2011:

```text
Quad-Idx: quad2-TA_CZEPOL09.09_GIS v4                       -> QUADIDX.DAT
Quad-Idx: quad2-TA_CZEPOL05.3_rf v2 rf_1_1__.travel_guide.1 -> RF_1_1__.DAT
Quad-Idx: quad2-TA_CZEPOL05.3_rf v2 rf_1_1_g.travel_guide.2 -> RF_1_1_G.DAT
Quad-Idx: quad2-TA_CZEPOL05.3_rf v2 rf_1_1_z.travel_guide.3 -> RF_1_1_Z.DAT
```

The QUADIDX header is byte-identical on all five examined discs in [0x00..0x6E] and fully decoded:

| Offset | Value | Meaning |
|---|---|---|
| +0x00 u16 | 0x0069 (105) | end of fixed header strings |
| +0x02 u16 | 3 | format version |
| +0x04 u32 | 0x6A (106) | start of u16 string-offset table |
| +0x08/+0x0C u32 | 0x24E (590) | end of string section = start of binary data |
| +0x10 u32 | 0x1E4 (484) | boundary inside the string table (semantics TBD) |
| +0x1C | `0A2.22.19:27:41` | generator version |
| +0x2F | `Blaupunkt GmbH … @(#)cl_gdf_2_sie.pkb 2.5` | GDF toolchain |
| +0x6A | u16[N], offsets relative to +0x6A | UI string directory |

Decoded strings (cp1252, German) are destination-search menu texts: *Verkehr, Keine Daten, Ortsauswahl, Zielumgebung, Standortumgebung, Ort A-Z, Ort eingeben, Ortsliste, Alle/Ziel auswählen, Alle anzeigen, Eingabe A-Z, Sortieren Distanz/A-Z, Name eingeben, Zielführung, Hauptmenü, Voriges/Aktuelles/Nächstes Objekt*. RF files share the family header (magic u16 0x0064, version 3; generator `Robert-Bosch-Data PTP-Hi-ah … 2.0`) with three u32 section pointers at +0x58.

In the firmware (`NAVECE_M.EXE`, NEC V810) the strings `QUADIDX.DAT` @ `ram:ffc0bbd4` and the template `RF_1_1_?.DAT` @ `ram:ffc0bbc4` sit inside the SDI/CDROM-FS router string region; neither has a direct code reference (no Ghidra xref, no MOVHI+MOVEA pair, no u32 pointer cell) — filenames are assembled in RAM at runtime while the FS enumerates the CD directory (formats `%d%c%d`, `%s%c `, `/Card%d/` nearby).

**Consequence for custom discs:** cluster addressing for routing most likely does not flow through QUADIDX at all; it should live in the MAP00001.MAP (TPMAP2 catalog) / NAV entry-table pair. A custom disc can plausibly keep the donor QUADIDX/RF (stale name search) or ship regenerated stubs — to be confirmed by tracing the coordinate→NAV-file open path and by a head-unit substitution test.

### 4.2. NAV file selection: two candidates rejected, one active

Tracing how the firmware picks a `NAVxxxxx.DAT` for a position (15.11.2026):

- The literal "NAV" appears in code only in the NAVDEMO task (`nd_tsk.c`); production filenames are assembled at runtime (`%d%c%d`, `%s%c ` formats at `ram:ffc0bbe8/bbf4`, no direct references).
- `map_file_open` (`ram:ffc4fe7e`) has a single caller and opens only `MAP00001.MAP`. NAV data is read through the block cache readers (`ram:ffc4f310`, `ram:ffc4f4f2`) sitting on `map_file_read` (`ram:ffc4feb2`, 18 callers) — i.e. by handle/index through the SDI layer, not by per-request name lookup.
- **Rejected: MAP stores NAV file numbers.** Intersections of the MAP u32 value set with each disc's NAV number set are at chance level in both directions (Czech/Poland MAP: own 25/318 vs foreign 70/897 ≈ 7.9% vs 7.8%; Germany MAP: 84/897 vs 31/318).
- **Rejected: TPMAP2 catalog block ↔ NAV file 1:1.** Catalog record counts (1/12/1320/132000 for CZ/POL; 1/12/1200/120000 for DE) do not correlate with NAV file counts (318/897).
- **Rejected: `NAV00001.DAT` as a coordinate→file index** (hypothesised 15.11 morning; resolved the same day): it is the place-name directory, see below.

**Resolved 15.11 (same iteration): NAV00001 is the place-name directory, not a file selector.** Blocks interleave key-sorted records `<u32 key, u16 a, u16 b>` (the leading segment of block 0 uses packed coordinate keys `(y<<16)|x` on a constant ~0x00C00025 raster step) with text pools containing place names in canonical and cross-reference forms: CZ "RADVANICE A BARTOVICE [CZ]", "MOKRA HORA [CZ], BRNO-RECKOVICE"; DE "AACHEN", "AACHEN, ZECHE", "OSNABRÜCK LAND" (cp1252). Together with QUADIDX (search trees/UI strings) and RF (travel guides) it forms the destination-search system.

**Numbering convention rejected 15.11 (static cross-disc test); mount-time scanning is the only remaining model.** Intersections of NAV file numbers between any pair of discs sit at chance level (1–3%). Decisive test: `NAV21793.DAT` is the cluster at 9.72°E 52.45°N (Braunschweig) on the Germany disc but the cluster at 13.98°E 41.01°N (Naples) on Major Roads of Europe — file numbers are disc-local project bookkeeping, so the firmware cannot derive a file from a position by any TeleAtlas numbering rule. Since NAV data reaches the reader only by handle and every NAV file carries bounds in its record headers, the firmware must enumerate `NAV*.DAT` at mount and keep an in-RAM `bounds → (file, entry)` index. Consequences for custom discs: file numbers are arbitrary within `NAV*.DAT`; entry tables and record bounds must be valid; QUADIDX/RF/NAV00001 are search-only and can ship as donor copies.

**Mount path traced 15.11 (iteration 10), refining the model from "mount-time bulk scan" to "lazy per-file mount + runtime cluster directory":** `FUN_ram_ffc44f40` mounts the current NAV container on demand (26-byte primary header via handle `DAT_ram_ffc08edc`, then the entry-table header through the block cache); the state dispatcher `FUN_ram_ffc4522c` and request handler `FUN_ram_ffd47d60` (codes 0x41/0x4c/7/0xd/…) sit above it; the ISO directory is read on demand (`FUN_ram_ffd5ab92` → growing-block reads → `FUN_ram_ffd5cd90` building a **sorted array of directory records** searched by 8-byte filename); no code reference exists to any file-name string (names, including the `.DAT` extension, are copied into RAM at runtime). The navigation layer (`nfc/TPNData.cpp`) maintains a runtime **cluster directory** with lazy insertion — error strings "Failed to find leaf cluster", "cluster header not read into memory", "no space in cluster directory", `ldb_InsertCluster`, "Cluster is not in Memory" — i.e. cluster headers (bounds) are read and inserted when first needed, and position→cluster lookup searches this directory. The file name is never computed from a coordinate; a substituted file with a valid container and cluster bounds should be discoverable exactly like donor files. Filename iteration details (sequential probing vs directory order) do not affect a same-name substitution.

**Test disc assembled 15.11** (workspace `analysis/testdisk/`, not part of this repository): pristine Czech/Poland 2010-2011 CloneCD copy with `/NAV21315.DAT;1` (1,991,121 bytes, smallest donor file ≥ generated container) replaced by the generated Krasnodar container (565 clusters) zero-padded to the same length. Verification: exactly the 973 extent sectors changed, EDC/ECC regenerate byte-identically, `.sub` preserved, all 565 entries decode with zero conflicts. Head-unit field test pending.

Headless-analysis recipe, script inventory, and key firmware addresses: `docs/GHIDRA.md`.

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

Extended header survey (five discs + generated map, 2026-11-15):

- uint32 at `0x00`: low uint16 = offset of the L0 directory (0x03d8–0x042c, matches string-length variability); **high uint16 (0x1ee0–0x4fb8 across discs) remains unclassified** — it does not correlate with file size, block count, directory sizes, or any simple function of them, and all simple checksum hypotheses (CRC32, byte sums) are rejected. Firmware semantics unknown; the generated map keeps the donor value.
- uint32 at `0x18` = address of a 64-byte header block plus `0x40000` (code uses the low 16 bits); bytes `0x1c..0x1f` and `0x20..0x23` are zero on every surveyed disc.
- uint32 at `0x04` = exact file size (all surveyed discs, including the generated map).

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

A zero means no fully local graph under the strict criterion, not absence of navigation data. Other blocks parse structurally but have unresolved endpoints.

### Cross-cluster boundary transitions (confirmed 2026-11-14)

Unresolved endpoints are cluster-boundary exits, and the stitching key is the pair (word body, geometry):

1. Local nodes of links with an unresolved endpoint sit twice as close to the cluster bounds edge as nodes in general (median relative distance 0.054 of cluster size vs 0.113).
2. For two clusters with overlapping bounds, links with unresolved endpoints whose raw words share the same body `(raw & 0x3ff)` have local endpoints that coincide spatially: 51 consistent pairs, median offset 55 internal units (~20 m), maximum ~500 units. Full words may differ in high bits (`0xe075` in one cluster vs `0xa075` in the neighbor), so the body is the boundary-crossing number while high bits are attributes (0x8000 selects the first/second endpoint; 0x4000 and other bits mark side/type).
3. The word identifies the boundary, not a single node: five distinct links in Europe entry 0462 sharing word `0xe075` each stitch to a distinct link with `0xa075` in neighboring clusters 0488/0525.

Coverage of the 948 unresolved endpoints by this rule is currently limited only by the sample: 24 NAV files out of ~1,983 on the discs were unpacked and indexed, so most boundary neighbors are absent from the stitch index. A full-NAV run is the next step.

Six pairs of consecutive entries with identical cluster `base`/bounds (95/96, 455/456, 457/458, 459/460, 469/470, 471/472) form a detail hierarchy: the small block is a coarse level (3–12 nodes, through-links of 82k–536k internal units crossing the whole area, coverage 0.88–1.0) and the large block is a fine level (29–184 nodes, median link 4.6k–10k). The level-selection rule used by the router is not yet recovered.

Link weight attribute: `field04_le32` of a resolved link equals the geometric path length divided by a stable factor of ~316.3 internal units (median ratio 316.3, range 294–347 over 105 buckets, prediction residual p90 = 3.2 %). It is computable from geometry when generating a cluster: `field04 = round(path_length / 316.3)`. A road-class attribute is not isolated yet; link flags are a subsection mask.

Control examples:

- Czech/Poland entry 241: 11 nodes, 11 links, 21 references, zero conflicts/errors.
- Germany entry 158: 346 nodes, 356 links, 709 references, zero conflicts/errors.

### 6.3 Subsection layout, graph mutation, and NAV write-back (confirmed 2026-11-14)

Full subsection layout, validated by area-tiling across all 128 parsed clusters (zero hard overlaps; apparent overlaps are content deduplication):

- Nodes with flag bit `0x0001` carry a second four-byte descriptor before the link-list descriptor: `(offset, count)` pointing into the node-subsection area, payload of `count` items × 4 bytes. Semantics unknown; carried raw. All payload offsets are 2-byte aligned; 3,746 of 9,711 are not 4-byte aligned.
- Link subsection descriptors form one contiguous array at `subsection_base` (4 bytes per set bit 0..4, in bit order); payloads live separately. Strides: shape/list4 4 bytes per item; annotations (bit 0) and unknown bit 2 payloads are **2 bytes per item** (17,121 and 12,649 occurrences across 35,876 links). Links with no subsection bits carry a stale unused `subsection_base`.
- Node link references are one-based link numbers; bit `0x8000` marks the node as the link's second endpoint.

`tools/tpnav2_graph_mutate.py` builds a `ClusterModel` (all node/link fields plus raw prefix/annotation/bit2 payloads and unknown small-section blobs), mutates it, and performs a full re-layout: node descriptor chains, node prefix/ref payloads, link descriptor arrays and payloads, section table, and node coordinates regenerated from the model. Batch test `tools/test_tpnav2_mutate.py` on five clusters (including the richest shape/list4/prefix cases):

- appending a node and a link resolves from both node-link references with zero endpoint conflicts;
- serialization is idempotent (mutate → parse → re-serialize is byte-identical);
- all pre-existing nodes, links, bounds, and header fields survive unchanged; raw payloads survive byte-for-byte;
- the validation-error set after mutation exactly equals the original set (no errors introduced or lost).

`tools/tpnav2_nav_patch.py` writes a mutated cluster back into a NAV container. For compressed entries (253 of 256 in `NAV20001.DAT`), the padded-to-logical-size uncompressed block is appended at end of file and its remap entry rewritten to point at it with `compression_flag = 0`, mirroring the firmware's backward search for the last exact logical match. End-to-end check: patched container re-opened, block decoded, graph parsed with zero errors/conflicts, semantic identity with the reference mutation, and all 256/256 entries still decode.

Round-trip provenance: `tpnav2_graph_write.py` rebuilds all 128 clusters byte-identically (conservative in-place strategy); the parser output is complete for the graph layer.

### 6.4 Cluster generator from a minimal model (confirmed 2026-11-14)

`tools/tpnav2_cluster_gen.py` (`ClusterBuilder`) emits a valid cluster with no source bytes: header per live conventions (`byte02=8`, `byte03=1`, `field11=4`, `field04_le32=0xB8010001`, four bounds corners), sections `0x0040/0x0080/0x0400` only, absolute-internal-coordinate API (`abs = base + (delta << shift)`), link weight `field04 = round(path_length / 316.3)` from geometry, and self-assigned boundary words (`0xA000|body` / `0xE000|body`, matching the observed `0xa075↔0xe075` pair pattern). Bodies are chosen above the node count so the parser's raw fallback stays out of range — the boundary end remains unresolved exactly like live data (a body inside the node range would silently pseudo-resolve to a real node, a quirk also present in live clusters such as entry 0241, where node 1's reference `0x0C0B` shadows the boundary word `0xE075`).

Demo: two neighbouring generated clusters (158 B and 146 B) sharing boundary x=15000 with overlapping bounds parse with zero conflicts and exactly one expected out-of-range fallback error each, serialize idempotently through the mutator round-trip, and stitch under the confirmed rule: `0xA25F ↔ 0xE25F`, body 607, local-end distance 0.0.

### 6.5 OSM region grid and from-scratch NAV container (confirmed 2026-11-14)

`tools/tpdx_osm_grid.py` turns an OSM extract into a stitched grid of generated clusters:

- drivable highway classes are decimated (20 m step; shared intersection vertices and way terminals always kept), split at uniform cell borders, and each border crossing becomes a shared node in both adjacent clusters plus a boundary word link (`node(cut)→word`, field04=0); geometry from the crossing into the cell is a normal link carrying intermediate vertices as shape points;
- boundary word bodies are assigned after the whole grid is built: `body = 1023 − pair_ordinal`, largest clusters claiming the highest bodies first, with the hard check `body > max(nodesA, nodesB)` (10-bit refs: ≤1000 links and ≤1023 nodes per cluster; ≤0xFFF0 bytes per cluster); the grid refines automatically (×2 per axis, up to 32×32) until all limits hold;
- three defects found and fixed during validation: link-number leakage into the 10-bit reference field, neighbour identification by point reflection (wrong at shallow crossing angles — replaced by the crossing axis), and zero-area runs (way ending exactly on a border / corner clips — absorbed into neighbours).

Results on real OSM extracts (Overpass API):

| Region | Ways | Grid | Clusters | Boundary ends | Stitched | Conflicts |
|---|---:|---:|---:|---:|---:|---:|
| Olomouc (13×15 km) | 15,702 | 32×32 | 565 | 4,850 | 4,850 (100 %) | 0 |
| Krasnodar, Russia (17×28 km) | 26,477 | 32×32 | 565 | 11,344 | 11,344 (100 %) | 0 |

Visual check (`tools/render_grid_check.py`, `results/grid-check-krasnodar.png`): generated geometry overlays the OSM street network exactly, including the Kuban river bend and radial highways.

`tools/tpnav2_nav_build.py` assembles a NAV container from scratch, mirroring observed real conventions: contiguous logical image starting at offset 320, `<IHHIHH>` entries with field06=0, uncompressed blocks (flag=0) packed after the table, and the 320-byte file head copied from a real container. The Krasnodar container holds 565 entries (the format's u32 entry_count allows more than the donor's 256) in 1,967,788 bytes; every entry round-trips byte-identically through our own reader with zero endpoint conflicts. Firmware acceptance of >256 entries and of our logical addressing scheme is verifiable only on a head unit.

Remaining blocker for a bootable disc: road attribute semantics (class/speed/direction) for routing and a hardware confirmation of the mount-time scan model (record bounds in generated entry tables are valid; numbering is arbitrary).

## 7. Executable and emulation

`NAVECE_M.EXE` is ELF32 little-endian for NEC V810 (`e_machine=36`), with no symbol table. It is not a desktop Linux or Windows CE executable. A normal virtual machine does not supply the V810 processor, memory map, CD calls, CAN/peripherals, graphics, input, audio, and initialization environment of a head unit.

Static decoder recovery has been more productive than treating a generic VM as a ready viewer. A full head-unit UI or emulation environment is not implemented.

### 7.1 Firmware lineage across disc generations (three-way diff, 2026-11-16)

The navigation executables of three disc generations were compared function-by-function with the Ghidra hash pipeline (`docs/GHIDRA.md`) and the standalone matcher `tools/fw_match_three_way.py`:

| Generation | Disc year | Executable | Functions |
|---|---|---|---|
| 182.01 | 2001 | `NAVECE_2001.EXE` | 2,480 |
| 289.25 | 2003 | (Germany 2003 disc) | — |
| 390.23 | 2010 | `NAVECE_M.EXE` | — |

Exact body-hash matches: 2001∩2003 ≈ 65 %, 2001∩2010 ≈ 61 % of the 2001 function set. The break in the MAP loader between 182.01 and 289.25 is visible as a changed function cluster.

Findings:

- **The map-bounds gate exists in all three generations.** The function that rejects coordinates outside the disc's coverage (2010: `FUN_ffcf8b1c`, 2003: `FUN_ffcea6d4`) has an exact-hash counterpart in the 2001 executable as well (698 instructions; the gate block is verbatim in the decompilation). The bounds gate is therefore **not** an anti-copy addition of later discs — it is original coverage logic.
- **TMC (traffic message) support appears with 289.25** (`CidBestOneCell*` symbols absent from 182.01).
- **C++ runtime type information appears with 390.23**; the 2001/2003 builds lack the RTTI sections.
- ETAK/Bosch copyright strings are present in all three generations, consistent with a single toolchain lineage.

### 7.2 "Firmware update from disc" = language-image rewrite of the boot flash

Field observation: inserting certain discs (e.g. the 2003 Germany disc) makes the head unit visibly "install firmware" before navigation starts; swapping between two same-generation discs does not. Static analysis of the executable (`tpmap32v\tpmapplg.cpp`, embedded source paths, offset ≈ 0xddb0) identifies this as a rewrite of the unit's **data flash** with the language-specific UI images shipped on the disc:

- File names `V01_006X.DAT` / `V01_N06X.DAT` and a device list `SFlash,BFlash,Card1,Card2,Card3,CDROM` are embedded in the executable.
- Each `.DAT` pair member is 1,048,580 bytes: a 4-byte header `47 0f 00 00` (u16 = language letter) plus a 1 MiB payload. Two members = 2 MiB, matching the **AM29LV160** boot/data flash (BFlash, IC D5830 on the processor board, see `docs/hardware/COMAND_DX_CD_drive.md`).
- The decision whether to reprogram is taken from the image header already present in flash — this is why a language/generation change triggers the install pass and like-for-like disc swaps do not.
- The payload is obfuscated (not a plain bitmap/ROM image); the transform is unresolved.

Consequence for custom discs: the language images travel with the donor disc and can be **copied as-is** — a map-only update (e.g. a Russian-region disc built from a Czech/Poland donor) needs no new firmware payloads, only the donor's V01 pair preserved byte-identical.

## 8. Modification and recording experiments

The experimental same-length patcher replaces an ISO extent only in a CloneCD copy, requires equal byte length, recalculates affected EDC/ECC, and copies `.ccd` and `.sub`. It can refuse to overwrite known special sectors when supplied with a verification report.

The regression test changed one byte in `CONFIG.SYS`, affecting only LBA 5037; all other 128,911 sectors and `.sub` were preserved. This proves a low-level operation on a PC, not map editing or compatibility with a head unit.

### 8.1 Head-unit field tests (2026-11-15, Mercedes COMAND 2.5-class DX unit)

| Disc | Content | Result |
|---|---|---|
| №3 | untouched CloneCD copy of CZ/POL 2010-2011 | **Accepted** (CloneCD 5.3.4.0 + Teleatlas profile, 1x, weak-sector amplify) |
| №2 | donor image with generated Krasnodar TPNAV2 container in `NAV21315.DAT` | **Accepted**; search index stays donor-side as predicted, map read confirmed |
| v2 | **fully rebuilt ISO** with generated TPMAP2 map of Krasnodar Krai (all new sectors, correct EDC/ECC) | **Rejected** — HU retries one sector rhythmically, then "not a navigation CD" |
| v3 | donor image patched in place: generated TPMAP2 MAP extent + Krasnodar NAV extent | **Rejected** — HU reads through the disc normally (no rhythmic re-read loop) but refuses activation with "insert navigation CD"; MAP-header validation in the firmware is the suspected gate |
| v4 | donor image, Poland/Czech regions removed, generated TPMAP2 Krasnodar Krai map | **Accepted** — but the Krasnodar geometry is not visible in the rendered map and `KRASNODAR` does not appear in destination search (search index stays donor-side); where Europe was removed the renderer shows sea at 100–200 km scale, while European roads still appear at ≤500 km, so remaining visuals come from untouched donor data |

The v2 rejection, combined with the accepted donor-layout discs, isolates the disc-level requirements that a from-scratch build must satisfy: the weak-sector protection gap, the original TOC/file order, and possibly fixed-LBA signature checks. The in-place patcher (`tools/patch_donor_image.py`) is the working build path until the protection check is fully characterized.

A real map update additionally requires:

1. current road geometry, restrictions, addresses, and POI;
2. valid source data for Bosch compilation or an equivalent writer;
3. TPMAP2 and TPNAV2 serialization;
4. rebuilt QUADIDX and related search/routing tables;
5. version and integrity reconciliation;
6. ISO/raw reconstruction **preserving the protection layers** (or a head unit that accepts regenerated media);
7. CD-R recording and physical head-unit testing.

No complete working chain for all of these steps is claimed.

## 9. Current capability matrix

| Task | Status |
|---|---|
| Inspect disc filesystem | Complete and validated on 11 ISO files |
| Extract five source sets with hashes | Complete |
| Read TPMAP2 metadata/directories | Complete for checked formats |
| Render TPMAP2 geometry | Working in internal units |
| Decompress TPNAV2 | Validated on 3,815 entries |
| Recover local TPNAV2 nodes/links | Working for 37 of 128 candidates; parser matches the firmware load pass |
| Render fully classified roads | Incomplete; type semantics remain unresolved |
| Build a global routing graph | Cross-cluster stitching confirmed on the full Germany run: 20,254 of 82,807 boundary ends stitched (24.5 %), median offset ~10 m; remainder explained by absent neighbour countries / duplicate boundary numbers |
| Convert coordinates to WGS84 | Fitted datum: X = 11.93M·lon, Y = 11.93M·lat (plate-carree-like; 1 unit ≈ 9.3 mm), 249 city-label anchors, residual median ~0.6 km; sufficient for OSM import, not for stitching to untouched clusters (~10 m would need a geometry-based refit) |
| Edit a road and serialize all data | Graph mutation with full re-layout proven (idempotent, lossless, zero new validation errors on 5 clusters); NAV container write-back proven end-to-end (256/256 entries still decode) |
| Build an updated map from OSM | **Cluster grid proven on real regions**: Olomouc 4,850/4,850 boundary ends stitched, Krasnodar 11,344/11,344, zero conflicts; NAV container from scratch (565 entries) round-trips byte-identically. Disc-level addressing: numbering/convention schemes all rejected statically; mount-time entry-table scan is the surviving model, awaiting mount-path trace + hardware test. Missing: road attributes, head-unit test |
| Validate a modified CD-R on hardware | **CD-R burning solved** (CloneCD + Teleatlas profile, 1x, amplify); donor-layout discs with generated TPNAV2 content accepted by the HU. From-scratch ISO rebuild **rejected** by the HU — weak-sector protection layer (§3.1) is enforced. In-place patched discs: v3 (generated MAP+NAV) rejected at activation, v4 (generated MAP, donor regions removed) accepted — but generated geometry not yet rendered, MAP-header validation is the open gate (§8.1, §10) |

## 10. Next research target

The v3 rejection (normal disc read, then activation refused) points at MAP-header validation in the firmware. Next: locate and understand the TPMAP2 header acceptance checks in `NAVECE_M.EXE` (V810, Ghidra project) — what fields the loader requires beyond geometry — and diff the MAP loader between the 2003 and 2010 executables to see what changed at the 289.25 break (§7.1). The v4 acceptance shows the protection layer and donor layout are satisfiable; closing the header-validation gap should make a generated-region map actually render.

In parallel: characterize the weak-sector check precisely (which LBAs are read and what response is expected), resolve the NAV2 geometry attribute semantics (id bytes, `k` counter, key table — `docs/NAV2_GEOMETRY.md`), road attributes for routing (class, speed, direction) from link-flag/list4 correlations, LZ compression for tighter generated clusters, and a geometry-based datum refit (~10 m) only for discs that stitch generated clusters to untouched TeleAtlas neighbours.

Recover nonlocal/cross-cluster TPNAV2 endpoint references. Aligning the resulting graph with NAV2 geometry should also help resolve the semantics of `0x10` and `0xf0` without guessing from appearance alone.

Hardware-side enablers: dump the three flash devices (SFlash via the ERIC-2 emulator interface, BFlash via the SPY pins — see `docs/hardware/COMAND_DX_CD_drive.md`) to capture a real disc-triggered language-image rewrite, and, if a CD-emulator path materializes, replace CD-R burn cycles with direct image swapping.
