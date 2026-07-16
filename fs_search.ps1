param([string]$Query, [int]$Limit = 12)

# Search the Windows index (fast, covers indexed locations) for files/folders
# whose name matches $Query. Prints one full path per line.
$q = ($Query -replace "'", "").Trim()
if (-not $q) { return }
$sql = "SELECT TOP $Limit System.ItemPathDisplay FROM SYSTEMINDEX " +
       "WHERE System.ItemNameDisplay LIKE '%$q%' ORDER BY System.DateModified DESC"
try {
    $conn = New-Object -ComObject ADODB.Connection
    $conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
    $rs = $conn.Execute($sql)
    while (-not $rs.EOF) {
        $p = $rs.Fields.Item("System.ItemPathDisplay").Value
        if ($p) { Write-Output $p }
        $rs.MoveNext()
    }
    $rs.Close()
    $conn.Close()
} catch {
    # index unavailable — caller falls back to a filesystem walk
    Write-Error "INDEX_UNAVAILABLE"
}
