' 게임 감시기 — 콘솔 창 없이 (로그인 시 상시 실행)
' 창이 뜨면 게임 중에 검은 창이 앞으로 튀어나온다. 다른 워치독과 같은 방식.
Option Explicit
Dim shell, repoRoot, ps, cmd
repoRoot = "C:\RoboMetaFit"
Set shell = CreateObject("WScript.Shell")
ps = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe")
cmd = ps & " -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -NonInteractive -File """ & repoRoot & "\tools\alture-jarvis\scripts\game_watchdog.ps1"" -RepoRoot """ & repoRoot & """"
shell.CurrentDirectory = repoRoot
shell.Run cmd, 0, False
