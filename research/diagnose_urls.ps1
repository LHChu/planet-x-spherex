param(
    [string]$VotablePath = (Join-Path $PSScriptRoot 'outputs/spherex_dr1.xml'),
    [int[]]$Candidates = @(40,42,41,43,44,45,7,6,30,31),
    [double]$Ra = 127.69444,
    [double]$Dec = -39.17760,
    [switch]$Probe,
    [string]$OutputPath = ''
)
# Standalone diagnostics only. Does not change the API, DNS, proxy or retries.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not $OutputPath) {
    if ($Probe) { $OutputPath = Join-Path $PSScriptRoot 'outputs/connection-diagnostics.json' }
    else { $OutputPath = Join-Path $PSScriptRoot 'outputs/url-inventory.json' }
}
Add-Type -AssemblyName System.Web
$watch = [Diagnostics.Stopwatch]::StartNew()
$limit = 16
$requestCount = 0
$notBefore = 0.0
$records = @()
$dns = @{}

function Get-DnsEvidence([string]$Name) {
    if (-not $dns.ContainsKey($Name)) {
        try {
            $addresses = [Net.Dns]::GetHostAddresses($Name)
            $dns[$Name] = [ordered]@{ hostname=$Name; addresses=@($addresses | ForEach-Object { $_.IPAddressToString }); status='resolved' }
        } catch {
            $dns[$Name] = [ordered]@{ hostname=$Name; status='failed'; error=$_.Exception.GetBaseException().Message }
        }
    }
    return $dns[$Name]
}

$xml = New-Object Xml.XmlDocument
$xml.XmlResolver = $null
$xml.Load((Resolve-Path -LiteralPath $VotablePath).Path)
$table = $xml.SelectSingleNode("//*[local-name()='TABLE'][*[local-name()='FIELD' and @name='access_url']]")
if ($null -eq $table) { throw 'No access_url table in VOTable' }
$fields = @($table.SelectNodes("./*[local-name()='FIELD']") | ForEach-Object { $_.GetAttribute('name') })
$urlIndex = [Array]::IndexOf($fields, 'access_url')
$rows = $table.SelectNodes("./*[local-name()='DATA']/*[local-name()='TABLEDATA']/*[local-name()='TR']")
if ($rows.Count -eq 0) { throw 'This PowerShell fallback needs TABLEDATA; use the Python diagnostic for BINARY VOTables.' }

foreach ($index in $Candidates) {
    if ($index -lt 0 -or $index -ge $rows.Count) { throw "Candidate index $index is outside this snapshot" }
    $cells = $rows[$index].SelectNodes("./*[local-name()='TD']")
    $access = $cells[$urlIndex].InnerText
    $uri = [Uri]$access
    $builder = New-Object UriBuilder($uri)
    $query = [Web.HttpUtility]::ParseQueryString($uri.Query)
    $query['center'] = [string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0},{1}deg', $Ra, $Dec)
    $query['size'] = '3arcmin'
    $builder.Query = $query.ToString()
    $cutout = $builder.Uri
    $supported = ($uri.Scheme -eq 'https' -and $uri.DnsSafeHost -eq 'irsa.ipac.caltech.edu' -and
        $uri.AbsolutePath -match '^/ibe/data/spherex/(dr1|qr3)/level2/.+\.fits$')
    $record = [ordered]@{ candidate_source_index=$index; access_url=$access; cutout_url=$cutout.AbsoluteUri;
        scheme=$cutout.Scheme; hostname=$cutout.DnsSafeHost; official_cutout_path=$supported;
        final_hostname=$null; final_hostname_confirmed=$false; hops=@(); result='not_probed' }
    if ($Probe -and $supported) {
        $current = $cutout
        for ($hopIndex=0; $hopIndex -lt 3; $hopIndex++) {
            $wait = [Math]::Max(0, $notBefore - $watch.Elapsed.TotalSeconds)
            if ($requestCount -ge $limit -or $watch.Elapsed.TotalSeconds + $wait -ge 120 -or $wait -gt 15) {
                $record.result='budget_or_retry_after_stop'; break
            }
            if ($wait -gt 0) { Start-Sleep -Milliseconds ([int][Math]::Ceiling($wait*1000)) }
            $hop = [ordered]@{ scheme=$current.Scheme; hostname=$current.DnsSafeHost; status=$null; retry_after=$null }
            $record.hops += $hop
            $hop.dns = Get-DnsEvidence $current.DnsSafeHost
            $request = [Net.HttpWebRequest]::Create($current)
            $request.Method = 'GET'
            $request.UserAgent = 'SPHEREx-Connection-Diagnostic/1.0'
            $request.AllowAutoRedirect = $false
            $remaining = 120-$watch.Elapsed.TotalSeconds
            if ($remaining -le 0) { $record.result='budget_stop_after_dns'; $request.Abort(); break }
            $request.Timeout = [int][Math]::Max(1, [Math]::Min(10, $remaining)*1000)
            $request.ReadWriteTimeout = $request.Timeout
            $hop.proxy_hostname = $null
            $hop.transport_hostname = $current.DnsSafeHost
            if ($null -ne $request.Proxy -and -not $request.Proxy.IsBypassed($current)) {
                $proxy = $request.Proxy.GetProxy($current)
                $hop.proxy_hostname = $proxy.DnsSafeHost
                $hop.transport_hostname = $proxy.DnsSafeHost
                $hop.proxy_dns = Get-DnsEvidence $proxy.DnsSafeHost
            }
            $response = $null
            $redirect = $null
            $requestCount++
            try {
                try { $response = $request.GetResponse() }
                catch [Net.WebException] {
                    if ($null -ne $_.Exception.Response) { $response = $_.Exception.Response }
                    else {
                        $hop.error = $_.Exception.GetBaseException().Message
                        $hop.web_exception_status = [string]$_.Exception.Status
                        if ($_.Exception.Status -eq [Net.WebExceptionStatus]::ProxyNameResolutionFailure) {
                            $hop.dns_failure_hostname = $hop.proxy_hostname
                        } elseif ($_.Exception.Status -eq [Net.WebExceptionStatus]::NameResolutionFailure) {
                            $hop.dns_failure_hostname = $current.DnsSafeHost
                        }
                        $record.result='transport_error'; break
                    }
                }
                $hop.status = [int]$response.StatusCode
                $record.final_hostname = $response.ResponseUri.DnsSafeHost
                $record.final_hostname_confirmed = $true
                $record.result = 'http_response'
                $hop.retry_after = $response.Headers['Retry-After']
                if ($hop.status -eq 503) {
                    $delay = 1.0
                    $seconds = 0
                    $date = [DateTimeOffset]::MinValue
                    if ([int]::TryParse($hop.retry_after, [ref]$seconds)) { $delay=[Math]::Max($delay,$seconds) }
                    elseif ([DateTimeOffset]::TryParse($hop.retry_after, [ref]$date)) { $delay=[Math]::Max($delay,($date-[DateTimeOffset]::UtcNow).TotalSeconds) }
                    $notBefore = $watch.Elapsed.TotalSeconds + $delay
                }
                if ($hop.status -in @(301,302,303,307,308) -and $response.Headers['Location']) {
                    $redirect = New-Object Uri($current, $response.Headers['Location'])
                    $hop.redirect_hostname = $redirect.DnsSafeHost
                    $hop.redirect_scheme = $redirect.Scheme
                    # A redirect target is an attempted hostname, not proof that
                    # an HTTP response was received from it.
                    $record.final_hostname = $null
                    $record.final_hostname_confirmed = $false
                    $record.result='redirect_pending'
                }
            } finally {
                if ($null -ne $response) { $response.Close() }
                $request.Abort()
            }
            if ($null -eq $redirect) { break }
            if ($redirect.Scheme -ne 'https') { $record.result='non_https_redirect_not_followed'; break }
            $current = $redirect
            if ($hopIndex -eq 2) { $record.result='redirect_limit' }
        }
    }
    $records += $record
}
$proxyEnv = @()
foreach ($name in @('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value) {
        try { $proxyEnv += @{ name=$name; hostname=([Uri]$value).DnsSafeHost } }
        catch { $proxyEnv += @{ name=$name; hostname='unparseable' } }
    }
}
$report = [ordered]@{ utc=[DateTime]::UtcNow.ToString('o'); snapshot=(Resolve-Path -LiteralPath $VotablePath).Path;
    snapshot_sha256=(Get-FileHash -LiteralPath $VotablePath -Algorithm SHA256).Hash;
    snapshot_last_write_utc=(Get-Item -LiteralPath $VotablePath).LastWriteTimeUtc.ToString('o');
    snapshot_note='Indices apply only to this saved SIA snapshot; it may differ from the failed API request.';
    transport='.NET HttpWebRequest; proxy behavior can differ from Python urllib'; probe=[bool]$Probe;
    request_count=$requestCount; elapsed_seconds=$watch.Elapsed.TotalSeconds; proxy_environment=$proxyEnv;
    candidates=$records }
$parent = Split-Path -Parent ([IO.Path]::GetFullPath($OutputPath))
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$report | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
# Console/prod-safe summary: no query strings, credentials or complete URLs.
$records | ForEach-Object { [pscustomobject]@{
    candidate=$_.candidate_source_index; scheme=$_.scheme; hostname=$_.hostname; supported=$_.official_cutout_path;
    result=$_.result; final_hostname=$_.final_hostname; statuses=(($_.hops | ForEach-Object { $_.status }) -join ',')
} } | Format-Table -AutoSize
Write-Output ('Diagnostic artifact: ' + [IO.Path]::GetFullPath($OutputPath))
