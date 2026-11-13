Option Explicit
Dim shell, fso, projectDir, pythonw, entry
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = projectDir & "\.venv\Scripts\pythonw.exe"
entry = projectDir & "\astra_desktop.pyw"
If Not fso.FileExists(pythonw) Then
    MsgBox "Astra Python environment was not found.", vbCritical, "Astra"
    WScript.Quit 1
End If
shell.CurrentDirectory = projectDir
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & entry & Chr(34), 1, False
