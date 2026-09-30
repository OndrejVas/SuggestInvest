Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "c:\Users\uzivatel\Desktop\SuggestInvest"
WshShell.Run "pythonw autoinvest_service.py", 0, False
