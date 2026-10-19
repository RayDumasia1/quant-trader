"""Manual DuckDB connectivity probe."""

def main():
    try:
        import duckdb
    except ImportError:
        print("Error: duckdb module not found. Install it with: pip install duckdb")
        exit(1)
    con = duckdb.connect()
    result = con.sql("SELECT 'DuckDB is working' AS status").fetchall()
    print(result)


if __name__ == "__main__":
    main()
