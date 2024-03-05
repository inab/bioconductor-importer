# Bioconductor packages metadata importer

This program is a metadata importer for Bioconductor packages. It provides a set of functions to import metadata from Bioconductor packages, including package information, citation information, and other package metadata. 

## Set-up and Usage

1. Install dependencies 

    ```sh
    pip3 install -r requirements.txt
    ```

2. Execute the importer 

    ```sh
    python3 main.py -l=info 
    ``` 
- `-l` or `--loglevel` specifies the log level.


## Configuration

### Environment variables 

| Name             | Description | Default | Notes |
|------------------|-------------|---------|-------|

| Name             | Description | Default | Notes |
|------------------|-------------|---------|-------|
| MONGO_HOST       |  Host of database where output will be pushed |   `localhost`        |  |
| MONGO_PORT       |  Port of database where output will be pushed |   `27017`            |  |
| MONGO_USER       |  User of database where output will be pushed |            |  |
| MONGO_PASS   |  Password of database where output will be pushed |            |  |
| MONGO_AUTH_SRC  |  Authentication source of database where output will be pushed |   `admin`  |  |
| MONGO_DB         |  Name of database where output will be pushed |   `observatory`      |  |
| ALAMBIQUE |  Name of database where output will be pushed  |   `alambique`        |  |

## CI/CD

This repository is integrated with GitLab CI/CD. The pipeline is defined in `.gitlab-ci.yml`. It is composed of the following stages:

| Stage | Description | Runs |
|-------|-------------|------|
| `prepare` | Pulls bioconda recipes. It is necessary for both testing and data importation | Always |
| `test` | Runs the tests | Always |
| `main_task` | Data importation | Manually or on schedule |

