"""Manual running-server smoke check; inert during test discovery."""

import requests


def main() -> int:
    try:
        response = requests.post(
            "http://127.0.0.1:5001/predict",
            json={
                "player": "Jayson Tatum",
                "opponent": "DAL",
                "spread": -5.5,
                "line": 8.5,
                "over_odds": -110,
                "under_odds": -110,
            },
            timeout=130,
        )
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        return 1

    print(response.status_code)
    print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
