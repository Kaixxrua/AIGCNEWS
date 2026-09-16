#Requires -Version 5.1
<#
.SYNOPSIS
Compare fixed regions in matching 1280x720 or 2560x1440 preview screenshots.
.DESCRIPTION
Reads images with System.Drawing and emits one JSON document to stdout.
Never resizes, crops, saves, or modifies either image. Both decoded images
must have the same supported dimensions. For 2K only the fixed rectangle
coordinates are doubled; the input pixels are never resized or resampled.

Luma is 0.2126*R + 0.7152*G + 0.0722*B on decoded 0..255 display-encoded
channels, without gamma linearization. It is not physical luminance or an
artistic quality score. Compression, motion and camera changes can affect
pixel differences, including the regions labelled as controls.

The dark subset uses BEFORE luma < 45 and BEFORE RGB != (0,0,0), then
compares the SAME coordinates in AFTER without filtering the after image.
Empty subsets report count 0 and null statistics. Standard deviation is
population standard deviation. All statistics use unrounded doubles.

Paths may be absolute or relative to the caller's current directory.
Errors use PowerShell's error stream; no partial JSON is emitted.
.EXAMPLE
& .\godot\tools\compare_preview_luminance.ps1 -BeforePath .\artifacts\v75\day-qa-continued.jpg -AfterPath .\artifacts\v76\day-first-trial.jpg
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [Alias('OldPath')]
    [ValidateNotNullOrEmpty()]
    [string]$BeforePath,

    [Parameter(Mandatory = $true, Position = 1)]
    [Alias('NewPath')]
    [ValidateNotNullOrEmpty()]
    [string]$AfterPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function Resolve-PreviewFile {
    param([string]$Path)

    $item = Get-Item -LiteralPath $Path -Force
    if ($item -isnot [System.IO.FileInfo]) {
        throw "Expected an existing image file: $Path"
    }
    return $item.FullName
}

function Assert-PreviewDimensions {
    param(
        [System.Drawing.Image]$Image,
        [string]$Path
    )

    if (-not (($Image.Width -eq 1280 -and $Image.Height -eq 720) -or ($Image.Width -eq 2560 -and $Image.Height -eq 1440))) {
        throw ("Image must be 1280x720 or 2560x1440; actual {0}x{1}: {2}. No resizing or cropping is performed." -f $Image.Width, $Image.Height, $Path)
    }
}

function New-LumaAccumulator {
    return [pscustomobject]@{
        SampleCount = [long]0
        BeforeMean = [double]0
        BeforeM2 = [double]0
        AfterMean = [double]0
        AfterM2 = [double]0
        AbsoluteDifferenceSum = [double]0
    }
}

function Add-LumaPair {
    param(
        [psobject]$Accumulator,
        [double]$BeforeLuma,
        [double]$AfterLuma
    )

    # Welford's algorithm avoids cancellation in population variance.
    $Accumulator.SampleCount += 1
    $beforeDelta = $BeforeLuma - $Accumulator.BeforeMean
    $Accumulator.BeforeMean += $beforeDelta / $Accumulator.SampleCount
    $Accumulator.BeforeM2 += $beforeDelta * ($BeforeLuma - $Accumulator.BeforeMean)
    $afterDelta = $AfterLuma - $Accumulator.AfterMean
    $Accumulator.AfterMean += $afterDelta / $Accumulator.SampleCount
    $Accumulator.AfterM2 += $afterDelta * ($AfterLuma - $Accumulator.AfterMean)
    $Accumulator.AbsoluteDifferenceSum += [Math]::Abs($AfterLuma - $BeforeLuma)
}

function Get-LumaStatistics {
    param([psobject]$Accumulator)

    if ($Accumulator.SampleCount -eq 0) {
        return [ordered]@{
            sample_count = 0
            before_mean = $null
            before_stddev = $null
            after_mean = $null
            after_stddev = $null
            mean_difference = $null
            mean_absolute_difference = $null
        }
    }

    return [ordered]@{
        sample_count = $Accumulator.SampleCount
        before_mean = $Accumulator.BeforeMean
        before_stddev = [Math]::Sqrt([Math]::Max(0.0, $Accumulator.BeforeM2 / $Accumulator.SampleCount))
        after_mean = $Accumulator.AfterMean
        after_stddev = [Math]::Sqrt([Math]::Max(0.0, $Accumulator.AfterM2 / $Accumulator.SampleCount))
        mean_difference = $Accumulator.AfterMean - $Accumulator.BeforeMean
        mean_absolute_difference = $Accumulator.AbsoluteDifferenceSum / $Accumulator.SampleCount
    }
}

# Inclusive, zero-based bounds in the original full frame. The lower-canopy
# interior was selected by inspecting v75/day-qa-continued.jpg; narrowing the
# suggested x1035..1110,y510..575 rectangle avoids grass at the outer edges.
$regions = @(
    [pscustomobject]@{
        id = 'foreground_right_tree_lower_canopy'
        name = 'Foreground right tree - lower canopy interior'
        role = 'vegetation_target'
        x_min = 1060; x_max = 1105; y_min = 520; y_max = 555
        selection_note = 'Fixed interior selected from v75 to avoid left and bottom background grass; no adaptive mask.'
    }
    [pscustomobject]@{
        id = 'foreground_right_tree_highlights'
        name = 'Foreground right tree - highlights'
        role = 'vegetation_target'
        x_min = 1110; x_max = 1190; y_min = 462; y_max = 513
        selection_note = 'Fixed requested highlight rectangle; all pixels inside are included.'
    }
    [pscustomobject]@{
        id = 'distant_forest'
        name = 'Distant forest'
        role = 'vegetation_target'
        x_min = 442; x_max = 618; y_min = 168; y_max = 190
        selection_note = 'Fixed requested distant-forest rectangle; all pixels inside are included.'
    }
    [pscustomobject]@{
        id = 'control_grass'
        name = 'Grass - expected unchanged control'
        role = 'expected_unchanged_control'
        x_min = 595; x_max = 650; y_min = 405; y_max = 437
        selection_note = 'Expected unchanged is a comparison role, not an assertion that the screenshots match.'
    }
    [pscustomobject]@{
        id = 'control_road'
        name = 'Road - expected unchanged control'
        role = 'expected_unchanged_control'
        x_min = 555; x_max = 625; y_min = 450; y_max = 470
        selection_note = 'Expected unchanged is a comparison role, not an assertion that the screenshots match.'
    }
    [pscustomobject]@{
        id = 'control_rock'
        name = 'Rock face - expected unchanged control'
        role = 'expected_unchanged_control'
        x_min = 160; x_max = 240; y_min = 342; y_max = 365
        selection_note = 'Expected unchanged is a comparison role, not an assertion that the screenshots match.'
    }
    [pscustomobject]@{
        id = 'control_sky'
        name = 'Sky - expected unchanged control'
        role = 'expected_unchanged_control'
        x_min = 800; x_max = 865; y_min = 18; y_max = 37
        selection_note = 'Expected unchanged is a comparison role, not an assertion that the screenshots match.'
    }
)

$resolvedBeforePath = Resolve-PreviewFile -Path $BeforePath
$resolvedAfterPath = Resolve-PreviewFile -Path $AfterPath
$beforeImage = $null
$afterImage = $null

try {
    # Disable embedded color management; read decoded RGB without transforms.
    $beforeImage = [System.Drawing.Image]::FromFile($resolvedBeforePath, $false)
    Assert-PreviewDimensions -Image $beforeImage -Path $resolvedBeforePath
    $afterImage = [System.Drawing.Image]::FromFile($resolvedAfterPath, $false)
    Assert-PreviewDimensions -Image $afterImage -Path $resolvedAfterPath
    if ($beforeImage.Width -ne $afterImage.Width -or $beforeImage.Height -ne $afterImage.Height) {
        throw 'Before/after dimensions must match exactly; cross-resolution comparisons are not supported.'
    }
    $coordinateScale = [int]($beforeImage.Width / 1280)
    foreach ($region in $regions) {
        $region.x_min *= $coordinateScale
        $region.y_min *= $coordinateScale
        $region.x_max = ($region.x_max + 1) * $coordinateScale - 1
        $region.y_max = ($region.y_max + 1) * $coordinateScale - 1
    }

    $regionResults = @(foreach ($region in $regions) {
        $allPixels = New-LumaAccumulator
        $oldDarkNonblack = New-LumaAccumulator

        for ($y = $region.y_min; $y -le $region.y_max; $y++) {
            for ($x = $region.x_min; $x -le $region.x_max; $x++) {
                $beforePixel = $beforeImage.GetPixel($x, $y)
                $afterPixel = $afterImage.GetPixel($x, $y)
                $beforeLuma = 0.2126 * $beforePixel.R + 0.7152 * $beforePixel.G + 0.0722 * $beforePixel.B
                $afterLuma = 0.2126 * $afterPixel.R + 0.7152 * $afterPixel.G + 0.0722 * $afterPixel.B

                Add-LumaPair -Accumulator $allPixels -BeforeLuma $beforeLuma -AfterLuma $afterLuma
                if ($beforeLuma -lt 45.0 -and ($beforePixel.R -ne 0 -or $beforePixel.G -ne 0 -or $beforePixel.B -ne 0)) {
                    Add-LumaPair -Accumulator $oldDarkNonblack -BeforeLuma $beforeLuma -AfterLuma $afterLuma
                }
            }
        }

        [ordered]@{
            id = $region.id
            name = $region.name
            role = $region.role
            bounds_inclusive = [ordered]@{
                x_min = $region.x_min; x_max = $region.x_max
                y_min = $region.y_min; y_max = $region.y_max
            }
            rectangle_pixel_count = ($region.x_max - $region.x_min + 1) * ($region.y_max - $region.y_min + 1)
            selection_note = $region.selection_note
            all_pixels = Get-LumaStatistics -Accumulator $allPixels
            old_dark_nonblack = Get-LumaStatistics -Accumulator $oldDarkNonblack
        }
    })

    $report = [ordered]@{
        schema_version = 2
        inputs = [ordered]@{
            before = [ordered]@{ path = $resolvedBeforePath; width = $beforeImage.Width; height = $beforeImage.Height }
            after = [ordered]@{ path = $resolvedAfterPath; width = $afterImage.Width; height = $afterImage.Height }
        }
        method = [ordered]@{
            decoder = 'System.Drawing.Image.FromFile(path, useEmbeddedColorManagement=false)'
            required_image_size = [ordered]@{ width = $beforeImage.Width; height = $beforeImage.Height }
            rectangle_reference_size = [ordered]@{ width = 1280; height = 720 }
            rectangle_coordinate_scale = $coordinateScale
            coordinate_system = 'Zero-based original full-frame pixels; origin top-left; x rightward, y downward; all bounds inclusive.'
            preprocessing = 'None: no resize, crop, alignment, orientation transform, gamma linearization or alpha compositing; use decoded RGB.'
            metric = 'Display-encoded RGB luma proxy, not physical luminance or an artistic quality score.'
            luma_formula = '0.2126 * R + 0.7152 * G + 0.0722 * B'
            luma_coefficients = [ordered]@{ R = 0.2126; G = 0.7152; B = 0.0722 }
            channel_range = @(0, 255)
            statistics_units = '0..255 display-encoded luma code values'
            standard_deviation = 'Population: sqrt(sum((luma - mean)^2) / sample_count), computed with Welford accumulation.'
            mean_difference = 'after_mean - before_mean; positive means higher encoded luma in AFTER.'
            mean_absolute_difference = 'mean(abs(after_luma(x,y) - before_luma(x,y))) over identical selected coordinates.'
            sample_sets = [ordered]@{
                all_pixels = 'Every pixel in the inclusive region rectangle; no content, RGB, alpha or black-pixel exclusions.'
                old_dark_nonblack = [ordered]@{
                    selector_image = 'before'
                    luma_less_than = 45
                    excluded_before_rgb = @(0, 0, 0)
                    predicate = 'before_luma < 45 AND (before_R != 0 OR before_G != 0 OR before_B != 0)'
                    after_sampling = 'Use the same selected coordinates; no threshold or black exclusion applied to AFTER.'
                }
            }
            empty_sample_set = 'sample_count=0; means, standard deviations and differences are null.'
            numeric_precision = 'Double-precision accumulation; no explicit rounding.'
            interpretation = 'JPEG compression, motion, lighting or camera changes can affect any region. Controls are observations, not automatic pass/fail checks or attribution to a code change.'
        }
        regions = $regionResults
    }
}
finally {
    if ($null -ne $afterImage) { $afterImage.Dispose() }
    if ($null -ne $beforeImage) { $beforeImage.Dispose() }
}

$report | ConvertTo-Json -Depth 12
