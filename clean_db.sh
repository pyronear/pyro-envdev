docker exec -i pyro-envdev-db-1 psql -U dummy_pg_user -d dummy_pg_db -c "TRUNCATE TABLE sequences, detections RESTART IDENTITY CASCADE;"

