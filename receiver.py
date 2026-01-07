import paho.mqtt.client as mqtt
import struct
import requests
import time
import threading

# -----------------------------
# CONFIGURATION
# -----------------------------
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "temperature/#"   # listen to all devices
ADDRESS = "temp.addr.es"

HTTP_URL_TEMPLATE = "http://{ADDRESS}/?devicerpi={DEVICE_ID}&cputemp={CPUTEMP}&temp={TEMP}&hum={HUM}&press=0"

UPDATE_INTERVAL = 60  # seconds between HTTP requests per device

# -----------------------------
# GLOBAL STATE
# -----------------------------
# {device_id: {"temp":..., "hum":..., "cpu":..., "last_mqtt":timestamp, "last_http":timestamp}}
last_data = {}
lock = threading.Lock()

# -----------------------------
# MQTT CALLBACKS
# -----------------------------
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT broker")
        client.subscribe(MQTT_TOPIC)
    else:
        print("Failed to connect, code:", rc)

def send_http(device_id, temp, hum, cpu_temp):
    url = HTTP_URL_TEMPLATE.format(
        DEVICE_ID=device_id,
        TEMP=temp,
        HUM=hum,
        CPUTEMP=cpu_temp
    )
    try:
        response = requests.get(url, timeout=5)
        print(f"[{time.strftime('%H:%M:%S')}] HTTP sent: {device_id} Temp={temp} Hum={hum} CPU={cpu_temp} Status={response.status_code}")
    except Exception as e:
        print(f"HTTP request failed for {device_id}: {e}")

def on_message(client, userdata, msg):
    try:
        # Get device ID from topic, support both SIM7080G and SIM868 devices
        topic_parts = msg.topic.split("/")
        device_id = topic_parts[-1]

        payload = msg.payload
        if len(payload) != 6:
            print(f"Invalid payload length from {device_id}: {len(payload)}")
            return

        # Decode binary payload: temp, hum, cpu
        temp_int, hum_int, cpu_int = struct.unpack(">hhh", payload)
        temp = temp_int / 100.0
        hum = hum_int / 10.0
        cpu_temp = cpu_int / 100.0

        with lock:
            last_data[device_id] = {
                "temp": temp,
                "hum": hum,
                "cpu": cpu_temp,
                "last_mqtt": time.time(),
                "last_http": last_data.get(device_id, {}).get("last_http", 0)
            }

    except Exception as e:
        print("Error handling message:", e)

# -----------------------------
# UPDATE LOOP: 1 HTTP request per device per 60s
# -----------------------------
def update_loop():
    while True:
        now = time.time()
        with lock:
            for device_id, data in last_data.items():
                if now - data.get("last_http", 0) >= UPDATE_INTERVAL:
                    # Use last known values (even if MQTT hasn't updated recently)
                    send_http(device_id, data["temp"], data["hum"], data["cpu"])
                    last_data[device_id]["last_http"] = now
        time.sleep(1)

# -----------------------------
# MAIN
# -----------------------------
def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    # Start HTTP update loop in separate thread
    threading.Thread(target=update_loop, daemon=True).start()

    client.loop_forever()

if __name__ == "__main__":
    main()
