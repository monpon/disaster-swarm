"""Stream raw MPU samples over USB as CSV (MicroPython, runs on the ESP32-S3).

Needs mpu.py on the board. One line per sample:  t_us,ax,ay,az,gx,gy,gz
accel in g, gyro in deg/s with no bias removed (the host estimates bias from the
still period at the start). Lines starting with '#' are metadata.

Run: mpremote connect /dev/ttyACM0 cp esp32/mpu.py :mpu.py + run imu/board_stream.py
"""
import time

from mpu import MPU

RATE_HZ = 200
SDA, SCL = 11, 12   # current wiring (an I2C sweep found 0x68 here, not on the mpu.py default 8/9)

def connect():
    # Loose jumpers drop the IMU off the bus mid-recording; keep retrying.
    while True:
        try:
            return MPU(sda=SDA, scl=SCL)
        except OSError:
            time.sleep_ms(100)


imu = connect()
print("# who 0x%02x rate %d" % (imu.who, RATE_HZ))
print("# t_us,ax,ay,az,gx,gy,gz")
period = 1000000 // RATE_HZ
next_t = time.ticks_us()
t0 = next_t
while True:
    try:
        r = imu.raw()
    except OSError as e:
        print("# i2c lost at %d: %s" % (time.ticks_diff(time.ticks_us(), t0), e))
        imu = connect()
        print("# i2c back at %d" % time.ticks_diff(time.ticks_us(), t0))
        next_t = time.ticks_us()
        continue
    now = time.ticks_us()
    print("%d,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f" % (
        time.ticks_diff(now, t0), r[0] / 8192, r[1] / 8192, r[2] / 8192,
        r[4] / 65.5, r[5] / 65.5, r[6] / 65.5))
    next_t = time.ticks_add(next_t, period)
    wait = time.ticks_diff(next_t, time.ticks_us())
    if wait > 0:
        time.sleep_us(wait)
    else:
        next_t = time.ticks_us()   # fell behind: resync instead of bursting
