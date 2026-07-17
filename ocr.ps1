param([string]$ImagePath)

# OCR via Windows' built-in engine (Windows.Media.Ocr) — no extra installs,
# no native binaries that Smart App Control could block.
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetGenericArguments().Count -eq 1
})[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(20000) | Out-Null
    return $netTask.Result
}

try {
    [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
    [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null

    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) { Write-Error "OCR_ENGINE_UNAVAILABLE"; exit 1 }

    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    Write-Output $result.Text
} catch {
    Write-Error ("OCR_ERROR: " + $_.Exception.Message)
    exit 1
}
