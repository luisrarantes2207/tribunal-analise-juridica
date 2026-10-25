# Demonstracao publica do Tribunal (porta 8779 + tunel https da Cloudflare).
#   powershell -ExecutionPolicy Bypass -File iniciar_demo.ps1
# - Instancia SEPARADA da v2: storage/ e uploads/ proprios, sem nenhum dado do uso real.
# - Modo demonstracao: senha (senha_demo.txt), cada testador ve so as proprias sessoes, limite diario.
# - O endereco publico do tunel e' gravado em link_demo.txt (muda a cada reinicio do tunel).
# Para parar: feche esta janela e encerre o processo da porta 8779 e o cloudflared.exe DESTA pasta.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $dir 'watchdog_demo.log'
$out = Join-Path $dir 'server_demo.log'
$tun = Join-Path $dir 'tunel_demo.log'
$env:TRIBUNAL_DEMO = '1'
$env:TRIBUNAL_SENHA = (Get-Content (Join-Path $dir 'senha_demo.txt') -Raw).Trim()
$env:TRIBUNAL_LIMITE_DIA = '3'
$env:TRIBUNAL_LIMITE_CHAT = '20'
$tunel = $null
while ($true) {
    if (-not (Get-NetTCPConnection -LocalPort 8779 -State Listen -ErrorAction SilentlyContinue)) {
        Add-Content -Path $log -Value ("{0} subindo a demonstracao" -f (Get-Date -Format s))
        Start-Process -FilePath cmd.exe -WindowStyle Hidden -WorkingDirectory $dir -ArgumentList '/v:on','/c',
            "python -m uvicorn app:app --host 127.0.0.1 --port 8779 --proxy-headers >> `"$out`" 2>&1 & echo !date! !time! demo saiu com codigo !errorlevel! >> `"$log`""
        Start-Sleep -Seconds 8
    }
    if (-not $tunel -or $tunel.HasExited) {
        Add-Content -Path $log -Value ("{0} abrindo o tunel" -f (Get-Date -Format s))
        if (Test-Path $tun) { Remove-Item $tun -Force }
        $tunel = Start-Process -FilePath (Join-Path $dir 'cloudflared.exe') -WindowStyle Hidden -PassThru `
            -ArgumentList 'tunnel','--no-autoupdate','--url','http://127.0.0.1:8779','--logfile',"`"$tun`""
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 2
            $m = if (Test-Path $tun) { Select-String -Path $tun -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1 } else { $null }
            if ($m) {
                $url = $m.Matches[0].Value
                Set-Content -Path (Join-Path $dir 'link_demo.txt') -Value $url -Encoding ASCII
                Add-Content -Path $log -Value ("{0} link publico: {1}" -f (Get-Date -Format s), $url)
                break
            }
        }
    }
    Start-Sleep -Seconds 5
}
