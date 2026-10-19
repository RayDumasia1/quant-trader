"""Manual FMP probe; requires FMP_API_KEY in the environment."""

def main():
    import os
    import requests
    import json
    
    API_KEY = os.environ["FMP_API_KEY"]
    TEST_SYMBOL = "AAPL"
    BASE_URL = "https://financialmodelingprep.com/stable"
    
    for endpoint, params in [
        ('earnings', {}),
        ('income-statement', {'period': 'quarter', 'limit': 8}),
        ('ratios', {'period': 'quarter', 'limit': 8}),
    ]:
        print(f"\n{'='*60}\n{endpoint}\n{'='*60}")
        resp = requests.get(f"{BASE_URL}/{endpoint}", params={**params, 'symbol': TEST_SYMBOL, 'apikey': API_KEY})
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Number of records returned: {len(data) if isinstance(data, list) else 'N/A (not a list)'}")
            print("First record:")
            print(json.dumps(data[0] if isinstance(data, list) and data else data, indent=2)[:1000])
        else:
            print(resp.text[:500])


if __name__ == "__main__":
    main()
