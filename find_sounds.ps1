# find_sounds.ps1 - shows all available indexes and finds sound paths

$MinecraftAssets = "$env:APPDATA\.minecraft\assets"
$IndexDir = "$MinecraftAssets\indexes"

Write-Host "=== Available indexes ===" -ForegroundColor Cyan
Get-ChildItem $IndexDir -Filter "*.json" | Sort-Object Name | ForEach-Object {
    Write-Host "  $($_.Name)  ($([math]::Round($_.Length/1KB, 1)) KB)" -ForegroundColor White
}

Write-Host ""
Write-Host "=== Searching player sounds in newest index ===" -ForegroundColor Cyan

$Newest = Get-ChildItem $IndexDir -Filter "*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "Using: $($Newest.Name)" -ForegroundColor Yellow

$Index = Get-Content $Newest.FullName -Raw | ConvertFrom-Json
$AllKeys = $Index.objects.PSObject.Properties.Name

$PlayerSounds = $AllKeys | Where-Object { $_ -like "*player*" }
Write-Host ""
Write-Host "Player sounds found:" -ForegroundColor Green
$PlayerSounds | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "=== Also checking all indexes for player/hurt ===" -ForegroundColor Cyan
Get-ChildItem $IndexDir -Filter "*.json" | Sort-Object Name | ForEach-Object {
    $idx = Get-Content $_.FullName -Raw | ConvertFrom-Json
    $keys = $idx.objects.PSObject.Properties.Name
    $hurt = $keys | Where-Object { $_ -like "*hurt*" } | Select-Object -First 1
    if ($hurt) {
        Write-Host "  $($_.Name): $hurt" -ForegroundColor Green
    } else {
        Write-Host "  $($_.Name): no hurt sounds" -ForegroundColor DarkGray
    }
}
