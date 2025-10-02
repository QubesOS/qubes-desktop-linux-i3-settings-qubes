#!/usr/bin/python3
import re
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime
from qubesadmin import Qubes
from qubesadmin import exc as qadmin_exc

app = Qubes()


def json_output(name, full_text, color=None):
    entry = {"name": name, "full_text": full_text}
    if color:
        entry["color"] = color
    return entry


def status_net():
    netvms = [
        vm for vm in app.domains if vm.features.get("servicevm") == "1" and not vm.netvm
    ]
    net_status = []

    for netvm in netvms:
        if not netvm.is_running():
            continue
        stdout, _ = netvm.run("ip -o -f inet addr")
        for line in stdout.decode("utf-8").splitlines():
            match = re.match(
                r"\d+: ((ens|eth|wl)\S+)(\s+)inet (\d+\.\d+\.\d+\.\d+)\/\d{1,2}", line
            )
            if match:
                device_name = match.group(1)
                ip = match.group(4)
                net_info = {
                    "device_name": device_name,
                    "info": f"{netvm.name}: {ip}",
                }
                if device_name.startswith("wl"):
                    iw_info, _ = netvm.run("iw dev {} link".format(device_name))
                    ssid = None
                    for iw_line in iw_info.decode("utf-8").splitlines():
                        # we allow only word and space characters
                        ssid_match = re.match(r"^\s+SSID: ([\w\s]*)$", iw_line)
                        if ssid_match:
                            ssid = iw_line.split("SSID:")[1].strip()
                            break
                    if ssid:
                        net_info["info"] += f" {ssid}"

                net_status.append(
                    json_output(net_info["device_name"], net_info["info"])
                )
    return net_status


def status_time():
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return json_output("time", current_time)


def status_bat():
    batteries = list(Path("/sys/class/power_supply").glob("BAT*"))
    if not batteries:
        return

    accum_now_mWh = 0
    accum_full_mWh = 0
    for battery in batteries:
        try:
            energy_now = battery / "energy_now"
            energy_full = battery / "energy_full"
            if energy_now.exists() and energy_full.exists():
                accum_now_mWh += int(energy_now.read_text().strip())
                accum_full_mWh += int(energy_full.read_text().strip())
            else:
                charge_now = battery / "charge_now"
                voltage_now = battery / "voltage_now"
                if charge_now.exists() and voltage_now.exists():
                    charge_now = int(charge_now.read_text().strip())
                    voltage_now = int(voltage_now.read_text().strip())
                    accum_now_mWh += (voltage_now / 1000) * (charge_now / 1000)
                    charge_full = battery / "charge_full"
                    if charge_full.exists():
                        charge_full = int(charge_full.read_text().strip())
                        accum_full_mWh += (voltage_now / 1000) * (charge_full / 1000)
        except Exception as e:
            print(f"Error reading battery info: {e}")
            return

    if accum_full_mWh == 0:
        bat_pct = 0
    else:
        bat_pct = int(100 * accum_now_mWh / accum_full_mWh)

    adps = list(Path("/sys/class/power_supply").glob("ADP*")) + list(
        Path("/sys/class/power_supply").glob("AC*")
    )
    ac_present = any(
        (adp / "online").read_text().strip() == "1"
        for adp in adps
        if (adp / "online").exists()
    )

    ac = ""
    color = None
    if ac_present:
        ac = " AC"
    elif bat_pct < 25:
        color = "#ff0000"
    elif bat_pct < 50:
        color = "#ffff00"

    return json_output("bat", f"Bat: {bat_pct}%{ac}", color)


def status_load():
    with open("/proc/loadavg", "r") as f:
        load_avg = f.read().split()[0]
    return json_output("load", f"Load: {load_avg}")


def status_qubes():
    running_qubes = len([vm for vm in app.domains if vm.is_running() and vm.name != "dom0"])
    if running_qubes == 0:
        return
    elif running_qubes == 1:
        return json_output("qubes", f"{running_qubes} qube")
    else:
        return json_output("qubes", f"{running_qubes} qubes")


def status_disk():
    default_pool = app.pools[app.property_get_default("default_pool_private")]
    size = int(default_pool.size)
    usage = int(default_pool.usage)
    free = size - usage

    if free >= 1 << 40:
        disk_free = f"{free >> 40}T"
    elif free >= 1 << 30:
        disk_free = f"{free >> 30}G"
    elif free >= 1 << 20:
        disk_free = f"{free >> 20}M"
    elif free >= 1 << 10:
        disk_free = f"{free >> 10}K"
    else:
        disk_free = f"{free} Bytes"
    return json_output("disk", f"Disk free: {disk_free}")


def status_volume():
    try:
        volcmd = subprocess.run(
            ["amixer", "sget", "Master"],
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception as e:
        print(f"Error reading volume info: {e}")
        return

    # Find the volume level and the on/off state
    volume_pattern = re.compile(r"Playback \d+ \[(\d+)%\] \[(on|off)\]")

    # Find all volumes
    volume_matches = volume_pattern.findall(volcmd.stdout)

    if volume_matches:
        # Check if any channel is on
        all_off = all(state == "off" for _, state in volume_matches)

        if all_off:
            return json_output("volume", "Volume: mute")

        # Assuming the first match with 'on' state is the required volume level
        for volume, state in volume_matches:
            if state == "on":
                return json_output("volume", f"Volume: {volume}")


def main():
    # Send the header so that i3 bar knows we want to use JSON.
    print('{"version": 1}', flush=True)
    # Begin the endless array.
    print("[", flush=True)
    # We send an empty first array of blocks to make the loop simpler.
    print("[]", flush=True)

    n = 0
    qubesd_status = None
    qubes_status = None
    disk_status = None
    bat_status = None
    load_status = None
    volume_status = None
    net_status = None
    while True:
        if n % 2 == 0:
            try:
                qubes_status = status_qubes()
                disk_status = status_disk()
                # network status disabled by default as it's dangerous to run a
                # command on an untrusted qube from dom0/adminvm
                # net_status = status_net()
            except qadmin_exc.QubesDaemonCommunicationError:
                qubesd_status = json_output("qubesd", "qubesd connection failed")
            bat_status = status_bat()
            load_status = status_load()
            volume_status = status_volume()

        time_status = status_time()

        status_list = [
            qubesd_status,
            qubes_status,
            disk_status,
            bat_status,
            load_status,
            volume_status,
            time_status,
            net_status,
        ]
        final_status_list = [status for status in status_list if status is not None]
        print("," + json.dumps(final_status_list), flush=True)

        time.sleep(1)
        n += 1


if __name__ == "__main__":
    main()
