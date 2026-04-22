import asyncio
import asyncpg
import yaml
from datetime import datetime
import matplotlib
matplotlib.use("MacOSX")          # native macOS backend; falls back gracefully
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
    if fig is None:
        return
    while True:
        choice = input(f"Save plot '{default_name}'? [y/N]: ").strip().lower()
        if choice in ('y', 'yes'):
            filename = input(f"Enter filename (default: {default_name}.png): ").strip()
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
        password=DB_PASSWORD
    )

async def fetch_modules_by_date(conn, start_date, end_date):
    query = """
        SELECT module_name
        FROM module_info
        WHERE assembled BETWEEN $1 AND $2
        ORDER BY assembled;
    """
    rows = await conn.fetch(query, start_date, end_date)
    return [r['module_name'] for r in rows]

async def fetch_latest_measurements(conn, module_names):
    v_info, i_info, adc_stdd, adc_mean = {}, {}, {}, {}

    for name in module_names:
        v = await conn.fetchrow(
            """SELECT meas_v FROM module_iv_test
               WHERE module_name=$1
               ORDER BY date_test DESC LIMIT 1""",
            name
        )
        i = await conn.fetchrow(
            """SELECT meas_i FROM module_iv_test
               WHERE module_name=$1
               ORDER BY date_test DESC LIMIT 1""",
            name
        )
        std = await conn.fetchrow(
            """SELECT adc_stdd FROM module_pedestal_test
               WHERE module_name=$1
               ORDER BY date_test DESC LIMIT 1""",
            name
        )
        mean = await conn.fetchrow(
            """SELECT adc_mean FROM module_pedestal_test
               WHERE module_name=$1
               ORDER BY date_test DESC LIMIT 1""",
            name
        )

        v_info[name]   = [abs(float(x)) for x in v['meas_v']]     if v    else []
        i_info[name]   = [float(x) for x in i['meas_i']]     if i    else []
        adc_stdd[name] = [float(x) for x in std['adc_stdd']] if std  else []
        adc_mean[name] = [float(x) for x in mean['adc_mean']]if mean else []
        print("vinfo = ", v_info)
        print("iinfo = ", i_info)
    return v_info, i_info, adc_stdd, adc_mean

# ----------------------------------------
# Plotting  (each function now returns fig)
# ----------------------------------------
def plot_iv_summary(modules, v_info, i_info, label):
    fig, ax = plt.subplots()
    for m in modules:
        if v_info[m] and i_info[m]:
            ax.plot(v_info[m], i_info[m], label=m)

    ax.set_yscale('log')
    ax.set_xlim(0, 850)
    ax.set_xlabel('V')
    ax.set_ylabel('I [A]')
    ax.set_title(f'IV Summary ({label})')
    ax.legend(fontsize='small')
    plt.show(block=False)
    return fig                    # ← was missing


def plot_adc_hist(modules, data, title, xlabel, xlim):
    fig, ax = plt.subplots()
    for m in modules:
        if data[m]:
            ax.hist(data[m], bins=20, alpha=0.6, label=m)

    ax.set_xlim(*xlim)
    ax.set_xlabel(xlabel)
    ax.set_ylabel('Frequency')
    ax.set_title(title)
    ax.legend(fontsize='small')
    plt.show(block=False)
    return fig                    # ← was missing

# ----------------------------------------
# Friendly UI helpers
# ----------------------------------------
def prompt_date(prompt):
    while True:
        val = input(prompt).strip()
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            print("Please use YYYY-MM-DD")


def prompt_modules():
    raw = input("\nEnter module names (comma separated):\n> ")
    return [m.strip() for m in raw.split(",") if m.strip()]

# ----------------------------------------
# Main workflow
# ----------------------------------------
async def main():
    print("\n" + "=" * 40)
    print(" Module Summary Plotter ")
    print("=" * 40)

    try:
        conn = await get_connection()
    except Exception as e:
        print("Could not connect to database.")
        print(e)
        sys.exit(1)

    while True:
        print("""
How would you like to select modules?

  1) By assembly date range
  2) By module name(s)
  3) Quit
""")
        choice = input("Enter choice [1–3]: ").strip()

        if choice == "3":
            print("Bye!")
            await conn.close()
            sys.exit(0)

        if choice == "1":
            start = prompt_date("Start date (YYYY-MM-DD): ")
            end   = prompt_date("End date   (YYYY-MM-DD): ")
            modules = await fetch_modules_by_date(conn, start, end)
            label = f"{start} → {end}"

        elif choice == "2":
            modules = prompt_modules()
            label = "selected modules"

        else:
            print("Invalid choice.")
            continue

        if not modules:
            print("No modules found.")
            continue

        print(f"\n Found {len(modules)} module(s)")
        v_info, i_info, adc_stdd, adc_mean = await fetch_latest_measurements(
            conn, modules
        )
        print("vinfo = ", v_info)
        print("iinfo = ", i_info)

        safe_label = label.replace(' ', '_').replace('→', 'to')

        fig_iv = plot_iv_summary(modules, v_info, i_info, label)
        maybe_save_plot(fig_iv, f"iv_summary_{safe_label}")

        fig_noise = plot_adc_hist(
            modules, adc_stdd,
            f"ADC Noise Summary ({label})",
            "ADC Standard Deviation", (0, 50)
        )
        maybe_save_plot(fig_noise, f"adc_noise_{safe_label}")

        fig_mean = plot_adc_hist(
            modules, adc_mean,
            f"ADC Mean Summary ({label})",
            "ADC Mean", (0, 500)
        )
        maybe_save_plot(fig_mean, f"adc_mean_{safe_label}")

        # Keep windows open until the user is done with them
        plt.pause(0.001)
        input("\nPress Enter to continue…")
        plt.close('all')

# ----------------------------------------
if __name__ == "__main__":
    asyncio.run(main())