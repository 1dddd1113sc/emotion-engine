Set objShell = CreateObject("Shell.Application")
objShell.ShellExecute "cmd", "/c python D:\OpenClawData\.openclaw\workspace\emotion-engine\read_temp.py > D:\OpenClawData\.openclaw\workspace\emotion-engine\temp_result.txt 2>&1", "", "runas", 0
WScript.Sleep 5000
