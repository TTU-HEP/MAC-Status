import csv
import psycopg2

# -------- SETTINGS --------
csv_file_path = "200um_list.csv"
sen_name_column_index = 1
ttu_column_index = 3
# --------------------------

DB_CONFIG = {
    "host": "129.118.107.198",
    "dbname": "ttu_mac_local",
    "user": "viewer",
    "password": "mac",
    "port": 5432
}

def main():
    # ---- Step 1: Load CSV sen_names ----
    csv_sen_names = set()

    with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) <= max(sen_name_column_index, ttu_column_index):
                continue
            if row[ttu_column_index] != "TTU":
                continue
            sen_name_raw = row[sen_name_column_index].strip()
            if sen_name_raw:
                csv_sen_names.add(f"{sen_name_raw}_0")  # add _0 like in insert

    print(f"Total CSV TTU sensors: {len(csv_sen_names)}")

    # ---- Step 2: Query PostgreSQL sensors with thickness=200 ----
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT sen_name,sen_batch_id FROM sensor WHERE thickness = 200;")
    db_sensors = {row[0] for row in cursor.fetchall()}

    cursor.close()
    conn.close()

    # ---- Step 3: Find sensors in DB not in CSV ----
    missing_in_csv = db_sensors - csv_sen_names

    print(f"Sensors in DB (thickness=200) not in CSV: {len(missing_in_csv)}")
    for sen in sorted(missing_in_csv):
        print(sen)

if __name__ == "__main__":
    main()