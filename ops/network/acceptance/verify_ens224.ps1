# verify_ens224_v2.ps1
# Verify ens224 IP address on machine 1~13
# This version avoids remote grep and complicated quote escaping.

$User = "switchpc1"
$Nic = "ens224"

$Hosts = @(
    "10.112.126.124",  # machine 1
    "10.112.253.42",   # machine 2
    "10.112.20.40",    # machine 3
    "10.112.83.255",   # machine 4
    "10.112.202.252",  # machine 5
    "10.112.151.47",   # machine 6
    "10.112.247.103",  # machine 7
    "10.112.36.172",   # machine 8
    "10.112.230.69",   # machine 9
    "10.112.232.94",   # machine 10
    "10.112.133.84",   # machine 11
    "10.112.229.254",  # machine 12
    "10.112.118.133"   # machine 13
)

$Failed = @()

for ($i = 0; $i -lt $Hosts.Count; $i++) {

    $MachineNo = $i + 1
    $HostIp = $Hosts[$i]
    $ExpectedIp = "172.16.0.$(151 + $i)"
    $ExpectedCidr = "$ExpectedIp/24"

    Write-Host "===================================================="
    Write-Host "Verify machine $MachineNo : $HostIp"
    Write-Host "Expected: $ExpectedCidr"
    Write-Host "===================================================="

    # Get ens224 status from remote host.
    # Important: no grep, no pipe, no bash -lc, avoid quote problems.
    $Output = ssh "$User@$HostIp" "ip -4 addr show dev $Nic" 2>&1

    # Print current status
    $Output | ForEach-Object { Write-Host $_ }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: ssh or ip command failed on machine $MachineNo" -ForegroundColor Red
        $Failed += "machine $MachineNo $HostIp ssh/ip command failed"
        Write-Host ""
        continue
    }

    if ($Output -match [regex]::Escape($ExpectedCidr)) {
        Write-Host "OK: machine $MachineNo has $ExpectedCidr" -ForegroundColor Green
    } else {
        Write-Host "FAILED: machine $MachineNo does not have $ExpectedCidr" -ForegroundColor Red
        $Failed += "machine $MachineNo $HostIp expected $ExpectedCidr"
    }

    Write-Host ""
}

Write-Host "================ Summary ================"

if ($Failed.Count -eq 0) {
    Write-Host "All machines passed." -ForegroundColor Green
} else {
    Write-Host "Failed machines:" -ForegroundColor Red
    foreach ($item in $Failed) {
        Write-Host $item -ForegroundColor Red
    }
}