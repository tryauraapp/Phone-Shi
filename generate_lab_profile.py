#!/usr/bin/env python3
"""Create per-AVD battery test fixtures. No physical battery health is claimed."""
import argparse
import json
from pathlib import Path
import random
import secrets


def create_profile(name):
    seed = secrets.randbits(128)
    rng = random.Random(seed)
    return {
        "schema": 2,
        "avd": name,
        "kind": "synthetic-battery-telemetry",
        "seed": str(seed),
        "battery": {
            "initial_level_percent": rng.randint(45, 85),
            "initial_temperature_tenths_c": rng.randint(270, 320),
            "simulated_full_charge_uah": rng.randint(3500, 3900) * 1000,
            "minutes_per_percent": rng.randint(8, 12),
        },
        "radio": {
            "initial_rssi_asu": rng.randint(16, 27),
            "interval_seconds": 15,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile = create_profile(args.name)
    battery = profile["battery"]
    # Exclusive creation keeps an existing device's fixture stable.
    with (args.output_dir / "device-profile.json").open("x") as stream:
        json.dump(profile, stream, indent=2)
        stream.write("\n")
    with (args.output_dir / "battery.conf").open("x") as stream:
        stream.write(
            "# Synthetic battery fixture; health/wear/voltage are not overridden.\n"
            f"LEVEL={battery['initial_level_percent']}\n"
            f"TEMP={battery['initial_temperature_tenths_c']}\n"
            f"FULL_CHARGE_UAH={battery['simulated_full_charge_uah']}\n"
            f"DRAIN_TICKS={battery['minutes_per_percent']}\n"
            "TICKS=0\n"
        )


if __name__ == "__main__":
    main()
