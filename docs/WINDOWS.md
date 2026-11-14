# Windows 10 visualization guide

This guide starts from a fresh 64-bit Windows 10 installation. No Python, Git, development tools, ISO mounting software, or administrator account is required.

## 1. Obtain the repository

Download the repository ZIP from GitHub and extract it to a normal writable folder, for example:

```text
C:\Users\YourName\Documents\travelpilot-dx-research
```

Do not run it from inside the ZIP, a read-only directory, or a protected system directory.

## 2. Prepare the source image

Use your own original, unfragmented CloneCD data-track image with these properties:

- `.img` extension;
- Mode 1 sectors;
- 2,352 bytes per raw sector;
- an unmodified file whose size is an exact multiple of 2,352.

The source image is opened read-only. Keep its companion `.ccd` and `.sub` files even though visualization does not need them. BIN/CUE, compressed, split, or Mode 2 images are not accepted by this workflow.

A standard 2,048-byte-sector ISO is also supported.

## 3. Run the script

Open the Start menu, type **PowerShell**, and open Windows PowerShell. Change to the repository directory, adjusting the path as needed:

```powershell
cd "$env:USERPROFILE\Documents\travelpilot-dx-research"
```

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\visualize.ps1 -DiskImage "D:\discs\germany.img"
```

You can also run `visualize.bat` from Command Prompt:

```bat
visualize.bat "D:\discs\germany.img"
```

The `-ExecutionPolicy Bypass` setting applies only to this PowerShell process. It does not change the persistent Windows execution-policy setting.

## 4. What happens on the first run

The script performs these steps automatically:

1. Looks for Python 3.10 or newer.
2. If Python is absent or too old, downloads the official Python 3.12.10 64-bit installer from `www.python.org` over HTTPS.
3. Verifies that the downloaded installer has a valid Authenticode signature.
4. Installs a private Python runtime under `.runtime\python` in the repository. It does not modify the system PATH or install Python for all users.
5. Creates an isolated `.venv` environment and installs the packages in `requirements.txt`.
6. Converts the CloneCD `.img` into `output\disc.iso`.
7. Extracts only `MAP00001.MAP`, writes `output\MAP00001.MAP.json` with its size and SHA-256, and does not extract the rest of the disc.
8. Renders `output\map-L1.png` and its `map-L1.stats.json` sidecar.
9. Opens the PNG in the default Windows image viewer unless `-NoOpen` was specified.

Internet access is required for the runtime and package installation. Later runs normally reuse the installed environment, but conversion and extraction are repeated to avoid silently using stale output from another source disc.

## 5. Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `-DiskImage` | required | Path to a CloneCD `.img` or ISO file |
| `-OutputDirectory` | `output` | Writable directory for generated data |
| `-Level` | `1` | TPMAP2 hierarchy level: 0, 1, 2, or 3 |
| `-Indices` | all blocks | Comma-separated tile indices or inclusive ranges |
| `-IncludeAreas` | off | Include table-A polygons in addition to table-B lines |
| `-NoOpen` | off | Do not open the rendered PNG automatically |

Examples:

```powershell
# Render an ISO without opening the result
.\visualize.bat "D:\discs\germany.iso" -NoOpen

# Render selected detailed tiles with polygons
.\visualize.bat "D:\discs\germany.img" -Level 3 -Indices "43661,44814-44816" -IncludeAreas

# Use another output directory
.\visualize.bat "D:\discs\germany.img" -OutputDirectory "D:\dx-output"
```

Level 1 is the recommended first render. Level 2 can contain tens of thousands of blocks. Level 3 should normally be restricted with `-Indices`.

## 6. Interpreting the output

The PNG displays decoded geometry with a legend keyed by numeric feature type. These are **not fully classified road classes**. Coordinates are signed internal TPMAP2 units, not latitude/longitude and not WGS84. The project has not yet established the projection, datum, or final scale conversion.

The stats JSON records decoded block counts, feature counts, geometry bounds, and the internal coordinate-system warning.

## 7. Troubleshooting

### “Bad CD sync pattern” or “Expected Mode 1”

The input is not a supported unfragmented Mode 1/2352 image. Do not rename another format to `.img`; convert or re-rip it correctly.

### “size is not a multiple of 2352”

The file is truncated, compressed, split, or not a raw Mode 1/2352 data track.

### “TPMAP2 signature is absent”

The extracted `MAP00001.MAP` is not a compatible indexed TPMAP2 file, or the file is damaged.

### “Selected blocks contain no visible geometry”

Choose different tile indices, another level, or add `-IncludeAreas`. Empty directory entries are valid in sparse maps.

### Download or package installation fails

Check internet access, DNS, proxy configuration, and available disk space. Corporate TLS interception can prevent package installation or signature validation. The script deliberately stops rather than executing an installer with an invalid signature.

### PowerShell cannot be found

Use the `visualize.bat` wrapper from Command Prompt. Windows PowerShell 5.1, included with Windows 10, is sufficient.

## 8. Privacy and source preservation

The bootstrap contacts Python.org and the Python package index to obtain software. The visualization tools themselves process the disc locally and contain no upload step. Original source images are never used as output destinations.
