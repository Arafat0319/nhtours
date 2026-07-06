# 验证 nhtours.com DNS 是否已指向 Lightsail
# 用法: powershell -File deploy/verify-dns.ps1

$ExpectedIp = "54.69.40.218"
$Domains = @("nhtours.com", "www.nhtours.com")
$Ok = $true

foreach ($d in $Domains) {
    Write-Host "`n=== $d ===" -ForegroundColor Cyan
    try {
        $result = Resolve-DnsName -Name $d -Type A -ErrorAction Stop
        $ips = $result | Where-Object { $_.Type -eq 'A' } | ForEach-Object { $_.IPAddress }
        if (-not $ips) {
            Write-Host "  无 A 记录（可能是 CNAME，需改为 A -> $ExpectedIp）" -ForegroundColor Yellow
            $Ok = $false
            continue
        }
        foreach ($ip in $ips) {
            if ($ip -eq $ExpectedIp) {
                Write-Host "  OK  $ip" -ForegroundColor Green
            } else {
                Write-Host "  仍为 $ip（期望 $ExpectedIp，可能仍是 CloudFront）" -ForegroundColor Red
                $Ok = $false
            }
        }
    } catch {
        Write-Host "  解析失败: $_" -ForegroundColor Red
        $Ok = $false
    }
}

if ($Ok) {
    Write-Host "`nDNS 已就绪，可在服务器运行: sudo bash deploy/setup-domain.sh --certbot" -ForegroundColor Green
    exit 0
} else {
    Write-Host "`n请在 GoDaddy 修改 DNS，详见 手册/域名接入GoDaddy.md" -ForegroundColor Yellow
    exit 1
}
