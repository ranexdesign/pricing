"""
JARVIS v0.1 - Windows voice assistant (free stack)
  Ears  : SpeechRecognition (free Google web API)
  Voice : pyttsx3 (offline Windows SAPI5)
  Brain : Ollama local LLM (free, offline) for anything the skills don't cover
  Hands : subprocess / webbrowser / pyautogui / psutil

Run:  python jarvis.py          (voice mode, say "Jarvis ...")
      python jarvis.py --text   (keyboard mode, for testing without a mic)
"""
import ctypes
import datetime
import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import psutil
import pyautogui
import pyttsx3
import requests

try:
    import speech_recognition as sr
except ImportError:
    sr = None

# ------------------------------ CONFIG ------------------------------
WAKE_WORD = "jarvis"
LANGUAGE = os.getenv("JARVIS_LANG", "en-IN")          # speech recognition language
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.getenv("JARVIS_MODEL", "llama3.2:3b")
USER_TITLE = os.getenv("JARVIS_TITLE", "sir")
HOME = Path.home()
NOTES_FILE = HOME / "Documents" / "jarvis_notes.txt"

SYSTEM_PROMPT = (
    f"You are JARVIS, a witty, calm, highly capable personal AI assistant running on the "
    f"user's Windows PC. Address the user as '{USER_TITLE}'. Replies are spoken aloud, so keep "
    f"them to 1-3 short sentences, no markdown, no lists."
)

APPS = {  # spoken name -> command
    "notepad": "notepad", "calculator": "calc", "paint": "mspaint",
    "command prompt": "cmd", "terminal": "wt", "task manager": "taskmgr",
    "file explorer": "explorer", "explorer": "explorer", "settings": "ms-settings:",
    "chrome": "chrome", "edge": "msedge", "firefox": "firefox",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "vs code": "code", "vscode": "code", "visual studio code": "code",
    "spotify": "spotify", "snipping tool": "snippingtool", "camera": "microsoft.windows.camera:",
}
PROCESS_NAMES = {  # for "close X"
    "notepad": "notepad.exe", "calculator": "CalculatorApp.exe", "paint": "mspaint.exe",
    "chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe",
    "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe",
    "vs code": "Code.exe", "vscode": "Code.exe", "spotify": "Spotify.exe",
    "task manager": "Taskmgr.exe",
}
SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "gmail": "https://mail.google.com", "github": "https://github.com",
    "chatgpt": "https://chat.openai.com", "whatsapp": "https://web.whatsapp.com",
    "maps": "https://maps.google.com", "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com", "twitter": "https://x.com",
}
FOLDERS = {
    "downloads": HOME / "Downloads", "documents": HOME / "Documents",
    "desktop": HOME / "Desktop", "pictures": HOME / "Pictures", "music": HOME / "Music",
    "videos": HOME / "Videos",
}

# ------------------------------ VOICE OUT ------------------------------
_engine = pyttsx3.init()
_engine.setProperty("rate", 175)
for v in _engine.getProperty("voices"):          # prefer a male voice if installed
    if any(k in v.name.lower() for k in ("david", "mark", "george", "ravi")):
        _engine.setProperty("voice", v.id)
        break

def speak(text: str):
    print(f"JARVIS: {text}")
    _engine.say(text)
    _engine.runAndWait()

# ------------------------------ VOICE IN ------------------------------
TEXT_MODE = "--text" in sys.argv or sr is None
_rec = sr.Recognizer() if sr else None
if _rec:
    _rec.pause_threshold = 0.8
    _rec.dynamic_energy_threshold = True

def listen(timeout=6, phrase_limit=10) -> str:
    """Return lowercase transcript, or '' if nothing understood."""
    if TEXT_MODE:
        return input("You: ").strip().lower()
    try:
        with sr.Microphone() as mic:
            _rec.adjust_for_ambient_noise(mic, duration=0.3)
            audio = _rec.listen(mic, timeout=timeout, phrase_time_limit=phrase_limit)
        text = _rec.recognize_google(audio, language=LANGUAGE).lower()
        print(f"You: {text}")
        return text
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except sr.RequestError:
        print("[speech service unreachable - check internet]")
        return ""

def confirm(question: str) -> bool:
    speak(question)
    return any(w in listen() for w in ("yes", "yeah", "confirm", "do it", "sure", "proceed", "y"))

# ------------------------------ BRAIN (LLM) ------------------------------
_history = []

def ask_llm(prompt: str) -> str:
    global _history
    _history.append({"role": "user", "content": prompt})
    _history = _history[-12:]
    try:
        r = requests.post(OLLAMA_URL, timeout=120, json={
            "model": MODEL, "stream": False,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + _history,
        })
        r.raise_for_status()
        reply = r.json()["message"]["content"].strip()
        _history.append({"role": "assistant", "content": reply})
        return reply
    except requests.ConnectionError:
        return (f"My brain isn't online, {USER_TITLE}. Install Ollama from ollama dot com, "
                f"then run: ollama pull {MODEL}")
    except Exception as e:
        return f"I hit a problem thinking about that: {e}"

# ------------------------------ SKILLS (PC AUTOMATION) ------------------------------
def launch(cmd: str):
    if cmd.endswith(":"):
        os.startfile(cmd)
    else:
        subprocess.Popen(f'start "" "{cmd}"', shell=True)

def sk_time(t):
    now = datetime.datetime.now()
    if "date" in t or "day" in t:
        return now.strftime("Today is %A, %d %B %Y.")
    return now.strftime("It's %I:%M %p.")

def sk_open(t):
    name = re.sub(r"^(please )?(open|launch|start|run)\s+", "", t).replace("the ", "").strip()
    if name in FOLDERS:
        os.startfile(str(FOLDERS[name])); return f"Opening {name}."
    if name in SITES:
        webbrowser.open(SITES[name]); return f"Opening {name}."
    if name in APPS:
        launch(APPS[name]); return f"Opening {name}."
    if "." in name and " " not in name:
        webbrowser.open(name if name.startswith("http") else f"https://{name}")
        return f"Opening {name}."
    launch(name); return f"Trying to open {name}."

def sk_close(t):
    name = re.sub(r"^(close|quit|kill|exit)\s+", "", t).replace("the ", "").strip()
    proc = PROCESS_NAMES.get(name)
    if not proc:
        return f"I don't know how to close {name} yet."
    subprocess.run(["taskkill", "/IM", proc, "/F"], capture_output=True)
    return f"Closed {name}."

def sk_search(t):
    q = re.sub(r"^(search|google|look up)( for)?( on google)?\s*", "", t).strip()
    webbrowser.open("https://www.google.com/search?q=" + requests.utils.quote(q))
    return f"Searching for {q}."

def sk_youtube(t):
    q = re.sub(r"^play\s+", "", t)
    q = re.sub(r"\s+on youtube$", "", q).strip()
    webbrowser.open("https://www.youtube.com/results?search_query=" + requests.utils.quote(q))
    return f"Playing {q} on YouTube."

def sk_volume(t):
    if "mute" in t:
        pyautogui.press("volumemute"); return "Toggled mute."
    key = "volumeup" if ("up" in t or "increase" in t or "raise" in t) else "volumedown"
    pyautogui.press(key, presses=6)
    return "Volume adjusted."

def sk_screenshot(t):
    folder = HOME / "Pictures"; folder.mkdir(exist_ok=True)
    path = folder / f"jarvis_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
    pyautogui.screenshot(str(path))
    return "Screenshot saved to your Pictures folder."

def sk_status(t):
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent
    msg = f"CPU is at {cpu:.0f} percent and memory at {ram:.0f} percent."
    b = psutil.sensors_battery()
    if b:
        msg += f" Battery is {b.percent:.0f} percent{', charging' if b.power_plugged else ''}."
    return msg

def sk_weather(t):
    m = re.search(r"weather (?:in|at|for) (.+)", t)
    city = m.group(1).strip() if m else ""
    try:
        r = requests.get(f"https://wttr.in/{requests.utils.quote(city)}?format=%l:+%C,+%t,+wind+%w", timeout=8)
        return r.text.strip()
    except Exception:
        return "I couldn't reach the weather service."

def sk_note(t):
    note = re.sub(r"^(take a note|note down|note|remember)( that)?\s*", "", t).strip()
    if not note:
        speak("What should I note?"); note = listen()
    if not note:
        return "I didn't catch that."
    NOTES_FILE.parent.mkdir(exist_ok=True)
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M}] {note}\n")
    return "Noted."

def sk_type(t):
    text = re.sub(r"^type\s+", "", t)
    time.sleep(1.5)
    pyautogui.write(text, interval=0.03)
    return "Done."

def sk_lock(t):
    ctypes.windll.user32.LockWorkStation(); return "Locking the workstation."

def sk_shutdown(t):
    restart = "restart" in t or "reboot" in t
    if confirm(f"Are you sure you want to {'restart' if restart else 'shut down'}?"):
        subprocess.run(["shutdown", "/r" if restart else "/s", "/t", "30"])
        return "Okay. Say 'cancel shutdown' within 30 seconds to abort."
    return "Cancelled."

def sk_cancel_shutdown(t):
    subprocess.run(["shutdown", "/a"]); return "Shutdown aborted."

def sk_minimize(t):
    pyautogui.hotkey("win", "d"); return "Showing desktop."

# (regex, handler) - first match wins. Anything unmatched goes to the LLM brain.
SKILLS = [
    (r"cancel (the )?(shutdown|restart)",                 sk_cancel_shutdown),
    (r"\b(shut ?down|restart|reboot) (the |my )?(pc|computer|laptop|system)", sk_shutdown),
    (r"\block (the |my )?(pc|computer|screen|laptop)",    sk_lock),
    (r"\b(what('s| is) the )?(time|date)\b|what day",     sk_time),
    (r"^(please )?(open|launch|start|run) ",              sk_open),
    (r"^(close|quit|kill|exit) ",                         sk_close),
    (r"^(search|google|look up)",                         sk_search),
    (r"^play .+",                                         sk_youtube),
    (r"\b(volume|mute|louder|quieter)\b",                 sk_volume),
    (r"screenshot|screen shot|capture (the )?screen",     sk_screenshot),
    (r"(system|pc|computer) (status|health|performance)|battery|cpu|ram usage", sk_status),
    (r"\bweather\b",                                      sk_weather),
    (r"^(take a note|note down|note|remember)",           sk_note),
    (r"^type ",                                           sk_type),
    (r"(minimi[sz]e all|show (the )?desktop)",            sk_minimize),
]

def handle(cmd: str) -> bool:
    """Returns False if JARVIS should quit."""
    if re.search(r"\b(goodbye|go to sleep|shut yourself down|exit jarvis|quit jarvis)\b", cmd):
        speak(f"Goodbye, {USER_TITLE}."); return False
    if re.search(r"(reset|forget) (our )?(chat|conversation|memory)", cmd):
        _history.clear(); speak("Memory cleared."); return True
    for pattern, fn in SKILLS:
        if re.search(pattern, cmd):
            try:
                speak(fn(cmd))
            except Exception as e:
                speak(f"That didn't work: {e}")
            return True
    speak(ask_llm(cmd))
    return True

# ------------------------------ MAIN LOOP ------------------------------
def greet():
    h = datetime.datetime.now().hour
    part = "morning" if h < 12 else "afternoon" if h < 18 else "evening"
    speak(f"Good {part}, {USER_TITLE}. JARVIS online and at your service.")

def main():
    greet()
    if TEXT_MODE:
        print("(text mode - type commands, no wake word needed)")
    running = True
    while running:
        heard = listen()
        if not heard:
            continue
        if not TEXT_MODE:
            if WAKE_WORD not in heard:
                continue
            cmd = heard.split(WAKE_WORD, 1)[1].strip(" ,.")
            if not cmd:
                speak("Yes?"); cmd = listen(timeout=7)
                if not cmd:
                    continue
        else:
            cmd = heard
        running = handle(cmd)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJARVIS offline.")
