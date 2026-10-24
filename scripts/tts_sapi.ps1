<#
SAPI 语音合成。文本从文件读，绝不经命令行传递——避免引号/命令注入。
用法：powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tts_sapi.ps1 -TextFile a.txt -OutFile a.wav
#>
param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [string]$Voice = 'Microsoft Huihui Desktop',
    [int]$Rate = 0
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

if (-not (Test-Path -LiteralPath $TextFile)) { Write-Error 'TextFile not found'; exit 2 }
$text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
if ([string]::IsNullOrWhiteSpace($text)) { Write-Error 'empty text'; exit 3 }

$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    try { $synth.SelectVoice($Voice) } catch { }   # 没装该音色就用默认
    $synth.Rate = $Rate
    $dir = Split-Path -Parent $OutFile
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $synth.SetOutputToWaveFile($OutFile, $fmt)
    $synth.Speak($text)
}
finally {
    $synth.Dispose()
}

if (-not (Test-Path -LiteralPath $OutFile)) { Write-Error 'no output'; exit 4 }
exit 0
