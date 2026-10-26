' campus-link-auto 开机自启：静默拉起校园网保活脚本（无黑框）
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\Mia\Project\campus-link-auto"
sh.Run """D:\New_Folder\anaconda3\pythonw.exe"" ""D:\Mia\Project\campus-link-auto\campus_link.py""", 0, False
