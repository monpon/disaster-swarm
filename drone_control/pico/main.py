"""Pico 2 W health heartbeat. Copy to the board as main.py: `mpremote cp pico/main.py :main.py`.

LED pattern: one short blink per second = MicroPython running. The LED is on the CYW43 radio chip,
so a working blink also proves the wifi chip initialised.
"""
import time

from machine import Pin

led = Pin("LED", Pin.OUT)
while True:
    led.on()
    time.sleep_ms(80)
    led.off()
    time.sleep_ms(920)
