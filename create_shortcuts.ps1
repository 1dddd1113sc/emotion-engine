$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("C:\Users\Daniel Wu\Desktop\V6 实时数据.lnk")
$Shortcut.TargetPath = "D:\OpenClawData\.openclaw\workspace\emotion-engine\v6_live_data.csv"
$Shortcut.Save()
Write-Output "done"
