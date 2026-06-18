$exe = 'C:\Users\Daniel Wu\AppData\Local\Microsoft\WinGet\Packages\LibreHardwareMonitor.LibreHardwareMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe\LibreHardwareMonitor.exe'
$ps = New-Object System.Diagnostics.Process
$ps.StartInfo.FileName = $exe
$ps.StartInfo.Verb = 'runas'
$ps.StartInfo.UseShellExecute = $true
$ps.Start()
Write-Output "PID: $($ps.Id)"
