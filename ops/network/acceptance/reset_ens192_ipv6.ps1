# reset_ens192_ipv6.ps1
# For machine 1~13:
# 1. set ens192 down
# 2. flush IPv6 addresses on ens192
# 3. set ens192 up
# 4. verify status

$User = "switchpc1"
$IFACE = "ens192"

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

    Write-Host "===================================================="
    Write-Host "Reset ens192 IPv6 on machine $MachineNo : $HostIp"
    Write-Host "===================================================="

    # Use bash -lc to ensure shell variable IFACE works correctly on remote host.
    $Cmd = "set -e; IFACE=$IFACE; sudo ip link set `$IFACE down && sudo ip -6 addr flush dev `$IFACE; sudo ip link set `$IFACE up; ip addr show dev `$IFACE"

    ssh "$User@$HostIp" "bash -lc '$Cmd'"

    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK: machine $MachineNo ens192 reset finished" -ForegroundColor Green
    } else {
        Write-Host "FAILED: machine $MachineNo ens192 reset failed" -ForegroundColor Red
        $Failed += "machine $MachineNo $HostIp"
    }

    Write-Host ""
}

Write-Host "================ Summary ================"

if ($Failed.Count -eq 0) {
    Write-Host "All machines executed successfully." -ForegroundColor Green
} else {
    Write-Host "Failed machines:" -ForegroundColor Red
    foreach ($item in $Failed) {
        Write-Host $item -ForegroundColor Red
    }
}