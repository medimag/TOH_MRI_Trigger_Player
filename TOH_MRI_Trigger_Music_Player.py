#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import random
import threading
import queue
import tkinter as tk
from tkinter import filedialog, scrolledtext

from PIL import Image, ImageTk

try:
    import serial
except ImportError:
    serial = None

try:
    import pygame
except ImportError:
    pygame = None


APP_TITLE = "TOH MRI Music Synchronization System"
DEFAULT_AUDIO_FILE = ""
DEFAULT_PORT = "COM3"
LOGO_FILE = "The_Ottawa_Hospital_Logo.jpg"


def resource_path(relative_path):
    """Find bundled resources when running as a PyInstaller .exe."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


class TriggerMusicGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)

        self.monitoring = False
        self.monitor_thread = None
        self.stop_event = threading.Event()
        self.gui_queue = queue.Queue()

        self.trigger_count = 0
        self.music_started = False
        self.last_trigger_time = None
        self.trigger_intervals = []
        self.trigger_times = []
        self.logo_photo = None

        self.audio_file = tk.StringVar(value=DEFAULT_AUDIO_FILE)
        self.serial_port = tk.StringVar(value=DEFAULT_PORT)
        self.simulate_mode = tk.BooleanVar(value=False)
        self.tr_seconds = tk.DoubleVar(value=2.0)
        self.jitter = tk.DoubleVar(value=0.0)
        self.play_only_first_trigger = tk.BooleanVar(value=True)
        self.volume = tk.DoubleVar(value=70)

        if pygame is not None:
            try:
                pygame.mixer.init()
            except Exception as e:
                pygame_error = str(e)
                pygame.mixer = None
            else:
                pygame_error = None
        else:
            pygame_error = "pygame is not installed."

        self.build_gui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.process_gui_queue)

        self.log("Ready.")
        self.log("Select an audio file and press Start Listening.")
        if pygame_error:
            self.log(f"Audio warning: {pygame_error}")

    def build_gui(self):
        main_frame = tk.Frame(self.root, padx=15, pady=15)
        main_frame.pack(fill="both", expand=True)

        left_frame = tk.Frame(main_frame)
        left_frame.grid(row=0, column=0, sticky="nw")

        right_frame = tk.Frame(main_frame, width=220)
        right_frame.grid(row=0, column=1, sticky="n", padx=25)
        right_frame.grid_propagate(False)

        self.add_logo(right_frame)

        tk.Label(left_frame, text="Audio file:").grid(row=0, column=0, sticky="w", pady=5)
        tk.Entry(left_frame, textvariable=self.audio_file, width=65).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(left_frame, text="Choose file", command=self.choose_file).grid(row=0, column=2, padx=5, pady=5)

        tk.Label(left_frame, text="Serial port:").grid(row=1, column=0, sticky="w", pady=5)
        tk.Entry(left_frame, textvariable=self.serial_port, width=45).grid(row=1, column=1, sticky="w", padx=5, pady=5)

        self.port_status_label = tk.Label(left_frame, text="Port Status: Not connected", font=("Arial", 11, "bold"))
        self.port_status_label.grid(row=1, column=2, sticky="w", padx=5)

        tk.Checkbutton(
            left_frame,
            text="Simulate triggers instead of USB trigger box",
            variable=self.simulate_mode
        ).grid(row=2, column=1, sticky="w", padx=5, pady=5)

        tk.Label(left_frame, text="Simulated TR [s]:").grid(row=3, column=0, sticky="w", pady=5)
        tk.Entry(left_frame, textvariable=self.tr_seconds, width=10).grid(row=3, column=1, sticky="w", padx=5)

        tk.Label(left_frame, text="Jitter [s]:").grid(row=4, column=0, sticky="w", pady=5)
        tk.Entry(left_frame, textvariable=self.jitter, width=10).grid(row=4, column=1, sticky="w", padx=5)

        tk.Checkbutton(
            left_frame,
            text="Start music only on Trigger #1",
            variable=self.play_only_first_trigger
        ).grid(row=5, column=1, sticky="w", padx=5, pady=5)

        tk.Label(left_frame, text="Volume:").grid(row=6, column=0, sticky="w", pady=5)
        self.volume_slider = tk.Scale(
            left_frame,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.volume,
            command=self.update_volume,
            length=250
        )
        self.volume_slider.grid(row=6, column=1, sticky="w", padx=5)

        self.start_button = tk.Button(left_frame, text="▶  Start Listening", command=self.start_monitoring, width=20)
        self.start_button.grid(row=7, column=0, padx=5, pady=15)

        self.stop_button = tk.Button(left_frame, text="■  Stop Listening", command=self.stop_monitoring, width=20, state="disabled")
        self.stop_button.grid(row=7, column=1, sticky="w", padx=5, pady=15)

        self.stop_audio_button = tk.Button(left_frame, text="♫  Stop Music", command=self.stop_music, width=20)
        self.stop_audio_button.grid(row=7, column=2, padx=5, pady=15)

        tk.Frame(left_frame, height=2, bd=1, relief="sunken").grid(row=8, column=0, columnspan=3, sticky="we", pady=10)

        tk.Label(left_frame, text="Trigger status:").grid(row=9, column=0, sticky="w", pady=5)

        self.trigger_canvas = tk.Canvas(left_frame, width=90, height=90)
        self.trigger_canvas.grid(row=9, column=1, sticky="w", padx=5)
        self.trigger_light = self.trigger_canvas.create_oval(10, 10, 80, 80, fill="gray")

        info_frame = tk.Frame(left_frame)
        info_frame.grid(row=9, column=1, sticky="w", padx=110)

        self.status_label = tk.Label(info_frame, text="Stopped", font=("Arial", 16, "bold"))
        self.status_label.grid(row=0, column=0, sticky="w", padx=(0, 25))

        self.count_label = tk.Label(info_frame, text="Triggers: 0", font=("Arial", 12, "bold"))
        self.count_label.grid(row=0, column=1, sticky="w", padx=(0, 20))

        self.last_trigger_label = tk.Label(info_frame, text="Last trigger: --", font=("Arial", 12))
        self.last_trigger_label.grid(row=0, column=2, sticky="w", padx=(0, 20))

        self.delta_label = tk.Label(info_frame, text="Δt: --", font=("Arial", 12))
        self.delta_label.grid(row=1, column=1, sticky="w", padx=(0, 20))

        self.measured_tr_label = tk.Label(info_frame, text="Measured TR: --", font=("Arial", 12))
        self.measured_tr_label.grid(row=1, column=2, sticky="w", padx=(0, 20))

        tk.Label(left_frame, text="Trigger timeline:").grid(row=10, column=0, sticky="w", pady=5)

        self.timeline_canvas = tk.Canvas(left_frame, width=720, height=70, bg="white")
        self.timeline_canvas.grid(row=10, column=1, columnspan=2, sticky="w", padx=5, pady=5)

        self.log_box = scrolledtext.ScrolledText(left_frame, width=95, height=10)
        self.log_box.grid(row=11, column=0, columnspan=3, padx=5, pady=10)

    def add_logo(self, parent):
        try:
            logo_path = resource_path(LOGO_FILE)
            if not os.path.exists(logo_path):
                raise FileNotFoundError(logo_path)

            img = Image.open(logo_path).convert("RGB")
            img.thumbnail((140, 140), Image.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(img)
            tk.Label(parent, image=self.logo_photo).pack(pady=(5, 5))
        except Exception as e:
            tk.Label(parent, text=f"Logo not loaded:\n{e}", fg="red", justify="left").pack()

        tk.Label(
            parent,
            text="Department of Medical Imaging\nThe Ottawa Hospital\nMRI Music Project",
            font=("Arial", 11, "bold"),
            justify="center"
        ).pack(pady=(5, 0))

    def choose_file(self):
        file_path = filedialog.askopenfilename(
            title="Choose audio file",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.m4a *.aiff *.aac *.ogg"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.audio_file.set(file_path)
            self.log(f"Selected audio file: {file_path}")

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_box.see(tk.END)

    def queue_log(self, message):
        self.gui_queue.put(("log", message))

    def queue_trigger(self, count, pin_state, trigger_time):
        self.gui_queue.put(("trigger", count, pin_state, trigger_time))

    def queue_port_status(self, message):
        self.gui_queue.put(("port", message))

    def update_volume(self, value=None):
        if pygame is not None and getattr(pygame, "mixer", None) is not None:
            try:
                pygame.mixer.music.set_volume(float(self.volume.get()) / 100.0)
            except Exception:
                pass

    def play_audio(self):
        if pygame is None or getattr(pygame, "mixer", None) is None:
            self.queue_log("ERROR: pygame audio is not available.")
            return

        audio_path = self.audio_file.get()
        if not audio_path:
            self.queue_log("ERROR: No audio file selected.")
            return

        if not os.path.exists(audio_path):
            self.queue_log(f"ERROR: Audio file not found: {audio_path}")
            return

        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.set_volume(float(self.volume.get()) / 100.0)
            pygame.mixer.music.play()
            self.queue_log("Music started.")
        except Exception as e:
            self.queue_log(f"ERROR playing audio: {e}")

    def stop_music(self):
        if pygame is not None and getattr(pygame, "mixer", None) is not None:
            pygame.mixer.music.stop()
            self.log("Music stopped.")

    def draw_timeline(self):
        self.timeline_canvas.delete("all")

        width = 720
        height = 70
        margin = 25
        self.timeline_canvas.create_line(margin, height // 2, width - margin, height // 2)

        recent_times = self.trigger_times[-20:]
        if not recent_times:
            return

        n = len(recent_times)
        spacing = (width - 2 * margin) / max(n - 1, 1)

        for i, trigger_time in enumerate(recent_times):
            x = margin + i * spacing
            self.timeline_canvas.create_line(x, 15, x, 50, width=2)

            original_index = len(self.trigger_times) - len(recent_times) + i + 1
            self.timeline_canvas.create_text(x, 10, text=f"T{original_index}", font=("Arial", 8))

            if original_index == 1:
                label = "0.000s"
            else:
                dt = trigger_time - recent_times[i - 1]
                label = f"{dt:.3f}s"

            self.timeline_canvas.create_text(x, 60, text=label, font=("Arial", 8))

    def process_gui_queue(self):
        while not self.gui_queue.empty():
            item = self.gui_queue.get()

            if item[0] == "log":
                self.log(item[1])

            elif item[0] == "port":
                self.port_status_label.config(text=item[1])

            elif item[0] == "trigger":
                count, pin_state, trigger_time = item[1], item[2], item[3]

                self.trigger_times.append(trigger_time)
                if len(self.trigger_times) > 50:
                    self.trigger_times = self.trigger_times[-50:]

                self.count_label.config(text=f"Triggers: {count}")
                self.last_trigger_label.config(
                    text=f"Last trigger: {time.strftime('%H:%M:%S', time.localtime(trigger_time))}"
                )

                if self.last_trigger_time is not None:
                    dt = trigger_time - self.last_trigger_time
                    self.trigger_intervals.append(dt)
                    if len(self.trigger_intervals) > 50:
                        self.trigger_intervals = self.trigger_intervals[-50:]

                    measured_tr = sum(self.trigger_intervals[-10:]) / min(len(self.trigger_intervals), 10)
                    self.delta_label.config(text=f"Δt: {dt:.3f} s")
                    self.measured_tr_label.config(text=f"Measured TR: {measured_tr:.3f} s")
                else:
                    self.delta_label.config(text="Δt: first pulse")
                    self.measured_tr_label.config(text="Measured TR: waiting")

                self.last_trigger_time = trigger_time
                self.trigger_canvas.itemconfig(self.trigger_light, fill="green")
                self.status_label.config(text="TRIGGER")

                self.root.after(350, lambda: self.trigger_canvas.itemconfig(self.trigger_light, fill="gray"))
                self.root.after(350, lambda: self.status_label.config(text="Listening..."))
                self.draw_timeline()

        self.root.after(100, self.process_gui_queue)

    def start_monitoring(self):
        if self.monitoring:
            return

        self.monitoring = True
        self.stop_event.clear()
        self.trigger_count = 0
        self.music_started = False
        self.last_trigger_time = None
        self.trigger_intervals = []
        self.trigger_times = []

        self.count_label.config(text="Triggers: 0")
        self.last_trigger_label.config(text="Last trigger: --")
        self.delta_label.config(text="Δt: --")
        self.measured_tr_label.config(text="Measured TR: --")
        self.status_label.config(text="Listening...")
        self.trigger_canvas.itemconfig(self.trigger_light, fill="gray")
        self.timeline_canvas.delete("all")

        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")

        if self.simulate_mode.get():
            self.queue_port_status("Port Status: Simulated mode")
            self.monitor_thread = threading.Thread(target=self.simulated_trigger_monitor, daemon=True)
        else:
            self.queue_port_status("Port Status: Connecting...")
            self.monitor_thread = threading.Thread(target=self.real_trigger_monitor, daemon=True)

        self.monitor_thread.start()
        self.log("Started listening.")

    def stop_monitoring(self):
        self.stop_event.set()
        self.monitoring = False
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.status_label.config(text="Stopped")
        self.trigger_canvas.itemconfig(self.trigger_light, fill="gray")
        if not self.simulate_mode.get():
            self.queue_port_status("Port Status: Not connected")
        self.log("Stopped listening.")

    def handle_trigger(self, pin_state):
        self.trigger_count += 1
        trigger_time = time.time()

        self.queue_log(f"Trigger #{self.trigger_count} detected (Pin state: {pin_state})")
        self.queue_trigger(self.trigger_count, pin_state, trigger_time)

        should_play = False
        if self.play_only_first_trigger.get():
            if self.trigger_count == 1 and not self.music_started:
                should_play = True
        else:
            should_play = True

        if should_play:
            self.queue_log("Starting music from trigger.")
            self.play_audio()
            self.music_started = True

    def real_trigger_monitor(self):
        if serial is None:
            self.queue_log("ERROR: pyserial is not installed.")
            self.queue_port_status("Port Status: pyserial missing")
            return

        port = self.serial_port.get().strip()

        try:
            ser = serial.Serial(port, baudrate=9600, timeout=1)
        except Exception as e:
            self.queue_log(f"ERROR opening serial port: {e}")
            self.queue_port_status("Port Status: Connection failed")
            return

        self.queue_log(f"Connected to {port}")
        self.queue_port_status("Port Status: Connected")
        self.queue_log("Waiting for real fMRI triggers...")

        last_dsr_state = ser.dsr

        while not self.stop_event.is_set():
            current_dsr_state = ser.dsr
            if current_dsr_state != last_dsr_state:
                self.handle_trigger(current_dsr_state)
                last_dsr_state = current_dsr_state
            time.sleep(0.001)

        ser.close()
        self.queue_log("Serial port closed.")

    def simulated_trigger_monitor(self):
        pin_state = False
        tr = float(self.tr_seconds.get())
        jitter = float(self.jitter.get())

        self.queue_log("Running simulated fMRI trigger mode.")
        self.queue_log(f"Expected TR = {tr:.3f} s")

        while not self.stop_event.is_set():
            sleep_time = tr
            if jitter > 0:
                sleep_time += random.uniform(-jitter, jitter)
            time.sleep(max(0, sleep_time))

            if self.stop_event.is_set():
                break

            pin_state = not pin_state
            self.handle_trigger(pin_state)

    def on_close(self):
        self.stop_monitoring()
        self.stop_music()
        if pygame is not None and getattr(pygame, "mixer", None) is not None:
            pygame.mixer.quit()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = TriggerMusicGUI(root)
    root.mainloop()
