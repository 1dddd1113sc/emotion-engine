$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("C:\Users\Daniel Wu\Desktop\启动温度监控.lnk")
$Shortcut.TargetPath = "C:\Users\Daniel Wu\AppData\Local\Microsoft\WinGet\Packages\LibreHardwareMonitor.LibreHardwareMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe\LibreHardwareMonitor.exe"
$Shortcut.WorkingDirectory = "C:\Users\Daniel Wu\AppData\Local\Microsoft\WinGet\Packages\LibreHardwareMonitor.LibreHardwareMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe"
$Shortcut.Save()

# Set "Run as administrator" flag in the shortcut
$bytes = [System.IO.File]::ReadAllBytes("C:\Users\Daniel Wu\Desktop\启动温度监控.lnk")
$bytes[0x15] = $bytes[0x15] -bor 0x20  # Set the "Run as administrator" flag
[System.IO.File]::WriteAllBytes("C:\Users\Daniel Wu\Desktop\启动温度监控.lnk", $bytes)

Write-Output "done"
