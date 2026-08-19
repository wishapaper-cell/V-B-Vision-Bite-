Option Explicit

Dim fso, shell, shellApp, appRoot, workspaceRoot, startScript, appUrl
Dim attempt, ready

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
Set shellApp = CreateObject("Shell.Application")

appRoot = fso.GetParentFolderName(WScript.ScriptFullName)
workspaceRoot = fso.GetParentFolderName(fso.GetParentFolderName(appRoot))
startScript = fso.BuildPath(workspaceRoot, "scripts\dev\start-supervisor-web.ps1")
appUrl = "http://127.0.0.1:5100"
ready = IsApplicationReady(appUrl)

If Not ready Then
    If Not fso.FileExists(startScript) Then
        MsgBox "Cannot find the canonical supervisor start script: " & startScript, vbCritical, "Admin application error"
        WScript.Quit 1
    End If

    shell.CurrentDirectory = workspaceRoot
    shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & Q(startScript), 0, False

    For attempt = 1 To 150
        WScript.Sleep 200
        If IsApplicationReady(appUrl) Then
            ready = True
            Exit For
        End If
    Next
End If

If ready Then
    shellApp.ShellExecute appUrl, "", "", "open", 1
    WScript.Quit 0
End If

MsgBox "The admin application did not start. Run scripts\dev\start-supervisor-web.ps1 to inspect the error.", vbCritical, "Admin application error"
WScript.Quit 1

Function IsApplicationReady(url)
    On Error Resume Next
    Dim http
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.SetTimeouts 300, 300, 300, 300
    http.Open "GET", url, False
    http.Send
    IsApplicationReady = (Err.Number = 0 And http.Status >= 200 And http.Status < 500)
    Err.Clear
    On Error GoTo 0
End Function

Function Q(value)
    Q = Chr(34) & value & Chr(34)
End Function
