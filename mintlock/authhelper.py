#!/usr/bin/python3 -I
"""One PAM conversation, run as its own process.

The locker starts this helper, reads JSON lines from its stdout and answers
prompts with JSON lines on its stdin. Running PAM out of process means a module
that blocks (pam_fprintd waiting for a finger) can be abandoned by killing the
helper, and nothing PAM does can take the locker down with it.

  stdout: {"t": "info"|"error", "msg": str}
          {"t": "prompt", "echo": bool, "msg": str}
          {"t": "result", "ok": bool, "msg": str}
  stdin:  JSON string (the answer to the last prompt)
"""

import json
import sys

import PAM


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def read_answer():
    line = sys.stdin.readline()
    if not line:  # locker went away
        sys.exit(3)
    try:
        value = json.loads(line)
    except ValueError:
        return ""
    return value if isinstance(value, str) else ""


def conversation(_auth, queries, _data):
    replies = []
    for text, kind in queries:
        text = (text or "").strip()
        if kind in (PAM.PAM_PROMPT_ECHO_OFF, PAM.PAM_PROMPT_ECHO_ON):
            send({"t": "prompt", "echo": kind == PAM.PAM_PROMPT_ECHO_ON, "msg": text})
            replies.append((read_answer(), 0))
        elif kind == PAM.PAM_ERROR_MSG:
            send({"t": "error", "msg": text})
            replies.append(("", 0))
        elif kind == PAM.PAM_TEXT_INFO:
            send({"t": "info", "msg": text})
            replies.append(("", 0))
        else:
            return None
    return replies


def main():
    if len(sys.argv) != 3:
        print("usage: authhelper.py SERVICE USER", file=sys.stderr)
        return 2
    service, user = sys.argv[1], sys.argv[2]

    pam = PAM.pam()
    try:
        pam.start(service)
        pam.set_item(PAM.PAM_USER, user)
        pam.set_item(PAM.PAM_CONV, conversation)
        pam.authenticate()
        pam.acct_mgmt()
    except PAM.error as err:
        msg = err.args[0] if err.args else "Authentication failed"
        send({"t": "result", "ok": False, "msg": str(msg)})
        return 1
    except Exception as err:  # never let a traceback look like success
        send({"t": "result", "ok": False, "msg": "Authentication error: %s" % err})
        return 1

    try:
        # Refreshes things like Kerberos tickets; failure here is not a lockout.
        pam.setcred(PAM.PAM_REINITIALIZE_CRED)
    except Exception:
        pass
    send({"t": "result", "ok": True, "msg": ""})
    return 0


if __name__ == "__main__":
    sys.exit(main())
