# config_ens224_fixed.ps1
# Configure ens224 on machine 1~13
# Machine 1~13 -> 172.16.0.151~172.16.0.163

$User = "switchpc1"
$Nic = "ens224"

$Hosts = @(
    "10.112.126.124",  # machine 1  -> 172.16.0.151
    "10.112.253.42",   # machine 2  -> 172.16.0.152
    "10.112.20.40",    # machine 3  -> 172.16.0.153
    "10.112.83.255",   # machine 4  -> 172.16.0.154
    "10.112.202.252",  # machine 5  -> 172.16.0.155
    "10.112.151.47",   # machine 6  -> 172.16.0.156
    "10.112.247.103",  # machine 7  -> 172.16.0.157
    "10.112.36.172",   # machine 8  -> 172.16.0.158
    "10.112.230.69",   # machine 9  -> 172.16.0.159
    "10.112.232.94",   # machine 10 -> 172.16.0.160
    "10.112.133.84",   # machine 11 -> 172.16.0.161
    "10.112.229.254",  # machine 12 -> 172.16.0.162
    "10.112.118.133"   # machine 13 -> 172.16.0.163
)

for ($i = 0; $i -lt $Hosts.Count; $i++) {

    $MachineNo = $i + 1
    $HostIp = $Hosts[$i]
    $NewIp = "172.16.0.$(151 + $i)"

    Write-Host "===================================================="
    Write-Host "Config machine $MachineNo : $HostIp -> $NewIp/24"
    Write-Host "===================================================="

    # Remote command.
    # set -e means: if any command fails, stop immediately.
    $Cmd = "set -e; sudo ip link set $Nic up; sudo ip addr flush dev $Nic; sudo ip addr add $NewIp/24 dev $Nic; ip -4 addr show dev $Nic"

    ssh "$User@$HostIp" "bash -lc '$Cmd'"

    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK: machine $MachineNo configured as $NewIp/24" -ForegroundColor Green
    } else {
        Write-Host "FAILED: machine $MachineNo $HostIp" -ForegroundColor Red
    }

    Write-Host ""
}