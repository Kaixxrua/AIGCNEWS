[CmdletBinding()]
param(
    [switch]$NoBuild,
    [switch]$MaterialOnly,
    [ValidatePattern('^v[0-9]+$')][string]$Version = 'v91',
    [ValidateRange(1024, 65535)][int]$Port = 4231
)

$ErrorActionPreference = 'Stop'
if ($NoBuild -and $MaterialOnly) {
    throw '-MaterialOnly requires cache verification and a fresh export; it cannot be combined with -NoBuild.'
}
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$WorkspaceRoot = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot '..')).Path
$PreviewRoot = Join-Path $WorkspaceRoot 'artifacts'
$BuildRoot = Join-Path $PreviewRoot $Version
$GodotExecutable = Join-Path $WorkspaceRoot '.tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe'
$RunStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$null = New-Item -ItemType Directory -Path $BuildRoot -Force

function Invoke-CheckedGodot {
    param([string]$Stage, [string[]]$EngineArguments)
    $StageLog = Join-Path $BuildRoot "$RunStamp-$Stage.log"
    & $GodotExecutable --log-file $StageLog @EngineArguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Godot $Stage failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath $StageLog)) { throw "Missing Godot log: $StageLog" }
    $StageText = Get-Content -LiteralPath $StageLog -Raw
    if ($StageText -match '(?m)(SCRIPT ERROR:|SHADER ERROR:|ERROR:)') {
        throw "Godot reported an error during $Stage. Inspect $StageLog"
    }
    if ($Stage -in @('source-check', 'pack-check')) {
        if ($StageText -notmatch 'MEADOW_CITY_ROOT_AUDIT: (\d+)/(\d+) mesh feet supported') {
            throw "City foundation audit is missing. Inspect $StageLog"
        }
        if ([int]$Matches[1] -ne [int]$Matches[2] -or [int]$Matches[2] -le 100) {
            throw "Not every measured city foot is supported. Inspect $StageLog"
        }
    }
    if ($Stage -eq 'weather-check' -and $StageText -notmatch 'MEADOW_WEATHER_AUDIT: PASS') {
        throw "Weather transition regression test did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'cache-bake' -and $StageText -notmatch 'MEADOW_BAKE_AUDIT: PASS') {
        throw "Static geometry bake did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'material-cache-check') {
        if ($StageText -notmatch 'MEADOW_MATERIAL_CACHE_AUDIT: PASS; 5/5 current bundles; version ([^;\r\n]+); source_signature ([0-9a-f]{64});') {
            throw "Independent current-cache verification did not complete. No material-only export is permitted. Inspect $StageLog"
        }
        $VerifiedVersion = [regex]::Escape($Matches[1])
        $VerifiedSignature = $Matches[2]
        foreach ($CachedGroup in @('terrain', 'detail', 'foothill', 'riverbank', 'brush')) {
            if ($StageText -notmatch "MEADOW_MATERIAL_CACHE_FILE: $CachedGroup; version $VerifiedVersion; source_signature $VerifiedSignature(?:\r?\n|$)") {
                throw "Missing matching $CachedGroup cache marker. No material-only export is permitted. Inspect $StageLog"
            }
        }
    }
    if ($Stage -eq 'reported-fixes-check' -and $StageText -notmatch 'MEADOW_REPORTED_FIXES_AUDIT: PASS') {
        throw "Clarity, bank support and distant grove regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'outcrop-check' -and $StageText -notmatch 'MEADOW_OUTCROP_INTEGRATION_AUDIT: PASS') {
        throw "Real erosion openings and complete walking-area regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'city-integration-check' -and $StageText -notmatch 'MEADOW_CITY_INTEGRATION_AUDIT: PASS') {
        throw "City aspect, window coverage and terrain preservation regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'window-sampling-check' -and $StageText -notmatch 'MEADOW_WINDOW_SAMPLING_AUDIT: PASS') {
        throw "Subpixel window coverage regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'ecotone-check' -and $StageText -notmatch 'MEADOW_ECOTONE_AUDIT: PASS') {
        throw "Grounded tapered vegetation, walking clearance and triangle-budget regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'rock-relief-check' -and $StageText -notmatch 'MEADOW_ROCK_RELIEF_AUDIT: PASS') {
        throw "Actual rock relief, turf edge and complete terrain regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'lighting-check' -and $StageText -notmatch 'MEADOW_LIGHTING_AUDIT: PASS') {
        throw "Material lighting, shadow budget and preserved geometry regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'riverbank-check' -and $StageText -notmatch 'MEADOW_RIVERBANK_AUDIT: PASS') {
        throw "Embedded bank volume, grounded riparian plants and preserved geometry regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'shore-terrain-check' -and $StageText -notmatch 'MEADOW_SHORE_TERRAIN_AUDIT: PASS') {
        throw "Camera-visible macro shore deformation and preserved world regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'meadow-massing-check' -and $StageText -notmatch 'MEADOW_MASSING_AUDIT: PASS') {
        throw "Actual broad-leaf footprint, populated links and unaffected geometry regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'cliff-planes-check' -and $StageText -notmatch 'MEADOW_CLIFF_PLANES_AUDIT: PASS') {
        throw "Actual camera-visible cliff planes and unaffected stone regression did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'canopy-brush-check' -and $StageText -notmatch 'MEADOW_CANOPY_BRUSH_AUDIT: PASS') {
        throw "Profiled canopy, real rooted branches and full play-space preservation did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'foliage-tone-check' -and $StageText -notmatch 'MEADOW_FOLIAGE_TONE_AUDIT: PASS') {
        throw "Plant-only reflectance, retained light/shadow state and v75 world preservation did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'architecture-check' -and $StageText -notmatch 'MEADOW_ARCHITECTURE_AUDIT: PASS') {
        throw "Architecture registration, windows and preserved world geometry did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'herb-check' -and $StageText -notmatch 'MEADOW_HERB_AUDIT: PASS') {
        throw "Native herb source, curved root support and world-preservation check did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'herb-source-check' -and $StageText -notmatch 'MEADOW_HERB_SOURCE_AUDIT: PASS') {
        throw "Native herb atlas alpha and crop registration did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'scrub-source-check' -and $StageText -notmatch 'MEADOW_SCRUB_SOURCE_AUDIT: PASS') {
        throw "New six-module source alpha and measured gutters did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'scrub-check' -and $StageText -notmatch 'MEADOW_SCRUB_AUDIT: PASS') {
        throw "Basal root support, independent rocks and preserved world checks did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'porous-growth-check' -and $StageText -notmatch 'MEADOW_POROUS_GROWTH_AUDIT: PASS') {
        throw "Actual twig support, camera-visible leaf mass, open crowns and protected geometry did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'middle-meadow-mass-check' -and $StageText -notmatch 'MEADOW_MIDDLE_MEADOW_MASS_AUDIT: PASS') {
        throw "Broader low meadow mass, unchanged roots, full leaf clearance and eight preserved world meshes did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'growth-check' -and
        ($StageText -notmatch 'MEADOW_GROWTH_FIELD_AUDIT: PASS' -or
         $StageText -notmatch 'MEADOW_FOLIAGE_PALETTE_AUDIT: PASS' -or
         $StageText -notmatch 'MEADOW_SHARED_SURFACE_AUDIT: 6 meshes' -or
         $StageText -notmatch 'MEADOW_FOOTHILL_ROOT_AUDIT: PASS' -or
         $StageText -notmatch 'MEADOW_CREEPING_ROOT_AUDIT:')) {
        throw "Meadow growth and cap support tests did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'canopy-check' -and $StageText -notmatch 'MEADOW_CANOPY_LAYOUT_AUDIT: PASS') {
        throw "Canopy layout test did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'village-check' -and $StageText -notmatch 'MEADOW_VILLAGE_MOTION_AUDIT: PASS') {
        throw "Actual windmill transform test did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'atmosphere-check' -and
        ($StageText -notmatch 'MEADOW_ATMOSPHERE_AUDIT: PASS' -or
         $StageText -notmatch 'MEADOW_CLOUD_SCALE_AUDIT: PASS')) {
        throw "Distant focus and settlement lighting test did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'wildlife-check' -and $StageText -notmatch 'MEADOW_WILDLIFE_AUDIT: PASS') {
        throw "Random wildlife, nocturnal animal and sky-flight test did not complete. Inspect $StageLog"
    }
    if ($Stage -eq 'sky-flight-check' -and $StageText -notmatch 'MEADOW_DRAGON_SKY_AUDIT: PASS') {
        throw "Whole-dragon skyline-clearance test did not complete. Inspect $StageLog"
    }
    if ($Stage -in @('source-check', 'pack-check') -and
        ($StageText -notmatch 'MEADOW_READY:' -or $StageText -notmatch '31/31 grounded probes' -or
         $StageText -notmatch 'MEADOW_PLAYSPACE_AUDIT:' -or
         $StageText -notmatch 'MEADOW_BRIDGE_AUDIT: 9/9' -or
         $StageText -notmatch 'MEADOW_CLIFF_SURFACE_AUDIT: 4 unique atlas regions' -or
         $StageText -notmatch 'MEADOW_HORIZON_GROUND_AUDIT: 4/4' -or
         $StageText -notmatch 'MEADOW_CITY_ROOT_AUDIT:' -or
         $StageText -notmatch 'MEADOW_VILLAGE_ROOT_AUDIT: 65/65' -or
         $StageText -notmatch 'MEADOW_SETTLEMENT_LIGHTS_AUDIT: 52/52' -or
         $StageText -notmatch 'MEADOW_HALO_AUDIT: 52 batched window halos' -or
         $StageText -notmatch 'MEADOW_RIVERBED_READY: 72 submerged stones' -or
         $StageText -notmatch 'MEADOW_PROP_SEAM_AUDIT:' -or
         $StageText -notmatch 'MEADOW_ROAD_LIGHTS_AUDIT: 3/3' -or
         $StageText -notmatch 'MEADOW_WILDLIFE_READY: 3 distinct eight-frame fantasy animals' -or
         $StageText -notmatch 'MEADOW_NOCTURNAL_READY: one unique eight-frame moon stag' -or
         $StageText -notmatch 'MEADOW_RIVER_FLOW_AUDIT: 345 paired bank rows' -or
         $StageText -notmatch 'MEADOW_FRAME_GROWTH_AUDIT: 4 unique designs' -or
         $StageText -notmatch 'MEADOW_FRAME_ROOT_AUDIT: 4/4' -or
         $StageText -notmatch 'MEADOW_COLONY_ROOT_AUDIT: 4/4' -or
         $StageText -notmatch 'MEADOW_CANOPY_ROOT_AUDIT: 4/4' -or
         $StageText -notmatch 'MEADOW_FENCE_AUDIT: 4/4' -or
         $StageText -notmatch 'MEADOW_FOREGROUND_ROOT_AUDIT: 2/2' -or
         $StageText -notmatch 'MEADOW_WEATHER_READY:' -or
         $StageText -notmatch 'MEADOW_GROWTH_AUDIT:' -or
         $StageText -notmatch 'MEADOW_COMPOSITION_AUDIT:' -or
         $StageText -notmatch 'MEADOW_VALLEY_AUDIT: 8 unique colonies')) {
        throw "Exported pack did not pass the scene smoke test. Inspect $StageLog"
    }
    if ($Stage -in @('source-check', 'pack-check')) {
        foreach ($CachedGroup in @('terrain', 'detail', 'foothill', 'riverbank', 'brush')) {
            if ($StageText -notmatch "MEADOW_STATIC_CACHE: $CachedGroup loaded") {
                throw "Missing or stale $CachedGroup cache. Inspect $StageLog"
            }
        }
        if ($StageText -notmatch 'MEADOW_BRIDGE_ENTRY_AUDIT: (\d+)/(\d+) supported entry probes; max error [\d.]+ m; grade ([\d.]+) deg') {
            throw "Missing bridge entry verification. Inspect $StageLog"
        }
        $EntrySlope = [double]::Parse($Matches[3], [System.Globalization.CultureInfo]::InvariantCulture)
        if ([int]$Matches[1] -ne [int]$Matches[2] -or [int]$Matches[2] -le 0 -or $EntrySlope -ge 18.0) {
            throw "Bridge entries are unsupported or too steep. Inspect $StageLog"
        }
    }
}

if (-not $NoBuild) {
    if (-not (Test-Path -LiteralPath $GodotExecutable)) {
        throw "Portable Godot is missing: $GodotExecutable. See godot/README.md."
    }
    if ($MaterialOnly) {
        $ScopeLog = Join-Path $BuildRoot "$RunStamp-build-scope.log"
        $ScopeText = 'MEADOW_PREVIEW_SCOPE: MATERIAL_ONLY; independent five-cache preflight, then import, 3 GPU probe parse checks (not GPU execution), source-check, foliage-tone-check, lighting-check, export and pack-check. 10 Godot stages total. Skips cache bake, unrelated geometry audits and long animal/sky-flight regressions. This is NOT a full 35-stage revalidation.'
        Set-Content -LiteralPath $ScopeLog -Value $ScopeText -Encoding UTF8
        Write-Host $ScopeText
        # This standalone script reads metadata without instantiating main or
        # invoking STATIC_CACHE.restore(), whose stale path builds geometry.
        # Fail before import/scene checks/export; never bake implicitly here.
        Invoke-CheckedGodot -Stage 'material-cache-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_material_cache.gd')
    }
    Invoke-CheckedGodot -Stage 'import' -EngineArguments @('--headless', '--path', $ProjectRoot, '--editor', '--import')
    # Web-only opt-in probes are dynamically loaded; ordinary scene checks do not
    # parse them. Catch API/parse mistakes before a browser diagnostic is requested.
    foreach ($Probe in @('render', 'canopy', 'architecture')) {
        Invoke-CheckedGodot -Stage "$Probe-response-parse" -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', "res://tools/audit_${Probe}_response.gd", '--check-only')
    }
    if (-not $MaterialOnly) {
        Invoke-CheckedGodot -Stage 'herb-source-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_meadow_herb_source.gd', '--', 'res://assets/foliage/meadow-herbs-v73.png')
        Invoke-CheckedGodot -Stage 'scrub-source-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_scrub_source.gd', '--', 'res://assets/foliage/meadow-scrub-v74.png')
        # This executes and checks the procedural source before serializing its exact
        # meshes; subsequent tests run the cached path actually used by Web players.
        Invoke-CheckedGodot -Stage 'cache-bake' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/bake_static_meadow.gd', '--quit-after', '16', '--', '--rebuild-static')
    }
    # Release packs disable assertions; also run the source with assertions active.
    Invoke-CheckedGodot -Stage 'source-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--quit-after', '8')
    if ($MaterialOnly) {
        Invoke-CheckedGodot -Stage 'foliage-tone-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_foliage_tone.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'lighting-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_lighting.gd', '--quit-after', '16')
    } else {
        Invoke-CheckedGodot -Stage 'shore-terrain-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_shore_terrain.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'meadow-massing-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_meadow_massing.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'cliff-planes-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_cliff_planes.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'canopy-brush-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_canopy_brush.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'foliage-tone-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_foliage_tone.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'porous-growth-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_porous_growth.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'middle-meadow-mass-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_middle_meadow_mass.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'architecture-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_architecture.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'herb-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_meadow_herbs.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'scrub-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_scrub_modules.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'weather-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_weather.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'growth-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_meadow_growth.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'canopy-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_canopy_layout.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'village-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_village_motion.gd', '--quit-after', '40')
        Invoke-CheckedGodot -Stage 'atmosphere-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_atmosphere.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'reported-fixes-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_reported_fixes.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'outcrop-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_outcrop_integration.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'city-integration-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_city_integration.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'window-sampling-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_window_sampling.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'ecotone-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_ecotone_growth.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'rock-relief-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_rock_relief.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'lighting-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_lighting.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'riverbank-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_riverbank.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'wildlife-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_wildlife.gd', '--quit-after', '16')
        Invoke-CheckedGodot -Stage 'sky-flight-check' -EngineArguments @('--headless', '--path', $ProjectRoot, '--script', 'res://tools/audit_dragon_sky.gd', '--quit-after', '16')
    }
    Invoke-CheckedGodot -Stage 'export' -EngineArguments @('--headless', '--path', $ProjectRoot, '--export-release', 'Web', (Join-Path $BuildRoot 'index.html'))
    Invoke-CheckedGodot -Stage 'pack-check' -EngineArguments @('--headless', '--path', $BuildRoot, '--main-pack', (Join-Path $BuildRoot 'index.pck'), '--quit-after', '8')
    # The custom shell uses small local DOM controls, with no CDN or framework.
    foreach ($WebAsset in @('meadow-controls.css', 'meadow-controls.js')) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "web/$WebAsset") -Destination (Join-Path $BuildRoot $WebAsset)
    }
    & python (Join-Path $PSScriptRoot 'prepare_web_build.py') $BuildRoot
    if ($LASTEXITCODE -ne 0) { throw 'Web payload preparation failed' }
    if ($MaterialOnly) {
        $ScopeResult = 'MEADOW_PREVIEW_SCOPE: MATERIAL_ONLY COMPLETE; 10 checked Godot stages and Web payload preparation; full 35-stage suite was not run.'
        Add-Content -LiteralPath $ScopeLog -Value $ScopeResult -Encoding UTF8
        Write-Host $ScopeResult
    }
}

foreach ($RequiredFile in @('index.html', 'index.pck', 'index.wasm', 'index.js')) {
    if (-not (Test-Path -LiteralPath (Join-Path $BuildRoot $RequiredFile))) {
        throw "Missing export file $RequiredFile. Run again without -NoBuild."
    }
}
if ((Get-Content -LiteralPath (Join-Path $BuildRoot 'index.html') -Raw).Contains('meadow-controls.js')) {
    foreach ($WebAsset in @('meadow-controls.css', 'meadow-controls.js')) {
        if (-not (Test-Path -LiteralPath (Join-Path $BuildRoot $WebAsset))) {
            throw "Missing Web control asset $WebAsset. Export again with this script."
        }
    }
}

$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
$NeedsServer = -not $Listener
if ($Listener) {
    # Never stop or repurpose an unknown service occupying this port.
    $Owners = @($Listener | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($Owners.Count -ne 1) { throw "Port $Port has multiple owners; choose another -Port." }
    $ServerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($Owners[0])"
    $ServerCommand = [string]$ServerProcess.CommandLine
    $ExpectedDirectory = $PreviewRoot.Replace('\', '/')
    $IsLegacyServer = $ServerCommand -match '-m\s+http\.server'
    $IsMeadowServer = $ServerCommand.Replace('\', '/').Contains((Join-Path $PSScriptRoot 'serve_meadow.py').Replace('\', '/'))
    if ((-not $IsLegacyServer -and -not $IsMeadowServer) -or
        -not $ServerCommand.Replace('\', '/').Contains($ExpectedDirectory) -or
        $ServerCommand -notmatch '--bind\s+127\.0\.0\.1') {
        throw "Port $Port belongs to another service. Choose another -Port; nothing was stopped."
    }
    if ($IsLegacyServer) {
        # Only the verified task-owned loopback preview is replaced. Other
        # processes/ports and all old version exports are left untouched.
        Stop-Process -Id $ServerProcess.ProcessId -ErrorAction Stop
        $NeedsServer = $true
    }
}
if ($NeedsServer) {
    $PythonExecutable = (Get-Command python -ErrorAction Stop).Source
    $ServerProcess = Start-Process -FilePath $PythonExecutable -WindowStyle Hidden -PassThru `
        -ArgumentList @("`"$(Join-Path $PSScriptRoot 'serve_meadow.py')`"", '--port', "$Port", '--bind', '127.0.0.1', '--directory', "`"$PreviewRoot`"") `
        -RedirectStandardOutput (Join-Path $BuildRoot "$RunStamp-server.log") `
        -RedirectStandardError (Join-Path $BuildRoot "$RunStamp-server-errors.log")
}

$PreviewUrl = "http://127.0.0.1:$Port/$Version/index.html"
$PreviewReady = $false
for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    try {
        $Response = Invoke-WebRequest -Uri $PreviewUrl -Method Head -UseBasicParsing -TimeoutSec 2
        if ($Response.StatusCode -eq 200) { $PreviewReady = $true; break }
    } catch { Start-Sleep -Milliseconds 150 }
}
if (-not $PreviewReady) { throw "Preview did not become available: $PreviewUrl" }
Write-Host "Preview: $PreviewUrl"
Write-Host 'Top-right: day/night and motion. N = day/night, P = pause/resume; C = scale guide, D = focus, G = depth.'
Write-Host 'Server is bound to this computer only. No SSH, hooks, commits or public deployment.'
