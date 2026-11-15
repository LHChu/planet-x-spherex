"""Run the backend suite with external socket access denied, even if LIVE is set."""
import os
import sys
import unittest


def main():
    os.environ["SPHEREX_LIVE"] = "0"
    blocked = []

    def audit(event, args):
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
                return
        elif event == "socket.getaddrinfo":
            if args[0] in ("localhost", "127.0.0.1", "::1"):
                return
        else:
            return
        blocked.append(event)
        raise RuntimeError("External network access forbidden in offline tests")

    sys.addaudithook(audit)
    suite = unittest.defaultTestLoader.discover("backend/tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if blocked:
        print(f"Blocked unexpected external network attempts: {len(blocked)}", file=sys.stderr)
    return 0 if result.wasSuccessful() and not blocked else 1


if __name__ == "__main__":
    sys.exit(main())
