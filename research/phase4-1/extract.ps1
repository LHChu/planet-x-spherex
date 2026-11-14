# Offline Phase 4.1 metadata inspection. No network calls and no FITS downloads.
param([string]$EvidenceDir = (Join-Path $PSScriptRoot '../outputs/phase4-1'))
$ErrorActionPreference = 'Stop'
$EvidenceDir = (Resolve-Path -LiteralPath $EvidenceDir).Path
$collections = @()
foreach ($collection in @('spherex_dr1', 'spherex_qr3')) {
    $path = Join-Path $EvidenceDir "$collection.xml"
    [xml]$xml = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $table = $xml.SelectSingleNode('//*[local-name()="TABLE"]')
    $fields = @($table.SelectNodes('./*[local-name()="FIELD"]'))
    $rows = @($table.SelectNodes('.//*[local-name()="TR"]') | ForEach-Object {
        $cells = @($_.SelectNodes('./*[local-name()="TD"]'))
        if ($cells.Count -ne $fields.Count) { throw 'Unexpected VOTable row width' }
        $row = [ordered]@{}
        for ($i = 0; $i -lt $fields.Count; $i++) { $row[$fields[$i].name] = $cells[$i].InnerText }
        [pscustomobject]$row
    })
    $collections += [ordered]@{
        collection = $collection
        sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = (Get-Item -LiteralPath $path).Length
        query_url = "https://irsa.ipac.caltech.edu/SIA?COLLECTION=$collection&POS=CIRCLE+127.69444+-39.17760+0.01&MAXREC=1000"
        status = @($xml.SelectNodes('//*[local-name()="INFO"]') | Where-Object name -eq 'QUERY_STATUS' | ForEach-Object { $_.value })
        columns = @($fields | ForEach-Object { @{name=$_.name; unit=$_.unit; description=[string]$_.DESCRIPTION} })
        rows = $rows
    }
}
$saved = Get-Content -LiteralPath (Join-Path $PSScriptRoot '../outputs/metadata.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$inputData = [ordered]@{
    analyzed_utc = [DateTime]::UtcNow.ToString('o')
    query = @{ra=127.69444; dec=-39.17760; radius_deg=0.01; maxrec=1000}
    collections = $collections
    existing_cutout = @{sia=$saved.sia; version=$saved.version; hdu=$saved.hdu; shape=$saved.shape; target_pixel_xy=$saved.target_pixel_xy}
}
$json = $inputData | ConvertTo-Json -Depth 25
[IO.File]::WriteAllText((Join-Path $EvidenceDir 'input.json'), $json, (New-Object Text.UTF8Encoding $false))
& node (Join-Path $PSScriptRoot 'summarize.mjs') (Join-Path $EvidenceDir 'input.json') $EvidenceDir
if ($LASTEXITCODE -ne 0) { throw 'Metadata analysis failed' }
