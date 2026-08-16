# Setup

**Read this before running any script in this repository.**

Every tool here is Python, standard library only — nothing to `pip install`, no
virtualenv, no `requirements.txt`. The single prerequisite is a Python 3.9+
interpreter.

That prerequisite is the whole problem. This skill's users are Sims 4 players,
not developers: they install a game and drag files into a folder. **Assume
Python is absent until you have proved otherwise**, and assume the person you
are helping has never installed a programming language and should not be asked
to. Do it for them.

## 1. Detect

Do not test whether a command exists. **Run it and read the output.**

```bash
py -3 -c "import sys; print(sys.version_info[0], sys.version_info[1])"
python3 -c "import sys; print(sys.version_info[0], sys.version_info[1])"
python -c "import sys; print(sys.version_info[0], sys.version_info[1])"
```

Take the first that exits 0 and prints a version ≥ 3.9. Use that exact command
for every later invocation — do not assume `py` works just because `python3`
did, or the reverse.

Presence checks lie here, on Windows especially: `%LOCALAPPDATA%\Microsoft\
WindowsApps\python3.exe` is a **zero-byte Microsoft Store stub**. It is on PATH
in a default Windows install, so `where python3` succeeds and `Get-Command`
finds it, but running it opens the Store and installs nothing. A skill that
checks for the command instead of running it will report Python as available
and then fail on every script with an error the user cannot interpret.

## 2. Install, if nothing answered

Say what you are doing and why before you install anything.

**Windows** — winget ships with Windows 11 and Windows 10 1809+, so this needs
no download and no admin prompt at user scope:

```
winget install -e --id Python.Python.3.13 --scope user \
  --accept-source-agreements --accept-package-agreements
```

Then **start a fresh shell**. PATH is read at process start, so the session that
ran the install cannot see the new interpreter. This is the single most common
way an otherwise-correct install looks broken. If you cannot start a new shell,
call the launcher by full path:
`%LOCALAPPDATA%\Programs\Python\Launcher\py.exe`.

If `winget` itself is missing (rare, but stripped-down or very old installs),
send the user to <https://python.org/downloads/> and have them run the
installer with **"Add python.exe to PATH"** ticked. Do not walk them through
anything more elaborate than that.

**macOS** — do not assume Homebrew. Very few Sims players have it, and
installing it to get Python is a much bigger ask than getting Python directly.
Two workable paths, preferring the first:

- Run `xcode-select --install`. This opens Apple's own GUI installer for the
  Command Line Tools, which include a real `python3`. The user clicks Install
  and waits.
- Or download the official universal installer from
  <https://python.org/downloads/macos/> and open the `.pkg`. It is a normal
  double-click install.

**Linux** — `python3` is present on essentially every desktop distribution. If
it genuinely is not, `sudo apt install python3` (Debian/Ubuntu),
`sudo dnf install python3` (Fedora), or `sudo pacman -S python` (Arch).

## 3. Verify before continuing

Re-run the detection command. Do not proceed on the assumption that an install
succeeded — winget can report success while the shell still cannot see the
interpreter, which is the same failure as step 1 wearing a different hat.

## Invocation

Scripts in this repository are written as `py scripts/foo.py`. `py` is the
Windows Python Launcher and does not exist on macOS or Linux; substitute
whichever command answered in step 1.
