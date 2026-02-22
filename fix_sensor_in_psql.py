import csv
import psycopg2
from datetime import datetime

# -------- SETTINGS --------
csv_file_path = "200um_list.csv"

sen_name_column_index = 1
ttu_column_index = 3
batch_column_index = 2   # OBA ID column (sen_batch_id)
# --------------------------

DB_CONFIG = {
    "host": "129.118.107.198",
    "dbname": "ttu_mac_local",
    "user": "postgres",
    "password": "ttulovescalox",
    "port": 5432
}

insert_query = """
INSERT INTO sensor (
    sen_name,
    geometry,
    resolution,
    thickness,
    grade,
    kind,
    sen_batch_id,
    date_verify_received
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (sen_name) DO NOTHING;
"""


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    inserted_count = 0

    with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)

        for row in reader:

            # Ensure row is long enough
            if len(row) <= max(sen_name_column_index, ttu_column_index, batch_column_index):
                continue

            # ✅ Only process TTU rows
            if row[ttu_column_index] != "TTU":
                continue

            sen_name = row[sen_name_column_index]
            sen_batch_id = row[batch_column_index]

            if not sen_name:
                continue

            # ---- Set static / derived values ----
            geometry = "Full"
            resolution = "LD"
            thickness = 200
            grade = "A"
            kind = "200um Si Sensor LD Full"

            today = datetime.today()
            date_verify_received = today.date()

            cursor.execute(insert_query, (
                sen_name,
                geometry,
                resolution,
                thickness,
                grade,
                kind,
                sen_batch_id,
                date_verify_received
            ))

            inserted_count += cursor.rowcount  # only counts if actually inserted

    conn.commit()
    cursor.close()
    conn.close()

    print("------ SUMMARY ------")
    print(f"Inserted new sensors: {inserted_count}")


if __name__ == "__main__":
    main()