"""Full-screen terminal UI for yt2obsidian: paste links, watch each one get filed. The save pipeline stays in yt2obsidian.py."""
import queue
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import Button, Footer, Input, ListItem, ListView, Select, Static, Switch

import yt2obsidian as y

INK, PAPER, MARK = "#17141f", "#efe9dc", "#a78bfa"  # night desk, cream page, Obsidian purple
COLOR = {"saved": "#7bd88f", "stub": "#f2c14e", "duplicate": "#8ab4ff", "skipped": "#f2c14e", "stopped": "#f2c14e",
         "failed": "#ff7b7b", "invalid": "#ff7b7b", "queued": "#8c85a3", "undone": "#8c85a3", "fetching": MARK}
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
EYES = {"idle": "• •", "blink": "- -", "work": "o o", "work2": "O O", "happy": "^ ^", "meh": "• •", "oops": "x x", "sleep": "- -"}
MOUTH = {"idle": "‿", "blink": "‿", "work": "·", "work2": "o", "happy": "◡", "meh": "~", "oops": "n", "sleep": "z"}
LINES = {
    "idle": ["Paste a link. I'll do the typing.", "Got a link? Enter on its own pastes the clipboard.", "Feed me YouTube links."],
    "happy": ["Filed! Obsidian owes me a treat.", "Another one for the vault.", "Done. That was a good one.", "Tucked in, nice and tidy."],
    "meh": ["No captions, so I left a note saying so.", "Nothing to transcribe. Stub filed."],
    "oops": ["That one got away.", "Hm. That did not work."],
    "sleep": ["YouTube said slow down. Napping. Try ctrl+r later."],
}
THEME = Theme(name="folio", primary=MARK, secondary="#f2c14e", accent="#8ab4ff", success="#7bd88f", warning="#f2c14e",
              error="#ff7b7b", background=INK, surface="#1f1b2b", panel="#262134", foreground=PAPER, dark=True)


def mascot(mood):
    return f"╭─────╮\n│ {EYES[mood]} │\n│  {MOUTH[mood]}  │\n╰─┬─┬─╯"


def drop_retry(url):
    """Take url out of retry.txt once it has been tried and did not get throttled again."""
    try:
        y.RETRY.write_text("".join(u + "\n" for u in y.read_retry() if u != url), encoding="utf-8")
    except OSError:
        pass


class Row(ListItem):
    """One link: status word, title, and a dim detail line. Enter on a saved row opens its note."""

    def __init__(self, title):
        self.status, self.title, self.detail, self.path, self.frame, self.lines = "queued", title, "waiting its turn", None, 0, []
        self.badge, self.body = Static(classes="badge"), Static(classes="body")
        super().__init__(Horizontal(self.badge, self.body))
        self.show()

    def show(self):
        word = self.status if self.status != "fetching" else SPIN[self.frame % len(SPIN)]
        self.badge.update(f"[bold {COLOR.get(self.status, PAPER)}]{word}[/]")
        self.body.update(f"{escape(self.title)}\n[dim]{escape(self.detail)}[/]")

    def set(self, **kw):
        self.__dict__.update(kw)
        self.show()


class PasteInput(Input):
    def _on_paste(self, event):  # one line, however many links: newlines become spaces and Enter saves them all
        event.prevent_default()
        event.stop()
        self.insert_text_at_cursor(" ".join(event.text.split()))


class SettingsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self):
        try:
            cfg = y.load_config()
        except ValueError as e:
            yield Static(f"[b #ff7b7b]Config problem[/]\n{escape(y.cap(e))}", id="cfgerr")
            yield Footer()
            return
        yield Static(f"[b]Settings[/]  [dim]{escape(str(y.HERE / 'config.toml'))}\nvault {escape(str(cfg['vault']))}[/]", id="settings-head")
        with VerticalScroll(id="settings"):
            for key, (label, _, allowed) in y.SETTINGS.items():
                with Horizontal(classes="setting"):
                    yield Static(label, classes="label")
                    if allowed is bool:
                        yield Switch(cfg[key], id=key)
                    elif isinstance(allowed, dict):
                        yield Select([(f"{k}: {note}", k) for k, note in allowed.items()], value=cfg[key], allow_blank=False, id=key)
                    else:
                        yield Input(str(cfg[key]), id=key, select_on_focus=False)
            yield Static("", id="status")
            yield Button("Reset all but the inbox", id="reset")
        yield Footer()

    def apply(self, key, value):
        status = self.query_one("#status", Static)
        try:
            new = y.parse_setting(key, value) if isinstance(value, str) and key not in ("notify",) else value
            if y.load_config()[key] == new:
                return
            y.set_value(key, new)
            status.update(f"[#7bd88f]saved[/] {y.SETTINGS[key][0].lower()}; applies to the next paste")
        except (ValueError, OSError) as e:
            status.update(f"[#ff7b7b]{escape(y.SETTINGS[key][0])}[/] {escape(y.cap(e))}")

    def on_switch_changed(self, e):
        self.apply(e.switch.id, e.value)

    def on_select_changed(self, e):
        if e.value != Select.BLANK:
            self.apply(e.select.id, e.value)

    def on_input_submitted(self, e):
        self.apply(e.input.id, e.value)

    def on_input_blurred(self, e):
        self.apply(e.input.id, e.value)

    def on_button_pressed(self, e):
        y.reset_settings()
        self.app.pop_screen()
        self.app.notify_user("Settings back to defaults (inbox kept).")


class YtApp(App):
    TITLE = "yt2obsidian"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; }
    #top { height: 6; padding: 1 2 0 2; }
    #mascot { width: 11; color: $primary; text-style: bold; }
    #talk { width: 1fr; padding: 1 0 0 2; }
    #say { height: 2; color: $foreground; }
    #meta { color: $text-muted; }
    #paste { margin: 0 2; border: tall $primary 50%; background: $surface; }
    #paste:focus { border: tall $primary; }
    #feed { margin: 1 2 0 2; background: $background; scrollbar-size-vertical: 1; }
    #feed > ListItem { padding: 0 1; background: $background; height: auto; }
    #feed > ListItem.-highlight { background: $panel; }
    #feed:focus > ListItem.-highlight { background: $panel; text-style: none; }
    Row Horizontal { height: auto; }
    Row .badge { width: 10; height: auto; }
    Row .body { width: 1fr; height: auto; }
    #empty { margin: 2 4; color: $text-muted; }
    SettingsScreen { background: $background; }
    #settings-head { padding: 1 2; }
    #settings { padding: 0 2; }
    .setting { height: 3; }
    .setting .label { width: 40; padding-top: 1; color: $text-muted; }
    .setting Input, .setting Select { width: 52; }
    #settings { height: auto; }
    #status { height: 1; margin-top: 1; }
    #reset { margin-top: 1; }
    #cfgerr { padding: 2; }
    """
    BINDINGS = [
        Binding("ctrl+o", "open_last", "Open last", priority=True),
        Binding("ctrl+r", "retry", "Retry queue", priority=True),
        Binding("f2", "settings", "Settings"),
        Binding("f3", "undo", "Undo last"),
        Binding("f4", "update", "Update yt-dlp"),
        Binding("escape", "cancel_undo", show=False),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, settings=False):
        super().__init__()
        self.open_settings = settings
        self.jobs = queue.Queue()
        self.busy = 0  # links queued or running
        self.mood, self.mood_until, self.frame = "idle", 0.0, 0
        self.made = []  # (row, Result) for undo
        self.undo_armed = 0.0
        self.last = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static(mascot("idle"), id="mascot")
            with Vertical(id="talk"):
                yield Static("", id="say")
                yield Static("", id="meta")
        yield PasteInput(placeholder="Paste YouTube links here, Enter saves (Enter on empty: use clipboard)", id="paste")
        yield ListView(id="feed")
        yield Footer()

    def on_mount(self):
        self.register_theme(THEME)
        self.theme = "folio"
        threading.Thread(target=self.worker, daemon=True).start()
        self.set_interval(0.12, self.tick)
        self.call_after_refresh(self.start)

    def start(self):
        self.refresh_meta()
        feed = self.query_one("#feed", ListView)
        for when, path in y.recent_saves(5):
            row = Row(Path(path).stem)
            row.set(status="saved", detail=f"earlier · {when.replace('T', ' ')[:16]}", path=Path(path))
            feed.append(row)
        if not feed.children:
            feed.mount(Static("Nothing saved this session yet. Your links will show up here.", id="empty"))
        self.mascot_says("idle")
        self.query_one("#paste").focus()
        if self.open_settings:
            self.action_settings()

    # -- talking mascot -------------------------------------------------
    def mascot_says(self, mood, text=None, hold=0.0):
        self.mood, self.mood_until = mood, time.monotonic() + hold
        self.say_text = text or random.choice(LINES.get(mood, LINES["idle"]))
        self.query_one("#say", Static).update(self.say_text)
        self.query_one("#mascot", Static).update(mascot(mood))

    def refresh_meta(self):
        try:
            cfg = y.load_config()
            where = f"{cfg['vault'].name} › {cfg['inbox']}"
            warn = "" if (cfg["vault"] / ".obsidian").is_dir() else "  [#f2c14e]no .obsidian folder in that vault[/]"
        except ValueError as e:
            where, warn = "", f"[#ff7b7b]{escape(y.cap(e, 120))}[/]"
        n = len(y.read_retry())
        queued = f"  [#f2c14e]{n} waiting in {y.RETRY.name}, ctrl+r retries[/]" if n else ""
        self.query_one("#meta", Static).update(f"{escape(where)} · yt-dlp {y.yt_dlp.version.__version__}{warn}{queued}")

    def tick(self):
        self.frame += 1
        working = self.busy > 0
        if working:
            mood = "work" if self.frame // 3 % 2 else "work2"
            self.query_one("#mascot", Static).update(mascot(mood))
            for row in self.query(Row):
                if row.status == "fetching":
                    row.set(frame=self.frame)
        elif time.monotonic() > self.mood_until:
            if self.mood not in ("idle", "blink"):
                self.mascot_says("idle")
            else:
                blink = self.frame % 40 == 0
                self.mood = "blink" if blink else "idle"
                self.query_one("#mascot", Static).update(mascot(self.mood))
        if self.undo_armed and time.monotonic() > self.undo_armed:
            self.undo_armed = 0.0

    def notify_user(self, text, mood="idle"):
        self.mascot_says(mood, text, hold=6)

    # -- pasting and saving ----------------------------------------------
    def on_input_submitted(self, event):
        text = event.value.strip()
        event.input.value = ""
        try:
            cfg = y.load_config()
            text = text or y.clipboard()  # Enter alone pastes for you
        except (ValueError, OSError, subprocess.SubprocessError) as e:
            return self.notify_user(f"Can't start: {y.cap(e, 150)}", "oops")
        self.refresh_meta()
        for url in y.urls_in(text):
            self.enqueue(url, cfg, "tui")

    def enqueue(self, url, cfg, source):
        feed = self.query_one("#feed", ListView)
        for empty in self.query("#empty"):
            empty.remove()
        row = Row(y.cap(url, 80))
        feed.append(row)
        feed.index = len(feed) - 1
        feed.scroll_end(animate=False)
        self.busy += 1
        self.jobs.put((row, url, cfg, source))
        self.mascot_says("work", "On it." if self.busy == 1 else f"{self.busy} links in the queue.")

    def worker(self):
        """One link at a time, in order (process() takes a lock anyway). A throttle parks the rest in retry.txt."""
        ui = self.call_from_thread
        while True:
            row, url, cfg, source = self.jobs.get()
            ui(row.set, status="fetching", detail="fetching the page")
            say, paint = y.say, y.paint
            y.say = lambda *a, row=row: (row.lines.append(" ".join(map(str, a))), ui(self.progress, row))
            y.paint = lambda s, color: s  # the rows do their own coloring; no ANSI in the text
            try:
                res = y.process(url, cfg, repl=True, source=source)
            finally:
                y.say, y.paint = say, paint
            if source == "retry" and res.outcome not in ("stopped", "cancelled"):
                drop_retry(url)
            ui(self.done, row, res)
            if res.outcome in ("stopped", "cancelled"):
                while not self.jobs.empty():
                    r2, u2, _, _ = self.jobs.get_nowait()
                    try:
                        y.queue_retry(y.watch_url(y.parse_url(u2)[0]))
                    except ValueError:
                        pass
                    ui(r2.set, status="queued", detail=f"saved in {y.RETRY.name} for later")
                    ui(self.settle)

    def progress(self, row):
        """Show the pipeline's latest line (retrying, waiting for another run); done() replaces it with the outcome."""
        if row.status == "fetching":
            row.set(detail=y.cap(row.lines[-1].strip("."), 90))

    def settle(self):
        self.busy = max(0, self.busy - 1)

    def done(self, row, res):
        self.settle()
        out = res.outcome
        head, *rest = (row.lines[-1] if row.lines else out).split("\n")
        secs = re.search(r"\((\d+\.\d)s\)", head)
        parts = [head.split(": ", 1)[-1]] + [r.strip() for r in rest[1 if out in ("saved", "stub") else 0:]]
        row.set(status=out, title=y.clean(res.title or row.title), path=res.path, detail=" · ".join(([f"{secs[1]}s"] if secs else []) + parts))
        if res.outcome in ("saved", "stub"):
            self.made.append((row, res))
            self.last = res.path
        mood = {"saved": "happy", "stub": "meh", "duplicate": "meh", "skipped": "meh", "stopped": "sleep"}.get(out, "oops")
        say = {"duplicate": "Already have that one.", "skipped": "Shorts aren't my thing."}.get(out)
        self.mascot_says(mood, say, hold=6)
        self.refresh_meta()

    # -- actions -----------------------------------------------------------
    def action_open_last(self):
        target = self.last or (y.recent_saves(1) or [(0, None)])[0][1]
        if not target:
            return self.notify_user("Nothing saved yet.")
        y.open_obsidian(target)
        self.notify_user(f"Opening {Path(target).stem} in Obsidian.")

    def action_retry(self):
        urls = y.read_retry()
        if not urls:
            return self.notify_user("retry.txt is empty. Nothing to retry.")
        try:
            cfg = y.load_config()
        except ValueError as e:
            return self.notify_user(f"Can't retry: {y.cap(e, 150)}", "oops")
        for u in urls:
            self.enqueue(u, cfg, "retry")

    def action_settings(self):
        self.push_screen(SettingsScreen())

    def action_undo(self):
        if not self.made:
            return self.notify_user("Nothing to undo in this session.")
        row, res = self.made[-1]
        if not self.undo_armed:
            self.undo_armed = time.monotonic() + 6
            return self.mascot_says("oops", f"Delete {row.title}? Press F3 again to confirm, Esc to keep it.", hold=6)
        self.undo_armed = 0.0
        try:
            res.path.unlink(missing_ok=True)
        except OSError as e:
            return self.notify_user(f"Couldn't delete it: {y.cap(e, 120)}", "oops")
        self.made.pop()
        y.log_run(res.path, "undone")
        row.set(status="undone", detail="deleted by you", path=None)
        self.notify_user("Deleted. It never happened.")

    def action_cancel_undo(self):
        if self.undo_armed:
            self.undo_armed = 0.0
            self.mascot_says("idle")

    def action_update(self):
        self.notify_user("Updating yt-dlp...", "work")
        self.run_worker(self.do_update, thread=True)

    def do_update(self):
        lines = []
        say, y.say = y.say, lines.append
        try:
            y.update_ytdlp()
        finally:
            y.say = say
        self.call_from_thread(self.notify_user, y.cap(" ".join(lines), 160))

    def on_list_view_selected(self, event):
        row = event.item
        if isinstance(row, Row) and row.path:
            y.open_obsidian(row.path)
            self.notify_user(f"Opening {row.title}.")


def run(settings=False):
    YtApp(settings).run()
    return 0


if __name__ == "__main__":
    sys.exit(run())
