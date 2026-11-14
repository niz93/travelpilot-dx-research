# Ghidra headless analysis of NAVECE_M.EXE

Recipe and scripts for reproducing the firmware-side findings of this research
with Ghidra 12.x against `NAVECE_M.EXE` (NEC V810). Disc firmware is **not**
included in this repository; extract it from a unit update disc you own
(e.g. with `tools/extract_iso.py`).

## Environment used

- Ghidra 12.2 PUBLIC, project `DX` on a local NTFS drive
- JDK 25 (`tools/jdk/jdk-25.0.5+8` in our workspace; any JDK 17+ should work)
- Git Bash on Windows 10 (MSYS2 argument conversion is the main pitfall)

## Import (once)

```bash
export JAVA_HOME='<path>/jdk-25.0.5+8'
export APPDATA='<workspace>/analysis/appdata'
export LOCALAPPDATA='<workspace>/analysis/localappdata'
export TEMP='<workspace>/analysis/temp'; export TMP="$TEMP"
export MSYS_NO_PATHCONV=1

<ghidra>/support/analyzeHeadless.bat <proj-dir> DX \
  -import extracted/germany/NAVECE_M.EXE -processor V810:LE:32:default \
  -analysisTimeoutPerFile 1200 -log analysis/ghidra-import.log
```

## Running a script against the imported program

```bash
<ghidra>/support/analyzeHeadless.bat <proj-dir> DX \
  -process NAVECE_M.EXE -noanalysis \
  -scriptPath tools/ghidra_scripts \
  -postScript <Script>.java <out-dir> [script args...] \
  -log analysis/<log>.log
```

### Hard-won gotchas (cost us a full evening)

1. **`-process` value must not contain `/`.** Ghidra validates it in
   `HeadlessOptions.setRunScriptsNoImport` and throws
   `IllegalArgumentException: invalid filename specified` (disassemble
   `Base.jar` if in doubt). Use the bare program name `NAVECE_M.EXE`.
   A leading `/` ("project-root path") is rejected in this version.
2. **The project location and name are two separate arguments**:
   `analyzeHeadless <projectDir> <projectName> ...` — passing
   `<projectDir>/<projectName>` as one token shifts positional parsing and
   produces confusing `Bad argument: <file>` errors.
3. **`-log` appends** to an existing log file. Always read the tail of the
   fresh run; stale exceptions from earlier runs sit above.
4. In Git Bash, either `export MSYS_NO_PATHCONV=1` for everything, or let MSYS
   convert every argument — mixing (`/process`-style flags) breaks silently.
5. JDK matters: Ghidra 12.2 refused to start under the bundled JDK 21 copy we
   first tried and worked with JDK 25 (`JAVA_HOME` must be exported for the
   bat launcher).

## Scripts in tools/ghidra_scripts

| Script | Purpose |
|---|---|
| `ResolveMapRefs.java` | Find MOVHI+MOVEA address constructions pointing at target strings (edit `needles` for your strings), export referring functions (.c/.asm) |
| `ResolveNavRefs.java` | Same, aimed at NAV-related strings |
| `ResolveQuadRefs.java` | Same, aimed at `QUADIDX.DAT`/`CONFIG.SYS`-style names |
| `FindStringXrefs.java` | Full xref sweep for one string: Ghidra references, raw u32 pointer scan over all memory; exports referring functions. Args: `<out-dir> <needle>` |
| `DumpAddressBytes.java` | Hex dump of RAM addresses through the program memory map. Args: `<out.txt> <addr> <len> [...]` |
| `ExportCallers.java` | Export callers of the map I/O trio (`map_file_read`, `map_file_open`, `map_open_directory`) |
| `ExportFunctionRange.java`, `ExportInstructionRange.java`, `ExportV810Functions.java`, `InspectMemory.java`, `InspectV810.java` | Bulk disassembly/decompilation helpers used during recovery |

## Key firmware addresses (NAVECE_M.EXE, Germany disc)

| Address | Item |
|---|---|
| ram:ffc0bbc4 | `RF_1_1_?.DAT` filename template (travel-guide index variants `_*`, `G`, `Z`) |
| ram:ffc0bbd4 | `QUADIDX.DAT` string (no direct code reference; names assembled in RAM) |
| ram:ffc0bbe8 / ffc0bbf4 | `«%s%c »` / `«%d%c%d»` filename construction formats |
| ram:ffc0bdf8–ffc0c138 | SDI/CDROM-FS router string region (`cdromfsroute.cpp`, `DfsRoute.cpp`) |
| ram:ffc4fe7e | `map_file_open` — single caller, opens only `MAP00001.MAP` |
| ram:ffc4feb2 | `map_file_read` — block read, 18 callers (block cache path) |
| ram:ffcf0798 | `map_open_directory` — TPMAP2 plugin open/read of `MAP00001.MAP` |
| ram:ffc4f310 / ram:ffc4f4f2 | NAV block cache readers above `map_file_read` |

## Findings these scripts support

- `QUADIDX.DAT`/`RF_*.DAT` are **name-search indexes** (destination/travel-guide
  search), not routing address maps — see `docs/TECHNICAL_REPORT.md` §4.1.
- No direct code references to `QUADIDX.DAT` or the `RF_1_1_*.DAT` template
  exist: the CD is enumerated by the SDI layer and filenames are assembled in
  RAM at runtime.
- NAV containers are read by index/handle through the block cache, not by name
  on each request.
