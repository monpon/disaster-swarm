# ESP32-S3 (N16R8) relay feasibility test

Result (2026-10-24, MicroPython 1.29.0): AP + client on one radio works. The S3 joined the E58 as a
client (channel 1) and ran its own AP on the same channel, forwarding UDP 8080/8090 both ways:
about 175 video datagrams/s (233 KiB/s) down, 40 RC/s up, 0 send drops, 1 client. The drone's own
datagram rate varies 170-235/s between runs, so the S3 is not clearly the bottleneck. Frame integrity
(JPEG fragment loss) was not measured.

## Flash (board needs a data cable; two cables here were power-only)

1. Plug in the port labelled USB. Hold BOOT, tap RESET, release BOOT. It shows as `303a:1001`.
2. Back up first: `esptool --port /dev/ttyACM0 read-flash 0 ALL s3-backup.bin` (16 MB, ~85 s).
3. `esptool --port /dev/ttyACM0 erase-flash`, then
   `esptool --port /dev/ttyACM0 write-flash -z 0 ESP32_GENERIC_S3-SPIRAM_OCT-<ver>.bin`
   (the SPIRAM_OCT build matches the N16R8's octal PSRAM).
4. The chip can stay in download mode after flashing. Boot it with
   `esptool --port /dev/ttyACM0 --after watchdog-reset chip-id`, or tap RESET. It then shows as `303a:4001`.

Serial access without logging out: `newgrp uucp` (this system has no `sg`).

## Run the test

```sh
mpremote connect /dev/ttyACM0 run esp32/relay_test.py        # drone must be on; prints stats every 2 s
DRONE_SSID=s3-relay-test JOIN_SUBNET='192\.168\.5\.' scripts/wifi_cycle.sh -- \
    env PYTHONPATH=. python probe.py --ip 192.168.5.1
```

The AP must be activated before it is configured (`Wifi Invalid Mode` otherwise).
