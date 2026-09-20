# setup_db.ps1 - Run as Administrator to setup RBAC PostgreSQL database
# This script modifies pg_hba.conf to trust, restarts PostgreSQL,
# creates the rbac user and database, then restores the original config.

$PGDATA = "X:\database\postgresql\data"
$PGBIN = "X:\database\postgresql\bin"
$SERVICE = "postgresql-x64-18"
$PG_HBA = "$PGDATA\pg_hba.conf"

Write-Host "Stopping PostgreSQL service..."
& "$PGBIN\pg_ctl.exe" stop -D $PGDATA -m fast

Write-Host "Setting trust authentication..."
(Get-Content $PG_HBA) -replace 'host\s+all\s+all\s+127\.0\.0\.1/32\s+scram-sha-256',
                                'host    all             all             127.0.0.1/32            trust' |
    Set-Content $PG_HBA

Write-Host "Starting PostgreSQL..."
& "$PGBIN\pg_ctl.exe" start -D $PGDATA

Start-Sleep -Seconds 3

Write-Host "Creating rbac role..."
$env:PGPASSWORD = ''
& "$PGBIN\psql.exe" -h 127.0.0.1 -U postgres -d postgres -c "CREATE ROLE rbac WITH LOGIN PASSWORD 'rbac_local_password';"

Write-Host "Creating rbac database..."
& "$PGBIN\psql.exe" -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE rbac OWNER rbac;"

Write-Host "Creating rbac_test database..."
& "$PGBIN\psql.exe" -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE rbac_test OWNER rbac;"

Write-Host "Restoring scram-sha-256 authentication..."
(Get-Content $PG_HBA) -replace 'host\s+all\s+all\s+127\.0\.0\.1/32\s+trust',
                                'host    all             all             127.0.0.1/32            scram-sha-256' |
    Set-Content $PG_HBA

Write-Host "Restarting PostgreSQL..."
& "$PGBIN\pg_ctl.exe" stop -D $PGDATA -m fast
& "$PGBIN\pg_ctl.exe" start -D $PGDATA

Write-Host "Done! rbac user and database created."
