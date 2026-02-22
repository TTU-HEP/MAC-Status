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
VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
"""
def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    cursor.execute("SELECT sen_name FROM sensor;")
    existing_sensors = {row[0] for row in cursor.fetchall()}

    inserted_count = 0
    skipped_count = 0

    with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)

        for row in reader:

            if len(row) <= max(sen_name_column_index, ttu_column_index, batch_column_index):
                continue

            # Only TTU rows
            if row[ttu_column_index] != "TTU":
                continue

            # sen_name = row[sen_name_column_index]
            sen_batch_id = row[batch_column_index]

            sen_name_raw = row[sen_name_column_index].strip()
            if not sen_name_raw:
                continue

            sen_name = f"{sen_name_raw}_0"
            if not sen_name:
                continue

            # Skip if already exists
            if sen_name in existing_sensors:
                skipped_count += 1
                continue

            geometry = "Full"
            resolution = "LD"
            thickness = 200
            grade = "A"
            kind = "200um Si Sensor LD Full"
            date_verify_received = datetime.today().date()

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

            existing_sensors.add(sen_name)  # prevent duplicates within same CSV
            inserted_count += 1

    conn.commit()
    cursor.close()
    conn.close()

    print("------ SUMMARY ------")
    print(f"Inserted: {inserted_count}")
    print(f"Skipped (already existed): {skipped_count}")


if __name__ == "__main__":
    main()