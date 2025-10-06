import pandas as pd

rows = [
    {
        "event_id": "demo-0001",
        "state": "OH",
        "event_type": "Hail",
        "episode_id": "E1",
        "cz_name": "Franklin",
        "begin_date_time": "2023-06-01 12:00:00",
        "end_date_time": "2023-06-01 12:30:00",
        "injuries_direct": 0,
        "deaths_direct": 0,
        "damage_property": "",
        "magnitude": 1.0,
        "latitude": 39.9612,
        "longitude": -82.9988,
    }
]
pd.DataFrame(rows).to_parquet("sample_event.parquet", index=False)
print("Wrote sample_event.parquet")
