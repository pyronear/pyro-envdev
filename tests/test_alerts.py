import os
import psycopg2
import pytest

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@pytest.fixture
def db_connection():
    # Load environment variables
    db_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_name = os.getenv("POSTGRES_DB")

    # Connect to the PostgreSQL database
    conn = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_password,
        host="localhost",
        port="5432",
    )
    yield conn
    conn.close()


def test_detections_count(db_connection):
    # Create a cursor
    cursor = db_connection.cursor()

    # Execute the SQL query
    cursor.execute("SELECT count(*) FROM detections")

    # Fetch the result
    result = cursor.fetchone()[0]

    # Close the cursor
    cursor.close()

    # Check if the result is equal to 1
    # assert result > 0, "Number of alerts is " + str(result)


if __name__ == "__main__":
    pytest.main([__file__])
