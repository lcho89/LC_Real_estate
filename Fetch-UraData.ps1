<#
.SYNOPSIS
    Fetches Singapore private residential transaction data from the URA Data
    Service API and saves it as ura_data.js for use with index.html.

    Native PowerShell port of fetch_ura_data.py — no Python required.

.DESCRIPTION
    Produces a byte-for-byte equivalent ura_data.js: the same compact columnar
    payload, the same derived fields, and the same fetchedAt stamp the dashboard
    reads to show its data age.

    Unlike the Python script, this one can generate the daily token for you —
    pass only -Key and it calls insertNewToken itself.

.PARAMETER Key
    URA Access Key (permanent, emailed to you on registration). Prompted for if
    omitted.

.PARAMETER Token
    URA daily token. Omit it and the script generates one from -Key.

.PARAMETER Out
    Output path. Defaults to ura_data.js in the current directory.

.PARAMETER Batches
    Which batches to fetch. Defaults to all four (1,2,3,4). Accepts -Batches 1,2
    from inside a PowerShell session as well as -Batches "1,2" via pwsh -File.

.EXAMPLE
    .\Fetch-UraData.ps1 -Key xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    Generates today's token automatically, then fetches all four batches.

.EXAMPLE
    .\Fetch-UraData.ps1 -Key YOUR_KEY -Token TODAYS_TOKEN -Out ura_data.js

.NOTES
    URA API registration (free): https://eservice.ura.gov.sg/maps/api/
    Tokens are valid for the day they are generated.
#>

[CmdletBinding()]
param(
    [string]   $Key,
    [string]   $Token,
    [string]   $Out     = 'ura_data.js',
    [string[]] $Batches = @('1', '2', '3', '4')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Windows PowerShell 5.1 still negotiates TLS 1.0 by default, which URA rejects.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────

$BASE_URL    = 'https://eservice.ura.gov.sg/uraDataService/invokeUraDS/v1'
$TOKEN_URL   = 'https://eservice.ura.gov.sg/uraDataService/insertNewToken/v1'
$SQM_TO_SQFT = 10.7639

# URA sits behind a WAF that drops default tool user-agents, so present a normal one.
$USER_AGENT  = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'

$PROPERTY_TYPES_INCLUDE = @('Condominium', 'Apartment', 'Executive Condominium')

$SALE_TYPE_MAP = @{ '1' = 'New Sale'; '2' = 'Sub-sale'; '3' = 'Resale' }

$BATCH_LABELS = @{
    1 = 'Districts 01-07'
    2 = 'Districts 08-14'
    3 = 'Districts 15-21'
    4 = 'Districts 22+'
}

$COLS = @('project','district','tenureType','tenure','bedroomType','sizeBand',
          'size','psf','transactionValue','year','month',
          'marketSegment','propertyType','floorRange','saleType')

# ─────────────────────────────────────────────
#  Derivation helpers
# ─────────────────────────────────────────────

# Infer bedroom type from floor area (sqm). URA does not provide bedroom count.
function Get-BedroomType {
    param([double] $AreaSqm)
    $sqft = $AreaSqm * $SQM_TO_SQFT
    if ($sqft -le 430)  { return 'Studio' }
    if ($sqft -le 650)  { return '1-Bedroom' }
    if ($sqft -le 970)  { return '2-Bedroom' }
    if ($sqft -le 1300) { return '3-Bedroom' }
    if ($sqft -le 2000) { return '4-Bedroom' }
    if ($sqft -le 2800) { return '5-Bedroom' }
    return 'Penthouse'
}

# Bucket floor area into the display bands the dashboard filter expects.
function Get-SizeBand {
    param([double] $Sqft)
    if ($Sqft -lt 500)  { return '< 500' }
    if ($Sqft -lt 600)  { return '500-600' }
    if ($Sqft -lt 700)  { return '600-700' }
    if ($Sqft -lt 800)  { return '700-800' }
    if ($Sqft -lt 900)  { return '800-900' }
    if ($Sqft -lt 1000) { return '900-1,000' }
    if ($Sqft -lt 1200) { return '1,000-1,200' }
    if ($Sqft -lt 1500) { return '1,200-1,500' }
    return '> 1,500'
}

# Returns @(tenureType, tenureLabel). The full string is preserved (e.g.
# '99 years lease commencing from 2017') so the dashboard can read the
# lease commencement year off it.
function Get-TenureParts {
    param([string] $TenureStr)
    if ([string]::IsNullOrWhiteSpace($TenureStr)) { return @('Unknown', 'Unknown') }
    $s = $TenureStr.Trim()
    if ($s.ToLowerInvariant() -eq 'freehold') { return @('Freehold', 'Freehold') }
    return @('Leasehold', $s)
}

# Parse 'MMYY' -> @(year, month). Returns $null on failure.
function Get-ContractDate {
    param([string] $DateStr)
    if ([string]::IsNullOrEmpty($DateStr) -or $DateStr.Length -ne 4) { return $null }
    $mm = 0; $yy = 0
    if (-not [int]::TryParse($DateStr.Substring(0, 2), [ref] $mm)) { return $null }
    if (-not [int]::TryParse($DateStr.Substring(2, 2), [ref] $yy)) { return $null }
    if ($mm -lt 1 -or $mm -gt 12) { return $null }
    # Parenthesised deliberately: the comma binds tighter than '+' in PowerShell,
    # so @(2000 + $yy, $mm) would parse as 2000 + ($yy, $mm).
    return @((2000 + $yy), $mm)
}

# Replicates Python's str.title(): a new word starts after any non-letter, so
# "d'leedon" -> "D'Leedon". .NET's ToTitleCase yields "D'leedon", which would
# rename real projects, so it is not used here.
function ConvertTo-PythonTitleCase {
    param([string] $Value)
    $sb = New-Object System.Text.StringBuilder $Value.Length
    $prevIsLetter = $false
    foreach ($ch in $Value.ToCharArray()) {
        if ([char]::IsLetter($ch)) {
            if ($prevIsLetter) { [void] $sb.Append([char]::ToLowerInvariant($ch)) }
            else               { [void] $sb.Append([char]::ToUpperInvariant($ch)) }
            $prevIsLetter = $true
        } else {
            [void] $sb.Append($ch)
            $prevIsLetter = $false
        }
    }
    return $sb.ToString()
}

# Title-case a project name, keeping small words lowercase mid-name.
function Format-ProjectName {
    param([string] $Raw)
    $small  = @('At','Of','In','On','By','The','And','Or','A')
    $words  = (ConvertTo-PythonTitleCase $Raw) -split '\s+'
    $result = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $words.Count; $i++) {
        if ($i -gt 0 -and $small -contains $words[$i]) { $result.Add($words[$i].ToLowerInvariant()) }
        else                                          { $result.Add($words[$i]) }
    }
    return ($result -join ' ')
}

# ─────────────────────────────────────────────
#  JSON output
# ─────────────────────────────────────────────

# ConvertTo-Json is recursive and far too slow for ~126k nested rows, so the
# payload is serialised by hand.
function ConvertTo-JsonStringLiteral {
    param([string] $Value)
    if ($null -eq $Value) { return '""' }
    $sb = New-Object System.Text.StringBuilder ($Value.Length + 2)
    [void] $sb.Append('"')
    foreach ($ch in $Value.ToCharArray()) {
        switch ($ch) {
            '"'     { [void] $sb.Append('\"');  continue }
            '\'     { [void] $sb.Append('\\');  continue }
            "`b"    { [void] $sb.Append('\b');  continue }
            "`f"    { [void] $sb.Append('\f');  continue }
            "`n"    { [void] $sb.Append('\n');  continue }
            "`r"    { [void] $sb.Append('\r');  continue }
            "`t"    { [void] $sb.Append('\t');  continue }
            default {
                if ([int] $ch -lt 32) { [void] $sb.Append(('\u{0:x4}' -f [int] $ch)) }
                else                  { [void] $sb.Append($ch) }
            }
        }
    }
    [void] $sb.Append('"')
    return $sb.ToString()
}

function ConvertTo-JsonScalar {
    param($Value)
    if ($null -eq $Value)      { return '""' }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) {
        return ([string] $Value)
    }
    return (ConvertTo-JsonStringLiteral ([string] $Value))
}

# ─────────────────────────────────────────────
#  API
# ─────────────────────────────────────────────

# A genuine URA reply is a JSON object carrying a Status field. A WAF block page
# arrives as HTML, which Invoke-RestMethod returns as a string or, when the markup
# happens to parse, as an XmlDocument - so test for the field rather than the type.
function Test-UraJsonResponse {
    param($Response)
    if ($null -eq $Response)                     { return $false }
    if ($Response -is [string])                  { return $false }
    if ($Response -is [System.Xml.XmlDocument])  { return $false }
    return ($Response.PSObject.Properties.Name -contains 'Status')
}

function New-UraToken {
    param([string] $AccessKey)
    $headers = @{ 'AccessKey' = $AccessKey; 'User-Agent' = $USER_AGENT }
    try {
        $resp = Invoke-RestMethod -Uri $TOKEN_URL -Headers $headers -TimeoutSec 45 -ErrorAction Stop
    } catch {
        throw "Could not reach the token endpoint: $($_.Exception.Message)"
    }
    if (-not (Test-UraJsonResponse $resp)) {
        throw "The token endpoint returned a web page instead of JSON - the URA firewall blocked this request. Try again from a different network, or generate the token manually in a browser."
    }
    if ($resp.Status -ne 'Success' -or [string]::IsNullOrWhiteSpace($resp.Result)) {
        $msg = if ($resp.PSObject.Properties.Name -contains 'Message') { $resp.Message } else { 'unknown error' }
        throw "URA refused to issue a token: $msg. Check that the Access Key is correct and still active."
    }
    return $resp.Result
}

function Get-UraBatch {
    param([int] $Batch, [hashtable] $Headers)

    # Declared up front so every exit path returns the same type. Each 'return'
    # below uses a unary comma: without it PowerShell unrolls the list, and a
    # single-row batch would surface as that row's 15 columns instead of 1 record.
    $records = New-Object System.Collections.Generic.List[object]

    $url = "${BASE_URL}?service=PMI_Resi_Transaction&batch=$Batch"
    try {
        $resp = Invoke-RestMethod -Uri $url -Headers $Headers -TimeoutSec 120 -ErrorAction Stop
    } catch {
        Write-Warning "  Batch ${Batch}: request failed - $($_.Exception.Message)"
        return ,$records
    }

    if (-not (Test-UraJsonResponse $resp)) {
        Write-Warning "  Batch ${Batch}: got a web page instead of JSON (firewall block)"
        return ,$records
    }
    if ($resp.Status -ne 'Success') {
        $msg = if ($resp.PSObject.Properties.Name -contains 'Message') { $resp.Message } else { 'unknown error' }
        Write-Warning "  Batch ${Batch}: API error - $msg"
        return ,$records
    }

    foreach ($project in $resp.Result) {
        if ([string]::IsNullOrWhiteSpace($project.project)) { continue }

        $projectName  = Format-ProjectName $project.project
        $marketSegment = if ($project.PSObject.Properties.Name -contains 'marketSegment') { $project.marketSegment } else { '' }
        $rawTenure     = if ($project.PSObject.Properties.Name -contains 'tenure')        { $project.tenure }        else { '' }
        $tenureParts   = Get-TenureParts $rawTenure

        if (-not ($project.PSObject.Properties.Name -contains 'transaction')) { continue }

        foreach ($tx in $project.transaction) {
            $propType = if ($tx.PSObject.Properties.Name -contains 'propertyType') { $tx.propertyType } else { '' }
            if ($PROPERTY_TYPES_INCLUDE -notcontains $propType) { continue }

            $areaSqm = 0.0; $price = 0.0
            if (-not [double]::TryParse([string] $tx.area,  [ref] $areaSqm)) { continue }
            if (-not [double]::TryParse([string] $tx.price, [ref] $price))   { continue }
            if ($areaSqm -le 0 -or $price -le 0) { continue }

            $areaSqft = [math]::Round($areaSqm * $SQM_TO_SQFT)
            if ($areaSqft -le 0) { continue }
            $psf = [math]::Round($price / $areaSqft)

            $contractDate = Get-ContractDate ([string] $tx.contractDate)
            if ($null -eq $contractDate) { continue }
            $year  = $contractDate[0]
            $month = $contractDate[1]

            $districtRaw = if ($tx.PSObject.Properties.Name -contains 'district') { [string] $tx.district } else { '00' }
            $district    = 'D' + $districtRaw.PadLeft(2, '0')

            $saleTypeRaw = if ($tx.PSObject.Properties.Name -contains 'typeOfSale') { [string] $tx.typeOfSale } else { '' }
            $saleType    = if ($SALE_TYPE_MAP.ContainsKey($saleTypeRaw)) { $SALE_TYPE_MAP[$saleTypeRaw] } else { 'Unknown' }

            $floorRange  = if ($tx.PSObject.Properties.Name -contains 'floorRange') { $tx.floorRange } else { '' }

            # Column order must match $COLS.
            $records.Add(@(
                $projectName,
                $district,
                $tenureParts[0],
                $tenureParts[1],
                (Get-BedroomType $areaSqm),
                (Get-SizeBand $areaSqft),
                [int] $areaSqft,
                [int] $psf,
                [long] ([math]::Round($price / 1000) * 1000),
                [int] $year,
                [int] $month,
                $marketSegment,
                $propType,
                $floorRange,
                $saleType
            ))
        }
    }

    return ,$records
}

# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

Write-Host ''
Write-Host ('=' * 60)
Write-Host '  URA Transaction Data Fetcher - index.html'
Write-Host ('=' * 60)
Write-Host ''

if ([string]::IsNullOrWhiteSpace($Key)) {
    # Read-Host yields $null on a closed stdin, so guard before trimming.
    $entered = Read-Host '  URA Access Key  '
    if ($null -ne $entered) { $Key = $entered.Trim() }
}
if ([string]::IsNullOrWhiteSpace($Key)) {
    Write-Host ''
    Write-Host '  Error: an Access Key is required.' -ForegroundColor Red
    Write-Host '  Register free at https://eservice.ura.gov.sg/maps/api/'
    exit 1
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    Write-Host '  No token supplied - generating one for today ... ' -NoNewline
    try {
        $Token = New-UraToken -AccessKey $Key
        Write-Host 'ok' -ForegroundColor Green
    } catch {
        Write-Host 'failed' -ForegroundColor Red
        Write-Host ''
        Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

Write-Host ''

$headers = @{ 'AccessKey' = $Key; 'Token' = $Token; 'User-Agent' = $USER_AGENT }

# Accept both invocation styles: '-Batches 1,2' inside a session arrives as two
# elements, while 'pwsh -File ... -Batches 1,2' arrives as the single string
# '1,2'. Joining then re-splitting normalises the two.
$batchNumbers = ($Batches -join ',') -split ',' |
    Where-Object { $_.Trim() -match '^\d+$' } |
    ForEach-Object { [int] $_.Trim() }

if (-not $batchNumbers) {
    Write-Host '  Error: -Batches must be one or more numbers, e.g. -Batches 1,2' -ForegroundColor Red
    exit 1
}

$allRecords = New-Object System.Collections.Generic.List[object]

foreach ($batchNum in $batchNumbers) {
    $label = if ($BATCH_LABELS.ContainsKey($batchNum)) { $BATCH_LABELS[$batchNum] } else { "Batch $batchNum" }
    Write-Host ("  Fetching batch {0}/4  ({1}) ... " -f $batchNum, $label) -NoNewline
    $records = Get-UraBatch -Batch $batchNum -Headers $headers
    foreach ($r in $records) { $allRecords.Add($r) }
    Write-Host ('{0:N0} records' -f $records.Count)
}

Write-Host ''

if ($allRecords.Count -eq 0) {
    Write-Host '  No records fetched. Verify the Access Key and Token.' -ForegroundColor Red
    Write-Host '  Tokens expire daily - generate a fresh one at:'
    Write-Host "    $TOKEN_URL"
    Write-Host '    Header: AccessKey: <your-key>'
    exit 1
}

# Summary — column indices follow $COLS.
$years     = $allRecords | ForEach-Object { $_[9] }  | Sort-Object -Unique
$districts = $allRecords | ForEach-Object { $_[1] }  | Sort-Object -Unique
$projects  = $allRecords | ForEach-Object { $_[0] }  | Sort-Object -Unique

$districtPreview = ($districts | Select-Object -First 10) -join ', '
if ($districts.Count -gt 10) { $districtPreview += '...' }

Write-Host ('  Total records : {0:N0}' -f $allRecords.Count)
Write-Host ('  Years         : {0}-{1}' -f ($years | Select-Object -First 1), ($years | Select-Object -Last 1))
Write-Host ('  Districts     : {0}' -f $districtPreview)
Write-Host ('  Projects      : {0:N0} unique' -f $projects.Count)
Write-Host ''

# Write ura_data.js — compact columnar payload, matching fetch_ura_data.py.
$fetchedAt = (Get-Date).ToString('yyyy-MM-dd')

$writer = New-Object System.IO.StreamWriter($Out, $false, (New-Object System.Text.UTF8Encoding $false))
try {
    $writer.Write("// URA Real Data $([char]0x2014) $fetchedAt $([char]0x2014) $($allRecords.Count) records`n")
    $writer.Write('window.URA_DATA={"cols":[')
    $writer.Write((($COLS | ForEach-Object { ConvertTo-JsonStringLiteral $_ }) -join ','))
    $writer.Write('],"rows":[')

    $first = $true
    foreach ($row in $allRecords) {
        if (-not $first) { $writer.Write(',') }
        $first = $false
        $writer.Write('[')
        $writer.Write((($row | ForEach-Object { ConvertTo-JsonScalar $_ }) -join ','))
        $writer.Write(']')
    }

    $writer.Write('],"fetchedAt":')
    $writer.Write((ConvertTo-JsonStringLiteral $fetchedAt))
    $writer.Write("};`n")
} finally {
    $writer.Dispose()
}

$outFull = (Resolve-Path $Out).Path
Write-Host ('  Saved {0:N0} records -> {1}' -f $allRecords.Count, $outFull) -ForegroundColor Green
Write-Host ''
Write-Host '  Next step:'
Write-Host "   Place '$Out' in the same folder as index.html"
Write-Host '   Then open (or refresh) index.html - it will load automatically.'
Write-Host ''
Write-Host '  Refresh cadence:'
Write-Host '   URA publishes on a monthly cycle - re-run this on the 1st of each month.'
Write-Host '   The dashboard flags the data as stale once it is a month old.'
Write-Host ''
