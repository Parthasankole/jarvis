from jarvis_apps import refresh_index, search_apps

idx = refresh_index()
print(f"Indexed apps: {len(idx)}")

# quick sanity check
print("Top matches for 'brave':", search_apps("brave"))
print("Top matches for 'notepad':", search_apps("notepad"))