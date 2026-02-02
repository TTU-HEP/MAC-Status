#!/usr/bin/env bash

# =========================
# Database configuration
# =========================
LAST_QUERY_TYPE=""

DB_HOST="129.118.107.198"
DB_PORT="5432"
DB_USER="viewer"
DB_NAME="ttu_mac_local"

PSQL_CMD="psql -x -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -Atc"
PSQL_META_CMD="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -Atc"

# =========================
# Utility functions
# =========================

print_divider() {
  echo "---------------------------------------------"
}

exit_program() {
  echo "Exiting database tool. Ciao!"
  exit 0
}

invalid_option() {
  echo "Oops! That's not an available option. Try again or type EXIT."
}

prompt() {
  echo -n ">> "
}

# =========================
# Menu definitions
# =========================

declare -A CATEGORY_TABLES

CATEGORY_TABLES["hexaboard"]="hexaboard hxb_pedestal_test hxb_inspect"
CATEGORY_TABLES["baseplate"]="baseplate bp_inspect"
CATEGORY_TABLES["sensor"]="sensor sen_iv_data"
CATEGORY_TABLES["protomodule"]="proto_assembly proto_inspect"
CATEGORY_TABLES["module"]="module_info module_pedestal_test module_assembly module_inspect module_ileak_estimate module_qc_summary module_iv_test"
CATEGORY_TABLES["other"]="back_encap back_wirebond bond_pull_test front_encap front_wirebond trophy_and_mezzanine_boards"

MAIN_OPTIONS=("hexaboard" "baseplate" "sensor" "protomodule" "module" "other")

declare -A TABLE_DATE_COLUMN

TABLE_DATE_COLUMN["module_info"]="assembled"

TABLE_DATE_COLUMN["module_inspect"]="date_inspect"
TABLE_DATE_COLUMN["proto_inspect"]="date_inspect"

TABLE_DATE_COLUMN["module_pedestal_test"]="date_test"
TABLE_DATE_COLUMN["module_iv_test"]="date_test"
TABLE_DATE_COLUMN["hxb_pedestal_test"]="date_test"

TABLE_DATE_COLUMN["module_assembly"]="ass_run_date"
TABLE_DATE_COLUMN["proto_assembly"]="ass_run_date"

TABLE_DATE_COLUMN["front_encap"]="date_encap"
TABLE_DATE_COLUMN["back_encap"]="date_encap"

TABLE_DATE_COLUMN["front_wirebond"]="date_bond"
TABLE_DATE_COLUMN["back_wirebond"]="date_bond"

WIDE_TABLES=(
  "module_iv_test"
  "module_pedestal_test"
  "hxb_pedestal_test"
)
SEARCH_COLUMNS=(
  "module_name"
  "proto_name"
  "hxb_name"
  "bp_name"
  "sen_name"
)

# =========================
# Menu handlers
# =========================

select_category() {
  print_divider
  echo "Welcome to database tool! What can I help you with?"
  echo "[Options: ${MAIN_OPTIONS[*]} | EXIT]"
  prompt
  read category

  [[ "$category" == "EXIT" ]] && exit_program

  if [[ -z "${CATEGORY_TABLES[$category]}" ]]; then
    invalid_option
    return 1
  fi

  SELECTED_CATEGORY="$category"
  return 0
}

select_table() {
  local tables=(${CATEGORY_TABLES[$SELECTED_CATEGORY]})

  print_divider
  echo "Great! Which table would you like to view?"
  echo "[Options: ${tables[*]} | BACK | EXIT]"
  prompt
  read table

  [[ "$table" == "EXIT" ]] && exit_program
  [[ "$table" == "BACK" ]] && return 1

  for t in "${tables[@]}"; do
    if [[ "$t" == "$table" ]]; then
      SELECTED_TABLE="$table"
      SELECTED_COLUMNS=""   # <-- RESET HERE
      SELECTED_CLAUSE="*"     # <-- optional but clean
      return 0
    fi
  done

  invalid_option
  return 1
}

is_wide_table() {
  for t in "${WIDE_TABLES[@]}"; do
    [[ "$t" == "$SELECTED_TABLE" ]] && return 0
  done
  return 1
}

get_table_columns() {
  $PSQL_META_CMD "
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = '$SELECTED_TABLE'
    ORDER BY ordinal_position;
  "
}

select_columns() {
  echo "Warning, this table has many columns."
  echo "Please select which columns you want to view."
  echo "(comma-separated, or type ALL to show everything - NOT RECOMMENDED)"

  print_divider
  AVAILABLE_COLUMNS=($(get_table_columns))
  echo "Available columns:"
  echo "${AVAILABLE_COLUMNS[@]}"
  print_divider

  prompt
  read column_input

  [[ "$column_input" == "ALL" ]] && SELECTED_COLUMNS="*" && return 0

  # Parse comma-separated input
  IFS=',' read -ra USER_COLUMNS <<< "$column_input"

  VALID_COLUMNS=()

  for col in "${USER_COLUMNS[@]}"; do
    col="$(echo "$col" | xargs)"   # trim spaces
    for valid in "${AVAILABLE_COLUMNS[@]}"; do
      [[ "$col" == "$valid" ]] && VALID_COLUMNS+=("$col")
    done
  done

  if [[ "${#VALID_COLUMNS[@]}" -eq 0 ]]; then
    echo "None of the selected columns were valid... "
    return 1
  fi

  SELECTED_COLUMNS=$(IFS=, ; echo "${VALID_COLUMNS[*]}")
  return 0
}

table_has_column() {
  local col="$1"
  for existing in $(get_table_columns); do
    [[ "$existing" == "$col" ]] && return 0
  done
  return 1
}

post_query_menu() {
  print_divider
  echo "What would you like to do next?"
  echo "[Options: repeat | back | exit]"
  prompt
  read choice

  case "$choice" in
    repeat)
      return 0   # repeat same query type
      ;;
    back)
      return 1   # go back to table selection
      ;;
    exit)
      exit_program
      ;;
    *)
      invalid_option
      post_query_menu
      return $?
      ;;
  esac
}

run_query_for_action() {
  local action="$1"

  # SELECTED_CLAUSE already set (handles wide tables)

  case "$action" in
    all)
      $PSQL_CMD "SELECT $SELECTED_CLAUSE FROM $SELECTED_TABLE;"
      ;;
    limit)
      echo "Enter number of rows:"
      prompt
      read limit
      [[ "$limit" =~ ^[0-9]+$ ]] || { invalid_option; return; }
      $PSQL_CMD "SELECT $SELECTED_CLAUSE FROM $SELECTED_TABLE LIMIT $limit;"
      ;;
    search)
      # uses your auto-search logic (name columns)
      run_name_search
      ;;
    sort_date)
      run_sort_date
      ;;
    date_range)
      run_date_range
      ;;
  esac

  echo
  echo "Query complete."
}


query_table() {
  SELECTED_CLAUSE="*"
  while true; do
    if is_wide_table && [[ -z "$SELECTED_COLUMNS" ]]; then
      select_columns || return 0
      SELECTED_CLAUSE="$SELECTED_COLUMNS"
    fi
    print_divider
    echo "How would you like to query '$SELECTED_TABLE'?"
    echo "[Options: all | search | sort_date | date_range | BACK | EXIT]"

    prompt
    read action
    LAST_QUERY_TYPE="$action"
    [[ "$action" == "EXIT" ]] && exit_program
    [[ "$action" == "BACK" ]] && return 1

    case "$action" in
      all)
        $PSQL_CMD "SELECT $SELECTED_CLAUSE  FROM $SELECTED_TABLE;"
        ;;

      sort_date)
        DATE_COL="${TABLE_DATE_COLUMN[$SELECTED_TABLE]}"

        if [[ -z "$DATE_COL" ]]; then
          echo "Sorry — no date column configured for this table. If needed, contact devs ASAP!"
          return 0
        fi

        echo "Sort by entry date:"
        echo "[Options: asc | desc ]"
        prompt
        read order

        if [[ "$order" != "asc" && "$order" != "desc" ]]; then
          invalid_option
          return 0
        fi

        $PSQL_CMD "SELECT $SELECTED_CLAUSE  FROM $SELECTED_TABLE ORDER BY $DATE_COL $order;"
        ;;

      search)
        echo "Enter name to search for:"
        prompt
        read search_term

        [[ -z "$search_term" ]] && { invalid_option; return 0; }

        CONDITIONS=()

        for col in "${SEARCH_COLUMNS[@]}"; do
          if table_has_column "$col"; then
            CONDITIONS+=("$col::text ILIKE '%$search_term%'")
          fi
        done

        if [[ "${#CONDITIONS[@]}" -eq 0 ]]; then
          echo "No searchable name columns exist in this table. Contact devs immediately!"
          return 0
        fi

        WHERE_CLAUSE=$(printf "(%s) OR " "${CONDITIONS[@]}")
        WHERE_CLAUSE=${WHERE_CLAUSE% OR }   # remove trailing OR
        WHERE_CLAUSE="($WHERE_CLAUSE)"      # wrap entire clause


        $PSQL_CMD "
          SELECT $SELECTED_CLAUSE
          FROM $SELECTED_TABLE
          WHERE $WHERE_CLAUSE;
        "
        ;;

      date_range)
        DATE_COL="${TABLE_DATE_COLUMN[$SELECTED_TABLE]}"

        if [[ -z "$DATE_COL" ]]; then
          echo "Sorry — no date column configured for this table."
          return 0
        fi

        echo "Enter START date (YYYY-MM-DD):"
        prompt
        read start_date

        echo "Enter END date (YYYY-MM-DD):"
        prompt
        read end_date

        # Basic date validation
        if ! [[ "$start_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || \
          ! [[ "$end_date"   =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
          echo "Oops! Invalid date format. Use YYYY-MM-DD."
          return 0
        fi

        echo "Sort results?"
        echo "[Options: asc | desc | none]"
        prompt
        read order

        if [[ "$order" != "asc" && "$order" != "desc" && "$order" != "none" ]]; then
          invalid_option
          return 0
        fi

        ORDER_CLAUSE=""
        [[ "$order" != "none" ]] && ORDER_CLAUSE="ORDER BY $DATE_COL $order"

        $PSQL_CMD "
          SELECT $SELECTED_CLAUSE
          FROM $SELECTED_TABLE
          WHERE $DATE_COL BETWEEN '$start_date' AND '$end_date'
          $ORDER_CLAUSE;
        "
        ;;
      
      *)
        invalid_option
        ;;
    esac

    echo

    post_query_menu
    case $? in
      0)  continue ;;  # repeat same query type
      1)  return 1 ;;  # back to table selection
    esac
  done
  return 0
}

# =========================
# Main program loop
# =========================

while true; do
  select_category || continue

  while true; do
    select_table || break

    while true; do
      query_table || break
    done
  done
done
