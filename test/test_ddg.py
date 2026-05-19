from ddgs import DDGS

with DDGS() as ddgs:
    results = ddgs.text("Elterngeld Bayern Probleme", max_results=5)
    for r in results:
        print(r["href"])