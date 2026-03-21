import psutil
import os
import sys
from time import sleep
from playsound import playsound, PlaysoundException
import threading
from pystray import Icon, MenuItem, Menu
from PIL import Image
from plyer import notification

class BatteryNotifier:
    current_dir = os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        self.low_value = 15
        self.full_value = 100
        self.sound_file = os.path.join(self.current_dir, "short_bell.mp3")
        self.running = True

    def check_battery(self, icon):
        while self.running:
            battery = psutil.sensors_battery()
            percent = battery.percent
            plugged = battery.power_plugged

            # 🔹 Update tray tooltip with current battery %
            icon.title = f"Battery Notifier - {percent}%"

            try:
                # 🔴 LOW BATTERY
                if not plugged and percent <= self.low_value:
                    icon.icon = Image.open(resource_path("icon_red.png"))
                    playsound(self.sound_file)
                    notification.notify(
                        title="Battery Low!",
                        message=f"Battery is at {percent}%",
                        timeout=5
                    )

                # 🟢 FULL / CHARGING
                elif plugged:
                    icon.icon = Image.open(resource_path("icon_green.png"))
                    if percent >= self.full_value:
                        playsound(self.sound_file)
                        notification.notify(
                            title="Battery Full",
                            message=f"Battery is at {percent}%",
                            timeout=5
                        )

                # ⚪ NORMAL (unplugged & above low threshold)
                else:
                    icon.icon = Image.open(resource_path("icon_white.png"))

            except PlaysoundException:
                print("Sound error")

            sleep(60)

    def stop(self, icon, item):
        self.running = False
        icon.stop()


def resource_path(filename):
    try:
        base_path = sys._MEIPASS  # PyInstaller temp folder
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, filename)


def create_tray_icon(notifier):
    image = Image.open(resource_path("icon_white.png"))

    menu = Menu(
        MenuItem("Exit", notifier.stop)
    )

    icon = Icon("BatteryNotifier", image, "Battery Notifier", menu)
    return icon


if __name__ == "__main__":
    notifier = BatteryNotifier()

    tray_icon = create_tray_icon(notifier)

    thread = threading.Thread(target=notifier.check_battery, args=(tray_icon,))
    thread.daemon = True
    thread.start()

    tray_icon.run()