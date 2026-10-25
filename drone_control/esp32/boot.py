# Keep wifi off at boot: ESP-IDF can auto-reconnect to a saved network and hog the drone's only client slot.
import network

network.WLAN(network.STA_IF).active(False)
network.WLAN(network.AP_IF).active(False)
