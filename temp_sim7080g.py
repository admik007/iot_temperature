import time
from machine import Pin, UART, mem32
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
CHECK_INTERVAL = 10  # seconds

MQTT_BROKER = "MQTT_URL_ADDRESS"
MQTT_PORT = 1883
MQTT_TOPIC = f"temperature/{DEVICE_ID}"

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def send_at(cmd, timeout=2000):
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

def nb_iot_check_signal():
    resp = send_at("AT+CSQ")
    try:
        parts = resp.split(":")[1].split(",")
        rssi = int(parts[0].strip())
        return rssi
    except:
        return 0

def nb_iot_init():
    print("Initializing SIM7080G...")
    send_at("AT")
    send_at("AT+CFUN=1")
    send_at("AT+CGATT=1")
    send_at('AT+CGDCONT=1,"IP","internet"')  # adjust APN
    time.sleep(2)
    print("NB-IoT ready.")

def nb_iot_wait_network():
    while True:
        rssi = nb_iot_check_signal()
        if rssi > 0 and rssi < 99:
            print("Network OK, RSSI:", rssi)
            break
        print("Waiting for NB-IoT network...")
        time.sleep(5)

def mqtt_connect():
    while True:
        try:
            send_at("AT+SMCONN=0")
            send_at(f'AT+SMCONF="CLIENTID","{DEVICE_ID}"')
            send_at(f'AT+SMCONF="URL","{MQTT_BROKER}",{MQTT_PORT}')
            send_at('AT+SMCONF="KEEPALIVE",60')
            send_at("AT+SMCONN")
            print("MQTT connected")
            return
        except Exception as e:
            print("MQTT connect failed, retrying...", e)
            time.sleep(5)

def mqtt_publish(topic, data_bytes):
    length = len(data_bytes)
    for _ in range(3):
        try:
            send_at(f'AT+SMPUB="{topic}",{length},1,0', timeout=5000)
            SIM_UART.write(data_bytes)
            print(f"Published binary data: {data_bytes}")
            return True
        except Exception as e:
            print("Publish failed, retrying MQTT...", e)
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
    # Pico CPU temp in Celsius
    # Formula from RP2040 datasheet: Temp = 27 - (ADC_VOLT - 0.706)/0.001721
    from machine import ADC
    sensor_temp = ADC(4)  # internal temp sensor
    reading = sensor_temp.read_u16() * 3.3 / 65535  # voltage
    temp_c = 27 - (reading - 0.706)/0.001721
    return temp_c

def encode_sensor(temp, hum, cpu_temp):
    """
    Encode temp, humidity, CPU temp as 6 bytes:
    - temp: int16 ×100
    - hum: int16 ×10
    - CPU temp: int16 ×100
    """
    temp_int = int(temp * 100)
    hum_int = int(hum * 10)
    cpu_int = int(cpu_temp * 100)
    return struct.pack(">hhh", temp_int, hum_int, cpu_int)  # big-endian shorts

# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    nb_iot_init()
    nb_iot_wait_network()
    mqtt_connect()

    last_temp = None
    last_hum = None
    last_cpu = None

    while True:
        rssi = nb_iot_check_signal()
        if rssi == 0 or rssi == 99:
            print("Network lost, reconnecting...")
            nb_iot_init()
            nb_iot_wait_network()
            mqtt_connect()

        temp, hum = read_sensor()
        cpu_temp = read_cpu_temp()

        if temp is None or hum is None or cpu_temp is None:
            time.sleep(CHECK_INTERVAL)
            continue

        # Only send if any value changed
        if (temp != last_temp) or (hum != last_hum):
            data_bytes = encode_sensor(temp, hum, cpu_temp)
            mqtt_publish(MQTT_TOPIC, data_bytes)
            last_temp = temp
            last_hum = hum
            last_cpu = cpu_temp

        time.sleep(CHECK_INTERVAL)

# -----------------------------
# RUN SCRIPT
# -----------------------------
if __name__ == "__main__":
    main()
