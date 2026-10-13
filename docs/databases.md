# PostgreSQL and MySQL

A personal install uses a SQLite file in the data folder. That file has one writer at a time. Use PostgreSQL or MySQL when more than one person uses the same BioQueue, or when the site and the worker should not share a single database file.

Result files stay on disk under the data folder from `bioqueue init`. The database server stores accounts, protocols, and job records. It does not store the result files.

Switching does not copy an existing SQLite database. Accounts and job records in the new database start empty. The old `db.sqlite3` file is left in place and is no longer used.

## Create an empty database

BioQueue creates the tables. It does not create the database itself.

PostgreSQL, from a role that can create users and databases:

```sql
CREATE USER bioqueue WITH PASSWORD 'replace-me';
CREATE DATABASE bioqueue OWNER bioqueue;
```

MySQL:

```sql
CREATE DATABASE bioqueue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'bioqueue'@'localhost' IDENTIFIED BY 'replace-me';
GRANT ALL PRIVILEGES ON bioqueue.* TO 'bioqueue'@'localhost';
```

`'localhost'` is the host that is allowed to connect, not the server's address. If BioQueue runs on another machine, use that machine's host (or `%`) in the `CREATE USER` name.

## Install the driver

```bash
pip install "bioqueue[postgres]"
```

or:

```bash
pip install "bioqueue[mysql]"
```

From a Pixi checkout, add the driver to that environment instead. PostgreSQL:

```bash
pixi add --pypi "psycopg2-binary>=2.9"
```

MySQL:

```bash
pixi add --pypi "PyMySQL>=1.1"
```

Then run `pixi run bioqueue init` with the variables below set.

With conda, install the driver beside BioQueue:

```bash
conda install -c conda-forge bioqueue psycopg2
```

```bash
conda install -c conda-forge bioqueue pymysql
```

## Point BioQueue at the server

Set these in the shell before `bioqueue init`, and again before every later `bioqueue`, `bioqueue worker`, and `bioqueue serve`. The site and the worker are separate processes. Both read the variables from the environment they were started in.

| Variable | PostgreSQL | MySQL |
| --- | --- | --- |
| `BIOQUEUE_DB_ENGINE` | `django.db.backends.postgresql` | `django.db.backends.mysql` |
| `BIOQUEUE_DB_NAME` | database name | database name |
| `BIOQUEUE_DB_USER` | role | user |
| `BIOQUEUE_DB_PASSWORD` | password | password |
| `BIOQUEUE_DB_HOST` | `localhost` if unset | `localhost` if unset |
| `BIOQUEUE_DB_PORT` | `5432` | `3306` |

PostgreSQL:

```bash
export BIOQUEUE_DB_ENGINE=django.db.backends.postgresql
export BIOQUEUE_DB_NAME=bioqueue
export BIOQUEUE_DB_USER=bioqueue
export BIOQUEUE_DB_PASSWORD='replace-me'
export BIOQUEUE_DB_HOST=localhost
export BIOQUEUE_DB_PORT=5432

bioqueue init
bioqueue
```

MySQL uses the same variables with `django.db.backends.mysql` and port `3306`. The `mysql` extra installs PyMySQL, which BioQueue registers as Django's MySQL driver.

`bioqueue init` creates the tables and asks for the first account. Then open <http://127.0.0.1:8000/> and sign in.

`config/custom.conf` still holds the data folder, logs, and outputs. It does not hold the server connection.

## A git checkout

An installed package reads the variables above. A checkout uses `BioQueue/settings.py` when that file already exists. `bioqueue init` then prints `Keeping existing ... (database was not changed).` Put the connection in that file's `DATABASES` setting, or use a `settings.py` that imports `BioQueue.default_settings` so the variables apply.

A `settings.py` that `bioqueue init` creates from `settings-example.py` does import `BioQueue.default_settings`.
