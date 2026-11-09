import csv

# -------- SETTINGS --------
csv_file_path = "sensor_debugging - Sheet3.csv"   # <-- change this
id_column_index = 2               # column containing OBA IDs
ttu_column_index = 3              # column that should contain "TTU"
# --------------------------

# OBA IDs with expected counts from parentheses
id_data = {
    "OBA46981": 19,
    "OBA46996": 23,
    "OBA47002": 20,
    "OBA47079": 25,
    "OBA47823": 25,
    "OBA47824": 23,
    "OBA47846": 23,
    "OBA47848": 24,
    "OBA47850": 23,
    "OBA47852": 24,
    "OBA47869": 24,
    "OBA47870": 25,
    "OBA47871": 24,
    "OBA47872": 25,
    "OBA47873": 25,
    "OBA47874": 25,
    "OBA47875": 22,
    "OBA47880": 20,
    "OBA47882": 25,
    "OBA47883": 24,
    "OBA47884": 25,
    "OBA47885": 24,
    "OBA47896": 24,
    "OBA47898": 25,
    "OBA48285": 25,
    "OBA48286": 20,
    "OBA48287": 25,
    "OBA48288": 25,
    "OBA48922": 24,
    "OBA48923": 25,
    "OBA48924": 25,
    "OBA48926": 25,
    "OBA48927": 24,
    "OBA48928": 25,
    "OBA48929": 24,
    "OBA48930": 24,
    "OBA48936": 23,
    "OBA48937": 24,
    "OBA48938": 24,
    "OBA48939": 24,
    "OBA48948": 25,
    "OBA48949": 25,
    "OBA48988": 22,
    "OBA48989": 24,
    "OBA48991": 25,
    "OBA48995": 19,
    "OBA48997": 24,
    "OBA48998": 25,
    "OBA48999": 18,
    "OBA49000": 24,
    "OBA49040": 23,
    "OBA49041": 25,
    "OBA49042": 25,
    "OBA49043": 25,
    "OBA49044": 22,
    "OBA49045": 19,
    "OBA49048": 24,
    "OBA49049": 25,
    "OBA49084": 24,
    "OBA49085": 24,
    "OBA49086": 22,
    "OBA49087": 23,
    "OBA49090": 25,
    "OBA49091": 25,
    "OBA48293": 25,
    "OBA48435": 25,
    "OBA49345": 25,
    "OBA49387": 25,
    "OBA49766": 25,
    "OBA50213": 25,
    "OBA50259": 25,
    "OBA50260": 25,
    "OBA50320": 25,
    "OBA50560": 25,
    "OBA50573": 25,
    "OBA50576": 25,
    "OBA50617": 25,
    "OBA50701": 25,
    "OBA51052": 25,
    "OBA51088": 22,
    "OBA51296": 24,
    "OBA51297": 22,
    "OBA51298": 23,
    "OBA51301": 25,
    "OBA51305": 25,
    "OBA51306": 24,
    "OBA51307": 25,
    "OBA51313": 23,
    "OBA51314": 24,
    "OBA51315": 24,
    "OBA51316": 22,
    "OBA51318": 25,
    "OBA51319": 25,
    "OBA51395": 24,
    "OBA51975": 24,
    "OBA52479": 24,
    "OBA52480": 24,
    "OBA52481": 25,
    "OBA52478": 24,
    "OBA52851": 24,
    "OBA52853": 25,
    "OBA52854": 24,
    "OBA50563": 24,
    "OBA52951": 12,
    "OBA53027": 12,
    "OBA53198": 20,
    "OBA53202": 24,
    "OBA53203": 11,
    "OBA53206": 23,
    "OBA53209": 23,
    "OBA53287": 24,
    "OBA53288": 25,
    "OBA53294": 25,
    "OBA53296": 23,
    "OBA53298": 24,
    "OBA53733": 21,
    "OBA53734": 21,
    "OBA53735": 20,
    "OBA53736": 24,
    "OBA54144": 24,
    "OBA54148": 25,
    "OBA54193": 24,
    "OBA54195": 25,
    "OBA54196": 24,
    "OBA54197": 25,
    "OBA54198": 25,
    "OBA54199": 25,
    "OBA54200": 25,
    "OBA54245": 25,
    "OBA54246": 24,
    "OBA54247": 24,
    "OBA54248": 25,
    "OBA54481": 24,
    "OBA54482": 25,
    "OBA54483": 25,
    "OBA54484": 25,
    "OBA54485": 25,
    "OBA54486": 24,
    "OBA54487": 23,
    "OBA54488": 22,
    "OBA54563": 24,
    "OBA54610": 25,
    "OBA54611": 25,
    "OBA54612": 25,
    "OBA54740": 23,
    "OBA54741": 24,
    "OBA54822": 17,
    "OBA54823": 22,
    "OBA54824": 23,
    "OBA54825": 20,
    "OBA54893": 23,
    "OBA54894": 22,
    "OBA54895": 22,
    "OBA54896": 23,
    "OBA54897": 25,
    "OBA54898": 24,
    "OBA55104": 25,
    "OBA55105": 25,
    "OBA55107": 23,
    "OBA54567": 24,
    "OBA54827": 22,
    "OBA54828": 18,
    "OBA55106": 24,
    "OBA55108": 25,
    "OBA55109": 24,
    "OBA55110": 25,
    "OBA55111": 25,
    "OBA55149": 23,
    "OBA55150": 23,
    "OBA55191": 25,
    "OBA55192": 25,
    "OBA55193": 25,
    "OBA55194": 25,
    "OBA55279": 24,
    "OBA55665": 22,
    "OBA55666": 24,
    "OBA55667": 24,
    "OBA55668": 25,
    "OBA53213": 21,
    "OBA54315": 24,
    "OBA54316": 24,
    "OBA54317": 22,
    "OBA54318": 24,
    "OBA54564": 25,
    "OBA54565": 23,
    "OBA54566": 25,
}

# Flag counters
no_match_count = 0
missing_ttu_count = 0
count_mismatch_count = 0
valid_count = 0

# Store difference tracking
count_differences = {}

# Load CSV
with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
    reader = list(csv.reader(csvfile))

# Process each ID
for target_id, expected_count in id_data.items():
    actual_matches = []
    
    for row in reader:
        if len(row) > id_column_index and row[id_column_index] == target_id:
            actual_matches.append(row)

    found_count = len(actual_matches)

    # ---- NO MATCH FLAG ----
    if found_count == 0:
        print(f"NO_MATCH FLAG: {target_id}")
        no_match_count += 1
        count_differences[target_id] = -expected_count
        continue

    # ---- COUNT MISMATCH FLAG ----
    if found_count != expected_count:
        diff = found_count - expected_count
        print(f"COUNT_MISMATCH FLAG: {target_id} | Expected: {expected_count}, Found: {found_count}, Diff: {diff}")
        count_mismatch_count += 1
        count_differences[target_id] = diff

    # ---- TTU CHECK ----
    for row in actual_matches:
        if len(row) <= ttu_column_index or row[ttu_column_index] != "TTU":
            print(f"MISSING_TTU FLAG: {target_id}")
            missing_ttu_count += 1
            break  # only flag once per ID

    # ---- VALID ----
    if found_count == expected_count:
        all_ttu = all(
            len(row) > ttu_column_index and row[ttu_column_index] == "TTU"
            for row in actual_matches
        )
        if all_ttu:
            valid_count += 1

# -------- SUMMARY --------
print("\n------ SUMMARY ------")
print(f"Valid IDs: {valid_count}")
print(f"NO_MATCH flags: {no_match_count}")
print(f"COUNT_MISMATCH flags: {count_mismatch_count}")
print(f"MISSING_TTU flags: {missing_ttu_count}")
print(f"Total IDs processed: {len(id_data)}")

print("\n------ COUNT DIFFERENCES ------")
for k, v in count_differences.items():
    print(f"{k}: {v}")