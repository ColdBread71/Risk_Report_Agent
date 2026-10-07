$ErrorActionPreference = 'Stop'
$base = 'd:\Coding\Risk_Report_Agent\scratch\tmp\extracted'
$ns = New-Object System.Xml.XmlNamespaceManager([System.Xml.NameTable]::new())
$ns.AddNamespace('m', 'http://schemas.openxmlformats.org/spreadsheetml/2006/main')

[xml]$ssXml = Get-Content "$base\xl\sharedStrings.xml" -Encoding UTF8
$shared = New-Object System.Collections.Generic.List[string]
foreach ($si in $ssXml.SelectNodes('//m:si', $ns)) {
    $text = ''
    foreach ($t in $si.SelectNodes('.//m:t', $ns)) { $text += $t.InnerText }
    $shared.Add($text)
}
Write-Host "sharedStrings: $($shared.Count)"

foreach ($sheet in @('sheet2', 'sheet3')) {
    [xml]$sh = Get-Content "$base\xl\worksheets\$sheet.xml" -Encoding UTF8
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($row in $sh.SelectNodes('//m:sheetData/m:row', $ns)) {
        $rowNum = [int]$row.GetAttribute('r')
        $cells = @()
        foreach ($c in $row.SelectNodes('./m:c', $ns)) {
            $ref = $c.GetAttribute('r')
            $t = $c.GetAttribute('t')
            $v = $c.SelectSingleNode('./m:v', $ns)
            if ($null -ne $v -and $null -ne $v.InnerText) {
                if ($t -eq 's') { $val = $shared[[int]$v.InnerText] }
                else { $val = $v.InnerText }
            } elseif ($t -eq 'inlineStr') {
                $tis = $c.SelectSingleNode('./m:is/m:t', $ns)
                $val = if ($null -ne $tis) { $tis.InnerText } else { '' }
            } else {
                continue
            }
            $val = $val -replace "`r", '' -replace "`n", '⏎'
            $cells += "$ref=$val"
        }
        if ($cells.Count -gt 0) { $out.Add("R$rowNum`t" + ($cells -join ' | ')) }
    }
    $out | Set-Content "$base\$sheet.dump.txt" -Encoding UTF8
    Write-Host "$sheet rows: $($out.Count)"
}
