import asyncio
import asyncpg
import yaml
import matplotlib.pyplot as plt
import sys
import os
import getpass

# ----------------------------------------
# Load configuration
# ----------------------------------------
with open('dbase_info/conn.yaml', 'r') as file:
    configuration = yaml.safe_load(file)

# ----------------------------------------
# Credential handling
# ----------------------------------------
def resolve_db_password():
    if os.getenv("PGPASSWORD"):
        return os.getenv("PGPASSWORD")

    pwd = configuration.get("DBPassword")
    if pwd:
        return pwd

    print("Database password (leave blank if none): ", end="", flush=True)
    entered = getpass.getpass("")
    if entered:
        os.environ["PGPASSWORD"] = entered
        return entered

    return None


def maybe_save_plot(fig, default_name):
    while True:
        choice = input(f"Save plot '{default_name}'? [y/N]: ").strip().lower()
        if choice in ('y', 'yes'):
            filename = input(
                f"Enter filename (default: {default_name}.png): "
            ).strip()
            if not filename:
                filename = default_name
            if not filename.endswith(".png"):
                filename += ".png"
            fig.savefig(filename, bbox_inches='tight')
            print(f"Plot saved as {filename}")
            break
        elif choice in ('n', 'no', ''):
            print("Skipping save.")
            break
        else:
            print("Please enter 'y' or 'n'.")


DB_PASSWORD = resolve_db_password()

# ----------------------------------------
# Database helpers
# ----------------------------------------
async def get_connection():
    return await asyncpg.connect(
        host=configuration['db_hostname'],
        database=configuration['dbname'],
        user='viewer',
        password=DB_PASSWORD,
        port=5432
    )


async def fetch_thickness_by_proto(conn, proto_names):
    query = """
        SELECT proto_name, avg_thickness
        FROM proto_inspect
        WHERE proto_name = ANY($1)
          AND avg_thickness IS NOT NULL;
    """
    rows = await conn.fetch(query, proto_names)

    thickness = {}
    for r in rows:
        val = r['avg_thickness']
        # only accept real numbers
        if isinstance(val, (int, float)):
            thickness.setdefault(r['proto_name'], []).append(val)

    return thickness



# ----------------------------------------
# Plotting
# ----------------------------------------
def plot_thickness_distribution(thickness, title):
    fig, ax = plt.subplots()

    for proto, values in thickness.items():
        if values:
            ax.hist(
                values,
                bins=30,
                alpha=0.6,
                label=proto,
                histtype='stepfilled'
            )

    ax.set_xlabel("Average Thickness")
    ax.set_ylabel("Frequency")
    ax.set_title(title)
    ax.legend(fontsize='small')
    plt.show()

    return fig


def plot_combined_distribution(thickness, title):
    all_values = []
    for values in thickness.values():
        all_values.extend(values)

    fig, ax = plt.subplots()
    ax.hist(all_values, bins=40, alpha=0.8)

    ax.set_xlabel("Average Thickness")
    ax.set_ylabel("Frequency")
    ax.set_title(title)
    plt.show()

    return fig


# ----------------------------------------
# Friendly UI helpers
# ----------------------------------------
def prompt_protos():
    raw = input("\nEnter proto names (comma separated):\n> ")
    return [p.strip() for p in raw.split(",") if p.strip()]


# ----------------------------------------
# Main workflow
# ----------------------------------------
async def main():
    print("\n" + "=" * 40)
    print(" Proto Thickness Distribution ")
    print("=" * 40)

    try:
        conn = await get_connection()
    except Exception as e:
        print("Could not connect to database.")
        print(e)
        sys.exit(1)

    while True:
        print("""
Options:

  1) Plot thickness for selected proto(s)
  2) Quit
""")
        choice = input("Enter choice [1–2]: ").strip()

        if choice == "2":
            print("Bye!")
            await conn.close()
            sys.exit(0)

        if choice != "1":
            print("Invalid choice.")
            continue

        protos = prompt_protos()
        if not protos:
            print("No proto names entered.")
            continue

        thickness = await fetch_thickness_by_proto(conn, protos)

        if not thickness:
            print("No data found.")
            continue

        fig_all = plot_combined_distribution(
            thickness,
            "Combined Avg Thickness Distribution"
        )
        maybe_save_plot(fig_all, "thickness_combined")

        fig_by_proto = plot_thickness_distribution(
            thickness,
            "Avg Thickness Distribution by Proto"
        )
        maybe_save_plot(fig_by_proto, "thickness_by_proto")


# ----------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
