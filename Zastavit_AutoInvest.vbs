Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell -WindowStyle Hidden -Command ""Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*autoinvest_service*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }""", 0, True
