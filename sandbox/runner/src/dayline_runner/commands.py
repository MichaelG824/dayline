"""Record the commands typed in a sandbox's terminal.

Every shell the runner opens loads ``BASHRC``, which appends one line per
command - ``<epoch seconds>\\t<exit code>\\t<command>`` - to
``/workspace/.dayline/commands.log``. The log is on the workspace volume, so
it outlives a stopped sandbox; ``.dayline`` is an ignored folder, so it never
shows in the file tree, a snapshot, or the diff.

The log is written by the candidate's own shell, so it is untrusted input:
malformed lines are skipped and the size is capped by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass

DAYLINE_DIR = ".dayline"
BASHRC_PATH = f"{DAYLINE_DIR}/bashrc"
COMMAND_LOG_PATH = f"{DAYLINE_DIR}/commands.log"
MAX_COMMAND_CHARS = 500
MAX_COMMANDS = 2000

# Loaded with `bash --rcfile` for interactive shells. History numbers tell a
# new command from a bare Enter (which adds nothing to history), and the
# first prompt only takes note of where history stands, so a reconnected
# shell does not log the previous shell's last command again.
BASHRC = r"""# Dayline: log each command (time, exit code, text) for the session record.
[ -f /etc/bash.bashrc ] && . /etc/bash.bashrc
HISTCONTROL=
__dayline_seen=
__dayline_ready=
__dayline_log() {
  local code=$? entry num cmd
  entry=$(HISTTIMEFORMAT= history 1)
  read -r num _ <<< "$entry"
  if [ -z "$__dayline_ready" ]; then
    __dayline_ready=1 __dayline_seen=$num
    return
  fi
  [ -z "$num" ] || [ "$num" = "$__dayline_seen" ] && return
  __dayline_seen=$num
  # "  42  the command": drop the number and the two spaces after it.
  cmd=${entry#*[0-9]  }
  cmd=${cmd//$'\n'/ }
  cmd=${cmd//$'\t'/ }
  cmd=${cmd#"${cmd%%[![:space:]]*}"}
  printf '%s\t%s\t%s\n' "$(date +%s)" "$code" "$cmd" >> /workspace/.dayline/commands.log
}
PROMPT_COMMAND="__dayline_log${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
"""


@dataclass(frozen=True, slots=True)
class CommandRun:
    at: float
    exit_code: int
    command: str


def parse_command_log(text: str) -> list[CommandRun]:
    runs: list[CommandRun] = []
    for line in text.splitlines():
        at, _, rest = line.partition("\t")
        code, _, command = rest.partition("\t")
        try:
            run = CommandRun(at=float(at), exit_code=int(code), command=command.strip())
        except ValueError:
            continue
        if run.command:
            runs.append(CommandRun(run.at, run.exit_code, run.command[:MAX_COMMAND_CHARS]))
    return runs[-MAX_COMMANDS:]
