# Introduction 
An index & manager of SharePoint powered by Python, Flask and Redis.
No need to generate OneDrive API Tokens or register application in Azure.
Built for those who can't authorize apps and don't have admin permissions.
Completely free to host.

# Dependents

psutil
redis
flask
chardet
requests
flask_caching
Office365-REST-Python-Client

# Quick Start

1.	Fork the repo

2.  Install Python3 and dependent modules.

    ```bash
    sudo apt install python3;pip install -r requirements.txt
    ```

3.	Change host, port, password with your Redis server.

4.	Write in a new hash named "SharePointAccountList" in to your Redis server.
    It should contain a Key which is your office account e-mail and a list with "[endpoint, email, password, SharePointSite(if there are multiple sites, separate by space)]"

5.	Run with command

    ```bash
    python app.py
    ```

# To-Do