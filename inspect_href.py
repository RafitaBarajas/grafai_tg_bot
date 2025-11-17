from bs4 import BeautifulSoup
s = BeautifulSoup(open('page.html',encoding='utf-8').read(),'html.parser')
a = s.select_one("a[href^='/decks/']")
href = a['href'] if a else None
print('sample href =>', href)
if href:
	import requests
	base = 'https://play.limitlesstcg.com'
	r = requests.get(base + href, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
	open('deck1.html', 'w', encoding='utf-8').write(r.text)
	print('wrote deck1.html, len=', len(r.text))
