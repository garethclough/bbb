from gc import enable

from flask import Flask, render_template, request, jsonify
from vl6180x_bbb import VL6180X, RANGE_ERRORS
import Adafruit_BBIO.GPIO as GPIO
import Adafruit_BBIO.PWM as PWM
import time
import threading
import json
from pathlib import Path
import subprocess


LED_PIN_1 = "P9_14"
LED_PIN_2 = "P9_16"
LEDPATH='/sys/class/leds/beaglebone:green:usr3/brightness'
TRIGGERPATH = '/sys/class/leds/beaglebone:green:usr3/trigger'
DELAY_ON = '/sys/class/leds/beaglebone:green:usr3/delay_on'
DELAY_OFF = '/sys/class/leds/beaglebone:green:usr3/delay_off'
PWM_PATH_1 = Path("/sys/class/pwm/pwmchip5/pwm0")
PWM_PATH_2 = Path("/sys/class/pwm/pwmchip5/pwm1")
LED_PIN_3 = "P9_22"
PWM_PATH_3 = Path("/sys/class/pwm/pwmchip3/pwm0")
PERIOD = 1000000  # 1 kHz

class LED:
    def __init__(self, id, name, pwm_path, pin):
        self.id = id
        self.name = name
        self.pwm_path = pwm_path
        self.pin = pin
        self.brightness = 50.0
        self.configure()
        self.initPVM()

    def configure(self):
        subprocess.run(
            ["config-pin", self.pin, "pwm"],
            check=True
        )

    def initPVM(self):
        enable = self.pwm_path / "enable"
        period = self.pwm_path / "period"
        duty = self.pwm_path / "duty_cycle"

        current_period = int(period.read_text())

        # Only disable if a period has already been configured
        if current_period > 0 and enable.read_text().strip() == "1":
            enable.write_text("0")

        period.write_text(str(PERIOD))
        duty.write_text("0")

    def turnOn(self):
        print(f"Turning on {self.name} with brightness {self.brightness}%")
        self.brightness = max(0, min(100, self.brightness))
        duty = int(PERIOD * self.brightness / 100)
        (self.pwm_path / "enable").write_text("0")
        (self.pwm_path / "period").write_text(str(PERIOD))
        (self.pwm_path / "duty_cycle").write_text(str(duty))
        (self.pwm_path / "enable").write_text("1")

    def turnOff(self):
        (self.pwm_path / "enable").write_text("0")

    def setBrightness(self, percent):
        percent = max(0, min(100, percent))
        self.brightness = percent
        duty = int(PERIOD * self.brightness / 100)
        (self.pwm_path / "duty_cycle").write_text(str(duty))

class DistanceSensor:
    """VL6180X time-of-flight distance sensor on I2C."""

    def __init__(self, id, name, bus_num=2):
        self.id = id
        self.name = name
        self.bus_num = bus_num
        self.sensor = None
        self.lock = threading.Lock()  # Flask may serve requests concurrently

    def connect(self):
        if self.sensor is None:
            sensor = VL6180X(self.bus_num)
            try:
                sensor.init()
            except Exception:
                sensor.close()
                raise
            self.sensor = sensor

    def read(self):
        with self.lock:
            try:
                self.connect()
                dist, status = self.sensor.range_mm()
            except Exception as e:
                # Drop the connection so the next read retries from scratch
                if self.sensor is not None:
                    self.sensor.close()
                    self.sensor = None
                return {"id": self.id, "name": self.name, "ok": False,
                        "distance_mm": None, "error": str(e)}, 503

        result = {
            "id": self.id,
            "name": self.name,
            "ok": status == 0,
            "distance_mm": dist if status == 0 else None,
        }
        if status != 0:
            result["error"] = RANGE_ERRORS.get(status, f"status {status}")
        return result, 200

app = Flask(__name__)
threadRunning = False

SETTINGS_FILE = Path(__file__).with_name("settings.json")

led1 = LED("led1", "LED 1", PWM_PATH_1, LED_PIN_1)
led2 = LED("led2", "LED 2", PWM_PATH_2, LED_PIN_2)
led3 = LED("led3", "LED 3", PWM_PATH_3, LED_PIN_3)

leds = [led1, led2, led3]

distance_sensor = DistanceSensor("vl6180x", "Distance Sensor", bus_num=2)

def loadSettings():
    try:
        with open(SETTINGS_FILE, "r") as file:
            settings = json.load(file)

        if isinstance(settings.get("led"), list):
            for setting_led in settings["led"]:
                if "id" in setting_led:
                    for led in leds:
                        if led.id == setting_led["id"] and "brightness" in setting_led:
                            led.brightness = setting_led["brightness"]

        return settings

    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def saveSettings():
    with open(SETTINGS_FILE, "w") as file:
        settings_to_save = {"led": []}
        for led in leds:
            settings_to_save["led"].append({
                "id": led.id,
                "brightness": led.brightness
            })
        json.dump(settings_to_save, file, indent=4)

loadSettings()

def setBrightness(percent):
    for led in leds:
        led.setBrightness(percent)

def mainThread(led):
    global threadRunning,brightness
    while threadRunning:
        led.turnOn()
        time.sleep(0.5)
        led.turnOff()
        time.sleep(0.5)

@app.route("/sensor", methods=['GET'])
def handleSensor():
    reading, status_code = distance_sensor.read()
    return jsonify(reading), status_code

@app.route("/",methods=['GET','POST'])
def handleRoute():
    global threadRunning, brightness

    if request.method == 'POST':
        print("POST data:", request.form.to_dict(), flush=True)
        led_id = request.form["led_id"]
        brightness = float(request.form.get("brightness", 50.0))
        current_led = None
        for led in leds:
            if led.id == led_id:
                current_led = led
                break
        if current_led is None:
            return "Invalid LED ID", 400

        action = request.form.get("action")
        if action == "ON":
            threadRunning = False
            current_led.setBrightness(brightness)
            current_led.turnOn()
        elif action == "OFF":
            threadRunning = False
            current_led.setBrightness(brightness)
            current_led.turnOff()

        elif action == "FLASH":
            current_led.setBrightness(brightness)
            threadRunning = True
            flash_thread = threading.Thread(target=mainThread, args=(current_led,))
            flash_thread.start()
        elif action == "brightness":
            current_led.setBrightness(brightness)
            saveSettings()
        else:
            pass # unknown
    elif request.method == 'GET':
        return render_template('index.html', leds=leds)

    return render_template("index.html", leds=leds)
