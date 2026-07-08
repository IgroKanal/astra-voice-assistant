' Starts Astra in background without a visible PowerShell/cmd window.
Option Explicit
Dim shell, fso, projectDir, pythonw, python, mainPy, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = projectDir & "\.venv\Scripts\pythonw.exe"
python = projectDir & "\.venv\Scripts\python.exe"
mainPy = projectDir & "\main.py"

If Not fso.FileExists(mainPy) Then
    MsgBox "main.py not found: " & mainPy, vbCritical, "Astra"
    WScript.Quit 1
End If

If Not fso.FolderExists(projectDir & "\logs") Then
    fso.CreateFolder(projectDir & "\logs")
End If

shell.CurrentDirectory = projectDir
shell.Environment("PROCESS")("PYTHONUTF8") = "1"

If fso.FileExists(pythonw) Then
    command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & mainPy & Chr(34)
ElseIf fso.FileExists(python) Then
    command = Chr(34) & python & Chr(34) & " " & Chr(34) & mainPy & Chr(34)
Else
    MsgBox "Python not found in .venv. Create the virtual environment and install dependencies first.", vbCritical, "Astra"
    WScript.Quit 1
End If

shell.Run command, 0, False
