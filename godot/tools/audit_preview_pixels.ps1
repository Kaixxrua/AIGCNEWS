[CmdletBinding()]
param([Parameter(Mandatory=$true)][string[]]$Paths)

# Read-only statistics on original browser screenshots. Never save image pixels.
Add-Type -AssemblyName System.Drawing
$Regions = @{
    foreground_leaves = @(0.30, 0.75, 0.55, 0.86)
    meadow = @(0.25, 0.45, 0.68, 0.76)
    village = @(0.065, 0.19, 0.33, 0.265)
    castle = @(0.48, 0.11, 0.73, 0.25)
    sky = @(0.32, 0.01, 0.65, 0.12)
}
foreach ($ImagePath in $Paths) {
    $ResolvedImage = (Resolve-Path -LiteralPath $ImagePath).Path
    $Bitmap = [System.Drawing.Bitmap]::new($ResolvedImage)
    try {
        $SceneHeight = [Math]::Min($Bitmap.Height, $Bitmap.Width / 1.6)
        $SceneWidth = $SceneHeight * 1.6
        $Left = ($Bitmap.Width - $SceneWidth) / 2.0
        $Top = ($Bitmap.Height - $SceneHeight) / 2.0
        foreach ($RegionName in $Regions.Keys) {
            $Bounds = $Regions[$RegionName]
            $Sum = 0.0; $Edges = 0.0; $Warm = 0; $Samples = 0
            $StartX = [int]($Left + $Bounds[0] * $SceneWidth)
            $StartY = [int]($Top + $Bounds[1] * $SceneHeight)
            $EndX = [int]($Left + $Bounds[2] * $SceneWidth)
            $EndY = [int]($Top + $Bounds[3] * $SceneHeight)
            for ($Y = $StartY; $Y -lt $EndY; $Y++) {
                for ($X = $StartX; $X -lt $EndX; $X++) {
                    $Pixel = $Bitmap.GetPixel($X, $Y)
                    $Luma = 0.2126 * $Pixel.R + 0.7152 * $Pixel.G + 0.0722 * $Pixel.B
                    $Next = $Bitmap.GetPixel($X + 1, $Y)
                    $OtherLuma = 0.2126 * $Next.R + 0.7152 * $Next.G + 0.0722 * $Next.B
                    $Sum += $Luma
                    $Edges += [Math]::Abs($Luma - $OtherLuma)
                    if ($Pixel.R -gt 85 -and $Pixel.R -gt $Pixel.G * 1.18 -and $Pixel.R -gt $Pixel.B * 1.55) { $Warm++ }
                    $Samples++
                }
            }
            [PSCustomObject]@{
                Image = [System.IO.Path]::GetFileName($ResolvedImage)
                Size = "$($Bitmap.Width)x$($Bitmap.Height)"
                Region = $RegionName
                MeanLuma255 = [Math]::Round($Sum / $Samples, 3)
                MeanHorizontalEdge = [Math]::Round($Edges / $Samples, 3)
                WarmPixels = $Warm
                Samples = $Samples
            }
        }
    } finally { $Bitmap.Dispose() }
}
