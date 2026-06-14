# extract_sounds.ps1 - Run from rpbot folder: .\extract_sounds.ps1

$MinecraftAssets = "$env:APPDATA\.minecraft\assets"
$IndexDir = "$MinecraftAssets\indexes"
$ObjectsDir = "$MinecraftAssets\objects"
$OutBase = ".\templates\sounds"

# Use newest index
$SoundsJson = Get-ChildItem $IndexDir -Filter "*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "Index: $($SoundsJson.Name)" -ForegroundColor Cyan
$Index = Get-Content $SoundsJson.FullName -Raw | ConvertFrom-Json

# Real paths from 1.21.x indexes
$SoundSets = @{}

$SoundSets["pvp"] = @(
    "minecraft/sounds/entity/player/hurt/berrybush_hurt1.ogg",
    "minecraft/sounds/entity/player/hurt/berrybush_hurt2.ogg",
    "minecraft/sounds/entity/player/attack/crit1.ogg",
    "minecraft/sounds/entity/player/attack/crit2.ogg",
    "minecraft/sounds/entity/player/attack/crit3.ogg",
    "minecraft/sounds/entity/player/attack/knockback1.ogg",
    "minecraft/sounds/entity/player/attack/knockback2.ogg",
    "minecraft/sounds/entity/player/attack/strong1.ogg",
    "minecraft/sounds/entity/player/attack/strong2.ogg",
    "minecraft/sounds/entity/player/attack/strong3.ogg",
    "minecraft/sounds/entity/player/attack/sweep1.ogg",
    "minecraft/sounds/entity/player/attack/sweep2.ogg",
    "minecraft/sounds/entity/player/attack/weak1.ogg",
    "minecraft/sounds/entity/player/attack/weak2.ogg"
)

$SoundSets["hit1"] = @(
    "minecraft/sounds/entity/player/hurt/berrybush_hurt1.ogg",
    "minecraft/sounds/entity/player/hurt/berrybush_hurt2.ogg",
    "minecraft/sounds/entity/player/attack/strong1.ogg",
    "minecraft/sounds/entity/player/attack/strong2.ogg",
    "minecraft/sounds/entity/player/attack/crit1.ogg",
    "minecraft/sounds/entity/player/attack/crit2.ogg"
)

$SoundSets["hit2"] = @(
    "minecraft/sounds/entity/player/hurt/freeze_hurt1.ogg",
    "minecraft/sounds/entity/player/hurt/freeze_hurt2.ogg",
    "minecraft/sounds/entity/player/attack/weak1.ogg",
    "minecraft/sounds/entity/player/attack/weak2.ogg"
)

$Copied = 0
$Missing = 0

foreach ($SetName in $SoundSets.Keys) {
    Write-Host ""
    Write-Host "Set: $SetName" -ForegroundColor Yellow
    $SetDir = "$OutBase\$SetName\assets\minecraft\sounds"

    foreach ($SoundPath in $SoundSets[$SetName]) {
        $Entry = $Index.objects.PSObject.Properties | Where-Object { $_.Name -eq $SoundPath }

        if ($Entry) {
            $Hash = $Entry.Value.hash
            $HashDir = $Hash.Substring(0, 2)
            $SrcFile = "$ObjectsDir\$HashDir\$Hash"

            if (Test-Path $SrcFile) {
                $RelPath = $SoundPath -replace "minecraft/sounds/", ""
                $DstDir = "$SetDir\$(Split-Path $RelPath -Parent)"
                $DstFile = "$DstDir\$(Split-Path $RelPath -Leaf)"
                New-Item -ItemType Directory -Force -Path $DstDir | Out-Null
                Copy-Item $SrcFile $DstFile -Force
                Write-Host "  OK $RelPath" -ForegroundColor Green
                $Copied++
            } else {
                Write-Host "  MISS $SoundPath" -ForegroundColor Yellow
                $Missing++
            }
        } else {
            Write-Host "  SKIP $SoundPath" -ForegroundColor DarkGray
            $Missing++
        }
    }
}

# Silent set - just sounds.json with low volume
$SilentDir = "$OutBase\silent\assets\minecraft"
New-Item -ItemType Directory -Force -Path $SilentDir | Out-Null
$sj = '{"entity.player.hurt":{"sounds":[{"name":"entity/player/hurt/berrybush_hurt1","volume":0.02}]},"entity.player.attack.strong":{"sounds":[{"name":"entity/player/attack/strong1","volume":0.02}]},"entity.player.attack.crit":{"sounds":[{"name":"entity/player/attack/crit1","volume":0.02}]}}'
[System.IO.File]::WriteAllText("$SilentDir\sounds.json", $sj)
Write-Host ""
Write-Host "  OK sounds.json (silent)" -ForegroundColor Green

Write-Host ""
Write-Host "==============================" -ForegroundColor Cyan
Write-Host "Copied: $Copied files" -ForegroundColor Green
Write-Host "Skipped: $Missing files" -ForegroundColor Yellow
Write-Host "Done! Folder: .\templates\sounds\" -ForegroundColor Cyan
