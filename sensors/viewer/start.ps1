param([int]$Port = 5174)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '..\tools\blender-5.2.3-windows-x64\5.2\python\bin\python.exe'
if (!(Test-Path -LiteralPath $taskPython)) {
    $taskPythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (!$taskPythonCommand) { throw 'Python was not found. Restore the portable Blender folder or install Python 3.' }
    $taskPython = $taskPythonCommand.Source
}
& $taskPython (Join-Path $PSScriptRoot 'serve.py') --port $Port
