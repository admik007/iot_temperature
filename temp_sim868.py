import time
from machine import Pin, UART, ADC
import dht
from ubinascii import hexlify
import struct

# -----------------------------
# CONFIGURATION
# -----------------------------
DEVICE_ID = hexlify(machine.unique_id()).decode()  # unique device ID
DHT_PIN = 15
dht_sensor = dht.DHT22(Pin(DHT_PIN))

SIM_UART = UART(1, baudrate=9600, tx=4, rx=5)  # adjust TX/RX pins
CHECK_INTERVAL = 10  # seconds between sensor reads

MQTT_BROKER = "MQTT_URL_ADDRESS"
MQTT_PORT = 1883
MQTT_TOPIC = f"temperature/{DEVICE_ID}"

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def send_at(cmd, timeout=3000):
    SIM_UART.write(cmd + "\r\n")
    t_start = time.ticks_ms()
    response = b""
    while time.ticks_ms() - t_start < timeout:
        if SIM_UART.any():
            response += SIM_UART.read(SIM_UART.any())
        if b"OK" in response or b"ERROR" in response:
            break
        time.sleep(0.1)
    return response.decode()

# -----------------------------
# NB-IoT -> 2G/GPRS INIT
# -----------------------------
def gprs_init():
    """Initialize SIM868 2G/GPRS network"""
    print("Initializing SIM868 GPRS...")
    send_at("AT")               # basic AT test
    send_at("AT+CFUN=1")        # full functionality
    send_at("AT+CGATT=1")       # attach to GPRS
    send_at('AT+SAPBR=3,1,"CONTYPE","GPRS"')
    send_at('AT+SAPBR=3,1,"APN","internet"')  # replace 'internet' with your APN
    send_at("AT+SAPBR=1,1")     # open bearer
    send_at("AT+SAPBR=2,1")     # query IP
    print("GPRS ready")

# -----------------------------
# MQTT FOR SIM868 (CMQTT commands)
# -----------------------------
def mqtt_connect():
    """Connect to MQTT broker"""
    while True:
        try:
            send_at("AT+CMQTTDISC=0")   # disconnect previous session
            send_at(f'AT+CMQTTSTART=0')
            send_at(f'AT+CMQTTACCQ=0,"{DEVICE_ID}"')
            send_at(f'AT+CMQTTCONNECT=0,"tcp://{MQTT_BROKER}:{MQTT_PORT}",60,1')
            print("MQTT connected")
            return
        except Exception as e:
            print("MQTT connect failed, retrying...", e)
            time.sleep(5)

def mqtt_publish(topic, data_bytes):
    """Publish binary data via SIM868"""
    length = len(data_bytes)
    for _ in range(3):
        try:
            send_at(f'AT+CMQTTTOPIC=0,"{topic}",{len(topic)}')
            send_at(f'AT+CMQTTPAYLOAD=0,{length}')
            SIM_UART.write(data_bytes)
            send_at("AT+CMQTTPUB=0,1,60")  # qos=1, timeout=60s
            print(f"Published binary data: {data_bytes}")
            return True
        except Exception as e:
            print("Publish failed, reconnecting MQTT...", e)
            mqtt_connect()
            time.sleep(2)
    print("Failed to publish after 3 attempts")
    return False

# -----------------------------
# SENSOR READING
# -----------------------------
def read_sensor():
    try:
        dht_sensor.measure()
        temp = dht_sensor.temperature()
        hum = dht_sensor.humidity()
        return temp, hum
    except Exception as e:
        print("Sensor read error:", e)
        return None, None

def read_cpu_temp():
    """RPi Pico internal CPU temp"""
    sensor_temp = ADC(4)  # internal sensor
    reading = sensor_temp.read_u16() * 3.3 / 65535
    temp_c = 27 - (reading - 0.706)/0.001721
    return temp_c

def encode_sensor(temp, hum, cpu_temp):
    """Encode 6 bytes: temp, hum, CPU temp"""
    temp_int = int(temp * 100)
    hum_int = int(hum * 10)
    cpu_int = int(cpu_temp * 100)
    return struct.pack(">hhh", temp_int, hum_int, cpu_int)

# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    gprs_init()
    mqtt_connect()

    last_temp = None
    last_hum = None

    while True:
        # Read sensors
        temp, hum = read_sensor()
        cpu_temp = read_cpu_temp()
        if temp is None or hum is None or cpu_temp is None:
            time.sleep(CHECK_INTERVAL)
            continue

        # Send only if temp or hum changed
        if temp != last_temp or hum != last_hum:
            data_bytes = encode_sensor(temp, hum, cpu_temp)
            mqtt_publish(MQTT_TOPIC, data_bytes)
            last_temp = temp
            last_hum = hum

        time.sleep(CHECK_INTERVAL)

# -----------------------------
# RUN SCRIPT
# -----------------------------
if __name__ == "__main__":
    main()
