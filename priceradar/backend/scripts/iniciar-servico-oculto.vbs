' Lanca iniciar-servico.bat sem janela visivel — e o que o Agendador de
' Tarefas chama no login. Um .bat direto sempre pisca um console; passar
' por este .vbs com WindowStyle=0 evita isso.
Set fso = CreateObject("Scripting.FileSystemObject")
caminhoBat = fso.GetParentFolderName(WScript.ScriptFullName) & "\iniciar-servico.bat"
CreateObject("WScript.Shell").Run """" & caminhoBat & """", 0, False
