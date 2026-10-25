"""MPU-6050 / MPU-6500 (GY-6500) over I2C. Reads accel (g) and gyro (deg/s), with startup gyro bias."""
import time

from machine import I2C, Pin


class MPU:
    def __init__(self, sda=8, scl=9, addr=0x68, freq=400000, i2c_id=0):
        self.i2c = I2C(i2c_id, sda=Pin(sda), scl=Pin(scl), freq=freq)
        self.addr = addr
        who = self.i2c.readfrom_mem(addr, 0x75, 1)[0]
        if who not in (0x68, 0x70, 0x71, 0x72):   # 6050=0x68, 6500=0x70, some clones differ
            raise OSError("unexpected WHO_AM_I 0x%02x" % who)
        self.who = who
        self.i2c.writeto_mem(addr, 0x6B, b"\x00")   # wake
        time.sleep_ms(100)
        self.i2c.writeto_mem(addr, 0x1C, b"\x08")   # accel +-4 g  -> 8192 LSB/g
        self.i2c.writeto_mem(addr, 0x1B, b"\x08")   # gyro +-500 dps -> 65.5 LSB/dps
        self.bias = (0.0, 0.0, 0.0)

    def raw(self):
        d = self.i2c.readfrom_mem(self.addr, 0x3B, 14)
        v = [(d[i] << 8 | d[i + 1]) for i in range(0, 14, 2)]
        v = [x - 65536 if x > 32767 else x for x in v]
        return v   # ax ay az temp gx gy gz

    def calibrate(self, n=200):
        sx = sy = sz = 0
        for _ in range(n):
            r = self.raw()
            sx += r[4]; sy += r[5]; sz += r[6]
            time.sleep_ms(5)
        self.bias = (sx / n, sy / n, sz / n)

    def read(self):
        r = self.raw()
        return {
            "accel_g": [round(r[0] / 8192, 3), round(r[1] / 8192, 3), round(r[2] / 8192, 3)],
            "gyro_dps": [round((r[4] - self.bias[0]) / 65.5, 2), round((r[5] - self.bias[1]) / 65.5, 2),
                         round((r[6] - self.bias[2]) / 65.5, 2)],
            "temp_c": round(r[3] / 340 + 36.53, 1),
        }
