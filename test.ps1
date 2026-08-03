$env:PYTHONPATH="src"
uv run python -X importtime -m main 2>.\import.log

Get-Content import.log | 
    Where-Object { $_ -match 'import time:' } | 
    Select-Object -Last 30 | 
    ForEach-Object {
        $parts = $_ -split '\|'
        if ($parts.Count -eq 3) {
            [PSCustomObject]@{
                Cumulative_us = [int]($parts[1].Trim())
                Self_us       = [int]($parts[0].Replace('import time:', '').Trim())
                Module        = $parts[2].Trim()
            }
        }
    } | 
    Sort-Object Cumulative_us -Descending | 
    Format-Table -AutoSize