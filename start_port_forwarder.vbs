Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\Gilman\Desktop\COMPARTIDOS\gilberto\WSL siempre en mini pc\ejecutables\port-forwarder"
sh.Run """C:\Users\Gilman\Desktop\COMPARTIDOS\gilberto\WSL siempre en mini pc\ejecutables\port-forwarder\port-forwarder.exe"" --minimized", 0, False
