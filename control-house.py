from flask import Flask, render_template, request
import Adafruit_BBIO.GPIO as GPIO
import Adafruit_BBIO.PWM as PWM
import time
import threading
import json
from pathlib import Path



LED_PIN = "P9_14"
LEDPATH='/sys/class/leds/beaglebone:green:usr3/brightness'
TRIGGERPATH = '/sys/class/leds/beaglebone:green:usr3/trigger'
DELAY_ON = '/sys/class/leds/beaglebone:green:usr3/delay_on'
DELAY_OFF = '/sys/class/leds/beaglebone:green:usr3/delay_off'
PWM_PATH = Path("/sys/class/pwm/pwmchip5/pwm0")
PERIOD = 1000000  # 1 kHz

app = Flask(__name__)
threadRunning = False
brightness = 50.0

SETTINGS_FILE = Path(__file__).with_name("settings.json")

def loadSettings():
    try:
        with open(SETTINGS_FILE, "r") as file:
            settings = json.load(file)

        return float(settings.get("brightness", 50.0))

    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return 50.0

def saveSettings(brightness):
    settings = {
        "brightness": brightness
    }

    with open(SETTINGS_FILE, "w") as file:
        json.dump(settings, file, indent=4)

brightness = loadSettings()
print(f"Loaded brightness setting: {brightness}")

def turnOnLED(brightness=50.0):
    duty = int(PERIOD * brightness / 100)
    (PWM_PATH / "enable").write_text("0")
    (PWM_PATH / "period").write_text(str(PERIOD))
    (PWM_PATH / "duty_cycle").write_text(str(duty))
    (PWM_PATH / "enable").write_text("1")

def turnOffLED():
    (PWM_PATH / "enable").write_text("0")

def setBrightness(percent):
    duty = int(PERIOD * percent / 100)
    (PWM_PATH / "duty_cycle").write_text(str(duty))

def mainThread():
    global threadRunning,brightness
    while threadRunning:
        turnOnLED(brightness)
        time.sleep(0.5)
        turnOffLED()
        time.sleep(0.5)

@app.route("/",methods=['GET','POST'])
def handleRoute():
    global threadRunning, brightness
    if request.method == 'POST':
        if "putON" in request.form:
            threadRunning = False
            turnOnLED(brightness)
        elif  "putOFF" in request.form:
            threadRunning = False
            turnOffLED()

        elif "flash" in request.form:
            threadRunning = True
            flash_thread = threading.Thread(target=mainThread)
            flash_thread.start()
        elif "brightness" in request.form:
            brightness = float(request.form["brightness"])
            setBrightness(brightness)
            saveSettings(brightness)
        else:
            pass # unknown
    elif request.method == 'GET':
        return render_template('index.html', brightness=brightness)

    return render_template("index.html", brightness=brightness)
