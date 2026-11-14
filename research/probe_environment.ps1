$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$runWatch = [Diagnostics.Stopwatch]::StartNew()
$evidence = [ordered]@{
    started_utc = [DateTime]::UtcNow.ToString('o')
    cwd = (Get-Location).Path
    status = 'blocked_before_fits_processing'
    python_attempts = @()
    network_attempts = @()
}
$registeredPath = 'C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.9_3.9.3568.0_x64__qbz5n2kfra8p0\python3.9.exe'
foreach ($exe in @('py', $registeredPath)) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $attempt = [ordered]@{ executable = $exe; arguments = @((Join-Path $PSScriptRoot 'verify_spherex.py')) }
    try {
        $lines = & $exe (Join-Path $PSScriptRoot 'verify_spherex.py') 2>&1
        $attempt.exit_code = $LASTEXITCODE
        $attempt.output = ($lines | Out-String)
    } catch {
        $attempt.error = $_.Exception.ToString()
    }
    $attempt.elapsed_seconds = $watch.Elapsed.TotalSeconds
    $evidence.python_attempts += $attempt
}
foreach ($collection in @('spherex_dr1','spherex_qr3')) {
    $url = 'https://irsa.ipac.caltech.edu/SIA?COLLECTION=' + $collection + '&POS=CIRCLE%20127.69444%20-39.17760%200.01&MAXREC=50'
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $attempt = [ordered]@{ collection = $collection; url = $url }
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30
        $attempt.http_status = [int]$response.StatusCode
        $attempt.bytes = $response.RawContentLength
        $response.Content | Set-Content -LiteralPath (Join-Path $PSScriptRoot ($collection + '-probe.xml')) -Encoding UTF8
    } catch {
        $attempt.error = $_.Exception.ToString()
        $attempt.http_status = $null
    }
    $attempt.elapsed_seconds = $watch.Elapsed.TotalSeconds
    $evidence.network_attempts += $attempt
}
$evidence.elapsed_seconds = $runWatch.Elapsed.TotalSeconds
$evidence.probe_powershell_peak_working_set_bytes = (Get-Process -Id $PID).PeakWorkingSet64
$evidence.memory_note = 'PowerShell probe process only; Python/FITS pipeline peak memory was not measured.'
$evidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'environment-probe.json') -Encoding UTF8
$evidence | ConvertTo-Json -Depth 10
