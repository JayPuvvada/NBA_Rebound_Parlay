# One-off diagnostics

These scripts are preserved for manual troubleshooting, not part of automated tests.
Run from the repository root with `python3 -m scripts.manual.<module_name>`.

`test_proxy_scraper` performs network calls at import time and can print proxy configuration. Do not include this folder in automated discovery, run it casually, or share its raw output. Normal tests: `python3 -m unittest discover -s tests -q`.
