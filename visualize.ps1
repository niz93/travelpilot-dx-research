[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$DiskImage,

    [string]$OutputDirectory = "output",

    [ValidateSet(0, 1, 2, 3)]
    [int]$Level = 1,

    [string]$Indices,

    [switch]$IncludeAreas,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonVersion = "3.12.10"
$MinimumPython = [version]"3.10"

function Resolve-FullPath([string]$Path) {
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Test-Python([string]$Executable) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $false
    }
    try {
        $versionText = & $Executable -c "import platform; print(platform.python_version())" 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        return ([version]$versionText.Trim() -ge $MinimumPython)
    }
    catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        (Join-Path $Root ".runtime\python\python.exe")
    )

    $pythonCommand = Get-Command "python.exe" -CommandType Application -ErrorAction SilentlyContinue
    if ($pythonCommand) { $candidates += $pythonCommand.Source }

    $pyCommand = Get-Command "py.exe" -CommandType Application -ErrorAction SilentlyContinue
    if ($pyCommand) {
        try {
            $pyPython = & $pyCommand.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $pyPython) { $candidates += $pyPython.Trim() }
        }
        catch { }
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Python $candidate) { return $candidate }
    }
    return $null
}

function Install-PrivatePython {
    $runtimeDirectory = Join-Path $Root ".runtime"
    $installer = Join-Path $runtimeDirectory "python-$PythonVersion-amd64.exe"
    $target = Join-Path $Root ".runtime\python"
    $uri = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"

    New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
    Write-Host "No suitable Python was found. Downloading official Python $PythonVersion..."
    Invoke-WebRequest -Uri $uri -OutFile $installer -UseBasicParsing

    $signature = Get-AuthenticodeSignature -FilePath $installer
    if ($signature.Status -ne "Valid") {
        throw "The Python installer signature is invalid or cannot be verified: $($signature.Status)"
    }

    Write-Host "Installing a private Python runtime (no system PATH changes)..."
    $arguments = @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=`"$target`"",
        "Include_launcher=0",
        "Include_pip=1",
        "Include_test=0",
        "PrependPath=0",
        "Shortcuts=0",
        "AssociateFiles=0"
    )
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) {
        throw "Python installer failed with exit code $($process.ExitCode)."
    }

    $executable = Join-Path $target "python.exe"
    if (-not (Test-Python $executable)) {
        throw "The private Python installation did not produce a usable interpreter."
    }
    return $executable
}

function Invoke-Python {
    & $script:VenvPython @args
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: $($args[0])"
    }
}

try {
    $source = Resolve-FullPath $DiskImage
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Source image not found: $source"
    }
    $extension = [IO.Path]::GetExtension($source).ToLowerInvariant()
    if ($extension -notin @(".img", ".iso")) {
        throw "DiskImage must be a CloneCD .img or a standard .iso file."
    }

    $output = Resolve-FullPath $OutputDirectory
    New-Item -ItemType Directory -Force -Path $output | Out-Null

    $basePython = Find-Python
    if (-not $basePython) { $basePython = Install-PrivatePython }
    Write-Host "Using base Python: $basePython"

    $script:VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Python $script:VenvPython)) {
        Write-Host "Creating the isolated Python environment..."
        & $basePython -m venv (Join-Path $Root ".venv")
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python virtual environment." }
    }

    Write-Host "Installing or verifying Python dependencies..."
    Invoke-Python -m pip install --disable-pip-version-check -r (Join-Path $Root "requirements.txt")

    if ($extension -eq ".img") {
        $iso = Join-Path $output "disc.iso"
        Write-Host "Converting the CloneCD image; the source remains unchanged..."
        Invoke-Python (Join-Path $Root "tools\clonecd_to_iso.py") $source $iso
    }
    else {
        $iso = $source
    }

    $map = Join-Path $output "MAP00001.MAP"
    Write-Host "Extracting only MAP00001.MAP..."
    Invoke-Python (Join-Path $Root "tools\extract_map.py") $iso $map

    $rendered = Join-Path $output "map-L$Level.png"
    $renderArguments = @(
        (Join-Path $Root "tools\tpmap_geometry.py"),
        "render",
        $map,
        "--level", "$Level",
        "--output", $rendered
    )
    if ($Indices) { $renderArguments += @("--indices", $Indices) }
    if ($IncludeAreas) { $renderArguments += "--include-areas" }

    Write-Host "Rendering TPMAP2 geometry in internal map units (not WGS84)..."
    Invoke-Python @renderArguments

    Write-Host ""
    Write-Host "Visualization complete: $rendered" -ForegroundColor Green
    Write-Host "Source image was not modified."
    if (-not $NoOpen) { Start-Process -FilePath $rendered }
}
catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
