import psutil
import os
import sys
import json
import winreg
from time import sleep
from playsound import playsound, PlaysoundException
import threading
from pystray import Icon, MenuItem, Menu
from PIL import Image
from plyer import notification
import tkinter as tk
import customtkinter as ctk


class BatteryNotifier:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.settings_file = os.path.join(self.current_dir, "settings.json")
        self.history_file  = os.path.join(self.current_dir, "history.json")
        self.load_settings()
        self.sound_file = os.path.join(self.current_dir, "short_bell.mp3")
        self.running = True
        self.low_alert_triggered  = False
        self.full_alert_triggered = False

        # Hidden main root — mainloop() runs on main thread
        self.root = tk.Tk()
        self.root.withdraw()

    # ---------------- Settings ----------------
    def load_settings(self):
        try:
            with open(self.settings_file, "r") as f:
                data = json.load(f)
                self.low_value  = data.get("low_value",  15)
                self.full_value = data.get("full_value", 100)
        except Exception:
            self.low_value  = 15
            self.full_value = 100

    def save_settings(self):
        with open(self.settings_file, "w") as f:
            json.dump({"low_value": self.low_value, "full_value": self.full_value}, f)

    def open_settings(self, icon=None, item=None):
        self.root.after(0, self._open_settings_ui)

    def _open_settings_ui(self):
        def save():
            try:
                low  = int(low_entry.get())
                full = int(full_entry.get())
                if not (0 < low < full <= 100):
                    raise ValueError
                self.low_value  = low
                self.full_value = full
                self.save_settings()
                # Reset triggers so new thresholds fire immediately if already met
                self.low_alert_triggered  = False
                self.full_alert_triggered = False
                win.destroy()
            except Exception:
                pass  # keep window open on bad input

        ctk.set_appearance_mode("dark")
        win = ctk.CTkToplevel(self.root)
        win.title("Settings")
        win.geometry("300x200")
        win.lift()
        win.attributes("-topmost", True)
        win.after(100, lambda: win.attributes("-topmost", False))

        ctk.CTkLabel(win, text="Low Battery %").pack(pady=5)
        low_entry = ctk.CTkEntry(win)
        low_entry.insert(0, str(self.low_value))
        low_entry.pack()

        ctk.CTkLabel(win, text="Full Battery %").pack(pady=5)
        full_entry = ctk.CTkEntry(win)
        full_entry.insert(0, str(self.full_value))
        full_entry.pack()

        ctk.CTkButton(win, text="Save", command=save).pack(pady=10)

        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.focus_force()

    # ---------------- History ----------------
    def log_history(self, message):
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
        except Exception:
            data = []

        data.append(message)
        with open(self.history_file, "w") as f:
            json.dump(data, f, indent=2)

    def show_history(self, icon=None, item=None):
        self.root.after(0, self._show_history_ui)

    def _show_history_ui(self):
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
        except Exception:
            data = []

        window = tk.Toplevel(self.root)
        window.title("Notification History")
        window.geometry("400x300")
        window.lift()
        window.attributes("-topmost", True)
        window.after(100, lambda: window.attributes("-topmost", False))

        text = tk.Text(window)
        text.pack(expand=True, fill="both")

        for entry in data:
            text.insert("end", entry + "\n")

        window.protocol("WM_DELETE_WINDOW", window.destroy)
        window.focus_force()

    # ---------------- Auto-Start ----------------
    def enable_startup(self, icon=None, item=None):
        if not self.is_startup_enabled():
            path = os.path.abspath(sys.argv[0])
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "BatteryNotifier", 0, winreg.REG_SZ, path)
            winreg.CloseKey(key)
            notification.notify(title="Startup Enabled",
                                message="App will start on boot", timeout=3)

    def disable_startup(self, icon=None, item=None):
        if self.is_startup_enabled():
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_SET_VALUE
                )
                winreg.DeleteValue(key, "BatteryNotifier")
                winreg.CloseKey(key)
                notification.notify(title="Startup Disabled",
                                    message="App won't start on boot", timeout=3)
            except Exception:
                pass

    def is_startup_enabled(self):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run"
            )
            winreg.QueryValueEx(key, "BatteryNotifier")
            return True
        except Exception:
            return False

    def startup_on_checked(self):
        return self.is_startup_enabled()

    def startup_off_checked(self):
        return not self.is_startup_enabled()

    # ---------------- Battery Checker ----------------
    def _play_alarm(self):
        """Fire alarm in its own daemon thread so nothing can block it."""
        threading.Thread(
            target=playsound,
            args=(self.sound_file,),
            daemon=True
        ).start()

    def check_battery(self):
        """
        Runs every 10 seconds.
        Alarm fires based purely on percentage — plug state is irrelevant.
        Each alert fires once and won't repeat until the battery level
        leaves the threshold zone and returns.
        """
        while self.running:
            try:
                battery = psutil.sensors_battery()
                if battery is None:
                    sleep(10)
                    continue

                percent = battery.percent

                if percent <= self.low_value:
                    if not self.low_alert_triggered:
                        self._play_alarm()
                        msg = f"Battery Low: {percent}%"
                        self.log_history(msg)
                        notification.notify(title="Battery Low!", message=msg, timeout=5)
                        self.low_alert_triggered  = True
                        self.full_alert_triggered = False

                elif percent >= self.full_value:
                    if not self.full_alert_triggered:
                        self._play_alarm()
                        msg = f"Battery Full: {percent}%"
                        self.log_history(msg)
                        notification.notify(title="Battery Full", message=msg, timeout=5)
                        self.full_alert_triggered = True
                        self.low_alert_triggered  = False

                else:
                    # Battery is between thresholds — reset both flags
                    self.low_alert_triggered  = False
                    self.full_alert_triggered = False

            except PlaysoundException:
                print("Sound error — check short_bell.mp3 exists")
            except Exception as e:
                print(f"Battery check error: {e}")

            sleep(10)

    def stop(self, icon=None, item=None):
        self.running = False
        icon.stop()
        self.root.after(0, self.root.quit)


# ---------------- Helpers ----------------
def resource_path(filename):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, filename)


def create_tray_icon(notifier):
    # Single static icon — no color changes
    image = Image.open(resource_path("battery_icon.ico"))

    startup_submenu = Menu(
        MenuItem(
            "On",
            notifier.enable_startup,
            checked=lambda item: notifier.startup_on_checked(),
            radio=True
        ),
        MenuItem(
            "Off",
            notifier.disable_startup,
            checked=lambda item: notifier.startup_off_checked(),
            radio=True
        ),
    )

    menu = Menu(
        MenuItem("Settings",     notifier.open_settings),
        MenuItem("Auto Start",   startup_submenu),
        MenuItem("View History", notifier.show_history),
        MenuItem("Exit",         notifier.stop),
    )

    return Icon("BatteryNotifier", image, "Battery Notifier", menu)


# ---------------- MAIN ----------------
if __name__ == "__main__":
    notifier   = BatteryNotifier()
    tray_icon  = create_tray_icon(notifier)

    # Battery checker in its own background thread
    battery_thread = threading.Thread(
        target=notifier.check_battery,
        daemon=True
    )
    battery_thread.start()

    # Tray icon in background thread
    tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
    tray_thread.start()

    # Tkinter mainloop on the MAIN thread (required by Windows)
    notifier.root.mainloop()
