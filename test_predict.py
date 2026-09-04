"""Manual Flask test-client smoke check; inert during test discovery."""


def main() -> None:
    from app import app

    client = app.test_client()
    response = client.post(
        "/predict",
        json={
            "player": "Jayson Tatum",
            "opponent": "DAL",
            "spread": -5.5,
            "line": 8.5,
            "over_odds": -110,
            "under_odds": -110,
        },
    )
    print(response.status_code)
    print(response.get_data(as_text=True))


if __name__ == "__main__":
    main()
