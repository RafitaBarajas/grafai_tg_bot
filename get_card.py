import requests
headers = {"User-Agent": "Mozilla/5.0"}

api_url = f"https://api.tcgdex.net/v2/en/series/tcgp"

r = requests.get(api_url, headers=headers, timeout=10)

print(r.json())