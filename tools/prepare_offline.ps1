# 서무비서 AI - 업무망(인터넷 없는 PC)용 설치 묶음 만들기
# 인터넷이 되는 PC에서 프로그램 폴더 안에서 한 번 실행합니다:
#   powershell -ExecutionPolicy Bypass -File tools\prepare_offline.ps1
# 결과: engine\(내장 AI 엔진), models\(AI 모델 .gguf), wheels\(Python 패키지)
# 이 폴더 전체를 USB 등으로 업무망 PC에 복사한 뒤 install.bat 을 실행하면 됩니다.

param(
  [string]$ChatModel = "gemma-4-E2B-it",          # Hugging Face에서 검색할 답변 모델 이름
  [string]$EmbedModel = "embeddinggemma-300m",    # 검색 보조 모델 (빈 값이면 받지 않음)
  [string]$Quant = "Q4_0|Q4_K_M",                 # 받을 양자화 파일 (QAT 모델은 Q4_0 권장)
  [switch]$SkipEngine, [switch]$SkipModels, [switch]$SkipWheels
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "[서무비서 AI] 업무망 설치 묶음을 만듭니다: $Root" -ForegroundColor Cyan

function Get-HFGguf([string]$Search, [string]$Dest) {
  $q = [uri]::EscapeDataString($Search)
  $models = Invoke-RestMethod "https://huggingface.co/api/models?search=$q&filter=gguf&sort=downloads&limit=10"
  foreach ($m in $models) {
    $info = Invoke-RestMethod "https://huggingface.co/api/models/$($m.id)"
    $file = $info.siblings | Where-Object { $_.rfilename -match '\.gguf$' -and $_.rfilename -notmatch 'mmproj' -and $_.rfilename -match $Quant } |
            Select-Object -First 1
    if ($file) {
      $name = Split-Path $file.rfilename -Leaf
      $out = Join-Path $Dest $name
      if (Test-Path $out) { Write-Host "  이미 있음: $name"; return }
      Write-Host "  받는 중: $($m.id) / $name"
      Invoke-WebRequest "https://huggingface.co/$($m.id)/resolve/main/$($file.rfilename)" -OutFile "$out.part" -UseBasicParsing
      Move-Item "$out.part" $out -Force
      return
    }
  }
  Write-Warning "  '$Search' GGUF 파일을 찾지 못했습니다. Hugging Face에서 직접 받아 models 폴더에 넣어 주세요."
}

if (-not $SkipEngine) {
  Write-Host "`n[1/3] 내장 AI 엔진(llama.cpp) 받는 중..." -ForegroundColor Cyan
  $rel = Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" -Headers @{ "User-Agent" = "SeomuAI" }
  $asset = $rel.assets | Where-Object { $_.name -match 'bin-win-cpu-x64\.zip$' } | Select-Object -First 1
  if (-not $asset) { throw "llama.cpp Windows CPU 빌드를 찾지 못했습니다." }
  $zip = Join-Path $env:TEMP $asset.name
  Invoke-WebRequest $asset.browser_download_url -OutFile $zip -UseBasicParsing
  if (Test-Path engine) { Remove-Item engine -Recurse -Force }
  Expand-Archive $zip -DestinationPath engine -Force
  Write-Host "  완료: $($rel.tag_name) → engine\"
}

if (-not $SkipModels) {
  Write-Host "`n[2/3] AI 모델(.gguf) 받는 중... (수 GB, 시간이 걸립니다)" -ForegroundColor Cyan
  New-Item -ItemType Directory -Force models | Out-Null
  Get-HFGguf $ChatModel "models"
  if ($EmbedModel) { Get-HFGguf $EmbedModel "models" }
}

if (-not $SkipWheels) {
  Write-Host "`n[3/3] Python 패키지 받는 중..." -ForegroundColor Cyan
  $py = "python"
  if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py" }
  & $py -m pip download -r requirements.txt -d wheels
}

Write-Host "`n완료! 이 폴더 전체를 업무망 PC로 복사한 뒤 install.bat 을 실행하세요." -ForegroundColor Green
Write-Host "(업무망 PC에는 Python 설치 파일도 함께 가져가세요: https://www.python.org/downloads/windows/)"
