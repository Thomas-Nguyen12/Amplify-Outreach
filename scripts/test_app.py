
import urllib.request
import urllib.error
import sys

# Adjust to match your application.
URL = "http://127.0.0.1:8000/health"

print("Testing application health...")

try:
    with urllib.request.urlopen(URL, timeout=10) as response:
        status = response.status
        body = response.read(500).decode(
            "utf-8", errors="replace"
        )

        print("HTTP status:", status)
        print("Response:", body)

        if status == 200:
            print("PASS: Health endpoint responded")
        else:
            print("FAIL: Unexpected HTTP status")
            sys.exit(1)

except Exception as error:
    print("FAIL:", error)
    sys.exit(1)
